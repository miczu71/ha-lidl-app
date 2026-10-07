"""Widok „Produkty”: stan importu, wiersze rankingu i odmiana liczebników."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

from lidl.accounts import Account
from lidl.history import History, RankedProduct
from lidl.sync import HistorySync

from .chart import fmt_day_month, fmt_pln

DEFAULT_LIMIT = 8
MORE_STEP = 25
MAX_LIMIT = 200


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count_text(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def parse_limit(raw: str | None) -> int:
    try:
        return min(max(int(raw or DEFAULT_LIMIT), 1), MAX_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT


def ranking_rows(ranking: list[RankedProduct], limit: int, link: Callable[..., str]) -> list[dict[str, Any]]:
    rows = []
    for pos, p in enumerate(ranking[:limit], start=1):
        if p.cycle_days is None:
            cycle = "jednorazowo"
        else:
            days = round(p.cycle_days)
            cycle = "co dzień" if days <= 1 else f"co {days} dni"
        rows.append(
            {
                "pos": pos,
                "name": p.name,
                "count": count_text(p.purchases, "zakup", "zakupy", "zakupów"),
                "last": f"ostatnio {fmt_pln(p.last_price, 2)}, "
                + fmt_day_month(date.fromisoformat(p.last_date)),
                "cycle": cycle,
                "aria": f"Pokaż {p.name} na wykresie",
                "href": link(produkt=p.art_id) + "#wykres",
            }
        )
    return rows


def import_status(sync: HistorySync, history: History, accounts: list[Account]) -> dict[str, Any]:
    """Jeden stan dla całego domu: running > error > empty > ok."""
    progress = [sync.progress(a.slug) for a in accounts]
    running = [p for p in progress if p.running]
    if running:
        done, total = sum(p.done for p in running), sum(p.total for p in running)
        eta = math.ceil((total - done) * sync.pause / 60) if total else 0
        return {"state": "running", "done": done, "total": total, "eta": max(eta, 1)}
    errors = [p for p in progress if p.error]
    if errors:
        return {"state": "error", "done": sum(p.done for p in errors), "total": sum(p.total for p in errors)}
    if history.ticket_count() == 0:
        return {"state": "empty"}
    return {"state": "ok"}
