"""Widok „Ceny” (E7): zmiany cen półkowych rok do roku, inflacja koszyka i cena produktu w czasie."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

from lidl.history import PriceChange, PriceOverview, PricePoint, ProductPrices, Shrink, SpendGroup
from lidl.text import count_text, fmt_date, fmt_pct

from .chart import LineChart, build_line, fmt_month_year_genitive, fmt_pln, fmt_qty

TOP = 5
TOP_MIN_SPEND = 50  # zł w 12 mies.; drobnica (sezonowe owoce za kilka zł rocznie) nie trafia do top
DEAL = 0.9  # zapłacono najwyżej 90% ceny półkowej = zakup z rabatem
_WORD = {"up": "drożej", "down": "taniej", "flat": "bez zmian"}
_SPLIT = {
    "compared": "Porównane: kupione w obu okresach",
    "no_recent": "Niekupowane w ostatnich 6 miesiącach",
    "no_old_window": "Kupowane wcześniej, ale nie w tych samych miesiącach rok temu",
    "no_history": "Pierwszy zakup w ostatnim roku (nowy produkt albo zmieniony kod lub nazwa)",
}


def delta(pct: float) -> dict[str, str]:
    kind = "up" if pct > 0 else "down" if pct < 0 else "flat"
    return {"kind": kind, "text": fmt_pct(pct), "word": _WORD[kind]}


def fmt_price(value: float, weight: bool) -> str:
    return fmt_pln(value, 2) + ("/kg" if weight else "")


def price_rows(changes: list[PriceChange], href: Callable[[str], str]) -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "href": href(c.art_id),
            "prices": f"{fmt_price(c.old, c.is_weight)} → {fmt_price(c.new, c.is_weight)}",
            "spend": f"{fmt_pln(c.spend)} rocznie",
            "delta": delta(c.pct),
        }
        for c in changes
    ]


def _pack(qty: float, unit: str) -> str:
    """Opakowanie z ilości bazowej: „500 g”, „1,5 l”, „6 szt.”."""
    if unit == "szt":
        return f"{fmt_qty(qty)} szt."
    if qty < 1:
        return f"{fmt_qty(qty * 1000)} {'g' if unit == 'kg' else 'ml'}"
    return f"{fmt_qty(qty)} {unit}"


def shrink_rows(items: list[Shrink], href: Callable[[str], str]) -> list[dict[str, Any]]:
    """Wiersze „Mniej w opakowaniu” (E18); `prices` = gramatura i ceny jednostkowe (macro ma jedno pole)."""
    rows = []
    for s in items:
        packs = f"{_pack(s.old_pack, s.unit)} → {_pack(s.new_pack, s.unit)}"
        rows.append(
            {
                "name": s.name,
                "href": href(s.art_id),
                "prices": f"{packs} · {fmt_pln(s.old_unit, 2)}/{s.unit} → {fmt_pln(s.new_unit, 2)}/{s.unit} · od {fmt_date(date.fromisoformat(s.day))}",
                "shelf": f"{fmt_pln(s.old_shelf, 2)} → {fmt_pln(s.new_shelf, 2)} na półce",
                "delta": delta(s.pct),
            }
        )
    return rows


def top_changes(changes: list[PriceChange]) -> tuple[list[PriceChange], list[PriceChange]]:
    """Największe podwyżki i obniżki produktów z wydatkami od `TOP_MIN_SPEND` (bez produktów bez zmiany)."""
    big = [c for c in changes if c.spend >= TOP_MIN_SPEND]
    ups = [c for c in big if c.pct > 0][:TOP]
    downs = sorted((c for c in big if c.pct < 0), key=lambda c: (c.pct, c.name))[:TOP]
    return ups, downs


def basket_view(overview: PriceOverview) -> dict[str, Any] | None:
    basket = overview.basket
    if basket.pct is None:
        return None
    points = [(date.fromisoformat(m), b.pct) for m, b in overview.series if b.pct is not None]
    chart: LineChart | None = None
    if len(points) >= 2:
        low, high = min(points, key=lambda p: p[1]), max(points, key=lambda p: p[1])
        aria = (
            f"Inflacja koszyka rok do roku, miesięcznie od {fmt_month_year_genitive(points[0][0])}: "
            f"obecnie {fmt_pct(basket.pct)}, najniżej {fmt_pct(low[1])} ({fmt_month_year_genitive(low[0])}), "
            f"najwyżej {fmt_pct(high[1])} ({fmt_month_year_genitive(high[0])})"
        )
        chart = build_line(points, lambda v: f"{fmt_qty(v)}%", aria, zero=True)
    return {
        "delta": delta(basket.pct),
        "products": count_text(basket.products, "produktu", "produktów", "produktów"),
        "coverage": f"{round(basket.coverage * 100)}%",
        "chart": chart,
        "split": _split_rows(overview.split),
        "old_unbought": overview.split["no_recent"].legacy_examples,
        "new_codes": overview.split["no_history"].examples,
    }


def _split_rows(split: dict[str, SpendGroup]) -> list[dict[str, Any]]:
    total = sum(g.spend for g in split.values())

    def value(spend: float, n: int) -> str:
        share = f" · {round(spend / total * 100)}%" if total else ""
        return f"{fmt_pln(spend, 2)} · {count_text(n, 'produkt', 'produkty', 'produktów')}{share}"

    rows = []
    for group, label in _SPLIT.items():  # kolejność grup: tu
        g = split[group]
        legacy = value(g.legacy_spend, g.legacy_products) if g.legacy_products else None
        rows.append({"label": label, "value": value(g.spend, g.products), "legacy": legacy})
    return rows


def _steps(points: Sequence[PricePoint]) -> list[tuple[date, float]]:
    """Schodki ceny półkowej: punkt tylko przy zmianie ceny."""
    steps: list[tuple[date, float]] = []
    for p in points:
        if not steps or steps[-1][1] != p.shelf:
            steps.append((date.fromisoformat(p.day), p.shelf))
    return steps


def product_view(product: ProductPrices, today: date) -> dict[str, Any]:
    """Cena półkowa (schodki, obowiązuje do następnej zmiany) i zapłacona przy każdym zakupie."""
    name, weight, points, change = product.name, product.weight, product.points, product.change
    steps = _steps(points)
    dots = [(date.fromisoformat(p.day), p.paid) for p in points]
    best = min(points, key=lambda p: (p.paid, p.day))
    first, last = date.fromisoformat(points[0].day), date.fromisoformat(points[-1].day)
    aria = (
        f"Cena {name} od {fmt_date(first)} do {fmt_date(last)}: na półce od "
        f"{fmt_price(points[0].shelf, weight)} do {fmt_price(points[-1].shelf, weight)}; "
        f"zapłacono najmniej {fmt_price(best.paid, weight)}"
    )
    unit_chart: LineChart | None = None
    if product.unit_points and product.unit:
        label = "zł/" + product.unit
        steps_u = _steps(product.unit_points)
        dots_u = [(date.fromisoformat(p.day), p.paid) for p in product.unit_points]
        last_u = product.unit_points[-1]
        aria_u = (
            f"Cena {name} za {product.unit} od {fmt_date(first)} do {fmt_date(last)}: na półce od "
            f"{fmt_pln(product.unit_points[0].shelf, 2)}/{product.unit} "
            f"do {fmt_pln(last_u.shelf, 2)}/{product.unit}"
        )
        unit_chart = build_line(
            steps_u, lambda v: f"{fmt_qty(v)} {label}", aria_u, dots=dots_u, step=True, last=today
        )
    return {
        "name": name,
        "unit_chart": unit_chart,
        "unit_label": {"kg": "Cena za kg", "l": "Cena za litr"}.get(product.unit or ""),
        "lead": f"Cena {'za kg' if weight else 'za sztukę'} · "
        + count_text(len(points), "zakup", "zakupy", "zakupów")
        + f" od {fmt_month_year_genitive(first)}",
        "last_shelf": fmt_price(points[-1].shelf, weight),
        "last_date": fmt_date(last),
        "year_ago": fmt_price(change.old, weight) if change else None,
        "delta": delta(change.pct) if change else None,
        "best": fmt_price(best.paid, weight),
        "best_date": fmt_date(date.fromisoformat(best.day)),
        "deals": sum(p.paid <= p.shelf * DEAL for p in points),
        "purchases": len(points),
        "paid_label": "Zapłacono za kg (po rabatach)" if weight else "Zapłacono za sztukę (po rabatach)",
        "chart": build_line(steps, fmt_qty, aria, dots=dots, step=True, last=today),
    }
