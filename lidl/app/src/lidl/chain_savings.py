"""Oszczędzanie w Biedronce (E28.5): vouchery, oferty „Tylko dla Ciebie” i Shakeomat z Mojej Biedronki.

Tylko odczyt. Migawka z ostatniego importu trafia do `chain_savings`; panel nie woła API przy wejściu.
Kształt elementu vouchera nie był jeszcze widziany na żywo (spike: konto bez voucherów), więc parser jest
tolerancyjny: nieznane pola pomija, a element bez identyfikatora i nazwy odrzuca.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .history import History

log = logging.getLogger(__name__)

OFFER_KINDS = {"offer", "shakeomat"}
SHAKEOMAT_TYPES = ("SHAKEOMAT", "SHAKEOMAT_2", "SHAKEOMARKA")
J4U_SLUG = "just4you"


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


def _num(value: Any) -> float | None:
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
                _num(item.get("price")),
                _num(item.get("regular_price")),
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
                        _num(item.get("price")),
                        _num(item.get("regular_price")),
                        _text(item, "start"),
                        _text(item, "end"),
                        {
                            "offer_type": offer_type,
                            "unit_price": _num(item.get("unit_price")),
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


async def fetch(api: Any) -> FetchResult:
    """Vouchery i oferty konta; błąd jednej części nie ukrywa drugiej (jej rodzaje w `failed_kinds`)."""
    result = FetchResult()
    try:
        result.rows.extend(parse_coupons(await api.coupons()))
    except Exception as err:
        result.failed_kinds.add("voucher")
        result.errors.append(f"vouchery: {err}")
    try:
        carousel_id = _carousel_id(await api.dashboard())
        if carousel_id is None:
            raise ValueError("dashboard bez karuzeli Just4You")
        result.rows.extend(parse_offers(await api.carousel(carousel_id)))
    except Exception as err:
        result.failed_kinds |= OFFER_KINDS
        result.errors.append(f"dashboard/oferty: {err}")
    return result


async def refresh(history: History, slug: str, api: Any) -> FetchResult:
    result = await fetch(api)
    kinds = {"voucher", "offer", "shakeomat"} - result.failed_kinds
    history.savings_replace(slug, kinds, result.rows)
    for error in result.errors:
        log.warning("Oszczędzanie Biedronki (%s): %s", slug, error)
        history.log_event("sync", "error", f"Oszczędzanie Biedronki: {error}", {"account": slug})
    return result
