"""Ceny półkowe Biedronki (E29.2): „dziś na półce” z aplikacji Moja Biedronka dla obserwowanych
produktów kupionych w Biedronce i zatwierdzonych par Lidl↔Biedronka. Odczyt raz dziennie w porannym przebiegu;
błąd jednego EAN nie zatrzymuje reszty, a stare wiersze zostają."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any

from .chain_savings import _bdr_slugs
from .client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from .history import History, ShelfPrice

log = logging.getLogger(__name__)

MAX_EANS = 60  # limit EAN-ów dziennie; cena + stan = ≤120 zapytań (E30: ≤1/s, plan E30)
REQUEST_PAUSE_S = 1.0
BATCH_SIZE = 20  # E6b.3b: zlecenia po EAN idą partiami
BATCH_PAUSE_S = 10.0  # pauza między partiami (w partii: REQUEST_PAUSE_S)
FRESH_DAYS = 7  # cena młodsza niż tyle dni nie jest odpytywana ponownie
ABSENT_DAYS = 30  # EAN z 404 młodszy niż tyle dni nie jest odpytywany ponownie
_EAN_RE = re.compile(r"\d{8,13}")
_PROMO_END_RE = re.compile(r"do\s+(\d{1,2})\.(\d{1,2})")
_PROMO_YEAR_BACK = 180  # data końca więcej niż tyle dni przed dziś = przełom roku
BACK_KEY = "shelf_back_pending"  # E30.3: JSON-lista EAN-ów, które wróciły na półkę, a nie są jeszcze w pushu


@dataclass
class RefreshResult:
    ok: int = 0  # odczyty bez błędu (także bez ceny: „DRUGI ZA x zł”)
    skipped: int = 0  # HTTP 404: nieznany EAN albo zły sklep — nie jest błędem
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    stock_failed: int = 0  # E30.2: błędy odczytu stanu (poprzedni stan zostaje)
    back_in_stock: list[str] = field(default_factory=list)  # obserwowane: brak → jest/mało w tym odczycie


def watched_eans(history: History) -> set[str]:
    """EAN-y obserwowanych kodów `b:`/`n:` (kody z wagą w kluczu nie są EAN-em i odpadają)."""
    found: set[str] = set()
    for code in history.watched_codes():
        prefix, _, rest = code.partition(":")
        if prefix in ("b", "n") and _EAN_RE.fullmatch(rest):
            found.add(rest)
    return found


def targets(history: History) -> list[str]:
    """EAN-y do odczytu: obserwowane kody `b:`/`n:` z samym EAN-em i strona Biedronki zatwierdzonych par."""
    found = watched_eans(history)
    for pair in history.chain_pair_list():
        if pair.status == "approved" and _EAN_RE.fullmatch(pair.b_art_id):
            found.add(pair.b_art_id)
    return sorted(found)[:MAX_EANS]


def _iso_or_none(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def parse_price(store: str, ean: str, data: Any, now: datetime) -> ShelfPrice | None:
    """Wiersz ceny półkowej; `None` = brak ceny (np. „DRUGI ZA x zł”). Nieznany kształt → ValueError."""
    if not isinstance(data, dict) or "price" not in data or "regular_price" not in data:
        raise ValueError("nieznany kształt odpowiedzi")
    if data["price"] in (None, ""):
        return None
    omnibus = _money(data.get("omnibus_price"))
    if omnibus is not None and omnibus <= 0:  # „0.00” = brak Omnibusa, nie cena zero
        omnibus = None
    period = data.get("promotion_valid_period") or None
    return ShelfPrice(
        store=store,
        ean=ean,
        price=float(data["price"]),
        regular=_money(data["regular_price"]),
        omnibus=omnibus,
        promo_from=period,
        promo_to=_iso_or_none(parse_promo_end(period, now.date())),
        card_only=bool(data.get("only_with_biedronka_card")),
        is_promotion=bool(data.get("is_promotion")),
        fetched_at=now.isoformat(timespec="seconds"),
    )


def parse_stock(data: Any) -> str | None:
    """Stan półki z `products/stock` (E30.1): `coverage` 0 → 'no', 1–2 → 'low', ≥3 → 'yes'.
    To jedyne miejsce mapowania (założenie do potwierdzenia w aplikacji, E30.5).
    Brak `coverage`, zły typ (także `bool`) albo wartość ujemna → ValueError."""
    coverage = data.get("coverage") if isinstance(data, dict) else None
    if type(coverage) is not int or coverage < 0:
        raise ValueError("nieznany kształt odpowiedzi")
    if coverage == 0:
        return "no"
    return "low" if coverage <= 2 else "yes"


def _stock_only(store: str, ean: str, stock: str | None, now: datetime) -> ShelfPrice:
    """Wiersz bez ceny, gdy znany jest tylko stan półki (E30.2)."""
    fetched = now.isoformat(timespec="seconds")
    return ShelfPrice(store, ean, None, None, None, None, None, False, False, fetched, stock)


async def refresh(
    history: History,
    api: Any,
    store: str,
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> RefreshResult:
    """Odczytuje ceny i stan półki dla `targets` w sklepie `store`; zapisuje tylko udane odczyty.
    Błąd sesji albo sieci przerywa pętlę (odczyty sprzed błędu zostają zapisane) i idzie w górę."""
    result = RefreshResult()
    rows: list[ShelfPrice] = []
    cleared: list[str] = []
    now = datetime.now()
    previous = {r.ean: r.stock for r in history.shelf_list(store)}
    watched = watched_eans(history)
    try:
        for index, ean in enumerate(targets(history)):
            if index:
                await sleep(REQUEST_PAUSE_S)
            price_404 = False
            try:
                row = parse_price(store, ean, await api.product_price(store, ean), now)
            except (LidlPlusAuthError, LidlPlusCannotConnect):
                raise  # dalsze zapytania nic nie dadzą
            except LidlPlusError as err:
                if err.status != 404:
                    result.failed += 1
                    result.errors.append(f"{ean}: {err}")
                    continue
                row, price_404 = None, True
            except (TypeError, ValueError):
                result.failed += 1
                result.errors.append(f"{ean}: nieznany kształt odpowiedzi")
                continue
            await sleep(REQUEST_PAUSE_S)
            stock: str | None
            try:
                stock = parse_stock(await api.product_stock(store, ean))
            except (LidlPlusAuthError, LidlPlusCannotConnect):
                raise
            except LidlPlusError as err:
                stock = None
                if err.status != 404:
                    stock = previous.get(ean)
                    result.stock_failed += 1
                    result.errors.append(f"{ean} (stan): {err}")
            except (TypeError, ValueError) as err:
                stock = previous.get(ean)
                result.stock_failed += 1
                result.errors.append(f"{ean} (stan): {err}")
            if stock in ("yes", "low") and previous.get(ean) == "no" and ean in watched:
                result.back_in_stock.append(ean)
            if row is not None:
                rows.append(replace(row, stock=stock))
                result.ok += 1
            elif stock is not None:
                rows.append(_stock_only(store, ean, stock, now))
                result.ok += 1
            elif price_404:
                result.skipped += 1
            else:
                result.ok += 1
                cleared.append(ean)
    finally:
        if rows or cleared:
            history.shelf_replace(store, rows, cleared)
        if result.back_in_stock:
            _store_back(history, result.back_in_stock)
    for error in result.errors:
        log.warning("Ceny półkowe Biedronki (%s): %s", store, error)
    if result.errors:
        failed = result.failed + result.stock_failed
        history.log_event(
            "shelf",
            "error",
            f"Ceny półkowe Biedronki: błędy odczytu ({failed})",
            {"store": store, "count": result.ok, "failed": failed},
        )
    elif result.ok == 0 and result.skipped:  # same 404: zły kod sklepu, nic nie odczytano
        history.log_event(
            "shelf",
            "warn",
            "Ceny półkowe Biedronki: sklep nie zna żadnego produktu",
            {"store": store, "skipped": result.skipped},
        )
    else:
        history.log_event(
            "shelf", "ok", "Ceny półkowe Biedronki: odczytane", {"store": store, "count": result.ok}
        )
    return result


def pending_back(history: History) -> list[str]:
    """EAN-y, które wróciły na półkę i czekają na push (E30.3); zły JSON albo brak ustawienia → `[]`."""
    try:
        value = json.loads(history.get_setting(BACK_KEY) or "[]")
    except ValueError:
        return []
    return [ean for ean in value if isinstance(ean, str)] if isinstance(value, list) else []


def _store_back(history: History, eans: list[str]) -> None:
    """Dopisuje EAN-y do oczekujących (bez duplikatów); trwałe, bo przeżywa nieudaną wysyłkę."""
    merged = sorted({*pending_back(history), *eans})
    history.set_setting(BACK_KEY, json.dumps(merged))


def clear_back(history: History, eans: Iterable[str]) -> None:
    """Usuwa podane EAN-y z oczekujących; wołane po udanym pushu."""
    drop = set(eans)
    current = pending_back(history)
    remaining = sorted(ean for ean in current if ean not in drop)
    if len(remaining) != len(current):
        history.set_setting(BACK_KEY, json.dumps(remaining))


def parse_promo_end(text: str | None, today: date) -> date | None:
    """Koniec okresu z tekstu `od 16.11 do 22.11` (rok = rok `today`, a data >180 dni wstecz to przyszły rok);
    `None`, gdy brak tekstu albo nie da się zbudować daty."""
    match = _PROMO_END_RE.search(text or "")
    if match is None:
        return None
    month, day = int(match.group(2)), int(match.group(1))
    try:
        end = date(today.year, month, day)
        if (today - end).days > _PROMO_YEAR_BACK:
            end = date(today.year + 1, month, day)
    except ValueError:
        return None
    return end


@dataclass(frozen=True)
class ShelfOffer:
    """Obserwowany produkt z ceną półki poniżej Omnibusa (albo zwykłej ceny, gdy Omnibusa brak)."""

    ean: str
    price: float
    was: float
    end: date | None
    card_only: bool
    stock: str | None = None  # E30.3: 'yes'|'low'|'no'|None (nieznany)


def _stored_promo_end(row: ShelfPrice, today: date) -> date | None:
    """Koniec promocji z zapisanej daty `promo_to` (E30.4); zły format albo brak → tekst okresu (stare)."""
    if row.promo_to:
        try:
            return date.fromisoformat(row.promo_to)
        except ValueError:
            pass
    return parse_promo_end(row.promo_from, today)


def shelf_offers(history: History, store: str, today: date) -> list[ShelfOffer]:
    """Promocje półkowe obserwowanych EAN-ów w sklepie `store`: cena niższa niż Omnibus (albo zwykła)."""
    watched = watched_eans(history)
    offers: list[ShelfOffer] = []
    for row in history.shelf_list(store):
        if not row.is_promotion or row.price is None or row.ean not in watched:
            continue
        was = row.omnibus if row.omnibus else row.regular
        if was is None or row.price >= was:
            continue
        end = _stored_promo_end(row, today)
        if end is not None and end < today:  # stary wiersz po nieudanych odczytach: promocja minęła
            continue
        offers.append(ShelfOffer(row.ean, row.price, was, end, row.card_only, row.stock))
    return offers


async def refresh_morning(history: History, service: Any) -> RefreshResult | None:
    """Poranny krok (E29.3): odczyt cen półkowych w sklepie z ustawienia `biedronka_store`, przez pierwsze
    połączone konto Biedronki; `None`, gdy nie ma sklepu albo konta."""
    store = history.get_setting("biedronka_store")
    if not store:
        history.log_event("shelf", "warn", "Ceny półkowe Biedronki: pominięto — brak sklepu", {})
        return None
    slugs = _bdr_slugs(service)
    if not slugs:
        history.log_event("shelf", "warn", "Ceny półkowe Biedronki: pominięto — brak połączonego konta", {})
        return None
    api = await service.chain_api(slugs[0])
    return await refresh(history, api, store)


def partition_eans(
    history: History, store: str, eans: Iterable[str], now: datetime
) -> tuple[list[str], int, int]:
    """Dzieli EAN-y zlecenia: (do odczytu, liczba świeżych ≤7 d, liczba „brak w Biedronce” ≤30 d);
    duplikaty zdejmowane, kolejność zachowana."""
    fresh_since = (now - timedelta(days=FRESH_DAYS)).isoformat(timespec="seconds")
    fresh = {r.ean for r in history.shelf_list(store) if r.fetched_at >= fresh_since}
    absent = set(history.shelf_absent_list(store, now - timedelta(days=ABSENT_DAYS)))
    todo: list[str] = []
    n_fresh = n_absent = 0
    for ean in dict.fromkeys(eans):
        if ean in fresh:
            n_fresh += 1
        elif ean in absent:
            n_absent += 1
        else:
            todo.append(ean)
    return todo, n_fresh, n_absent


async def refresh_eans(
    history: History,
    api: Any,
    store: str,
    eans: Iterable[str],
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    now: datetime | None = None,
) -> RefreshResult:
    """Zlecenie Diety (E6b.3b): ceny (bez stanu) podanych EAN-ów, z pominięciem świeżych i „braków”.
    Pierwsze zapytanie jest próbne: błąd inny niż 404 (np. 429) przerywa całość. Dalej partie ≤`BATCH_SIZE`,
    `REQUEST_PAUSE_S` w partii, `BATCH_PAUSE_S` między partiami. 429, błąd sesji albo sieci przerywa pętlę;
    odczyty sprzed błędu zostają zapisane. Nie rzuca wyjątków z API."""
    now = now or datetime.now()
    result = RefreshResult()
    todo, _, _ = partition_eans(history, store, eans, now)
    rows: list[ShelfPrice] = []
    cleared: list[str] = []
    absent: list[str] = []
    aborted = False
    try:
        for index, ean in enumerate(todo):
            if index:
                await sleep(BATCH_PAUSE_S if index % BATCH_SIZE == 0 else REQUEST_PAUSE_S)
            try:
                row = parse_price(store, ean, await api.product_price(store, ean), now)
            except LidlPlusError as err:
                if err.status == 404 and not isinstance(err, (LidlPlusAuthError, LidlPlusCannotConnect)):
                    absent.append(ean)
                    result.skipped += 1
                    continue
                result.failed += 1
                result.errors.append(f"{ean}: {err}")
                # sesja, sieć, 429 i każdy błąd zapytania próbnego kończą zlecenie
                if (
                    isinstance(err, (LidlPlusAuthError, LidlPlusCannotConnect))
                    or err.status == 429
                    or index == 0
                ):
                    aborted = True
                    break
                continue
            except (TypeError, ValueError):
                result.failed += 1
                result.errors.append(f"{ean}: nieznany kształt odpowiedzi")
                if index == 0:  # zapytanie próbne: zmieniony format API — nie ciągniemy reszty
                    aborted = True
                    break
                continue
            result.ok += 1
            if row is None:
                cleared.append(ean)
                absent.append(ean)  # bez ceny: Dieta nie ponawia co noc, wraca po TTL „braków”
            else:
                rows.append(row)
    finally:
        if rows or cleared:
            history.shelf_replace(store, rows, cleared)
        if absent:
            history.shelf_absent_mark(store, absent, now)
        history.shelf_absent_clear(store, [r.ean for r in rows])
    for error in result.errors:
        log.warning("Ceny półkowe Biedronki (%s, zlecenie): %s", store, error)
    meta = {"store": store, "count": result.ok, "failed": result.failed, "absent": len(absent)}
    if aborted:
        history.log_event("shelf", "error", "Ceny półkowe Biedronki (zlecenie): przerwano po błędzie", meta)
    elif result.failed:
        history.log_event("shelf", "warn", "Ceny półkowe Biedronki (zlecenie): błędy odczytu", meta)
    else:
        history.log_event("shelf", "ok", "Ceny półkowe Biedronki (zlecenie): odczytane", meta)
    return result
