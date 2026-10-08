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
import statistics
import zlib
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .receipt import PARSER_VERSION
from .receipt_html import ParsedReceipt
from .text import matches

if TYPE_CHECKING:
    from .coupons import Coupon
    from .promotions import Promotion

SCHEMA_VERSION = 4
CANDIDATE_MIN_PURCHASES = 3
ADDON_START = date(2026, 10, 7)  # pierwsza aktywacja kuponów przez add-on; granica „przed / po” w E16
EFFECT_DAYS = 30
PRICE_WINDOW_DAYS = 182  # E7: okno mediany ceny (ok. 6 miesięcy), porównywane z tym samym oknem rok wcześniej

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
CREATE TABLE IF NOT EXISTS watched (art_id TEXT PRIMARY KEY);
-- wysłane powiadomienia: obserwowane (`c:`/`p:`, E15) i promocje w porannym (`m:`)
CREATE TABLE IF NOT EXISTS watched_sent (key TEXT PRIMARY KEY, sent_at TEXT NOT NULL);
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
    watched: bool  # gwiazdka E15: osobne powiadomienie o kuponach i promocjach
    regular: bool = True  # False: spoza progu, na liście tylko dzięki gwiazdce (zakupy z całej historii)


@dataclass(frozen=True)
class WatchedCoupon:
    """Bieżący kupon konta na obserwowany produkt (E15)."""

    account: str
    promotion_id: str
    title: str
    discount: str
    valid_to: date


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
class CouponEffect:
    """Rabaty z paragonów z ostatnich `EFFECT_DAYS` dni i średnia z takiego okresu sprzed add-onu."""

    coupons: float
    coupons_before: float
    promotions: float
    promotions_before: float
    delta: float
    delta_pct: float | None


@dataclass(frozen=True)
class ActivatedCoupon:
    account: str
    title: str
    discount: str
    valid_to: str
    status: str  # used | lost | pending | unknown (brak kodów artykułów — nie rozstrzygamy)


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


@dataclass(frozen=True)
class PriceChange:
    """Zmiana ceny półkowej r/r: mediana z ostatnich `PRICE_WINDOW_DAYS` dni vs to samo okno rok wcześniej."""

    art_id: str
    name: str
    is_weight: bool  # ceny za kg
    old: float
    new: float
    pct: float
    spend: float  # zapłacono za produkt w ostatnich 365 dniach (waga w koszyku)


@dataclass(frozen=True)
class BasketInflation:
    pct: float | None  # średnia zmian r/r ważona wydatkami; None bez produktów do porównania
    products: int
    coverage: float  # udział porównanych produktów w wydatkach z ostatnich 365 dni (0–1)


@dataclass(frozen=True)
class PricePoint:
    day: str
    shelf: float
    paid: float  # za jednostkę po rabatach pozycji


@dataclass(frozen=True)
class PriceOverview:
    changes: list[PriceChange]
    basket: BasketInflation
    series: list[tuple[str, BasketInflation]]  # koszyk na koniec każdego miesiąca (bieżący: na dziś)
    split: dict[str, SpendGroup]  # wydatki z 365 dni wg grup `_spend_split`


SPLIT_EXAMPLES = 8


@dataclass(frozen=True)
class SpendGroup:
    spend: float
    products: int
    legacy_spend: float  # z tego pod starymi kodami `n:<EAN>` (paragony NATIVE bez mostu po nazwie)
    legacy_products: int
    examples: list[str]  # nazwy z nowymi kodami, od największych wydatków (do `SPLIT_EXAMPLES`)
    legacy_examples: list[str]  # nazwy ze starymi kodami `n:`


@dataclass(frozen=True)
class ProductPrices:
    name: str  # z ostatniego zakupu
    weight: bool  # ceny za kg
    points: list[PricePoint]
    change: PriceChange | None  # bez zakupu w którymś z okien r/r: None


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


# pozycja do analizy cen: (produkt po moście nazw, nazwa, dzień, cena półkowa, zapłacono, ilość, ważony)
_PriceRow = tuple[str, str, date, float, float, float, bool]


