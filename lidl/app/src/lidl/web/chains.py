"""Widok zakładki „Sieci” (E28.4.2): zatwierdzanie par „produkt Biedronki → produkt Lidla”."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from lidl.history import CATEGORIES, CatalogItem, ChainPair, History, PlPrice, ShelfPrice
from lidl.packsize import pack_size
from lidl.text import CHAIN_LABELS, fmt_day_month, fmt_pln, matches

CATALOG_LIMIT = 100000
UNPAIRED_LIMIT = 50  # produkty bez propozycji AI (ręczne parowanie) pokazywane naraz
SOURCE_LABELS = {"ean": "EAN", "ai": "AI", "manual": "ręcznie"}
RECENT_DAYS = 90  # okno mediany ceny
WIDE_DAYS = 365  # okno zapasowe mediany, oszczędności i pokrycia (12 miesięcy)


def lidl_catalog(history: History) -> dict[str, CatalogItem]:
    return {c.art_id: c for c in history.chain_catalog("lidl", limit=CATALOG_LIMIT)}


def _biedronka(history: History) -> dict[str, CatalogItem]:
    return {c.art_id: c for c in history.chain_catalog("biedronka", limit=CATALOG_LIMIT)}


def _price(item: CatalogItem) -> str:
    return fmt_pln(item.last_price, 2)


def proposal_cards(history: History, pairs: list[ChainPair] | None = None) -> list[dict[str, Any]]:
    """Produkty Biedronki do decyzji; kandydaci spoza katalogu Lidla są pomijani."""
    lidl, bdr = lidl_catalog(history), _biedronka(history)
    entries = [
        (p.b_art_id, p.b_name, p.candidates)
        for p in (history.chain_pair_list() if pairs is None else pairs)
        if p.status == "proposed"
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


def decided_rows(history: History, status: str, pairs: list[ChainPair] | None = None) -> list[dict[str, Any]]:
    """Zatwierdzone (z nazwą produktu Lidla i źródłem pary) albo odrzucone pary."""
    return [
        {
            "b_art_id": p.b_art_id,
            "name": p.b_name,
            "lidl_name": p.lidl_name or p.lidl_art_id or "",
            "source": SOURCE_LABELS.get(p.source or "", ""),
            "is_ean": p.source == "ean",
        }
        for p in (history.chain_pair_list() if pairs is None else pairs)
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


@dataclass(frozen=True)
class ChainStat:
    last: float  # cena półkowa za jednostkę z ostatniego zakupu
    median: float  # mediana cen za jednostkę (90 d, a gdy pusto 365 d)
    wide: bool  # mediana z okna 365 d


@dataclass(frozen=True)
class CompareRow:
    b_art_id: str
    b_name: str
    lidl_name: str
    unit: str  # „kg” | „l” | „szt”
    lidl: ChainStat
    biedronka: ChainStat
    diff_pct: float  # droższa / tańsza − 1, w procentach
    cheaper: str  # „lidl” | „biedronka” | „” (remis)
    wide: bool
    category: str


@dataclass(frozen=True)
class NoPrice:
    b_art_id: str
    b_name: str
    lidl_name: str


@dataclass(frozen=True)
class ChainComparison:
    rows: list[CompareRow]
    no_price: list[NoPrice]
    savings: dict[str, float]  # sieć zakupu → ile taniej wyszłoby po medianie drugiej sieci (12 mies.)
    savings_total: float
    covered_products: int
    total_products: int
    covered_spend: float
    total_spend: float


@dataclass(frozen=True)
class _Unit:
    price: float  # cena półkowa za jednostkę
    paid: float  # zapłacone za jednostkę (po rabatach)
    qty: float  # ilość w jednostkach


def _mode(last_l: PlPrice, last_b: PlPrice) -> tuple[str, str] | None:
    """(rodzaj, jednostka): ważone → kg; gramatura w tej samej jednostce kg/l → kg/l;
    inaczej szt (tylko gdy gramatury obu nazw się zgadzają albo żadna jej nie ma).

    None = nieporównywalne (ważone vs sztuki — zł/kg ≠ zł/szt; różne albo jednostronne gramatury).
    """
    if last_l.is_weight != last_b.is_weight:
        return None
    if last_l.is_weight:
        return "weight", "kg"
    pl, pb = pack_size(last_l.name), pack_size(last_b.name)
    if pl and pb and pl[1] == pb[1] and pl[1] in ("kg", "l"):
        return "pack", pl[1]
    if pl != pb:  # różne/jednostronne gramatury → cena za sztukę byłaby fałszywą oszczędnością
        return None
    return "piece", "szt"


def _unit(row: PlPrice, mode: tuple[str, str]) -> _Unit | None:
    kind, unit = mode
    if kind == "weight":
        return _Unit(row.price, row.paid / row.qty, row.qty) if row.is_weight else None
    if kind == "pack":
        pack = pack_size(row.name)
        if pack is None or pack[1] != unit:
            return None
        return _Unit(row.price / pack[0], row.paid / row.qty / pack[0], row.qty * pack[0])
    return _Unit(row.price, row.paid / row.qty, row.qty)


def _stat(series: list[tuple[date, _Unit]], today: date) -> ChainStat | None:
    if not series:
        return None
    recent = [u.price for d, u in series if d >= today - timedelta(days=RECENT_DAYS)]
    wide = not recent
    prices = recent or [u.price for _d, u in series]
    return ChainStat(series[-1][1].price, statistics.median(prices), wide)


def compare(
    pairs: list[ChainPair],
    rows: list[PlPrice],
    categories: dict[str, str],
    today: date,
    category: str | None = None,
) -> ChainComparison:
    """Porównanie cen Lidl vs Biedronka dla zatwierdzonych par (czysta funkcja, bez I/O).

    `categories`: kod Biedronki → kategoria pary. Pokrycie liczone bez filtra kategorii.
    """
    start = today - timedelta(days=WIDE_DAYS)
    by_art: dict[str, list[PlPrice]] = {}
    for r in sorted(rows, key=lambda r: r.day):
        if start <= r.day <= today:
            by_art.setdefault(r.art_id, []).append(r)
    approved = [p for p in pairs if p.status == "approved" and p.lidl_art_id]
    out: list[CompareRow] = []
    no_price: list[NoPrice] = []
    savings = {"lidl": 0.0, "biedronka": 0.0}
    for p in approved:
        cat = categories.get(p.b_art_id, "food")
        if category is not None and cat != category:
            continue
        lidl_name = p.lidl_name or p.lidl_art_id or ""
        lrows, brows = by_art.get(p.lidl_art_id or "", []), by_art.get(p.b_art_id, [])
        if not lrows or not brows:
            no_price.append(NoPrice(p.b_art_id, p.b_name, lidl_name))
            continue
        mode = _mode(lrows[-1], brows[-1])
        if mode is None:
            no_price.append(NoPrice(p.b_art_id, p.b_name, lidl_name))
            continue
        series = {
            "lidl": [(r.day, u) for r in lrows if (u := _unit(r, mode))],
            "biedronka": [(r.day, u) for r in brows if (u := _unit(r, mode))],
        }
        stats = {c: _stat(s, today) for c, s in series.items()}
        sl, sb = stats["lidl"], stats["biedronka"]
        if sl is None or sb is None:
            no_price.append(NoPrice(p.b_art_id, p.b_name, lidl_name))
            continue
        lo, hi = sorted((sl.median, sb.median))
        cheaper = "" if sl.median == sb.median else ("lidl" if sl.median < sb.median else "biedronka")
        diff = (hi / lo - 1) * 100 if lo > 0 else 0.0
        out.append(
            CompareRow(
                p.b_art_id, p.b_name, lidl_name, mode[1], sl, sb, diff, cheaper, sl.wide or sb.wide, cat
            )
        )
        for chain, other in (("lidl", sb), ("biedronka", sl)):
            for _d, u in series[chain]:
                if other.median < u.paid:
                    savings[chain] += u.qty * (u.paid - other.median)
    out.sort(key=lambda r: (r.b_name.lower(), r.b_art_id))
    # pokrycie: wszystkie zakupy z 12 miesięcy, niezależnie od filtra kategorii
    paired_b = {p.b_art_id for p in approved}
    paired = paired_b | {p.lidl_art_id for p in approved if p.lidl_art_id}
    b_products = {r.art_id for r in rows if r.chain == "biedronka" and start <= r.day <= today}
    in_window = [r for r in rows if start <= r.day <= today]
    return ChainComparison(
        out,
        no_price,
        savings,
        sum(savings.values()),
        len(b_products & paired_b),
        len(b_products),
        sum(r.paid for r in in_window if r.art_id in paired),
        sum(r.paid for r in in_window),
    )


def category_filter(value: str | None) -> str | None:
    """`?kat=`: nieznana wartość = brak filtra."""
    return value if value in CATEGORIES else None


def _pct(v: float) -> str:
    return f"{round(v, 1):+.1f}".replace(".", ",").replace("-", "\u2212") + "%"


def _shelf_by_ean(history: History) -> dict[str, ShelfPrice]:
    """Ceny i stan półki wybranego sklepu Biedronki (E29.4, E30.3); bez sklepu w ustawieniach albo bez
    odczytów → pusto, a kolumna „Dziś na półce” się nie pokazuje."""
    store = history.get_setting("biedronka_store")
    if not store:
        return {}
    rows = history.shelf_list(store)
    return {row.ean: row for row in rows if row.price is not None or row.stock is not None}


def _shelf_cell(row: ShelfPrice | None) -> dict[str, Any] | None:
    """Komórka kolumny; `None` → „—” (nie odczytano albo produkt ważony bez EAN-u w kluczu odczytu).
    Stan `stock` ('yes'|'low'|'no') bez ceny też daje komórkę (sam znacznik + odczyt)."""
    if row is None or (row.price is None and row.stock is None):
        return None
    return {
        "price": fmt_pln(row.price, 2) if row.price is not None else None,
        "promo": row.is_promotion,
        "stock": row.stock,
        "read": fmt_day_month(datetime.fromisoformat(row.fetched_at).date()),
    }


def comparison_view(
    history: History, category: str | None, today: date, all_pairs: list[ChainPair] | None = None
) -> dict[str, Any]:
    """Dane sekcji „Porównanie” (I/O + formatowanie); liczy `compare`."""
    pairs = [
        p
        for p in (history.chain_pair_list() if all_pairs is None else all_pairs)
        if p.status == "approved" and p.lidl_art_id
    ]
    # pokrycie wymaga wszystkich zakupów 12 miesięcy obu sieci, nie tylko par
    ids = {c.art_id for chain in CHAIN_LABELS for c in history.chain_catalog(chain, limit=CATALOG_LIMIT)}
    ids |= {p.b_art_id for p in pairs} | {p.lidl_art_id for p in pairs if p.lidl_art_id}
    rows = history.chain_price_rows(ids)
    categories: dict[str, str] = {}
    for p in pairs:
        cat, source = history.category_of(p.lidl_art_id or "")
        if source is None:
            cat, source = history.category_of(p.b_art_id)
        categories[p.b_art_id] = cat
    c = compare(pairs, rows, categories, today, category)
    shelf = _shelf_by_ean(history)
    pct_spend = c.covered_spend / c.total_spend * 100 if c.total_spend else 0.0
    return {
        "rows": [
            {
                "name": r.b_name,
                "lidl_name": r.lidl_name,
                "unit": r.unit,
                "lidl_last": fmt_pln(r.lidl.last, 2),
                "lidl_median": fmt_pln(r.lidl.median, 2),
                "b_last": fmt_pln(r.biedronka.last, 2),
                "b_median": fmt_pln(r.biedronka.median, 2),
                "diff": _pct(r.diff_pct),
                "cheaper": r.cheaper,
                "cheaper_label": CHAIN_LABELS.get(r.cheaper, "Tak samo"),
                "wide": r.wide,
                "shelf": _shelf_cell(shelf.get(r.b_art_id.partition(":")[2] or r.b_art_id)),
            }
            for r in c.rows
        ],
        "no_price": [{"name": n.b_name, "lidl_name": n.lidl_name} for n in c.no_price],
        "savings_total": fmt_pln(c.savings_total, 2),
        "savings_lidl": fmt_pln(c.savings["lidl"], 2),
        "savings_biedronka": fmt_pln(c.savings["biedronka"], 2),
        "covered_products": c.covered_products,
        "total_products": c.total_products,
        "spend_pct": f"{pct_spend:.0f}".replace(".", ",") + "%",
        "category": category or "",
        "has_pairs": bool(pairs),
        "has_shelf": bool(shelf),
    }
