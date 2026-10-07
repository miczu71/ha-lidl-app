"""Widoki „Produkty” i „Kupony”: stan importu, wiersze list i odmiana liczebników."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from lidl.accounts import Account
from lidl.history import CouponCandidate, History, RankedProduct
from lidl.rewards import Rewards
from lidl.sync import HistorySync
from lidl.text import count_text, fmt_day_month, fmt_recent, fmt_until, matches

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


def coupon_cards(
    accounts: list[Account], history: History, now: datetime, q: str = ""
) -> list[dict[str, Any]]:
    """Bieżące kupony każdego połączonego konta ze statusem słownym (daty w czasie lokalnym) i znacznikiem
    „wspólny” / „tylko <konto>” (ten sam tytuł i rabat na wszystkich kontach); liczniki z całej listy, wiersze
    zawężone do frazy `q`."""
    cards: list[dict[str, Any]] = []
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
    # wspólny = ten sam tytuł i rabat na wszystkich kontach; None przy jednym koncie (bez znaczników)
    common = (
        set.intersection(*({(r["title"], r["discount"]) for r in c["rows"]} for c in cards))
        if cards
        else set()
    )
    for card in cards:
        rows = card["rows"]
        for r in rows:
            r["shared"] = (r["title"], r["discount"]) in common if len(cards) > 1 else None
        card.update(
            total=len(rows),
            active=sum(r["kind"] == "on" for r in rows),
            only=sum(r["shared"] is False for r in rows),
            rows=[r for r in rows if matches(r["title"], q)],
        )
    return cards


def _pln(value: float) -> str:
    """Kwota bez łamania wiersza w środku („500 zł”, „1 000 zł”)."""
    return fmt_pln(value, 0 if value == int(value) else 2).replace(" ", " ")


def reward_cards(rewards: dict[str, Rewards], today: date) -> list[dict[str, Any]]:
    """Nagrody kont do panelu: zdrapki (ważność słowem) i Kupon Plus jako pasek — progi w pozycjach
    proporcjonalnych do kwoty (ostatni próg = koniec paska), jak w aplikacji."""
    cards = []
    for label, r in rewards.items():
        scratch = []
        for c in r.scratch_cards:
            ends = c.expires.astimezone().date()
            scratch.append(
                {
                    "created": fmt_day_month(c.created.astimezone().date()),
                    "until": fmt_until(ends, today),
                    "last": ends == today,
                }
            )
        plus = None
        cp = r.coupon_plus
        if cp and cp.goals:
            top = cp.goals[-1].value or 1
            nxt = cp.next_goal
            plus = {
                "reached": _pln(cp.reached),
                "pct": round(min(cp.reached / top, 1) * 100, 2),
                "goals": [
                    {"pct": round(g.value / top * 100, 2), "value": _pln(g.value), "won": g.won}
                    for g in cp.goals
                ],
                "next": nxt
                and {
                    "prize": nxt.prize,
                    "discount": nxt.discount,
                    "value": _pln(nxt.value),
                    "missing": _pln(nxt.value - cp.reached),
                },
                # jak w aplikacji: dzień końca liczy się do końca
                "days": count_text((cp.ends - today).days + 1, "dzień", "dni", "dni"),
                "ends": fmt_day_month(cp.ends),
            }
        cards.append({"label": label, "scratch": scratch, "plus": plus})
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