def _windows(today: date) -> tuple[date, date, date]:
    """Granice r/r: (rok temu, początek okna bieżącego, początek okna sprzed roku) — okna (od, do]."""
    year = today - timedelta(days=365)
    return year, today - timedelta(days=PRICE_WINDOW_DAYS), year - timedelta(days=PRICE_WINDOW_DAYS)


def _price_changes(rows: list[_PriceRow], days: list[date], today: date) -> tuple[list[PriceChange], float]:
    """Zmiany r/r produktów kupionych w obu oknach (od największej podwyżki) i wydatki z 365 dni do dziś.
    `rows` posortowane po dniu, `days` to ich dni; liczymy tylko wycinek z okien (seria koszyka woła to dla
    każdego miesiąca)."""
    year, new_from, old_from = _windows(today)
    acc: dict[str, dict[str, Any]] = {}
    total = 0.0
    window = rows[bisect_right(days, old_from) : bisect_right(days, today)]
    for key, name, day, price, paid, _qty, weight in window:
        p = acc.setdefault(key, {"old": [], "new": [], "spend": 0.0})
        p["name"], p["weight"] = name, weight
        if old_from < day <= year:
            p["old"].append(price)
        if day > new_from:
            p["new"].append(price)
        if day > year:
            p["spend"] += paid
            total += paid
    changes = []
    for key, p in acc.items():
        if not p["old"] or not p["new"]:
            continue
        old, new = statistics.median(p["old"]), statistics.median(p["new"])
        pct = round((new - old) / old * 100, 1)
        changes.append(PriceChange(key, p["name"], p["weight"], old, new, pct, round(p["spend"], 2)))
    changes.sort(key=lambda c: (-c.pct, c.name))
    return changes, total


def _spend_split(rows: list[_PriceRow], today: date, compared: set[str]) -> dict[str, SpendGroup]:
    """Wydatki z 365 dni wg tego, czemu produkt jest (nie)porównany: `compared`, `no_recent` (bez zakupu
    w ostatnich `PRICE_WINDOW_DAYS` dniach), `no_old_window` (kupowany ponad rok, ale nie w tych samych
    miesiącach rok temu), `no_history` (pierwszy zakup w ostatnim roku: nowy albo zmieniony kod/nazwa)."""
    year, new_from, _ = _windows(today)
    first: dict[str, date] = {}
    recent: set[str] = set()
    spend: dict[str, float] = {}
    names: dict[str, str] = {}
    for key, name, day, _price, paid, _qty, _weight in rows:
        if day > today:
            break
        first.setdefault(key, day)
        names[key] = name
        if day > new_from:
            recent.add(key)
        if day > year:
            spend[key] = spend.get(key, 0.0) + paid
    members: dict[str, list[str]] = {g: [] for g in ("compared", "no_recent", "no_old_window", "no_history")}
    for key in sorted(spend, key=lambda k: -spend[k]):
        if key in compared:
            group = "compared"
        elif key not in recent:
            group = "no_recent"
        else:
            group = "no_old_window" if first[key] <= year else "no_history"
        members[group].append(key)
    out = {}
    for group, keys in members.items():
        legacy = [k for k in keys if k.startswith("n:")]
        current = [k for k in keys if not k.startswith("n:")]
        out[group] = SpendGroup(
            round(sum(spend[k] for k in keys), 2),
            len(keys),
            round(sum(spend[k] for k in legacy), 2),
            len(legacy),
            [names[k] for k in current[:SPLIT_EXAMPLES]],
            [names[k] for k in legacy[:SPLIT_EXAMPLES]],
        )
    return out


