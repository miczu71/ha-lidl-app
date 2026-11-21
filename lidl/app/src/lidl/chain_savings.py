"""Oszczędzanie w Biedronce (E28.5): vouchery, oferty „Tylko dla Ciebie” i Shakeomat z Mojej Biedronki.

Tylko odczyt. Migawka z ostatniego importu trafia do `chain_savings`; panel nie woła API przy wejściu.
Kształt elementu vouchera nie był jeszcze widziany na żywo (spike: konto bez voucherów), więc parser jest
tolerancyjny: nieznane pola pomija, a element bez identyfikatora i nazwy odrzuca.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from functools import cache
from typing import Any

from .history import History

log = logging.getLogger(__name__)

SAVINGS_FETCHED_KEY = "savings_fetched_at"  # czas ostatniego udanego odświeżenia migawki (nie wygasa)
OFFER_KINDS = {"offer", "shakeomat"}
SHAKEOMAT_TYPES = ("SHAKEOMAT", "SHAKEOMAT_2", "SHAKEOMARKA")
SHAKE_DRAWN_KEY = "shake_drawn"  # ustawienie: wynik dzisiejszego odsłonięcia {"day": ISO, "items": [...]}
J4U_SLUG = "just4you"
URGENT_DAYS = 3  # voucher kończący się w tylu dniach trafia do porannego powiadomienia


@cache
def _tz() -> Any:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Warsaw")
    except Exception:  # brak bazy stref w obrazie: czas zimowy wystarcza do daty końca
        return timezone(timedelta(hours=1))


def local_date(iso: str | None) -> date | None:
    """Data (czas polski) z znacznika API, np. `2026-11-21T22:59:59Z` → 21 listopada."""
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(_tz()).date()


def local_hhmm(moment: datetime) -> str:
    """Godzina (czas polski) z aware datetime, np. `13:47`."""
    return moment.astimezone(_tz()).strftime("%H:%M")


@dataclass(frozen=True)
class Saving:
    kind: str  # voucher | offer | shakeomat
    ext_id: str
    name: str
    price: float | None
    regular_price: float | None
    valid_from: str | None
    valid_to: str | None
    extra: dict[str, Any]


@dataclass(frozen=True)
class SavedSaving:
    slug: str
    kind: str
    ext_id: str
    name: str
    price: float | None
    regular_price: float | None
    valid_from: str | None
    valid_to: str | None
    extra: dict[str, Any]


@dataclass
class FetchResult:
    rows: list[Saving] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_kinds: set[str] = field(default_factory=set)


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_coupons(data: Any) -> list[Saving]:
    items = data.get("coupons") if isinstance(data, dict) else None
    out: list[Saving] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ext_id = _text(item, "id", "offer_id", "coupon_id")
        name = _text(item, "name", "title")
        if not ext_id or not name:
            continue
        out.append(
            Saving(
                "voucher",
                ext_id,
                name,
                _as_float(item.get("price")),
                _as_float(item.get("regular_price")),
                _text(item, "start", "available_from", "valid_from"),
                _text(item, "end", "available_to", "valid_to"),
                {},
            )
        )
    return out


def parse_offers(carousel: Any) -> list[Saving]:
    items = carousel.get("items") if isinstance(carousel, dict) else None
    out: list[Saving] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        offer_type = item.get("offer_type")
        if item.get("type") in SHAKEOMAT_TYPES or offer_type in SHAKEOMAT_TYPES:
            ext_id = _text(item, "offer_id", "id")
            if ext_id:
                out.append(
                    Saving(
                        "shakeomat",
                        ext_id,
                        "Shakeomat",
                        None,
                        None,
                        _text(item, "available_from"),
                        _text(item, "available_to"),
                        {"offer_type": offer_type or item.get("type")},
                    )
                )
        elif item.get("type") == "SINGLE_PRODUCT_PROMOTION":
            ext_id = _text(item, "id", "offer_id")
            name = _text(item, "name")
            if ext_id and name:
                out.append(
                    Saving(
                        "offer",
                        ext_id,
                        name,
                        _as_float(item.get("price")),
                        _as_float(item.get("regular_price")),
                        _text(item, "start"),
                        _text(item, "end"),
                        {
                            "offer_type": offer_type,
                            "unit_price": _as_float(item.get("unit_price")),
                            "ean": _text(item, "product_main_ean_code"),
                            "card_only": bool(item.get("only_with_moja_biedronka_card")),
                            "limit": _text(item, "limit_message_short", "limit_message"),
                            "from_shakeomat": bool(item.get("from_shakeomat")),
                        },
                    )
                )
    return out


def _carousel_id(dashboard: Any) -> str | None:
    sections = dashboard.get("sections") if isinstance(dashboard, dict) else None
    for section in sections if isinstance(sections, list) else []:
        if (
            isinstance(section, dict)
            and section.get("type") == "Carousels"
            and str(section.get("slug", "")).lower() == J4U_SLUG
            and isinstance(section.get("param"), str)
        ):
            return str(section["param"])
    return None


def _unparsed(data: Any, key: str, parsed: list[Saving]) -> bool:
    """Surowa lista niepusta, a parser nic z niej nie wyciągnął — zmiana kształtu API, nie „brak ofert”."""
    raw = data.get(key) if isinstance(data, dict) else None
    return bool(raw) and isinstance(raw, list) and not parsed


async def fetch(api: Any) -> FetchResult:
    """Vouchery i oferty konta; błąd jednej części nie ukrywa drugiej (jej rodzaje w `failed_kinds`)."""
    result = FetchResult()
    try:
        data = await api.coupons()
        vouchers = parse_coupons(data)
        if _unparsed(data, "coupons", vouchers):
            raise ValueError("vouchery w nieznanym kształcie (nic nie rozpoznano)")
        result.rows.extend(vouchers)
    except Exception as err:
        result.failed_kinds.add("voucher")
        result.errors.append(f"vouchery: {err}")
    try:
        carousel_id = _carousel_id(await api.dashboard())
        if carousel_id is None:
            raise ValueError("dashboard bez karuzeli Just4You")
        data = await api.carousel(carousel_id)
        offers = parse_offers(data)
        if _unparsed(data, "items", offers):
            raise ValueError("karuzela w nieznanym kształcie (nic nie rozpoznano)")
        result.rows.extend(offers)
    except Exception as err:
        result.failed_kinds |= OFFER_KINDS
        result.errors.append(f"dashboard/oferty: {err}")
    return result


def _carry_revealed(history: History, slug: str, rows: list[Saving]) -> list[Saving]:
    """Znacznik „odsłonięty dziś” przeżywa odświeżenie migawki (API nie mówi, który kafelek odsłonięto)."""
    marks = {
        r.ext_id: r.extra["revealed_on"]
        for r in history.savings_list()
        if r.slug == slug and r.kind == "shakeomat" and r.extra.get("revealed_on")
    }
    return [
        replace(r, extra={**r.extra, "revealed_on": marks[r.ext_id]})
        if r.kind == "shakeomat" and r.ext_id in marks
        else r
        for r in rows
    ]


async def refresh(history: History, slug: str, api: Any) -> FetchResult:
    result = await fetch(api)
    result.rows = _carry_revealed(history, slug, result.rows)
    kinds = {"voucher", "offer", "shakeomat"} - result.failed_kinds
    history.savings_replace(slug, kinds, result.rows)
    for error in result.errors:
        log.warning("Oszczędzanie Biedronki (%s): %s", slug, error)
        history.log_event("sync", "error", f"Oszczędzanie Biedronki: {error}", {"account": slug})
    if not result.errors:  # czas migawki dla podpisu w panelu (area „savings”, nie miesza się z importem)
        history.log_event("savings", "ok", "Oszczędzanie Biedronki: migawka odświeżona", {"account": slug})
        history.set_setting(SAVINGS_FETCHED_KEY, datetime.now().isoformat(timespec="seconds"))
    return result


def is_current(valid_to: str | None, today: date) -> bool:
    end = local_date(valid_to)
    return end is None or end >= today


@dataclass
class ShakeResult:
    slug: str
    done: int = 0
    failed: list[str] = field(default_factory=list)
    skipped: int = 0  # HTTP 409: kafelek jeszcze/już niedostępny — nie jest błędem
    new_offers: list[str] = field(default_factory=list)  # oferty, które po odsłonięciu doszły do migawki
    drawn: list[dict[str, Any]] = field(default_factory=list)  # oferty wylosowane (z odpowiedzi odsłonięcia)


def _utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _current_tiles(rows: list[Any], today: date) -> list[Any]:
    return [r for r in rows if r.kind == "shakeomat" and is_current(r.valid_to, today)]


def _open_tiles(rows: list[Any], today: date) -> list[Any]:
    """Kafelki Shakeomatu ważne dziś i jeszcze nieodsłonięte dziś."""
    return [r for r in _current_tiles(rows, today) if r.extra.get("revealed_on") != today.isoformat()]


def _is_ready(row: Any, now: datetime) -> bool:
    start = _utc(row.valid_from)
    return start is None or start <= now


def shake_state(rows: list[Any], today: date, now: datetime) -> tuple[str, datetime | None]:
    """Stan przycisku: `none` (brak kafelka), `ready`, `wait` (+ kiedy dostępny), `done` (odsłonięte)."""
    if not _current_tiles(rows, today):
        return "none", None
    open_ = _open_tiles(rows, today)
    if not open_:
        return "done", None
    if any(_is_ready(r, now) for r in open_):
        return "ready", None
    return "wait", min(t for t in (_utc(r.valid_from) for r in open_) if t is not None)


def drawn_from_reply(reply: Any) -> dict[str, Any] | None:
    """Wylosowana oferta z odpowiedzi odsłonięcia (nazwa, cena, cena regularna, koniec ważności)."""
    if not isinstance(reply, dict):
        return None
    name = _text(reply, "name")
    if not name:
        return None
    return {
        "name": name,
        "price": _as_float(reply.get("price")),
        "regular_price": _as_float(reply.get("regular_price")),
        "end": _text(reply, "end"),
    }


def _valid_drawn(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and all(item.get(k) is None or isinstance(item[k], int | float) for k in ("price", "regular_price"))
        and (item.get("end") is None or isinstance(item["end"], str))
    )


def load_drawn(history: History, today: date) -> list[dict[str, Any]]:
    """Dzisiejszy wynik Shakeomatu (puste, gdy brak, z innego dnia albo uszkodzone)."""
    try:
        data = json.loads(history.get_setting(SHAKE_DRAWN_KEY) or "{}")
    except ValueError:
        log.warning("Shakeomat: uszkodzony zapis wyniku dnia (%s) — pomijam", SHAKE_DRAWN_KEY)
        return []
    items = data.get("items") if isinstance(data, dict) and data.get("day") == today.isoformat() else None
    return [i for i in items if _valid_drawn(i)] if isinstance(items, list) else []


def _save_drawn(history: History, today: date, items: list[dict[str, Any]]) -> None:
    history.set_setting(
        SHAKE_DRAWN_KEY,
        json.dumps({"day": today.isoformat(), "items": [*load_drawn(history, today), *items]}),
    )


async def shake(
    history: History, slug: str, api: Any, today: date, now: datetime | None = None
) -> ShakeResult:
    """Odsłania gotowe oferty Shakeomatu z migawki konta (zapis na koncie: przycisk albo opcja auto).

    Pomija kafelki z `available_from` w przyszłości i odsłonięte dziś. Błąd jednej oferty nie przerywa
    pozostałych. 409 to „jeszcze/już niedostępny”, nie błąd; kafelek bez dat po 409 uznajemy za odsłonięty
    dziś (na żywo zostaje w karuzeli po odsłonięciu), kafelek z datą nie. Błędy trafiają do dziennika
    (Status), bez treści odpowiedzi. Po odsłonięciu migawka jest odświeżana; nowe oferty z różnicy migawek
    to wynik."""
    now = now or datetime.now(UTC)
    result = ShakeResult(slug)
    rows = [r for r in history.savings_list() if r.slug == slug]
    tiles = [r for r in _open_tiles(rows, today) if _is_ready(r, now)]
    offers_before = {r.ext_id for r in rows if r.kind == "offer"}
    reply_keys: list[str] = []
    for tile in tiles:
        try:
            reply = await api.reveal_and_activate(tile.ext_id)
        except Exception as err:
            if getattr(err, "status", None) == 409:
                result.skipped += 1
                if tile.valid_from is None:
                    history.savings_mark_revealed(slug, tile.ext_id, today)
            else:
                result.failed.append(f"{type(err).__name__}: {err}")
            continue
        result.done += 1  # zapis znacznika poza try: jego błąd nie jest błędem odsłonięcia
        history.savings_mark_revealed(slug, tile.ext_id, today)
        if (drawn := drawn_from_reply(reply)) is not None:
            result.drawn.append(drawn)
        else:
            log.warning(
                "Shakeomat Biedronki (%s): odpowiedź odsłonięcia bez nazwy oferty (klucze: %s)",
                slug,
                sorted(reply) if isinstance(reply, dict) else type(reply).__name__,
            )
        if isinstance(reply, dict) and not reply_keys:
            reply_keys = sorted(str(k) for k in reply)  # kształt odpowiedzi PATCH (same klucze, bez wartości)
    drawn_save_failed = False
    if result.drawn:
        try:
            _save_drawn(history, today, result.drawn)
        except (
            Exception
        ):  # zapis wyniku jest poboczny: odsłonięcie się udało i reszta przebiegu ma się dokończyć
            drawn_save_failed = True
            log.exception("Shakeomat Biedronki: zapis wyniku dnia nieudany")
    refresh_failed = False
    if result.done:
        try:
            await refresh(history, slug, api)
            result.new_offers = [
                r.name
                for r in history.savings_list()
                if r.slug == slug and r.kind == "offer" and r.ext_id not in offers_before
            ]
        except Exception:
            refresh_failed = True
            log.exception("Oszczędzanie Biedronki: odświeżenie po Shakeomacie nieudane")
    if tiles:
        history.log_event(
            "daily",
            "error" if result.failed else "ok",
            f"Shakeomat Biedronki: odsłonięto {result.done} z {len(tiles)}"
            + (f", pominięto {result.skipped} (jeszcze niedostępne)" if result.skipped else "")
            + (f"; nowe oferty: {', '.join(result.new_offers)}" if result.new_offers else "")
            + (" (migawka nieodświeżona)" if refresh_failed else "")
            + (f" ({'; '.join(result.failed)})" if result.failed else ""),
            {
                "run": "shakeomat",
                "account": slug,
                "done": result.done,
                "skipped": result.skipped,
                "failed": len(result.failed),
                "reply_keys": reply_keys,
                "refresh_failed": refresh_failed,
                "drawn": len(result.drawn),
                "drawn_save_failed": drawn_save_failed,
            },
        )
    return result


def _bdr_slugs(service: Any) -> list[str]:
    return [a.slug for a in service.store.list() if a.chain == "biedronka" and a.connected]


async def refresh_accounts(history: History, service: Any) -> None:
    """Odświeża migawkę na wszystkich połączonych kontach Biedronki; błąd konta nie zatrzymuje pozostałych."""
    for slug in _bdr_slugs(service):
        try:
            await refresh(history, slug, await service.chain_api(slug))
        except Exception as err:
            log.exception("Oszczędzanie Biedronki: odświeżenie nieudane")
            history.log_event("sync", "error", f"Oszczędzanie Biedronki: {err}", {"account": slug})


async def shake_accounts(history: History, service: Any, today: date) -> list[ShakeResult]:
    """Shakeomat na wszystkich połączonych kontach Biedronki; błąd konta nie zatrzymuje pozostałych."""
    results: list[ShakeResult] = []
    for slug in _bdr_slugs(service):
        try:
            api = await service.chain_api(slug)
            await refresh(history, slug, api)  # migawka z importu w tle bywa nieświeża (dzisiejszy Shakeomat)
            results.append(await shake(history, slug, api, today))
        except Exception as err:
            log.exception("Shakeomat Biedronki (%s) nieudany", slug)
            history.log_event(
                "daily", "error", f"Shakeomat Biedronki: {err}", {"run": "shakeomat", "account": slug}
            )
            results.append(ShakeResult(slug, failed=[f"{type(err).__name__}: {err}"]))
    return results
