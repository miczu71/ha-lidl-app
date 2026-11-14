"""Widok zakładki „Kraje” (K6b): zatwierdzanie par produktów zagranicznych z polskimi."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from lidl.history import CatalogItem, History, PairLine, PlPrice
from lidl.packsize import pack_size
from lidl.text import matches

from .chart import fmt_pln

COUNTRY_NAMES = {"CZ": "Czechy", "IT": "Włochy"}
CATALOG_LIMIT = 100000
UNPAIRED_LIMIT = 50  # nazwy bez propozycji AI (ręczne parowanie) pokazywane naraz


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, code)


def _catalog(history: History) -> dict[str, CatalogItem]:
    return {c.art_id: c for c in history.pl_catalog(limit=CATALOG_LIMIT)}


def _price(item: CatalogItem) -> str:
    return fmt_pln(item.last_price, 2)


def proposal_cards(history: History) -> list[dict[str, Any]]:
    """Propozycje do zatwierdzenia; kandydaci spoza katalogu PL są pomijani."""
    catalog = _catalog(history)
    entries = [(p["country"], p["foreign_name"], p["candidates"]) for p in history.pair_list("proposed")]
    # nazwy bez żadnego wiersza (np. bez klucza AI): do ręcznego sparowania przez wyszukiwarkę
    entries += [(c, n, []) for c, n, _ex in history.pair_pending()[:UNPAIRED_LIMIT]]
    cards: list[dict[str, Any]] = []
    for country, foreign_name, candidates in entries:
        sample = history.pair_foreign_sample(country, foreign_name)
        cards.append(
            {
                "country": country,
                "country_name": country_name(country),
                "foreign_name": foreign_name,
                "sample": sample[0] if sample else foreign_name,
                "price": fmt_pln(sample[1], 2) if sample else "",
                "candidates": [
                    {"art_id": a, "name": catalog[a].name, "price": _price(catalog[a])}
                    for a in candidates
                    if a in catalog
                ],
            }
        )
    return cards


def decided_rows(history: History, status: str) -> list[dict[str, Any]]:
    """Zatwierdzone (z nazwą produktu PL albo jego identyfikatorem) i odrzucone pary."""
    catalog = _catalog(history)
    rows: list[dict[str, Any]] = []
    for p in history.pair_list(status):
        art_id = p["pl_art_id"]
        rows.append(
            {
                "country": p["country"],
                "country_name": country_name(p["country"]),
                "foreign_name": p["foreign_name"],
                "pl_name": (catalog[art_id].name if art_id in catalog else art_id) if art_id else "",
            }
        )
    return rows


def search(history: History, q: str, limit: int = 8) -> list[dict[str, str]]:
    """Wyszukiwarka po katalogu PL (bez względu na wielkość liter i ogonki)."""
    q = q.strip()
    if not q:
        return []
    found = [c for c in _catalog(history).values() if matches(c.name, q)]
    return [{"art_id": c.art_id, "name": c.name, "price": _price(c)} for c in found[:limit]]


def has_catalog_item(history: History, art_id: str) -> bool:
    return art_id in _catalog(history)


PL_WINDOW_DAYS = 365


@dataclass(frozen=True)
class PairRow:
    country: str
    country_name: str
    foreign_name: str
    pl_name: str
    unit: str  # „kg” | „l” | „szt”
    pl_price: str
    foreign_price: str
    diff_pct: float
    diff: str


@dataclass(frozen=True)
class Basket:
    country: str
    country_name: str
    foreign_total: str
    pl_total: str
    diff_pct: float
    diff: str
    covered: int
    total: int


@dataclass(frozen=True)
class Missing:
    country: str
    country_name: str
    name: str
    lines: int


@dataclass(frozen=True)
class Comparison:
    rows: list[PairRow]
    baskets: list[Basket]
    missing: list[Missing]


def _pct(foreign: float, pl: float) -> float:
    return round((foreign / pl - 1) * 100, 1)


def _fmt_pct(v: float) -> str:
    v = round(v, 1) + 0.0  # \u22120,0 \u2192 0,0 (bez ujemnego zera)
    return f"{v:+.1f}".replace(".", ",").replace("-", "\u2212") + "%"


def compare(lines: list[PairLine], pl_prices: list[PlPrice], line_counts: dict[str, int]) -> Comparison:
    """Koszyk porównawczy w PLN (czysta funkcja). Dodatni % = za granicą drożej."""
    by_art: dict[str, list[PlPrice]] = defaultdict(list)
    for p in sorted(pl_prices, key=lambda r: r.day):
        by_art[p.art_id].append(p)
    # grupa (kraj, nazwa, tryb) -> [Σ ilość, Σ koszt zagr., Σ koszt PL, nazwa PL]
    groups: dict[tuple[str, str, str], list[Any]] = {}
    missing: dict[tuple[str, str], int] = defaultdict(int)
    covered: dict[str, int] = defaultdict(int)
    for ln in lines:
        window = [
            p
            for p in by_art.get(ln.pl_art_id, [])
            if ln.day - timedelta(days=PL_WINDOW_DAYS) <= p.day < ln.day
        ]
        if not window:
            missing[(ln.country, ln.foreign_name)] += 1
            continue
        last = window[-1]
        pl_avg = sum(p.price * p.qty for p in window) / sum(p.qty for p in window)
        foreign_pln = ln.unit_price * ln.fx_rate
        f_pack, p_pack = pack_size(ln.name), pack_size(last.name)
        if ln.is_weight and last.is_weight:
            unit, qty, f_unit, p_unit = "kg", ln.quantity, foreign_pln, pl_avg
        elif f_pack and p_pack and f_pack[1] == p_pack[1] and f_pack[1] in ("kg", "l"):
            unit, qty = f_pack[1], ln.quantity * f_pack[0]
            f_unit, p_unit = foreign_pln / f_pack[0], pl_avg / p_pack[0]
        else:
            unit, qty, f_unit, p_unit = "szt", ln.quantity, foreign_pln, pl_avg
        covered[ln.country] += 1
        g = groups.setdefault((ln.country, ln.foreign_name, unit), [0.0, 0.0, 0.0, last.name])
        g[0] += qty
        g[1] += qty * f_unit
        g[2] += qty * p_unit
        g[3] = last.name
    rows: list[PairRow] = []
    totals: dict[str, list[float]] = {}
    for (country, foreign_name, unit), (qty, f_cost, p_cost, pl_name) in sorted(groups.items()):
        pct = _pct(f_cost, p_cost)
        rows.append(
            PairRow(
                country, country_name(country), foreign_name, pl_name, unit,
                fmt_pln(p_cost / qty, 2), fmt_pln(f_cost / qty, 2), pct, _fmt_pct(pct),
            )
        )  # fmt: skip
        t = totals.setdefault(country, [0.0, 0.0])
        t[0] += f_cost
        t[1] += p_cost
    baskets = [
        Basket(
            country, country_name(country), fmt_pln(f, 2), fmt_pln(p, 2), _pct(f, p), _fmt_pct(_pct(f, p)),
            covered[country], line_counts.get(country, covered[country]),
        )
        for country, (f, p) in sorted(totals.items())
    ]  # fmt: skip
    return Comparison(
        rows,
        baskets,
        [Missing(c, country_name(c), n, k) for (c, n), k in sorted(missing.items())],
    )