def _basket(changes: list[PriceChange], total: float) -> BasketInflation:
    spend = sum(c.spend for c in changes)
    pct = round(sum(c.pct * c.spend for c in changes) / spend, 1) if spend > 0 else None
    return BasketInflation(pct, len(changes), round(spend / total, 3) if total > 0 else 0.0)


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
        dom) — kandydaci do auto-aktywacji kuponów. Zapisujemy tylko odznaczenia, więc nowy jest włączony.
        Do tego produkty z gwiazdką spoza progu (E15.4, `regular=False`, zakupy z całej historii, zawsze
        włączone) — kupony, promocje i gazetka obejmują je tak samo."""
        opted_out = {r[0] for r in self._db.execute("SELECT art_id FROM coupon_optout")}
        watched = self.watched_codes()

        def candidate(key: str, p: dict[str, Any], regular: bool) -> CouponCandidate:
            matchable = not key.startswith("n:")
            return CouponCandidate(
                key,
                p["name"],
                len(p["tickets"]),
                p["last"],
                p["uses"],
                round(-p["coupon"], 2),
                round(p["coupon"] - p["discount"], 2),
                matchable,
                matchable and key not in opted_out,  # gwiazdka kasuje odznaczenie (`set_watched`)
                matchable and key in watched,
                regular,
            )

        out = [
            candidate(key, p, True)
            for key, p in self._products(_year_ago(today)).items()
            if len(p["tickets"]) >= CANDIDATE_MIN_PURCHASES
        ]
        extra = watched - {c.art_id for c in out}
        if extra:
            out += [candidate(key, p, False) for key, p in self._products().items() if key in extra]
        out.sort(key=lambda c: (-c.purchases, c.name))
        return out

    def merge_candidates(self) -> dict[str, list[dict[str, Any]]]:
        """E21: stare kody `n:` bez mostu po nazwie (`old`) i wszystkie nowe kody (`new`; `bridged` = wskazuje
        na nie któryś stary) — do jednorazowego dopasowania; od najczęściej kupowanych. Nazwy i ceny tylko
        z pozycji pod danym kodem; cena = mediana ceny półkowej."""
        resolve = self._resolver()
        acc: dict[str, dict[str, Any]] = {}
        bridged: set[str] = set()
        for art_id, name, day, price, weight in self._db.execute(
            "SELECT i.art_id, i.name, t.day, i.unit_price, i.is_weight FROM items i"
            " JOIN tickets t ON t.id = i.ticket_id WHERE i.quantity > 0 AND i.unit_price > 0 ORDER BY t.day"
        ):
            key = resolve(art_id, name)
            if key != art_id:
                bridged.add(key)
                continue
            p = acc.setdefault(key, {"names": [], "prices": [], "days": set(), "weight": False})
            if name not in p["names"]:
                p["names"].append(name)
            p["prices"].append(price)
            p["days"].add(day)
            p["weight"] = bool(weight)
        out: dict[str, list[dict[str, Any]]] = {"old": [], "new": []}
        for key, p in acc.items():
            entry = {
                "code": key,
                "names": p["names"],
                "weight": p["weight"],
                "price": statistics.median(p["prices"]),
                "purchases": len(p["days"]),
                "first": min(p["days"]),
                "last": max(p["days"]),
            }
            if key.startswith("n:"):
                out["old"].append(entry)
                continue
            out["new"].append({**entry, "bridged": key in bridged})
        for side in out.values():
            side.sort(key=lambda c: (-c["purchases"], c["code"]))
        return out

    def other_products(self, query: str, listed: set[str], limit: int = 20) -> list[RankedProduct]:
        """Kupione kiedykolwiek produkty z kodem artykułu spoza listy `listed` („Kupowane regularnie”)
        pasujące do frazy — do nadania gwiazdki (E15.4)."""
        found = [
            r
            for r in self.ranking()
            if not r.art_id.startswith("n:") and r.art_id not in listed and matches(r.name, query)
        ]
        return found[:limit]

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
                self._db.execute("DELETE FROM watched WHERE art_id = ?", (art_id,))

    def watched_codes(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT art_id FROM watched")}

    def set_watched(self, art_id: str, on: bool) -> None:
        """Gwiazdka E15; obserwowany produkt jest zawsze auto-aktywowany (i odwrotnie: wyłączenie
        auto-aktywacji zdejmuje gwiazdkę)."""
        with self._db:
            if on:
                self._db.execute("INSERT OR IGNORE INTO watched VALUES (?)", (art_id,))
                self._db.execute("DELETE FROM coupon_optout WHERE art_id = ?", (art_id,))
            else:
                self._db.execute("DELETE FROM watched WHERE art_id = ?", (art_id,))

    def watched_coupons(self, today: date) -> list[WatchedCoupon]:
        """Kupony z bieżącej listy Lidla, ważne co najmniej do dziś, z kodem obserwowanego produktu."""
        watched = self.watched_codes()
        rows = self._db.execute(
            "SELECT account, promotion_id, title, discount, valid_to, article_ids FROM coupons"
            " WHERE gone_at IS NULL AND substr(valid_to, 1, 10) >= ? ORDER BY valid_to, title",
            (today.isoformat(),),
        )
        return [
            WatchedCoupon(account, pid, title, discount, date.fromisoformat(valid_to[:10]))
            for account, pid, title, discount, valid_to, ids in rows
            if watched.intersection(ids.split(","))
        ]

    def watched_sent_keys(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT key FROM watched_sent")}

    def mark_watched_sent(self, keys: Iterable[str], sent_at: str) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR IGNORE INTO watched_sent VALUES (?, ?)", [(k, sent_at) for k in keys]
            )

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

    def leaflet_matches_active(self, today: date) -> list[tuple[str, str, str, str, str]]:
        """Promocje z gazetki trwające `today` w kolejności pól `Promotion` (kod, nazwa, rabat, start,
        koniec; daty ISO)."""
        cur = self._db.execute(
            "SELECT art_id, title, discount, start, end FROM leaflet_matches"
            " WHERE start <= ? AND end >= ? ORDER BY title",
            (today.isoformat(), today.isoformat()),
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

    def coupon_effect(self, today: date | None = None) -> CouponEffect:
        """Kupony i promocje (zł, rabaty z pozycji) z ostatnich 30 dni vs średnia 30-dniowa z 365 dni przed
        `ADDON_START`; bez paragonów w tamtym okresie nie ma procentu."""
        today = today or date.today()
        base_start = ADDON_START - timedelta(days=365)
        row = self._db.execute(
            "SELECT"
            " SUM(CASE WHEN t.day > :s AND t.day <= :e THEN i.coupon END),"
            " SUM(CASE WHEN t.day > :s AND t.day <= :e THEN i.discount END),"
            " SUM(CASE WHEN t.day >= :b0 AND t.day < :b1 THEN i.coupon END),"
            " SUM(CASE WHEN t.day >= :b0 AND t.day < :b1 THEN i.discount END)"
            " FROM items i JOIN tickets t ON t.id = i.ticket_id",
            {
                "s": (today - timedelta(days=EFFECT_DAYS)).isoformat(),
                "e": today.isoformat(),
                "b0": base_start.isoformat(),
                "b1": ADDON_START.isoformat(),
            },
        ).fetchone()
        coupons, total, coupons_b, total_b = (0.0 - (v or 0.0) for v in row)
        coupons_b, total_b = (v * EFFECT_DAYS / 365 for v in (coupons_b, total_b))
        delta = coupons - coupons_b
        return CouponEffect(
            coupons=round(coupons, 2),
            coupons_before=round(coupons_b, 2),
            promotions=round(total - coupons, 2),
            promotions_before=round(total_b - coupons_b, 2),
            delta=round(delta, 2),
            delta_pct=round(delta / coupons_b * 100, 1) if coupons_b > 0 else None,
        )

    def activated_coupons(self, now: datetime, since: datetime | None = None) -> list[ActivatedCoupon]:
        """Aktywowane kupony (także z archiwum) ze statusem: kupon produktowy jest wykorzystany, gdy na
        paragonie tego konta w oknie ważności jest pozycja z rabatem kuponowym i kodem z `article_ids`.
        Bez kodów (ogólne, sprzed 0.9.2) status to `unknown`. `since` odcina kupony wygasłe wcześniej."""
        out = []
        rows = self._db.execute(
            "SELECT account, title, discount, valid_from, valid_to, article_ids FROM coupons"
            " WHERE activated = 1 AND valid_to >= ? ORDER BY valid_to DESC, title",
            (since.astimezone(UTC).isoformat() if since else "",),
        ).fetchall()
        for account, title, discount, valid_from, valid_to, codes in rows:
            ids = codes.split(",") if codes else []
            end = datetime.fromisoformat(valid_to)
            if not ids:
                status = "unknown"
            elif self._coupon_used(account, ids, valid_from, valid_to):
                status = "used"
            else:
                status = "lost" if end <= now else "pending"
            out.append(ActivatedCoupon(account, title, discount, valid_to, status))
        return out

    def _coupon_used(self, account: str, ids: list[str], valid_from: str, valid_to: str) -> bool:
        first = datetime.fromisoformat(valid_from).astimezone().date().isoformat()
        last = datetime.fromisoformat(valid_to).astimezone().date().isoformat()
        marks = ",".join("?" * len(ids))
        return (
            self._db.execute(
                "SELECT 1 FROM items i JOIN tickets t ON t.id = i.ticket_id"
                f" WHERE t.account = ? AND i.coupon < 0 AND i.art_id IN ({marks}) AND t.day BETWEEN ? AND ?",
                [account, *ids, first, last],
            ).fetchone()
            is not None
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

    def _price_rows(self) -> list[_PriceRow]:
        resolve = self._resolver()
        rows = self._db.execute(
            "SELECT i.art_id, i.name, t.day, i.unit_price, i.total + i.discount, i.quantity, i.is_weight"
            " FROM items i JOIN tickets t ON t.id = i.ticket_id WHERE i.quantity > 0 AND i.unit_price > 0"
            " ORDER BY t.day, i.ticket_id, i.line"
        )
        return [
            (resolve(art_id, name), name, date.fromisoformat(day), price, paid, qty, bool(weight))
            for art_id, name, day, price, paid, qty, weight in rows
        ]

    def price_changes(self, today: date | None = None) -> list[PriceChange]:
        """Zmiany ceny półkowej r/r (E7), od największej podwyżki."""
        rows = self._price_rows()
        return _price_changes(rows, [r[2] for r in rows], today or date.today())[0]

    def price_overview(self, today: date | None = None) -> PriceOverview:
        """Zmiany cen r/r, inflacja koszyka (zmiany ważone wydatkami z 365 dni) i jej seria miesięczna od
        pierwszego miesiąca z rokiem historii (miesiące bez porównania pominięte), z jednego odczytu."""
        today = today or date.today()
        rows = self._price_rows()
        days = [r[2] for r in rows]
        changes, total = _price_changes(rows, days, today)
        series = []
        month = _bucket_start(days[0] + timedelta(days=365), "month") if days else today + timedelta(days=1)
        while month <= today:
            following = _next_bucket(month, "month")
            basket = _basket(*_price_changes(rows, days, min(following - timedelta(days=1), today)))
            if basket.products:
                series.append((month.isoformat(), basket))
            month = following
        split = _spend_split(rows, today, {c.art_id for c in changes})
        return PriceOverview(changes, _basket(changes, total), series, split)

    def product_prices(self, art_id: str, today: date | None = None) -> ProductPrices | None:
        """Każdy zakup produktu (cena półkowa i zapłacona za jednostkę po rabatach) i jego zmiana r/r."""
        rows = [r for r in self._price_rows() if r[0] == art_id]
        if not rows:
            return None
        changes, _ = _price_changes(rows, [r[2] for r in rows], today or date.today())
        points = [
            PricePoint(day.isoformat(), price, round(paid / qty, 2))
            for _, _, day, price, paid, qty, _ in rows
        ]
        return ProductPrices(rows[-1][1], rows[-1][6], points, changes[0] if changes else None)
