"""Historia zakupów w SQLite (`<data>/history.db`): paragony, pozycje, ranking i KPI oszczędności.

Produkt = kod artykułu (`art_id`); nazwa w rankingu to ta z najnowszego paragonu.
Zapis szczegółów paragonu jest atomowy (pozycje wymieniane w jednej transakcji), więc import
można przerwać i wznowić w dowolnym miejscu.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .receipt_html import ParsedReceipt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    day TEXT NOT NULL,
    total REAL NOT NULL,
    savings REAL NOT NULL,
    coupons_used INTEGER NOT NULL,
    store TEXT,
    detail_fetched INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    line INTEGER NOT NULL,
    art_id TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    total REAL NOT NULL,
    discount REAL NOT NULL,
    PRIMARY KEY (ticket_id, line)
);
CREATE INDEX IF NOT EXISTS items_art ON items(art_id);
"""


@dataclass(frozen=True)
class RankedProduct:
    art_id: str
    name: str
    purchases: int
    quantity: float
    last_price: float
    last_date: str
    cycle_days: float | None


@dataclass(frozen=True)
class SavingsKpi:
    tickets: int
    total: float
    last_12m: float
    coupons_used: int
    first_date: str | None
    last_date: str | None


class History:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def upsert_tickets(self, account: str, tickets: list[dict[str, Any]]) -> int:
        """Dodaje nowe paragony z listy API; zwraca liczbę nowych. Istniejących nie rusza."""
        before = self.ticket_count()
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO tickets (id, account, day, total, savings, coupons_used, store)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        str(t["id"]),
                        account,
                        str(t["date"])[:10],
                        float(t.get("totalAmount") or 0),
                        float(t.get("savings") or 0),
                        int(t.get("couponsUsedCount") or 0),
                        t.get("storeCode"),
                    )
                    for t in tickets
                ],
            )
        return self.ticket_count() - before

    def ticket_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0])

    def pending_details(self, account: str) -> list[str]:
        """Paragony bez pobranych pozycji, od najnowszych."""
        rows = self._db.execute(
            "SELECT id FROM tickets WHERE account = ? AND detail_fetched = 0 ORDER BY day DESC, id DESC",
            (account,),
        )
        return [r[0] for r in rows]

    def save_detail(self, ticket_id: str, store: str | None, receipt: ParsedReceipt) -> None:
        with self._db:
            self._db.execute("DELETE FROM items WHERE ticket_id = ?", (ticket_id,))
            self._db.executemany(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (ticket_id, n, i.art_id, i.name, i.quantity, i.unit_price, i.total, i.discount)
                    for n, i in enumerate(receipt.items)
                ],
            )
            self._db.execute(
                "UPDATE tickets SET detail_fetched = 1, store = COALESCE(?, store) WHERE id = ?",
                (store, ticket_id),
            )

    def ranking(self, limit: int = 200) -> list[RankedProduct]:
        rows = self._db.execute(
            "SELECT i.art_id, i.name, i.quantity, i.unit_price, i.ticket_id, t.day"
            " FROM items i JOIN tickets t ON t.id = i.ticket_id ORDER BY t.day, i.ticket_id, i.line"
        )
        acc: dict[str, dict[str, Any]] = {}
        for art_id, name, qty, price, ticket_id, day in rows:
            p = acc.setdefault(art_id, {"tickets": set(), "days": set(), "qty": 0.0})
            p["tickets"].add(ticket_id)
            p["days"].add(day)
            p["qty"] += qty
            p["name"], p["price"], p["last"] = name, price, day
        ranked = []
        for art_id, p in acc.items():
            days = sorted(date.fromisoformat(d) for d in p["days"])
            cycle = (days[-1] - days[0]).days / (len(days) - 1) if len(days) > 1 else None
            ranked.append(
                RankedProduct(
                    art_id, p["name"], len(p["tickets"]), round(p["qty"], 3), p["price"], p["last"], cycle
                )
            )
        ranked.sort(key=lambda r: (-r.purchases, r.name))
        return ranked[:limit]

    def savings_kpi(self, today: date | None = None) -> SavingsKpi:
        since = ((today or date.today()) - timedelta(days=365)).isoformat()
        row = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(savings), 0),"
            " COALESCE(SUM(CASE WHEN day >= ? THEN savings END), 0),"
            " COALESCE(SUM(coupons_used), 0), MIN(day), MAX(day) FROM tickets",
            (since,),
        ).fetchone()
        return SavingsKpi(row[0], round(row[1], 2), round(row[2], 2), row[3], row[4], row[5])
