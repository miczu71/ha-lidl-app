"""Widok „Ceny” (E7): zmiany cen półkowych rok do roku, inflacja koszyka i cena produktu w czasie."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from lidl.history import PriceChange, PriceOverview, ProductPrices, SpendGroup
from lidl.text import count_text, fmt_date

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


def fmt_pct(value: float) -> str:
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f}%".replace(".", ",")


def delta(pct: float) -> dict[str, str]:
    kind = "up" if pct > 0 else "down" if pct < 0 else "flat"
    return {"kind": kind, "text": fmt_pct(pct), "word": _WORD[kind]}


def _price(value: float, weight: bool) -> str:
    return fmt_pln(value, 2) + ("/kg" if weight else "")


def price_rows(changes: list[PriceChange], href: Callable[[str], str]) -> list[dict[str, Any]]:
    return [
        {
            "name": c.name,
            "href": href(c.art_id),
            "prices": f"{_price(c.old, c.is_weight)} → {_price(c.new, c.is_weight)}",
            "spend": f"{fmt_pln(c.spend)} rocznie",
            "delta": delta(c.pct),
        }
        for c in changes
    ]


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


def product_view(product: ProductPrices, today: date) -> dict[str, Any]:
    """Cena półkowa (schodki, obowiązuje do następnej zmiany) i zapłacona przy każdym zakupie."""
    name, weight, points, change = product.name, product.weight, product.points, product.change
    steps: list[tuple[date, float]] = []
    for p in points:
        if not steps or steps[-1][1] != p.shelf:
            steps.append((date.fromisoformat(p.day), p.shelf))
    dots = [(date.fromisoformat(p.day), p.paid) for p in points]
    best = min(points, key=lambda p: (p.paid, p.day))
    first, last = date.fromisoformat(points[0].day), date.fromisoformat(points[-1].day)
    aria = (
        f"Cena {name} od {fmt_date(first)} do {fmt_date(last)}: na półce od "
        f"{_price(points[0].shelf, weight)} do {_price(points[-1].shelf, weight)}; "
        f"zapłacono najmniej {_price(best.paid, weight)}"
    )
    return {
        "name": name,
        "lead": f"Cena {'za kg' if weight else 'za sztukę'} · "
        + count_text(len(points), "zakup", "zakupy", "zakupów")
        + f" od {fmt_month_year_genitive(first)}",
        "last_shelf": _price(points[-1].shelf, weight),
        "last_date": fmt_date(last),
        "year_ago": _price(change.old, weight) if change else None,
        "delta": delta(change.pct) if change else None,
        "best": _price(best.paid, weight),
        "best_date": fmt_date(date.fromisoformat(best.day)),
        "deals": sum(p.paid <= p.shelf * DEAL for p in points),
        "purchases": len(points),
        "paid_label": "Zapłacono za kg (po rabatach)" if weight else "Zapłacono za sztukę (po rabatach)",
        "chart": build_line(steps, fmt_qty, aria, dots=dots, step=True, last=today),
    }
