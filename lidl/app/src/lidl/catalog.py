"""Katalog cen (E6b.1): obserwacje cen z paragonów trafiają do `catalog_obs`; Frisco — `frisco_feed.py`.

Produkt rozpoznajemy po EAN (Biedronka: `art_id` = `b:<EAN>`) albo po kodzie Lidla; pozycje bez żadnego
z nich (`b:<nazwa>`) są pomijane. Cena obserwacji to cena jednostkowa po rabacie, jak w `purchase_aggregates`.
"""

from __future__ import annotations

import logging

from .history import History
from .shelf_prices import EAN_RE

_log = logging.getLogger(__name__)

RECEIPT = "receipt"


def _ean(art_id: str) -> str | None:
    code = art_id.removeprefix("b:")
    if len(code) == 14 and code.isdigit() and code[0] == "0":
        code = code[1:]  # GTIN-14 z wiodącym 0 to EAN-13
    return code if EAN_RE.fullmatch(code) else None


def ingest_receipts(history: History, ticket_id: str | None = None) -> int:
    """Zapisuje obserwacje cen z pozycji paragonu (albo wszystkich — backfill); zwraca liczbę nowych.
    Idempotentne: cena równa poprzedniej obserwacji tego źródła nie jest dopisywana."""
    if ticket_id is None:
        with history.catalog_bulk():
            return _ingest(history, None)
    return _ingest(history, ticket_id)


def backfill_receipts(history: History) -> int:
    """Start add-onu: pełny backfill tylko przy pustym katalogu (potem paragony wchodzą pojedynczo)."""
    return 0 if history.catalog_has_receipt_obs() else ingest_receipts(history)


def _ingest(history: History, ticket_id: str | None) -> int:
    added = 0
    skipped = 0
    for art_id, name, quantity, unit_price, amount, day, chain in history.catalog_receipt_lines(ticket_id):
        if quantity <= 0 or amount <= 0:
            continue
        if art_id.startswith("b:"):
            ean = _ean(art_id)
            if ean is None:
                if art_id.removeprefix("b:").isdigit():  # `b:<nazwa>` (towar bez kodu) to nie błąd
                    skipped += 1
                continue
            pid = history.catalog_upsert_product(ean=ean, name=name)
        else:
            pid = history.catalog_upsert_product(lidl_art=art_id, name=name)
        regular = round(unit_price, 2) if unit_price > 0 else None
        if history.catalog_add_obs(pid, RECEIPT, chain, round(amount / quantity, 2), regular, day):
            added += 1
    if skipped:
        _log.info("katalog: pominięto %d pozycji paragonu z kodem b: spoza EAN-8..13", skipped)
    return added
