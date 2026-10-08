"""Panel add-onu (Ingress): konta Lidl Plus i ich logowanie.

- Ingress: prefiks z `X-Ingress-Path` trafia do szablonów jako `base`; żądania spoza proxy
  Supervisora (172.30.32.2) są odrzucane (poza trybem dev).
- WebView aplikacji HA agresywnie cache'uje: HTML i odpowiedzi `no-store`, statyki z `?v=<wersja>`
  i `immutable`, wersja widoczna w stopce.
- Tokeny i wklejany adres callback nigdy nie trafiają do logów.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lidl import __version__
from lidl.accounts import AccountStore, slugify
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from lidl.coupons import CouponRunner
from lidl.daily import EVENING, DailyJob, at_time_loop
from lidl.history import CANDIDATE_MIN_PURCHASES, History
from lidl.leaflet import LeafletRunner
from lidl.promotions import PromotionRunner
from lidl.receipt import parse_detail
from lidl.rewards import RewardsRunner
from lidl.service import LidlService
from lidl.settings import Settings
from lidl.sync import HistorySync
from lidl.text import count_text, fmt_date, fmt_time_day_month, matches

from .chart import build_chart, fmt_month_year_genitive, fmt_pln, parse_chart_query
from .products import (
    MORE_STEP,
    coupon_cards,
    coupon_rows,
    effect_view,
    import_status,
    parse_limit,
    ranking_rows,
    reward_cards,
)

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
INGRESS_PROXY = "172.30.32.2"

LOGIN_ERRORS = {
    "token_rejected": "Lidl odrzucił kod: wygasł albo został już użyty. Zaloguj się od nowa.",
    "missing_auth_code": "Nie znalazłem kodu w wklejonym tekście. Skopiuj cały nagłówek Location.",
    "no_pending_login": "Sesja logowania wygasła (add-on był restartowany). Zaloguj się od nowa.",
    "no_loyalty_card": "Zalogowano, ale konto nie ma karty Lidl Plus.",
}
MESSAGES = {
    "connected": ("ok", "Konto połączone."),
    "checked": ("ok", "Połączenie działa."),
    "deleted": ("ok", "Konto usunięte."),
    "expired": ("err", "Sesja wygasła. Zaloguj to konto ponownie."),
    "offline": ("err", "Brak połączenia z Lidl. Spróbuj za chwilę."),
}


def _login_error(err: Exception) -> str:
    if isinstance(err, LidlPlusCannotConnect):
        return "Brak połączenia z Lidl. Zaloguj się od nowa, gdy sieć wróci."
    return LOGIN_ERRORS.get(str(err), "Logowanie nie powiodło się. Zaloguj się od nowa.")


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            service = LidlService(AccountStore(settings.accounts_dir), session)
            history = History(settings.data_dir / "history.db")
            history.reparse(parse_detail)  # paragony zapisane starszym parserem, z lokalnej kopii
            sync = HistorySync(service, history)
            runner = CouponRunner(service, history)
            rewards = RewardsRunner(service)
            promotions = PromotionRunner(session, history)
            job = DailyJob(
                service.store, sync, runner, rewards, promotions, session, dry_run=not settings.auto_activate
            )
            app.state.service, app.state.history, app.state.sync = service, history, sync
            app.state.runner, app.state.job, app.state.rewards = runner, job, rewards

            loops = [
                asyncio.create_task(at_time_loop(settings.run_time, job)),
                asyncio.create_task(at_time_loop(EVENING, job.evening)),
                asyncio.create_task(job.refresh_rewards()),
            ]
            if not settings.dev:  # w dev/testach bez zapytań do Lidla i modelu przy starcie
                # promocje od razu, żeby „Sprawdź teraz” po restarcie nie czekało do rana
                loops.append(asyncio.create_task(promotions.refresh()))
                if settings.leaflet_enabled:
                    loops.append(asyncio.create_task(LeafletRunner(session, history, settings).run_forever()))
            try:
                yield
            finally:
                for loop in loops:
                    loop.cancel()
                await asyncio.gather(*loops, return_exceptions=True)
                await job.close()
                await sync.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        peer = request.client.host if request.client else ""
        if not settings.dev and peer != INGRESS_PROXY:
            return Response("Dostęp tylko przez panel Home Assistant (Ingress).", 403)
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
        return response

    def service(request: Request) -> LidlService:
        svc: LidlService = request.app.state.service
        return svc

    def base(request: Request) -> str:
        return request.headers.get("x-ingress-path", "").rstrip("/")

    def render(request: Request, name: str, **ctx: Any) -> Response:
        return templates.TemplateResponse(
            request, name, {"base": base(request), "version": __version__, **ctx}
        )

    def go(request: Request, path: str) -> RedirectResponse:
        return RedirectResponse(f"{base(request)}{path}", status_code=303)

    @app.get("/healthz")
    async def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/")
    async def index(request: Request, m: str = "", a: str = "") -> Response:
        svc = service(request)
        msg = None
        if m in MESSAGES:
            kind, text = MESSAGES[m]
            msg = {"kind": kind, "text": text}
        return render(request, "index.html", section="konta", accounts=svc.store.list(), msg=msg)

    @app.post("/accounts")
    async def add_account(request: Request, label: str = Form(...)) -> Response:
        try:
            slugify(label)
        except ValueError:
            return go(request, "/")
        account = service(request).store.create(label)
        return go(request, f"/accounts/{account.slug}/login")

    @app.get("/accounts/{slug}/login")
    async def login_page(request: Request, slug: str) -> Response:
        svc = service(request)
        try:
            account = svc.store.get(slug)
        except KeyError:
            return go(request, "/")
        return render(request, "login.html", account=account, auth_url=svc.begin_login(slug), error=None)

    @app.post("/accounts/{slug}/login")
    async def login_submit(request: Request, slug: str, pasted: str = Form(...)) -> Response:
        svc = service(request)
        try:
            account = svc.store.get(slug)
        except KeyError:
            return go(request, "/")
        try:
            await svc.finish_login(slug, pasted)
        except (LidlPlusError, LidlPlusAuthError) as err:
            log.warning("Logowanie konta %s nieudane: %s", slug, type(err).__name__)
            return render(
                request,
                "login.html",
                account=account,
                auth_url=svc.begin_login(slug),
                error=_login_error(err),
            )
        return go(request, "/?m=connected")

    @app.post("/accounts/{slug}/check")
    async def check(request: Request, slug: str) -> Response:
        try:
            await service(request).check(slug)
        except KeyError:
            return go(request, "/")
        except LidlPlusCannotConnect:
            return go(request, "/?m=offline")
        except LidlPlusError as err:
            log.warning("Sprawdzenie konta %s nieudane: %s", slug, type(err).__name__)
            return go(request, "/?m=expired")
        return go(request, "/?m=checked")

    @app.post("/accounts/{slug}/delete")
    async def delete(request: Request, slug: str) -> Response:
        try:
            await service(request).delete(slug)
        except KeyError:
            pass
        return go(request, "/?m=deleted")

    @app.get("/produkty")
    async def products(request: Request) -> Response:
        svc = service(request)
        history: History = request.app.state.history
        sync: HistorySync = request.app.state.sync
        params = dict(request.query_params)
        accounts = svc.store.list()
        status = import_status(sync, history, accounts)

        def link(**over: object) -> str:
            keep = {
                k: v
                for k, v in params.items()
                if k in ("od", "do", "krok", "produkt", "miara", "zakres", "limit", "q")
            }
            keep.update({k: str(v) for k, v in over.items()})
            keep = {k: v for k, v in keep.items() if v}  # pusta wartość = bez filtra
            return f"{base(request)}/produkty?{urlencode(keep)}" if keep else f"{base(request)}/produkty"

        ctx: dict[str, Any] = {"section": "produkty", "status": status, "accounts": accounts}
        if status["state"] != "empty":
            kpi = history.savings_kpi()
            first = date.fromisoformat(kpi.first_date) if kpi.first_date else None
            query = parse_chart_query(params, date.today(), first)
            ranking = history.ranking(start=query.start, end=query.end) if query.error is None else []
            q = params.get("q", "").strip()
            found = [p for p in ranking if matches(p.name, q)] if q else ranking
            limit = parse_limit(params.get("limit"))
            ctx.update(
                query=query,
                q=q,
                found=len(found),
                ranked=len(ranking),
                clear_href=link(q=""),
                rows=ranking_rows(found, limit, link),
                more_href=link(limit=limit + MORE_STEP) if len(found) > limit else None,
            )
            if request.headers.get("hx-target") == "wyniki":  # wyszukiwanie na żywo: tylko wyniki rankingu
                return render(request, "_ranking.html", **ctx)
            chart = None
            range_totals = None
            if query.error is None:
                series = history.spend_series(query.start, query.end, query.step, query.art_id)
                chart = build_chart(series, query.step, query.metric)
                if query.art_id is None and query.metric == "spend":
                    totals = history.purchase_totals(query.start, query.end)
                    range_totals = {
                        "paid": fmt_pln(totals.paid),
                        "charged": fmt_pln(totals.charged),
                        "refunded": fmt_pln(totals.refunded),
                    }
            all_totals = history.purchase_totals()
            ctx.update(
                chart=chart,
                range_totals=range_totals,
                kpi_paid=fmt_pln(all_totals.paid, 2),
                kpi_charged=fmt_pln(all_totals.charged, 2),
                kpi_refunded=fmt_pln(all_totals.refunded, 2),
                kpi_dep_known=all_totals.with_deposits,
                product_name=query.art_id and (history.product_name(query.art_id) or query.art_id),
                all_products_href=link(produkt=""),
                rank_range=f"{fmt_date(query.start)} – {fmt_date(query.end)}",
                kpi_total=fmt_pln(kpi.total, 2),
                kpi_coupon_money=fmt_pln(kpi.coupons, 2),
                kpi_promo_money=fmt_pln(kpi.promotions, 2),
                kpi_last12=fmt_pln(kpi.last_12m, 2),
                kpi_tickets=kpi.tickets,
                kpi_with_details=kpi.with_details,
                kpi_unparsed=kpi.unparsed,
                kpi_coupons=kpi.coupons_used,
                pending_accounts=[
                    a
                    for a in accounts
                    if a.connected and history.ticket_count(a.slug) == 0 and not sync.progress(a.slug).running
                ],
                ok_text=(
                    f"Historia jest aktualna: {count_text(kpi.tickets, 'paragon', 'paragony', 'paragonów')}"
                    + (f" od {fmt_month_year_genitive(first)}" if first else "")
                    + ". Nowe pobieramy codziennie."
                ),
            )
        return render(request, "products.html", **ctx)

    @app.get("/kupony")
    async def coupons(request: Request) -> Response:
        history: History = request.app.state.history
        job: DailyJob = request.app.state.job
        q = request.query_params.get("q", "").strip()
        ctx: dict[str, Any] = {
            "section": "kupony",
            "q": q,
            "clear_href": f"{base(request)}/kupony",
            "cards": coupon_cards(service(request).store.list(), history, datetime.now(UTC)),
            "dry_run": job.dry_run,
            "running": job.running,
            "last_check": fmt_time_day_month(job.last_check) if job.last_check else None,
            "run_time": settings.run_time.strftime("%H:%M"),
            "rewards": reward_cards(request.app.state.rewards.last, date.today()),
        }
        target = request.headers.get("hx-target")
        if target == "kupony-konta":  # odświeżanie w trakcie sprawdzania: tylko karty kont
            return render(request, "_coupons_accounts.html", **ctx)
        regular = coupon_rows(history.coupon_candidates())
        ctx.update(
            effect=effect_view(history, service(request).store.list(), date.today(), datetime.now(UTC)),
            rows=[r for r in regular if matches(r["name"], q)],
            regular_total=len(regular),
            min_purchases=CANDIDATE_MIN_PURCHASES,
            on=sum(r["on"] for r in regular),
            no_code=sum(not r["matchable"] for r in regular),
        )
        live = target == "kupony-wyniki"  # wyszukiwanie na żywo: tylko wyniki
        return render(request, "_coupons_results.html" if live else "coupons.html", **ctx)

    @app.post("/kupony/sprawdz")
    async def check_coupons(request: Request, q: str = Form("")) -> Response:
        request.app.state.job.start_coupons()
        return go(request, f"/kupony?{urlencode({'q': q})}" if q else "/kupony")

    @app.post("/kupony/{slug}/{promotion_id}/aktywuj")
    async def activate_coupon(request: Request, slug: str, promotion_id: str) -> Response:
        try:
            await request.app.state.runner.activate_one(slug, promotion_id)
        except LidlPlusError as err:
            log.warning("Ręczna aktywacja kuponu na koncie %s nieudana: %s", slug, err)
        return go(request, f"/kupony#kupony-{quote(slug)}")

    @app.post("/kupony/produkt/{art_id}")
    async def toggle_coupon(request: Request, art_id: str, enabled: str = Form(...)) -> Response:
        request.app.state.history.set_auto_activate(art_id, enabled == "1")
        return go(request, f"/kupony#p-{quote(art_id)}")

    @app.post("/accounts/{slug}/history")
    async def start_history(request: Request, slug: str) -> Response:
        try:
            account = service(request).store.get(slug)
        except KeyError:
            return go(request, "/")
        if not account.connected:
            return go(request, "/?m=expired")
        request.app.state.sync.start(slug, full=True)
        return go(request, "/produkty")

    @app.post("/history/resume")
    async def resume_history(request: Request) -> Response:
        history: History = request.app.state.history
        for account in service(request).store.list():
            if account.connected and history.ticket_count(account.slug) > 0:
                request.app.state.sync.start(account.slug, full=True)
        return go(request, "/produkty")

    return app
