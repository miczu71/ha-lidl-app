"""Oszczędności z kuponów i promocji (E27): czysta logika bez SQL, używana przez `savings_breakdown`."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

COUPON_LABELS = frozenset({"lidl plus kupon", "lidl plus voucher"})
GROUP_OTHER = "Inne"
GROUP_MULTI = "Kilka promocji naraz"
_PERCENT = re.compile(r"rabat -\d+(?:[.,]\d+)?%")
_TANIEJ = re.compile(r"taniej za \d+")


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", _norm(text).replace("ł", "l"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_coupon_label(label: str) -> bool:
    return _norm(label) in COUPON_LABELS


def classify_promo(label: str) -> tuple[str, str]:
    """Grupa promocji i dokładna etykieta (spacje scalone, wielkość liter bez zmian)."""
    exact = " ".join(label.split())
    key = _norm(label)
    if _PERCENT.fullmatch(key):
        return "Rabat procentowy", exact
    if key == "rabat grupowy":
        return "Rabat grupowy", exact
    if _TANIEJ.fullmatch(key):
        return "Taniej za N", exact
    if key == "lidl plus rabat":
        return "Lidl Plus rabat", exact
    if key in COUPON_LABELS:
        return "Kupon", exact
    return GROUP_OTHER, exact


def split_promo(promo: str) -> list[str]:
    return [part.strip() for part in promo.split("; ") if part.strip()]


def promo_group(labels: list[str]) -> tuple[str, str]:
    """Grupa i etykieta dla części promocyjnej pozycji (etykiety kuponowe już odjęte)."""
    if not labels:
        return GROUP_OTHER, "(bez etykiety)"
    if len(labels) == 1:
        return classify_promo(labels[0])
    return GROUP_MULTI, "; ".join(labels)


def match_title(item_name: str, coupons: list[dict[str, str]]) -> dict[str, str] | None:
    """Kupon z `ticket_coupons` pasujący do nazwy pozycji: najpierw równe tytuły, potem zawarte."""
    name = _fold(item_name)
    titles = [(_fold(c["title"]), c) for c in coupons if _fold(c["title"])]
    for title, coupon in titles:
        if title == name:
            return coupon
    for title, coupon in titles:
        if title in name:
            return coupon
    return None


@dataclass(frozen=True)
class CouponRow:
    art_id: str  # kod produktu po moście nazw (jak w Produktach)
    name: str
    amount: float  # zł z kuponów na produkt
    uses: int  # liczba różnych paragonów z kuponem na produkt
    last_day: str
    title: str | None  # tytuł kuponu z paragonu, jeśli pasuje do pozycji
    discount: str | None


@dataclass(frozen=True)
class PromoGroup:
    name: str
    amount: float
    labels: list[tuple[str, float]]  # dokładne etykiety z kwotami, malejąco


@dataclass(frozen=True)
class SavingsMonth:
    month: str  # RRRR-MM
    coupons: float
    promos: float


@dataclass(frozen=True)
class Savings:
    """Rozbicie oszczędności. `coupons_total` = kupony z pozycji, `promos_total` = rabaty pozycji bez kuponów.
    `general_coupons_amount` (różnica nagłówka paragonu i pozycji, ≥0 per paragon) jest raportowany OSOBNO:
    nie wchodzi do `coupons_total`, `promos_total`, `coupon_rows` ani `groups`."""

    coupons_total: float
    promos_total: float
    spend_total: float
    months: list[SavingsMonth]
    coupon_rows: list[CouponRow]
    general_coupons_amount: float
    repeat_products: int  # produkty z kuponem na ≥2 paragonach
    groups: list[PromoGroup]
