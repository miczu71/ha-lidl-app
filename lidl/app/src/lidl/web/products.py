"""Widoki „Produkty” i „Kupony”: stan importu, wiersze list i odmiana liczebników."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from lidl.accounts import Account
from lidl.history import CouponCandidate, History, RankedProduct
from lidl.sync import HistorySync
from lidl.text import count_text, fmt_day_month, fmt_recent

from .chart import fmt_pln

DEFAULT_LIMIT = 8
MORE_STEP = 25
MAX_LIMIT = 200


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
                + fmt_recent(date.fromisoformat(p.last_date)),
                "cycle": cycle,
                "aria": f"Pokaż {p.name} na wykresie",
                "href": link(produkt=p.art_id) + "#wykres",
            }
        )
    return rows


def coupon_rows(candidates: list[CouponCandidate]) -> list[dict[str, Any]]:
    rows = []
    for c in candidates:
        meta = [
            count_text(c.purchases, "zakup", "zakupy", "zakupów"),
            "ostatnio " + fmt_recent(date.fromisoformat(c.last_date)),
        ]
        if c.coupon_uses:
            meta.append(f"kupon {c.coupon_uses}×, {fmt_pln(c.coupon_saved, 2)}")
        if c.promo_saved > 0:
            meta.append(f"promocje {fmt_pln(c.promo_saved, 2)}")
        rows.append({"id": c.art_id, "name": c.name, "meta": meta, "matchable": c.matchable, "on": c.enabled})
    return rows


def coupon_cards(accounts: list[Account], history: History, now: datetime) -> list[dict[str, Any]]:
    """Bieżące kupony każdego połączonego konta ze statusem słownym; daty w czasie lokalnym."""
    cards = []
    for a in accounts:
        if not a.connected:
            continue
        rows = []
        for c in history.account_coupons(a.slug):
            start = datetime.fromisoformat(c["valid_from"])
            end = datetime.fromisoformat(c["valid_to"])
            if end <= now:
                continue
            if c["activated"]:
                kind = "on"
                label = {"activated": "Aktywowany przez add-on", "manual": "Aktywowany ręcznie"}.get(
                    c["status"], "Aktywny"
                )
            elif start > now:
                kind, label = "soon", "Od " + fmt_day_month(start.astimezone().date())
            elif c["status"] == "would":
                kind, label = "would", "Aktywowałbym"
            elif c["status"] == "failed":
                kind, label = "err", "Nie udało się"
            else:
                kind, label = "", ""
            rows.append(
                {
                    "pid": c["promotion_id"],
                    "title": c["title"],
                    "discount": c["discount"],
                    "until": "do " + fmt_day_month(end.astimezone().date()),
                    "kind": kind,
                    "label": label,
                }
            )
        cards.append({"slug": a.slug, "label": a.label, "rows": rows})
    return cards


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
