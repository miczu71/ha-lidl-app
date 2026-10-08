"""Historia zakupów w SQLite (`<data>/history.db`): paragony, pozycje, ranking i KPI oszczędności.

Produkt = kod artykułu z paragonu HTML (`art_id`) albo `n:<EAN>` ze starszych paragonów NATIVE. Kody obu
formatów się nie pokrywają, więc pozycja NATIVE dostaje kod HTML, gdy jej znormalizowana nazwa pasuje do
dokładnie jednego kodu HTML (most po nazwie, liczony przy zapytaniach); reszta zostaje pod `n:<EAN>`.
Zapis szczegółów paragonu jest atomowy (pozycje wymieniane w jednej transakcji), więc import
można przerwać i wznowić w dowolnym miejscu.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .receipt import PARSER_VERSION
from .receipt_html import ParsedReceipt

if TYPE_CHECKING:
    from .coupons import Coupon
    from .promotions import Promotion

SCHEMA_VERSION = 4
CANDIDATE_MIN_PURCHASES = 3

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
    parsed INTEGER NOT NULL DEFAULT 0,
    purchased_at TEXT,
    store_code TEXT,
    store_name TEXT,
    store_address TEXT,
    store_postal TEXT,
    store_locality TEXT,
    payment TEXT,
    deposit_charged REAL NOT NULL DEFAULT 0,
    deposit_refunded REAL NOT NULL DEFAULT 0,
    detail_version INTEGER NOT NULL DEFAULT 0
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
    is_weight INTEGER NOT NULL DEFAULT 0,
    promo TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (ticket_id, line)
);
CREATE INDEX IF NOT EXISTS items_art ON items(art_id);
CREATE TABLE IF NOT EXISTS ticket_coupons (
    ticket_id TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    line INTEGER NOT NULL,
    title TEXT NOT NULL,
    coupon_title TEXT NOT NULL,
    description TEXT NOT NULL,
    discount TEXT NOT NULL,
    PRIMARY KEY (ticket_id, line)
);
CREATE TABLE IF NOT EXISTS coupon_optout (art_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS coupons (
    account TEXT NOT NULL,
    promotion_id TEXT NOT NULL,
    coupon_id TEXT NOT NULL,
    title TEXT NOT NULL,
    discount TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    activated INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    seen_at TEXT NOT NULL,
    article_ids TEXT NOT NULL DEFAULT '',
    gone_at TEXT,
    PRIMARY KEY (account, promotion_id)
);
CREATE TABLE IF NOT EXISTS ticket_raw (
    ticket_id TEXT PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS leaflet_batches (
    flyer_id TEXT NOT NULL,
    batch INTEGER NOT NULL,
    pages TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (flyer_id, batch)
);
CREATE TABLE IF NOT EXISTS leaflet_matches (
    flyer_id TEXT NOT NULL,
    art_id TEXT NOT NULL,
    start TEXT NOT NULL,
    title TEXT NOT NULL,
    discount TEXT NOT NULL,
    end TEXT NOT NULL,
    PRIMARY KEY (flyer_id, art_id, start)
);
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
class CouponCandidate:
    art_id: str
    name: str
    purchases: int  # paragony z ostatnich 365 dni
    last_date: str
    coupon_uses: int  # pozycje z rabatem z kuponu Lidl Plus
    coupon_saved: float
    promo_saved: float
    matchable: bool  # kod z paragonu HTML = kod w `articleIds` kuponu; `n:<EAN>` się nie dopasuje
    enabled: bool  # do auto-aktywacji w E3 (domyślnie tak, chyba że odznaczony)


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
    paid: float  # suma kwot paragonów (po rabatach, z saldem kaucji)
    charged: float  # kaucje pobrane (z paragonów odczytanych bieżącym parserem)
    refunded: float  # kaucje i opakowania zwrócone
    tickets: int  # paragonów w zakresie
    with_deposits: int  # z nich z odczytanymi kaucjami


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


def _year_ago(today: date | None) -> date:
    return (today or date.today()) - timedelta(days=365)


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


class History:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        has_tables = self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'tickets'").fetchone()
        version = self._db.execute("PRAGMA user_version").fetchone()[0] if has_tables else SCHEMA_VERSION
        if version < 2:
            self._migrate_v1()
        if version < 3:
            self._migrate_v2()
        if version < 4:
            self._migrate_v3()
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

    def _migrate_v2(self) -> None:
        """v2 → v3: koperta paragonu, kaucje pobrane/zwrócone, opis rabatu i flaga ważenia przy pozycjach.
        Pozycje zostają (wykres i KPI działają dalej); `detail_version` = 0 oznacza ponowne pobranie."""
        with self._db:
            for sql in (
                "ALTER TABLE tickets ADD COLUMN purchased_at TEXT",
                "ALTER TABLE tickets ADD COLUMN store_code TEXT",
                "ALTER TABLE tickets ADD COLUMN store_name TEXT",
                "ALTER TABLE tickets ADD COLUMN store_address TEXT",
                "ALTER TABLE tickets ADD COLUMN store_postal TEXT",
                "ALTER TABLE tickets ADD COLUMN store_locality TEXT",
                "ALTER TABLE tickets ADD COLUMN payment TEXT",
                "ALTER TABLE tickets ADD COLUMN deposit_charged REAL NOT NULL DEFAULT 0",
                "ALTER TABLE tickets ADD COLUMN deposit_refunded REAL NOT NULL DEFAULT 0",
                "ALTER TABLE tickets ADD COLUMN detail_version INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE items ADD COLUMN is_weight INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE items ADD COLUMN promo TEXT NOT NULL DEFAULT ''",
            ):
                self._db.execute(sql)

    def _migrate_v3(self) -> None:
        """v3 → v4: archiwum kuponów — kody artykułów i znacznik zniknięcia z listy Lidla (E16)."""
        if not self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'coupons'").fetchone():
            return
        with self._db:
            self._db.execute("ALTER TABLE coupons ADD COLUMN article_ids TEXT NOT NULL DEFAULT ''")
            self._db.execute("ALTER TABLE coupons ADD COLUMN gone_at TEXT")

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
        """Paragony bez pobranych pozycji albo zapisane starszym parserem, od najnowszych."""
        rows = self._db.execute(
            "SELECT id FROM tickets WHERE account = ? AND (detail_fetched = 0 OR detail_version < ?)"
            " ORDER BY day DESC, id DESC",
            (account, PARSER_VERSION),
        )
        return [r[0] for r in rows]

    def save_detail(
        self,
        ticket_id: str,
        store: str | None,
        receipt: ParsedReceipt,
        raw: dict[str, Any] | None = None,
    ) -> bool:
        """Zapisuje pozycje i kopertę paragonu; zwraca False, gdy paragon miał artykuły, a nic nie rozpoznano.

        `raw` to oczyszczona kopia szczegółu (zapisywana skompresowana); bez niej istniejąca kopia zostaje.
        """
        row = self._db.execute("SELECT articles FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        parsed = bool(receipt.items) or (row is not None and row[0] == 0)
        st = receipt.store or {}
        with self._db:
            self._db.execute("DELETE FROM items WHERE ticket_id = ?", (ticket_id,))
            self._db.executemany(
                "INSERT INTO items (ticket_id, line, art_id, name, quantity, unit_price, total, discount,"
                " coupon, is_weight, promo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (ticket_id, n, i.art_id, i.name, i.quantity, i.unit_price, i.total, i.discount,
                     i.coupon, int(i.is_weight), i.promo)
                    for n, i in enumerate(receipt.items)
                ],
            )  # fmt: skip
            self._db.execute("DELETE FROM ticket_coupons WHERE ticket_id = ?", (ticket_id,))
            self._db.executemany(
                "INSERT INTO ticket_coupons VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (ticket_id, n, c.title, c.coupon_title, c.description, c.discount)
                    for n, c in enumerate(receipt.coupons)
                ],
            )
            self._db.execute(
                "UPDATE tickets SET detail_fetched = 1, parsed = ?, store = COALESCE(?, store),"
                " purchased_at = ?, store_code = ?, store_name = ?, store_address = ?, store_postal = ?,"
                " store_locality = ?, payment = ?, deposit_charged = ?, deposit_refunded = ?,"
                " detail_version = ? WHERE id = ?",
                (
                    int(parsed), store, receipt.purchased_at, st.get("code"), st.get("name"),
                    st.get("address"), st.get("postal"), st.get("locality"), receipt.payment,
                    receipt.deposit_charged, receipt.deposit_refunded, PARSER_VERSION, ticket_id,
                ),
            )  # fmt: skip
            if raw is not None:
                blob = zlib.compress(json.dumps(raw, ensure_ascii=False).encode(), 6)
                self._db.execute("INSERT OR REPLACE INTO ticket_raw VALUES (?, ?)", (ticket_id, blob))
        return parsed

    def ticket_row(self, ticket_id: str) -> dict[str, Any] | None:
        cur = self._db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        row = cur.fetchone()
        return dict(zip([c[0] for c in cur.description], row, strict=True)) if row else None

    def coupons(self, ticket_id: str) -> list[dict[str, str]]:
        rows = self._db.execute(
            "SELECT title, coupon_title, description, discount FROM ticket_coupons"
            " WHERE ticket_id = ? ORDER BY line",
            (ticket_id,),
        )
        return [{"title": r[0], "coupon_title": r[1], "description": r[2], "discount": r[3]} for r in rows]

    def raw_detail(self, ticket_id: str) -> dict[str, Any] | None:
        row = self._db.execute("SELECT data FROM ticket_raw WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            return None
        detail: dict[str, Any] = json.loads(zlib.decompress(row[0]))
        return detail

    def reparse(self, parse: Callable[[dict[str, Any]], ParsedReceipt]) -> int:
        """Przetwarza ponownie paragony z zapisanej kopii (po zmianie parsera), bez pytania Lidla."""
        rows = self._db.execute(
            "SELECT t.id FROM tickets t JOIN ticket_raw r ON r.ticket_id = t.id WHERE t.detail_version < ?",
            (PARSER_VERSION,),
        ).fetchall()
        done = 0
        for (ticket_id,) in rows:
            detail = self.raw_detail(ticket_id)
            if detail is not None:
                self.save_detail(ticket_id, None, parse(detail))
                done += 1
        return done

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

    def _products(self, start: date | None = None, end: date | None = None) -> dict[str, dict[str, Any]]:
        """Pozycje z paragonów z dni `start`–`end` (domknięty, bez zakresu: całość) zebrane per produkt
        (po moście nazw); nazwa i cena z ostatniego zakupu."""
        resolve = self._resolver()
        where = ""
        args: list[str] = []
        if start is not None:
            where += " AND t.day >= ?"
            args.append(start.isoformat())
        if end is not None:
            where += " AND t.day <= ?"
            args.append(end.isoformat())
        rows = self._db.execute(
            "SELECT i.art_id, i.name, i.quantity, i.unit_price, i.ticket_id, t.day, i.discount, i.coupon"
            f" FROM items i JOIN tickets t ON t.id = i.ticket_id WHERE 1 = 1{where}"
            " ORDER BY t.day, i.ticket_id, i.line",
            args,
        )
        acc: dict[str, dict[str, Any]] = {}
        for art_id, name, qty, price, ticket_id, day, discount, coupon in rows:
            p = acc.setdefault(
                resolve(art_id, name),
                {"tickets": set(), "days": set(), "qty": 0.0, "uses": 0, "discount": 0.0, "coupon": 0.0},
            )
            p["tickets"].add(ticket_id)
            p["days"].add(day)
            p["qty"] += qty
            p["uses"] += coupon < 0
            p["discount"] += discount
            p["coupon"] += coupon
            p["name"], p["price"], p["last"] = name, price, day
        return acc

    def product_name(self, art_id: str) -> str | None:
        """Ostatnia nazwa produktu z paragonów (kod po moście nazw albo `n:<EAN>`)."""
        resolve = self._resolver()
        for code, name in self._db.execute(
            "SELECT i.art_id, i.name FROM items i JOIN tickets t ON t.id = i.ticket_id ORDER BY t.day DESC"
        ):
            if resolve(code, name) == art_id:
                return str(name)
        return None

    def ranking(self, start: date | None = None, end: date | None = None) -> list[RankedProduct]:
        """Najczęściej kupowane w dniach `start`–`end` (domyślnie cała historia)."""
        ranked = []
        for key, p in self._products(start, end).items():
            days = sorted(date.fromisoformat(d) for d in p["days"])
            cycle = (days[-1] - days[0]).days / (len(days) - 1) if len(days) > 1 else None
            ranked.append(
                RankedProduct(
                    key, p["name"], len(p["tickets"]), round(p["qty"], 3), p["price"], p["last"], cycle
                )
            )
        ranked.sort(key=lambda r: (-r.purchases, r.name))
        return ranked

    def coupon_candidates(self, today: date | None = None) -> list[CouponCandidate]:
        """Produkty kupowane regularnie (≥ `CANDIDATE_MIN_PURCHASES` paragonów w ostatnich 365 dniach, cały
        dom) — kandydaci do auto-aktywacji kuponów. Zapisujemy tylko odznaczenia, więc nowy jest włączony."""
        opted_out = {r[0] for r in self._db.execute("SELECT art_id FROM coupon_optout")}
        out = []
        for key, p in self._products(_year_ago(today)).items():
            if len(p["tickets"]) < CANDIDATE_MIN_PURCHASES:
                continue
            matchable = not key.startswith("n:")
            out.append(
                CouponCandidate(
                    key,
                    p["name"],
                    len(p["tickets"]),
                    p["last"],
                    p["uses"],
                    round(-p["coupon"], 2),
                    round(p["coupon"] - p["discount"], 2),
                    matchable,
                    matchable and key not in opted_out,
                )
            )
        out.sort(key=lambda c: (-c.purchases, c.name))
        return out

    def enabled_candidates(self, today: date | None = None) -> list[CouponCandidate]:
        """Lista „Kupowane regularnie” z włączonym przełącznikiem (kupony, promocje, gazetka)."""
        return [c for c in self.coupon_candidates(today) if c.enabled]

    def enabled_codes(self, today: date | None = None) -> set[str]:
        return {c.art_id for c in self.enabled_candidates(today)}

    def set_auto_activate(self, art_id: str, enabled: bool) -> None:
        with self._db:
            if enabled:
                self._db.execute("DELETE FROM coupon_optout WHERE art_id = ?", (art_id,))
            else:
                self._db.execute("INSERT OR IGNORE INTO coupon_optout VALUES (?)", (art_id,))

    def save_coupons(self, account: str, coupons: Iterable[Coupon], seen_at: str) -> None:
        """Bieżąca lista kuponów konta; status ostatniej decyzji zostaje, kupony spoza listy trafiają
        do archiwum (`gone_at`) zamiast znikać — z archiwum liczymy skuteczność (E16)."""
        with self._db:
            self._db.executemany(
                "INSERT INTO coupons (account, promotion_id, coupon_id, title, discount, valid_from,"
                " valid_to, activated, seen_at, article_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (account, promotion_id) DO UPDATE SET coupon_id = excluded.coupon_id,"
                " title = excluded.title, discount = excluded.discount, valid_from = excluded.valid_from,"
                " valid_to = excluded.valid_to, activated = excluded.activated, seen_at = excluded.seen_at,"
                " article_ids = excluded.article_ids, gone_at = NULL",
                [
                    (account, c.promotion_id, c.coupon_id, c.title, c.discount, c.valid_from.isoformat(),
                     c.valid_to.isoformat(), int(c.activated), seen_at, ",".join(c.article_ids))
                    for c in coupons
                ],
            )  # fmt: skip
            self._db.execute(
                "UPDATE coupons SET gone_at = ? WHERE account = ? AND seen_at != ? AND gone_at IS NULL",
                (seen_at, account, seen_at),
            )

    def set_coupon_statuses(self, account: str, rows: list[tuple[str, str, str | None]]) -> None:
        """Decyzje przebiegu: (`promotionId`, status, `id` po udanej aktywacji albo None)."""
        with self._db:
            self._db.executemany(
                "UPDATE coupons SET status = ?, coupon_id = COALESCE(?, coupon_id),"
                " activated = MAX(activated, ?) WHERE account = ? AND promotion_id = ?",
                [
                    (status, cid, int(status in ("activated", "manual")), account, pid)
                    for pid, status, cid in rows
                ],
            )

    def account_coupons(self, account: str) -> list[dict[str, Any]]:
        cur = self._db.execute(
            "SELECT * FROM coupons WHERE account = ? AND gone_at IS NULL ORDER BY valid_to, title", (account,)
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur]

    def main_store(self, today: date | None = None) -> str | None:
        """Sklep z największą liczbą paragonów w ostatnich 365 dniach (kod jak `PL0001`)."""
        row = self._db.execute(
            "SELECT store_code FROM tickets WHERE store_code IS NOT NULL AND day >= ?"
            " GROUP BY store_code ORDER BY COUNT(*) DESC LIMIT 1",
            (_year_ago(today).isoformat(),),
        ).fetchone()
        return row[0] if row else None

    def has_leaflet(self, flyer_id: str) -> bool:
        return (
            self._db.execute("SELECT 1 FROM leaflet_batches WHERE flyer_id = ?", (flyer_id,)).fetchone()
            is not None
        )

    def add_leaflet(self, flyer_id: str, batches: list[list[Any]], start: date, end: date) -> None:
        """Nowa gazetka: paczki stron (lista [numer, adres obrazu]) do przetworzenia; gazetki starsze niż
        30 dni po końcu znikają razem z trafieniami."""
        old = (date.today() - timedelta(days=30)).isoformat()
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO leaflet_batches (flyer_id, batch, pages, start, end)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (flyer_id, n, json.dumps(b), start.isoformat(), end.isoformat())
                    for n, b in enumerate(batches)
                ],
            )
            self._db.execute("DELETE FROM leaflet_batches WHERE end < ?", (old,))
            self._db.execute("DELETE FROM leaflet_matches WHERE end < ?", (old,))

    def next_leaflet_batch(self, now: str) -> dict[str, Any] | None:
        cur = self._db.execute(
            "SELECT * FROM leaflet_batches WHERE status = 'pending' AND next_try <= ?"
            " ORDER BY start, flyer_id, batch LIMIT 1",
            (now,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        out = dict(zip([c[0] for c in cur.description], row, strict=True))
        out["pages"] = json.loads(out["pages"])
        return out

    def has_pending_leaflet(self) -> bool:
        return (
            self._db.execute("SELECT 1 FROM leaflet_batches WHERE status = 'pending'").fetchone() is not None
        )

    def set_leaflet_batch(self, flyer_id: str, batch: int, status: str, attempts: int, next_try: str) -> None:
        with self._db:
            self._db.execute(
                "UPDATE leaflet_batches SET status = ?, attempts = ?, next_try = ?"
                " WHERE flyer_id = ? AND batch = ?",
                (status, attempts, next_try, flyer_id, batch),
            )

    def save_leaflet_matches(self, flyer_id: str, promos: Iterable[Promotion]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO leaflet_matches VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (flyer_id, p.art_id, p.start.isoformat(), p.title, p.discount, p.end.isoformat())
                    for p in promos
                ],
            )

    def leaflet_matches_starting(self, today: date) -> list[tuple[str, str, str, str, str]]:
        """Promocje z gazetki zaczynające się `today` w kolejności pól `Promotion` (kod, nazwa, rabat, start,
        koniec; daty ISO)."""
        cur = self._db.execute(
            "SELECT art_id, title, discount, start, end FROM leaflet_matches WHERE start = ? ORDER BY title",
            (today.isoformat(),),
        )
        return list(cur)

    def savings_kpi(self, today: date | None = None) -> SavingsKpi:
        """Oszczędności z rabatów na pozycjach (kupony Lidl Plus osobno od promocji); lista API ma to pole
        tylko dla garstki najnowszych paragonów, więc go nie używamy."""
        since = _year_ago(today).isoformat()
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
        """Ile zapłacono łącznie oraz kaucje pobrane i zwrócone (zakres dat domknięty, bez zakresu: całość).

        „Zapłacono” to suma kwot paragonów (po rabatach, z saldem kaucji). Kaucje liczymy tylko z paragonów
        przetworzonych bieżącym parserem i rozpoznanych; `with_deposits` mówi, z ilu paragonów.
        Zachodzi: pozycje po rabatach + pobrane − zwrócone = zapłacono.
        """
        where = ""
        args: list[str] = []
        if start is not None:
            where += " AND t.day >= ?"
            args.append(start.isoformat())
        if end is not None:
            where += " AND t.day <= ?"
            args.append(end.isoformat())
        paid, tickets = self._db.execute(
            f"SELECT SUM(t.total), COUNT(*) FROM tickets t WHERE 1 = 1{where}", args
        ).fetchone()
        charged, refunded, known = self._db.execute(
            "SELECT SUM(t.deposit_charged), SUM(t.deposit_refunded), COUNT(*) FROM tickets t"
            f" WHERE t.parsed = 1 AND t.detail_version >= ?{where}",
            [PARSER_VERSION, *args],
        ).fetchone()
        return PurchaseTotals(
            round(paid or 0.0, 2), round(charged or 0.0, 2), round(refunded or 0.0, 2), tickets, known
        )

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
