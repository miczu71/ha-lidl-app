"""Ceny półkowe Biedronki (E29.2): „dziś na półce” z aplikacji Moja Biedronka dla obserwowanych
produktów kupionych w Biedronce i zatwierdzonych par Lidl↔Biedronka. Odczyt raz dziennie w porannym przebiegu;
błąd jednego EAN nie zatrzymuje reszty, a stare wiersze zostają."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .chain_savings import _bdr_slugs
from .client.exceptions import LidlPlusAuthError, LidlPlusError
from .history import History, ShelfPrice

log = logging.getLogger(__name__)

MAX_EANS = 60  # limit zapytań dziennie (E29.1: ≤60/dzień, ≤1/s)
REQUEST_PAUSE_S = 1.0
_EAN_RE = re.compile(r"\d{8,13}")
_PROMO_END_RE = re.compile(r"do\s+(\d{1,2})\.(\d{1,2})")
_PROMO_YEAR_BACK = 180  # data końca więcej niż tyle dni przed dziś = przełom roku


@dataclass
class RefreshResult:
    ok: int = 0  # odczyty bez błędu (także bez ceny: „DRUGI ZA x zł”)
    skipped: int = 0  # HTTP 404: nieznany EAN albo zły sklep — nie jest błędem
    failed: int = 0
    errors: list[str] = field(default_factory=list)


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
        promo_to=None,
        card_only=bool(data.get("only_with_biedronka_card")),
        is_promotion=bool(data.get("is_promotion")),
        fetched_at=now.isoformat(timespec="seconds"),
    )


async def refresh(
    history: History,
    api: Any,
    store: str,
    *,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> RefreshResult:
    """Odczytuje ceny półkowe dla `targets` w sklepie `store`; zapisuje tylko udane odczyty.
    `LidlPlusAuthError` przerywa pętlę (odczyty z przed błędu zostają zapisane) i idzie dalej w górę."""
    result = RefreshResult()
    rows: list[ShelfPrice] = []
    cleared: list[str] = []
    now = datetime.now()
    try:
        for index, ean in enumerate(targets(history)):
            if index:
                await sleep(REQUEST_PAUSE_S)
            try:
                row = parse_price(store, ean, await api.product_price(store, ean), now)
            except LidlPlusAuthError:
                raise
            except LidlPlusError as err:
                if err.status == 404:
                    result.skipped += 1
                else:
                    result.failed += 1
                    result.errors.append(f"{ean}: {err}")
                continue
            except (TypeError, ValueError):
                result.failed += 1
                result.errors.append(f"{ean}: nieznany kształt odpowiedzi")
                continue
            result.ok += 1
            if row is not None:
                rows.append(row)
            else:
                cleared.append(ean)
    finally:
        if rows or cleared:
            history.shelf_replace(store, rows, cleared)
    for error in result.errors:
        log.warning("Ceny półkowe Biedronki (%s): %s", store, error)
    if result.errors:
        history.log_event(
            "shelf",
            "error",
            f"Ceny półkowe Biedronki: błędy odczytu ({result.failed})",
            {"store": store, "count": result.ok, "failed": result.failed},
        )
    else:
        history.log_event(
            "shelf", "ok", "Ceny półkowe Biedronki: odczytane", {"store": store, "count": result.ok}
        )
    return result


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
        offers.append(
            ShelfOffer(row.ean, row.price, was, parse_promo_end(row.promo_from, today), row.card_only)
        )
    return offers


async def refresh_morning(history: History, service: Any) -> RefreshResult | None:
    """Poranny krok (E29.3): odczyt cen półkowych w sklepie z ustawienia `biedronka_store`, przez pierwsze
    połączone konto Biedronki; `None`, gdy nie ma sklepu albo konta."""
    store = history.get_setting("biedronka_store")
    if not store:
        return None
    slugs = _bdr_slugs(service)
    if not slugs:
        return None
    api = await service.chain_api(slugs[0])
    return await refresh(history, api, store)
