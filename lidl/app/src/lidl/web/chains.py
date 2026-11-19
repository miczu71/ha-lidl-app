"""Widok zakładki „Sieci” (E28.4.2): zatwierdzanie par „produkt Biedronki → produkt Lidla”."""

from __future__ import annotations

from typing import Any

from lidl.history import CatalogItem, History
from lidl.text import matches

from .chart import fmt_pln

CATALOG_LIMIT = 100000
UNPAIRED_LIMIT = 50  # produkty bez propozycji AI (ręczne parowanie) pokazywane naraz
SOURCE_LABELS = {"ean": "EAN", "ai": "AI", "manual": "ręcznie"}


def lidl_catalog(history: History) -> dict[str, CatalogItem]:
    return {c.art_id: c for c in history.chain_catalog("lidl", limit=CATALOG_LIMIT)}


def _biedronka(history: History) -> dict[str, CatalogItem]:
    return {c.art_id: c for c in history.chain_catalog("biedronka", limit=CATALOG_LIMIT)}


def _price(item: CatalogItem) -> str:
    return fmt_pln(item.last_price, 2)


def proposal_cards(history: History) -> list[dict[str, Any]]:
    """Produkty Biedronki do decyzji; kandydaci spoza katalogu Lidla są pomijani."""
    lidl, bdr = lidl_catalog(history), _biedronka(history)
    entries = [
        (p.b_art_id, p.b_name, p.candidates) for p in history.chain_pair_list() if p.status == "proposed"
    ]
    # produkty bez żadnego wiersza (np. bez klucza AI): do ręcznego sparowania przez wyszukiwarkę
    entries += [(a, n, []) for a, n in history.chain_pending()[:UNPAIRED_LIMIT]]
    return [
        {
            "b_art_id": b_id,
            "name": name,
            "price": _price(bdr[b_id]) if b_id in bdr else "",
            "candidates": [
                {"art_id": a, "name": lidl[a].name, "price": _price(lidl[a])} for a in cands if a in lidl
            ],
        }
        for b_id, name, cands in entries
    ]


def decided_rows(history: History, status: str) -> list[dict[str, Any]]:
    """Zatwierdzone (z nazwą produktu Lidla i źródłem pary) albo odrzucone pary."""
    return [
        {
            "b_art_id": p.b_art_id,
            "name": p.b_name,
            "lidl_name": p.lidl_name or p.lidl_art_id or "",
            "source": SOURCE_LABELS.get(p.source or "", ""),
            "is_ean": p.source == "ean",
        }
        for p in history.chain_pair_list()
        if p.status == status
    ]


def search(history: History, q: str, limit: int = 8) -> list[dict[str, str]]:
    """Wyszukiwarka po katalogu Lidla (bez względu na wielkość liter i ogonki)."""
    q = q.strip()
    if not q:
        return []
    found = [c for c in lidl_catalog(history).values() if matches(c.name, q)]
    return [{"art_id": c.art_id, "name": c.name, "price": _price(c)} for c in found[:limit]]


def has_lidl_item(history: History, art_id: str) -> bool:
    return art_id in lidl_catalog(history)


def is_known_product(history: History, b_art_id: str) -> bool:
    """Tylko produkty z paragonów Biedronki (bez śmieciowych wierszy w `chain_pairs`)."""
    return b_art_id in _biedronka(history)
