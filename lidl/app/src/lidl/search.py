"""Wspólna wyszukiwarka E31: paragony, oferty, promocje i kupony Lidla i Biedronki, katalog Biedronki.

`search_all` jest czystą funkcją: czyta historię i podane listy, bez sieci i zapisów. Zdalne wyniki
(`products/search` Biedronki) przychodzą z zewnątrz i trafiają do `catalog`, a cache zapytań trzyma je krótko.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Protocol

from .history import History
from .promotions import Promotion
from .text import _fold, matches

EAN_RE = re.compile(r"\d{8,14}")


@dataclass(frozen=True)
class SearchHit:
    """Jeden wynik wyszukiwania; `kind` to bought|offer|promo|coupon|catalog."""

    kind: str
    chain: str
    name: str
    key: str | None = None
    ean: str | None = None
    price: float | None = None
    purchases: int = 0
    last_date: str | None = None
    until: str | None = None


class _ProductSearch(Protocol):
    async def product_search(self, query: str) -> list[dict[str, Any]]: ...


def ean_of(art_id: str) -> str | None:
    """EAN z kodu `b:<EAN>` / `n:<EAN>`; nazwy zastępcze (`b:<nazwa>`) nie są EAN-em."""
    code = art_id[2:] if art_id[:2] in ("b:", "n:") else ""
    return code if EAN_RE.fullmatch(code) else None


def _active(start: str | None, end: str | None, today: date) -> bool:
    """Ważność ISO (od/do), pusta granica = bez ograniczenia."""
    if start and start[:10] > today.isoformat():
        return False
    return not (end and end[:10] < today.isoformat())


def _plain(name: str) -> str:
    return _fold(" ".join(name.split()))


def search_all(
    history: History,
    query: str,
    *,
    today: date,
    promos: Iterable[Promotion] = (),
    remote: Iterable[dict[str, Any]] = (),
    limit: int = 30,
) -> list[SearchHit]:
    """Łączy źródła wyszukiwania w jedną listę: kupowane, oferty, promocje, kupony, katalog (zdalny)."""
    if not query.strip():
        return []

    # a) produkty z paragonów (kupowane wcześniej, z historią zakupów)
    bought: list[SearchHit] = []
    for p in history.ranking(query=query):
        bought.append(
            SearchHit(
                kind="bought",
                chain="biedronka" if p.art_id.startswith("b:") else "lidl",
                name=p.name,
                key=p.art_id,
                ean=ean_of(p.art_id),
                price=p.last_price,
                purchases=p.purchases,
                last_date=p.last_date,
            )
        )
    by_ean = {h.ean: i for i, h in enumerate(bought) if h.ean}
    by_key = {h.key: i for i, h in enumerate(bought) if h.key}
    hits = list(bought)

    # b) oferty Biedronki z karuzeli; gdy produkt już kupowany, tylko dopisuje ważność i cenę oferty
    for s in history.savings_list():
        if s.kind != "offer" or not matches(s.name, query) or not _active(s.valid_from, s.valid_to, today):
            continue
        ean = s.extra.get("ean") or None
        if ean and ean in by_ean:
            i = by_ean[ean]
            hits[i] = replace(hits[i], until=s.valid_to, price=s.price)
            continue
        hits.append(
            SearchHit(
                kind="offer",
                chain="biedronka",
                name=s.name,
                ean=ean,
                price=s.price,
                until=s.valid_to,
            )
        )

    # c) promocje Lidla: lista z `promotions.py` i gazetka; kupiony produkt dostaje tylko datę końca
    promo_rows: list[Promotion] = list(promos)
    for art_id, title, discount, start, end in history.leaflet_matches_active(today):
        promo_rows.append(
            Promotion(art_id, title, discount, date.fromisoformat(start), date.fromisoformat(end))
        )
    seen_promo: set[str] = set()
    for pr in promo_rows:
        if pr.art_id in seen_promo or pr.end < today or pr.start > today or not matches(pr.title, query):
            continue
        seen_promo.add(pr.art_id)
        if pr.art_id in by_key:
            i = by_key[pr.art_id]
            hits[i] = replace(hits[i], until=pr.end.isoformat())
            continue
        hits.append(
            SearchHit(
                kind="promo",
                chain="lidl",
                name=pr.title,
                key=pr.art_id,
                until=pr.end.isoformat(),
            )
        )

    # d) kupony Lidla (bieżąca lista, nie zarchiwizowane)
    for title, valid_to in history.coupons_active(today):
        if matches(title, query):
            hits.append(
                SearchHit(
                    kind="coupon",
                    chain="lidl",
                    name=title,
                    until=valid_to,
                )
            )

    # e) katalog Biedronki po nazwie (zdalnie, bez EAN i ceny); pomija nazwy, które już są na liście
    known = {_plain(h.name) for h in hits}
    for item in remote:
        name = str(item.get("name") or "")
        if not name or not matches(name, query) or _plain(name) in known:
            continue
        known.add(_plain(name))
        hits.append(SearchHit(kind="catalog", chain="biedronka", name=name))

    order = {"bought": 0, "offer": 1, "promo": 2, "coupon": 3, "catalog": 4}
    hits.sort(key=lambda h: (order[h.kind], -h.purchases))
    return hits[:limit]


class BiedronkaSearchCache:
    """Cache wyników `products/search` Biedronki w pamięci (TTL, bez zmiany schematu bazy).

    Klucz to złożona fraza, więc „Masło” i „masło” dzielą wynik; wyjątek z API nie jest zapamiętywany.
    """

    def __init__(self, ttl: float = 600, now: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._now = now
        self._items: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def names(self, api: _ProductSearch, query: str) -> list[dict[str, Any]]:
        key = _fold(query).strip()
        if len(key) < 3:
            return []
        t = self._now()
        hit = self._items.get(key)
        if hit and t - hit[0] < self._ttl:
            return list(hit[1])
        rows = await api.product_search(query)
        self._items = {k: v for k, v in self._items.items() if t - v[0] < self._ttl}
        self._items[key] = (t, rows)
        return list(rows)
