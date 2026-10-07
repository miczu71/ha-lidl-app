"""Historia zakupów w SQLite (`<data>/history.db`): paragony, pozycje, ranking i KPI oszczędności.

Produkt = kod artykułu z paragonu HTML (`art_id`) albo `n:<EAN>` ze starszych paragonów NATIVE. Kody obu
formatów się nie pokrywają, więc pozycja NATIVE dostaje kod HTML, gdy jej znormalizowana nazwa pasuje do
dokładnie jednego kodu HTML (most po nazwie, liczony przy zapytaniach); reszta zostaje pod `n:<EAN>`.
Zapis szczegółów paragonu jest atomowy (pozycje wymieniane w jednej transakcji), więc import
można przerwać i wznowić w dowolnym miejscu.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .receipt_html import ParsedReceipt

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    account TEXT NOT NULL,
    day TEXT NOT NULL,
    total REAL NOT NULL,
    savings REAL NOT NULL,
    coupons_used INTEGER NOT NULL,
    store TEXT,
    detail_fetched INTEGER NOT NULL DEFAULT 0,
    articles INTEGER NOT NULL DEFAULT -1,
    parsed INTEGER NOT NULL DEFAULT 0
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
    coupon REAL NOT NULL DEFAULT 0,
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
    with_details: int
    unparsed: int
    total: float
    coupons: float
    promotions: float
    last_12m: float
    coupons_used: int
    first_date: str | None
    last_date: str | None


@dataclass(frozen=True)
class PurchaseTotals:
    paid: float  # suma kwot paragonów (po rabatach, z kaucją)
    deposits: float  # kaucje wyliczone: kwota paragonu minus pozycje po rabatach


@dataclass(frozen=True)
class SpendBucket:
    start: str
    spend: float
    quantity: float
    purchases: int


def _bucket_start(d: date, step: str) -> date:
    if step == "week":
        return d - timedelta(days=d.weekday())
    if step == "month":
        return d.replace(day=1)
    if step == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    return d.replace(month=1, day=1)


def _next_bucket(d: date, step: str) -> date:
    if step == "week":
        return d + timedelta(days=7)
    months = {"month": 1, "quarter": 3, "year": 12}[step]
    month = d.month - 1 + months
    return date(d.year + month // 12, month % 12 + 1, 1)


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


class History:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        has_tables = self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'tickets'").fetchone()
        if has_tables and self._db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
            self._migrate_v1()
        self._db.executescript(_SCHEMA)
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_v1(self) -> None:
        """v1 → v2: nowe kolumny, a pozycje i znacznik pobrania zerowane, więc szczegóły pobiorą się od nowa
        (v1 nie znał formatu NATIVE i nie rozdzielał kuponów od promocji)."""
        with self._db:
            self._db.execute("ALTER TABLE items ADD COLUMN coupon REAL NOT NULL DEFAULT 0")
            self._db.execute("ALTER TABLE tickets ADD COLUMN articles INTEGER NOT NULL DEFAULT -1")
            self._db.execute("ALTER TABLE tickets ADD COLUMN parsed INTEGER NOT NULL DEFAULT 0")
            self._db.execute("DELETE FROM items")
            self._db.execute("UPDATE tickets SET detail_fetched = 0")

    def upsert_tickets(self, account: str, tickets: list[dict[str, Any]]) -> int:
        """Dodaje nowe paragony z listy API (zwraca ich liczbę); istniejącym odświeża tylko `articles`."""
        before = self.ticket_count()
        with self._db:
            self._db.executemany(
                "INSERT INTO tickets (id, account, day, total, savings, coupons_used, store, articles)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET articles = excluded.articles",
                [
                    (
                        str(t["id"]),
                        account,
                        str(t["date"])[:10],
                        float(t.get("totalAmount") or 0),
                        float(t.get("savings") or 0),
                        int(t.get("couponsUsedCount") or 0),
                        t.get("storeCode"),
                        int(t.get("articlesCount", -1)),
                    )
                    for t in tickets
                ],
            )
        return self.ticket_count() - before

    def ticket_count(self, account: str | None = None) -> int:
        sql, args = (
            ("SELECT COUNT(*) FROM tickets", ())
            if account is None
            else (
                "SELECT COUNT(*) FROM tickets WHERE account = ?",
                (account,),
            )
        )
        return int(self._db.execute(sql, args).fetchone()[0])

    def pending_details(self, account: str) -> list[str]:
        """Paragony bez pobranych pozycji, od najnowszych."""
        rows = self._db.execute(
            "SELECT id FROM tickets WHERE account = ? AND detail_fetched = 0 ORDER BY day DESC, id DESC",
            (account,),
        )
        return [r[0] for r in rows]

    def save_detail(self, ticket_id: str, store: str | None, receipt: ParsedReceipt) -> bool:
        """Zapisuje pozycje paragonu; zwraca False, gdy paragon miał artykuły, a nic nie rozpoznano."""
        row = self._db.execute("SELECT articles FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        parsed = bool(receipt.items) or (row is not None and row[0] == 0)
        with self._db:
            self._db.execute("DELETE FROM items WHERE ticket_id = ?", (ticket_id,))
            self._db.executemany(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (ticket_id, n, i.art_id, i.name, i.quantity, i.unit_price, i.total, i.discount, i.coupon)
                    for n, i in enumerate(receipt.items)
                ],
            )
            self._db.execute(
                "UPDATE tickets SET detail_fetched = 1, parsed = ?, store = COALESCE(?, store) WHERE id = ?",
                (int(parsed), store, ticket_id),
            )
        return parsed

    def _resolver(self) -> Callable[[str, str], str]:
        """Most po nazwie: kod `n:` → kod HTML, gdy nazwa pasuje do dokładnie jednego kodu HTML."""
        names: dict[str, set[str]] = {}
        for art_id, name in self._db.execute(
            "SELECT DISTINCT art_id, name FROM items WHERE art_id NOT LIKE 'n:%'"
        ):
            names.setdefault(_norm(name), set()).add(art_id)
        unique = {n: next(iter(ids)) for n, ids in names.items() if len(ids) == 1}

        def resolve(art_id: str, name: str) -> str:
            return unique.get(_norm(name), art_id) if art_id.startswith("n:") else art_id

        return resolve

    def ranking(self, limit: int = 200) -> list[RankedProduct]:
        resolve = self._resolver()
        rows = self._db.execute(
            "SELECT i.art_id, i.name, i.quantity, i.unit_price, i.ticket_id, t.day"
            " FROM items i JOIN tickets t ON t.id = i.ticket_id ORDER BY t.day, i.ticket_id, i.line"
        )
        acc: dict[str, dict[str, Any]] = {}
        for art_id, name, qty, price, ticket_id, day in rows:
            p = acc.setdefault(resolve(art_id, name), {"tickets": set(), "days": set(), "qty": 0.0})
            p["tickets"].add(ticket_id)
            p["days"].add(day)
            p["qty"] += qty
            p["name"], p["price"], p["last"] = name, price, day
        ranked = []
        for key, p in acc.items():
            days = sorted(date.fromisoformat(d) for d in p["days"])
            cycle = (days[-1] - days[0]).days / (len(days) - 1) if len(days) > 1 else None
            ranked.append(
                RankedProduct(
                    key, p["name"], len(p["tickets"]), round(p["qty"], 3), p["price"], p["last"], cycle
                )
            )
        ranked.sort(key=lambda r: (-r.purchases, r.name))
        return ranked[:limit]

    def savings_kpi(self, today: date | None = None) -> SavingsKpi:
        """Oszczędności z rabatów na pozycjach (kupony Lidl Plus osobno od promocji); lista API ma to pole
        tylko dla garstki najnowszych paragonów, więc go nie używamy."""
        since = ((today or date.today()) - timedelta(days=365)).isoformat()
        t = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(detail_fetched), 0),"
            " COALESCE(SUM(CASE WHEN detail_fetched = 1 AND parsed = 0 THEN 1 ELSE 0 END), 0),"
            " COALESCE(SUM(coupons_used), 0), MIN(day), MAX(day) FROM tickets"
        ).fetchone()
        d = self._db.execute(
            "SELECT SUM(i.discount), SUM(i.coupon), SUM(CASE WHEN t.day >= ? THEN i.discount END)"
            " FROM items i JOIN tickets t ON t.id = i.ticket_id",
            (since,),
        ).fetchone()
        total, coupons, last_12m = (round(0.0 - (v or 0.0), 2) for v in d)
        return SavingsKpi(
            tickets=t[0],
            with_details=t[1],
            unparsed=t[2],
            total=total,
            coupons=coupons,
            promotions=round(total - coupons, 2),
            last_12m=last_12m,
            coupons_used=t[3],
            first_date=t[4],
            last_date=t[5],
        )

    def purchase_totals(self, start: date | None = None, end: date | None = None) -> PurchaseTotals:
        """Ile zapłacono łącznie i ile z tego to kaucje (zakres dat domknięty, bez zakresu = cała historia).

        Kaucji paragon nie podaje wprost w liście, więc liczymy ją per paragon jako kwotę paragonu minus
        pozycje po rabatach (min. 0); tylko dla paragonów z rozpoznanymi pozycjami.
        """
        where = ""
        args: list[str] = []
        if start is not None:
            where += " AND t.day >= ?"
            args.append(start.isoformat())
        if end is not None:
            where += " AND t.day <= ?"
            args.append(end.isoformat())
        paid = self._db.execute(f"SELECT SUM(t.total) FROM tickets t WHERE 1 = 1{where}", args).fetchone()[0]
        deposits = self._db.execute(
            "SELECT SUM(MAX(0.0, ROUND(t.total - x.net, 2))) FROM tickets t JOIN"
            " (SELECT ticket_id, SUM(total + discount) AS net FROM items GROUP BY ticket_id) x"
            f" ON x.ticket_id = t.id WHERE t.parsed = 1{where}",
            args,
        ).fetchone()[0]
        return PurchaseTotals(round(paid or 0.0, 2), round(deposits or 0.0, 2))

    def spend_series(self, start: date, end: date, step: str, art_id: str | None = None) -> list[SpendBucket]:
        """Wydatki netto (cena minus rabaty pozycji, bez kaucji) w przedziałach `step`.

        Zakres jest obustronnie domknięty, puste przedziały dostają zera. Bez `art_id` sumuje
        wszystkie pozycje, z `art_id` tylko jeden produkt (łącznie z jego wpisami ze starszych paragonów).
        """
        if step not in ("week", "month", "quarter", "year"):
            raise ValueError("step")
        if start > end:
            raise ValueError("range")
        resolve = self._resolver()
        rows = self._db.execute(
            "SELECT t.day, i.total + i.discount, i.quantity, i.ticket_id, i.art_id, i.name FROM items i"
            " JOIN tickets t ON t.id = i.ticket_id WHERE t.day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        )
        spend: dict[date, float] = {}
        qty: dict[date, float] = {}
        tickets: dict[date, set[str]] = {}
        for day, net, quantity, ticket_id, item_art, item_name in rows:
            if art_id is not None and resolve(item_art, item_name) != art_id:
                continue
            b = _bucket_start(date.fromisoformat(day), step)
            spend[b] = spend.get(b, 0.0) + net
            qty[b] = qty.get(b, 0.0) + quantity
            tickets.setdefault(b, set()).add(ticket_id)
        series = []
        b = _bucket_start(start, step)
        while b <= end:
            series.append(
                SpendBucket(
                    b.isoformat(),
                    round(spend.get(b, 0.0), 2),
                    round(qty.get(b, 0.0), 3),
                    len(tickets.get(b, ())),
                )
            )
            b = _next_bucket(b, step)
        return series
