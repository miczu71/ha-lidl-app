"""Widok zakładki „Kraje” (K6b): zatwierdzanie par produktów zagranicznych z polskimi."""

from __future__ import annotations

from typing import Any

from lidl.history import CatalogItem, History
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
