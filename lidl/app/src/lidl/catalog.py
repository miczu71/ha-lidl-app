"""Katalog cen (E6b.1): obserwacje cen z paragonów trafiają do `catalog_obs`; Frisco — `frisco_feed.py`.

Produkt rozpoznajemy po EAN (Biedronka: `art_id` = `b:<EAN>`) albo po kodzie Lidla; pozycje bez żadnego
z nich (`b:<nazwa>`) są pomijane. Cena obserwacji to cena jednostkowa po rabacie, jak w `purchase_aggregates`.
"""

from __future__ import annotations

from .history import History

RECEIPT = "receipt"


def _ean(art_id: str) -> str | None:
    code = art_id.removeprefix("b:")
    return code if code.isdigit() and 8 <= len(code) <= 14 else None


def ingest_receipts(history: History, ticket_id: str | None = None) -> int:
    """Zapisuje obserwacje cen z pozycji paragonu (albo wszystkich — backfill); zwraca liczbę nowych.
    Idempotentne: cena równa poprzedniej obserwacji tego źródła nie jest dopisywana."""
    if ticket_id is None:
        with history.catalog_bulk():
            return _ingest(history, None)
    return _ingest(history, ticket_id)


def backfill_receipts(history: History) -> int:
    """Start add-onu: pełny backfill tylko do pierwszego wypełnienia katalogu (potem paragony wchodzą pojedynczo)."""
    return 0 if history.catalog_has_receipt_obs() else ingest_receipts(history)


def _ingest(history: History, ticket_id: str | None) -> int:
    added = 0
    for art_id, name, quantity, unit_price, amount, day, chain in history.catalog_receipt_lines(ticket_id):
        if quantity <= 0 or amount <= 0:
            continue
        if art_id.startswith("b:"):
            ean = _ean(art_id)
            if ean is None:
                continue
            pid = history.catalog_upsert_product(ean=ean, name=name)
        else:
            pid = history.catalog_upsert_product(lidl_art=art_id, name=name)
        regular = round(unit_price, 2) if unit_price > 0 else None
        if history.catalog_add_obs(pid, RECEIPT, chain, round(amount / quantity, 2), regular, day):
            added += 1
    return added
