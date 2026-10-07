"""Panel add-onu (Ingress): konta Lidl Plus i ich logowanie.

- Ingress: prefiks z `X-Ingress-Path` trafia do szablonów jako `base`; żądania spoza proxy
  Supervisora (172.30.32.2) są odrzucane (poza trybem dev).
- WebView aplikacji HA agresywnie cache'uje: HTML i odpowiedzi `no-store`, statyki z `?v=<wersja>`
  i `immutable`, wersja widoczna w stopce.
- Tokeny i wklejany adres callback nigdy nie trafiają do logów.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiohttp
from fastapi import FastAPI, Form, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lidl import __version__
from lidl.accounts import AccountStore, slugify
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from lidl.service import LidlService
from lidl.settings import Settings

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
            app.state.service = LidlService(AccountStore(settings.accounts_dir), session)
            yield

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
        return render(request, "index.html", accounts=svc.store.list(), msg=msg)

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

    return app
