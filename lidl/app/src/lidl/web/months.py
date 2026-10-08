"""Widok „Miesiące” (E19): podsumowanie miesiąca w stylu „Wrapped”, wspólne dla domu."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from lidl.history import MonthProduct, MonthSummary
from lidl.text import count_text, fmt_date, fmt_in_month, month_bounds

from .chart import fmt_month_year, fmt_month_year_genitive, fmt_pln, fmt_qty
from .prices import delta

_WEEKDAYS = ["poniedziałki", "wtorki", "środy", "czwartki", "piątki", "soboty", "niedziele"]
BANNER_DAYS = 7  # tyle dni od 1. strona główna (tu otwiera powiadomienie) prowadzi do podsumowania


def default_month(months: Iterable[str], today: date) -> str | None:
    """Ostatni pełny miesiąc z zakupami; bez takiego najnowszy (w toku)."""
    known = sorted(months)
    full = [m for m in known if m < today.strftime("%Y-%m")]
    return full[-1] if full else (known[-1] if known else None)


def _compare(paid: float, other: float | None, label: str) -> dict[str, Any] | None:
    if not other:
        return None
    return {"delta": delta(round((paid - other) / other * 100, 1)), "label": label}


def _products(
    items: list[MonthProduct], href: Callable[[str], str], amount: Callable[[float], str]
) -> list[dict[str, Any]]:
    """Wiersze produktów z paskiem względem pierwszego (listy są od największej wartości)."""
    top = max((p.value for p in items), default=0.0) or 1.0
    return [
        {"name": p.name, "href": href(p.art_id), "amount": amount(p.value), "bar": round(p.value / top * 100)}
        for p in items
    ]


def month_view(
    s: MonthSummary,
    labels: Mapping[str, str],
    first_month: str,
    *,
    today: date,
    product_href: Callable[[str], str],
    receipt_href: Callable[[str], str],
) -> dict[str, Any]:
    start, _ = month_bounds(s.month)
    t = s.totals
    stats = [
        {"label": "Wizyty", "value": str(t.tickets)},
        {"label": "Średni paragon", "value": fmt_pln(t.paid / t.tickets, 2)},
        {"label": "Zaoszczędziliśmy", "value": fmt_pln(s.savings, 2), "save": True},
    ]
    if s.coupons > 0:
        stats.append({"label": "W tym kupony", "value": fmt_pln(s.coupons, 2), "save": True})
    if t.charged or t.refunded:
        stats.append(
            {
                "label": "Kaucje pobrane / zwrócone",
                "value": f"{fmt_pln(t.charged, 2)} / {fmt_pln(t.refunded, 2)}",
            }
        )
    rhythm = f"Najczęściej {_WEEKDAYS[s.weekday]}"
    if s.hour is not None:
        rhythm += f", około {s.hour}:00"
    b = s.biggest
    shares = [
        {
            "name": labels.get(a, a),
            "visits": count_text(n, "wizyta", "wizyty", "wizyt"),
            "paid": fmt_pln(paid, 2),
            "share": round(paid / t.paid * 100) if t.paid else 0,
        }
        for a, (n, paid) in sorted(s.accounts.items(), key=lambda kv: -kv[1][1])
    ]
    last_no = s.first_no + t.tickets - 1
    in_progress = s.month == today.strftime("%Y-%m")  # porównania i miejsce dopiero po końcu miesiąca
    compare = [
        _compare(t.paid, s.prev_paid, "niż " + fmt_in_month(start - timedelta(days=1))),
        _compare(t.paid, s.year_ago_paid, "niż " + fmt_in_month(start.replace(year=start.year - 1), True)),
    ]

    def money(value: float) -> str:
        return fmt_pln(value, 2)

    return {
        "in_month": fmt_in_month(start),
        "in_progress": in_progress,
        "paid": fmt_pln(t.paid, 2),
        "compare": [] if in_progress else [c for c in compare if c],
        "stats": stats,
        "top_spend": _products(s.top_spend, product_href, money),
        "top_quantity": _products(s.top_quantity, product_href, lambda q: f"{fmt_qty(q)} szt."),
        "new_products": _products(s.new_products, product_href, money),
        "best_saving": s.best_saving and _products([s.best_saving], product_href, money)[0],
        "biggest": {
            "amount": fmt_pln(b.total, 2),
            "when": fmt_date(date.fromisoformat(b.day)) + (f", {b.time}" if b.time else ""),
            "where": b.store or "Sklep nieznany",
            "who": labels.get(b.account, b.account),
            "href": receipt_href(b.id),
        },
        "rhythm": rhythm,
        "store": s.store
        and s.store.tickets > 1
        and {
            "name": s.store.name,
            "visits": f"{s.store.tickets} z {count_text(t.tickets, 'wizyty', 'wizyt', 'wizyt')}",
        },
        "accounts": shares if len(shares) > 1 else [],
        "all_time": fmt_pln(s.all_time_paid),
        "since": fmt_month_year_genitive(month_bounds(first_month)[0]),
        "tickets_range": f"{s.first_no}–{last_no}" if last_no > s.first_no else str(s.first_no),
        "rank": None if in_progress else s.rank,
        "months": s.months,
    }


def month_banner(months: Callable[[], Mapping[str, Any]], today: date) -> str | None:
    """„września 2026”, gdy w pierwszym tygodniu miesiąca jest podsumowanie poprzedniego; inaczej None
    (`months` — miesiące z zakupami — czytane tylko w tym tygodniu)."""
    prev = today.replace(day=1) - timedelta(days=1)
    if today.day > BANNER_DAYS or prev.strftime("%Y-%m") not in months():
        return None
    return fmt_month_year_genitive(prev)


def month_nav(months: Iterable[str], current: str, href: Callable[[str], str]) -> dict[str, Any]:
    """Poprzedni i następny miesiąc z zakupami oraz wszystkie do wyboru (od najnowszego, z bieżącym)."""
    known = sorted(months)
    i = known.index(current) if current in known else None
    return {
        "prev": href(known[i - 1]) if i else None,
        "next": href(known[i + 1]) if i is not None and i + 1 < len(known) else None,
        "options": [
            {"value": m, "label": fmt_month_year(month_bounds(m)[0]), "on": m == current}
            for m in sorted({*known, current}, reverse=True)
        ],
    }
