"""Zakładka „Oszczędności” (E27): widok `History.savings_breakdown` — KPI, ranking kuponów, promocje."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from lidl.savings import CouponRow, PromoGroup, Savings
from lidl.text import count_text, fmt_date, fmt_pln


@dataclass(frozen=True)
class CouponView:
    name: str
    href: str
    amount: str
    uses: str
    average: str
    last: str
    title: str | None  # tytuł kuponu z paragonu (gdy pasuje do pozycji)
    discount: str | None
    repeat: bool


@dataclass(frozen=True)
class GroupView:
    name: str
    amount: str
    share: int  # % promocji, na pasek
    labels: list[tuple[str, str]]


@dataclass(frozen=True)
class SavingsView:
    coupons: str
    promos: str
    total: str
    percent: str | None  # % wydatków okresu (rabaty / (wydatki + rabaty))
    rows: list[CouponView]
    repeat: str
    general: str | None
    groups: list[GroupView]


def _coupon_view(r: CouponRow, href: Callable[[str], str]) -> CouponView:
    return CouponView(
        name=r.name,
        href=href(r.art_id),
        amount=fmt_pln(r.amount, 2),
        uses=f"{r.uses}×",
        average=fmt_pln(r.amount / r.uses, 2),
        last=fmt_date(date.fromisoformat(r.last_day)),
        title=r.title,
        discount=r.discount,
        repeat=r.uses >= 2,
    )


def _group_view(g: PromoGroup, promos_total: float) -> GroupView:
    return GroupView(
        name=g.name,
        amount=fmt_pln(g.amount, 2),
        share=round(100 * g.amount / promos_total) if promos_total else 0,
        labels=[(label, fmt_pln(v, 2)) for label, v in g.labels],
    )


def savings_view(s: Savings, href: Callable[[str], str]) -> SavingsView:
    total = s.coupons_total + s.promos_total
    base = s.spend_total + total  # wydatki są już po rabatach
    return SavingsView(
        coupons=fmt_pln(s.coupons_total, 2),
        promos=fmt_pln(s.promos_total, 2),
        total=fmt_pln(total, 2),
        percent=f"{100 * total / base:.1f}".replace(".", ",") + "%" if base > 0 else None,
        rows=[_coupon_view(r, href) for r in s.coupon_rows],
        repeat=count_text(s.repeat_products, "produkt", "produkty", "produktów"),
        general=fmt_pln(s.general_coupons_amount, 2) if s.general_coupons_amount > 0.004 else None,
        groups=[_group_view(g, s.promos_total) for g in s.groups],
    )
