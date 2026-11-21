"""Widok wyszukiwarki E31: zbiór EAN-ów znanych historii i wiersze wyników (bez I/O poza `History`)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from lidl.history import History
from lidl.search import SearchHit, ean_of
from lidl.text import CHAIN_LABELS, fmt_day_month, fmt_pln

LIDL_CODE_RE = re.compile(r"\d{7}")

KIND_LABELS = {
    "bought": "Kupowane",
    "offer": "Oferta",
    "promo": "Promocja",
    "coupon": "Kupon",
    "catalog": "Katalog",
}


def known_eans(history: History) -> set[str]:
    """EAN-y z kupowanych produktów (`b:`/`n:` + 8–14 cyfr) i z ofert Biedronki w karuzeli."""
    eans: set[str] = set()
    for p in history.ranking():
        if code := ean_of(p.art_id):
            eans.add(code)
    for s in history.savings_list():
        if s.kind == "offer" and s.extra.get("ean"):
            eans.add(str(s.extra["ean"]))
    return eans


def _day(iso: str | None) -> date | None:
    return date.fromisoformat(iso[:10]) if iso else None


def _watch_key(h: SearchHit) -> str | None:
    if h.chain == "biedronka" and h.ean:
        return f"b:{h.ean}"
    if h.chain == "lidl":
        return h.key or None
    return None


def rows(hits: Iterable[SearchHit], watched: set[str]) -> list[dict[str, Any]]:
    """Wiersze listy wyników dla szablonu `_search_results.html`."""
    out: list[dict[str, Any]] = []
    for h in hits:
        last = _day(h.last_date)
        until = _day(h.until)
        watch_key = _watch_key(h)
        history = f"kupowane {h.purchases}× · ostatnio {fmt_day_month(last)}" if h.purchases and last else ""
        out.append(
            {
                "chain": h.chain,
                "chain_label": CHAIN_LABELS.get(h.chain, h.chain),
                "kind_label": KIND_LABELS.get(h.kind, h.kind),
                "name": h.name,
                "price": fmt_pln(h.price, 2) if h.price is not None else "",
                "history": history,
                "until": f"do {fmt_day_month(until)}" if until else "",
                "ean": h.ean or "",
                "can_stock": h.chain == "biedronka" and bool(h.ean),
                "watch_key": watch_key,
                "watched": watch_key is not None and watch_key in watched,
            }
        )
    return out
