from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem


def _ticket(
    tid: str, day: str, total: float = 10.0, savings: float = 0.0, coupons: int = 0, articles: int = 1
) -> dict[str, Any]:
    return {
        "articlesCount": articles,
        "id": tid,
        "date": f"{day}T10:00:00+00:00",
        "totalAmount": total,
        "savings": savings,
        "couponsUsedCount": coupons,
        "storeCode": "PL0001",
    }


def _receipt(*items: tuple[str, str, float, float]) -> ParsedReceipt:
    return ParsedReceipt(items=[ReceiptItem(a, n, q, p, round(q * p, 2)) for a, n, q, p in items])


def test_upsert_is_idempotent_and_keeps_detail_flag(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    assert h.upsert_tickets("osoba-1", [_ticket("t1", "2026-01-01"), _ticket("t2", "2026-01-08")]) == 2
    h.save_detail("t1", "Sklep X", _receipt(("1", "Produkt A", 1, 5.0)))
    assert h.upsert_tickets("osoba-1", [_ticket("t1", "2026-01-01"), _ticket("t3", "2026-01-09")]) == 1
    assert h.ticket_count() == 3
    assert h.pending_details("osoba-1") == ["t3", "t2"]


def test_save_detail_replaces_items(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-01-01")])
    h.save_detail("t1", "Sklep X", _receipt(("1", "Produkt A", 1, 5.0), ("2", "Produkt B", 2, 3.0)))
    h.save_detail("t1", "Sklep X", _receipt(("1", "Produkt A", 1, 5.0)))
    assert [r.art_id for r in h.ranking()] == ["1"]


def test_ranking_counts_tickets_and_cycle(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [_ticket("t1", "2026-01-01"), _ticket("t2", "2026-01-11"), _ticket("t3", "2026-01-21")],
    )
    h.save_detail("t1", "S", _receipt(("1", "Mleko", 2, 2.0), ("2", "Chleb", 1, 4.0)))
    h.save_detail("t2", "S", _receipt(("1", "Mleko UHT", 1, 2.5)))
    h.save_detail("t3", "S", _receipt(("1", "Mleko UHT", 3, 2.6), ("1", "Mleko UHT", 1, 2.6)))
    milk, bread = h.ranking()
    assert (milk.art_id, milk.name, milk.purchases, milk.quantity) == ("1", "Mleko UHT", 3, 7.0)
    assert (milk.last_price, milk.last_date, milk.cycle_days) == (2.6, "2026-01-21", 10.0)
    assert (bread.purchases, bread.cycle_days) == (1, None)


def test_savings_kpi_from_item_discounts_split_and_last_12_months(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [
            _ticket("old", "2024-01-01", coupons=1),
            _ticket("new1", "2026-03-01", coupons=2),
            _ticket("new2", "2026-09-01"),
            _ticket("nodetail", "2026-09-02"),
        ],
    )

    def one(discount: float, coupon: float) -> ParsedReceipt:
        return ParsedReceipt(items=[ReceiptItem("1", "A", 1, 10.0, 10.0, discount, coupon)])

    h.save_detail("old", "S", one(-4.0, -1.0))
    h.save_detail("new1", "S", one(-5.5, -5.5))
    h.save_detail("new2", "S", one(-0.5, 0.0))
    kpi = h.savings_kpi(today=date(2026, 10, 7))
    assert (kpi.total, kpi.coupons, kpi.promotions, kpi.last_12m) == (10.0, 6.5, 3.5, 6.0)
    assert (kpi.tickets, kpi.with_details, kpi.coupons_used, kpi.unparsed) == (4, 3, 3, 0)
    assert (kpi.first_date, kpi.last_date) == ("2024-01-01", "2026-09-02")


def test_receipt_without_items_is_unparsed_unless_it_had_no_articles(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-01-01", articles=5), _ticket("t2", "2026-01-02", articles=0)])
    assert h.save_detail("t1", "S", ParsedReceipt()) is False
    assert h.save_detail("t2", "S", ParsedReceipt()) is True
    assert h.savings_kpi().unparsed == 1
    assert h.save_detail("t1", "S", _receipt(("1", "A", 1, 1.0))) is True
    assert h.savings_kpi().unparsed == 0


def test_native_items_merge_with_html_products_by_unique_name(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("old", "2026-01-01"), _ticket("new", "2026-05-01")])
    h.save_detail(
        "old", "S", _receipt(("n:57490", "Bagietka  duża", 1, 2.5), ("n:999", "Tylko stare", 1, 9.0))
    )
    h.save_detail("new", "S", _receipt(("0193875", "bagietka duża", 2, 2.9)))
    by_id = {r.art_id: r for r in h.ranking()}
    assert set(by_id) == {"0193875", "n:999"}
    assert (by_id["0193875"].purchases, by_id["0193875"].quantity) == (2, 3.0)
    series = h.spend_series(date(2026, 1, 1), date(2026, 5, 31), "month", art_id="0193875")
    assert [b.spend for b in series] == [2.5, 0.0, 0.0, 0.0, 5.8]


def test_ambiguous_html_name_is_not_merged(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("old", "2026-01-01"), _ticket("new", "2026-05-01")])
    h.save_detail("old", "S", _receipt(("n:1", "Lody", 1, 5.0)))
    h.save_detail("new", "S", _receipt(("111", "Lody", 1, 6.0), ("222", "Lody", 1, 7.0)))
    assert {r.art_id for r in h.ranking()} == {"n:1", "111", "222"}


def test_v1_database_is_migrated_and_details_are_refetched(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "h.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE tickets (id TEXT PRIMARY KEY, account TEXT NOT NULL, day TEXT NOT NULL,
            total REAL NOT NULL, savings REAL NOT NULL, coupons_used INTEGER NOT NULL, store TEXT,
            detail_fetched INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE items (ticket_id TEXT NOT NULL, line INTEGER NOT NULL, art_id TEXT NOT NULL,
            name TEXT NOT NULL, quantity REAL NOT NULL, unit_price REAL NOT NULL, total REAL NOT NULL,
            discount REAL NOT NULL, PRIMARY KEY (ticket_id, line));
        INSERT INTO tickets VALUES ('t1', 'a', '2026-01-01', 10, 0, 0, 'S', 1);
        INSERT INTO items VALUES ('t1', 0, '1', 'A', 1, 5, 5, 0);
        """
    )
    db.commit()
    db.close()
    h = History(path)
    assert h.pending_details("a") == ["t1"]
    assert h.ranking() == []
    h.save_detail("t1", "S", _receipt(("1", "A", 1, 5.0)))
    assert h.savings_kpi().unparsed == 0
    assert History(path).pending_details("a") == []  # druga migracja nic nie resetuje


def _seed_series(h: History) -> None:
    h.upsert_tickets(
        "a",
        [_ticket("t1", "2026-01-05"), _ticket("t2", "2026-01-20"), _ticket("t3", "2026-03-02")],
    )
    h.save_detail("t1", "S", _receipt(("1", "Mleko", 2, 2.0), ("2", "Chleb", 1, 4.0)))
    h.save_detail("t2", "S", _receipt(("1", "Mleko", 1, 2.0)))
    h.save_detail("t3", "S", _receipt(("1", "Mleko", 3, 2.0)))


def test_spend_series_monthly_fills_empty_buckets(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_series(h)
    series = h.spend_series(date(2026, 1, 1), date(2026, 3, 31), "month")
    assert [(b.start, b.spend, b.quantity, b.purchases) for b in series] == [
        ("2026-01-01", 10.0, 4.0, 2),
        ("2026-02-01", 0.0, 0.0, 0),
        ("2026-03-01", 6.0, 3.0, 1),
    ]


def test_spend_series_filters_by_product(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_series(h)
    series = h.spend_series(date(2026, 1, 1), date(2026, 1, 31), "month", art_id="2")
    assert [(b.spend, b.quantity, b.purchases) for b in series] == [(4.0, 1.0, 1)]


def test_spend_series_is_net_of_item_discounts(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-01-05")])
    item = ReceiptItem("1", "Mleko", 2, 5.0, 10.0, discount=-2.5)
    h.save_detail("t1", "S", ParsedReceipt(items=[item]))
    (bucket,) = h.spend_series(date(2026, 1, 1), date(2026, 1, 31), "month")
    assert bucket.spend == 7.5


def test_spend_series_range_is_inclusive_and_ignores_outside(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_series(h)
    series = h.spend_series(date(2026, 1, 20), date(2026, 3, 2), "month")
    assert [b.spend for b in series] == [2.0, 0.0, 6.0]


def test_spend_series_week_starts_on_monday_quarter_and_year(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_series(h)
    weeks = h.spend_series(date(2026, 1, 5), date(2026, 1, 25), "week")
    assert [(b.start, b.spend) for b in weeks] == [
        ("2026-01-05", 8.0),
        ("2026-01-12", 0.0),
        ("2026-01-19", 2.0),
    ]
    quarters = h.spend_series(date(2025, 12, 1), date(2026, 3, 31), "quarter")
    assert [(b.start, b.spend) for b in quarters] == [("2025-10-01", 0.0), ("2026-01-01", 16.0)]
    years = h.spend_series(date(2025, 6, 1), date(2026, 12, 31), "year")
    assert [(b.start, b.spend) for b in years] == [("2025-01-01", 0.0), ("2026-01-01", 16.0)]


def test_spend_series_rejects_bad_step_and_reversed_range(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    with pytest.raises(ValueError, match="step"):
        h.spend_series(date(2026, 1, 1), date(2026, 2, 1), "day")
    with pytest.raises(ValueError, match="range"):
        h.spend_series(date(2026, 2, 1), date(2026, 1, 1), "month")


def _with_deposits(charged: float = 0.0, refunded: float = 0.0) -> ParsedReceipt:
    return ParsedReceipt(
        items=[ReceiptItem("1", "A", 1, 10.0, 10.0)], deposit_charged=charged, deposit_refunded=refunded
    )


def test_purchase_totals_paid_charged_refunded_and_coverage(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [
            _ticket("t1", "2026-01-10", total=20.0),
            _ticket("t2", "2026-02-10", total=11.0),
            _ticket("t3", "2026-03-10", total=5.0),
            _ticket("t4", "2026-04-10", total=7.0, articles=3),
        ],
    )
    h.save_detail("t1", "S", _with_deposits(charged=2.5))
    h.save_detail("t2", "S", _with_deposits(refunded=1.5))
    h.save_detail("t4", "S", ParsedReceipt())  # nierozpoznany: kaucji nie znamy
    # t3 nie został jeszcze pobrany: zapłacono liczy się, kaucje nie
    totals = h.purchase_totals()
    assert (totals.paid, totals.charged, totals.refunded) == (43.0, 2.5, 1.5)
    assert (totals.tickets, totals.with_deposits) == (4, 2)
    ranged = h.purchase_totals(date(2026, 2, 1), date(2026, 3, 31))
    assert (ranged.paid, ranged.charged, ranged.refunded, ranged.with_deposits) == (16.0, 0.0, 1.5, 1)
    assert h.purchase_totals(date(2030, 1, 1), date(2030, 12, 31)).paid == 0.0


def test_save_detail_stores_envelope_coupons_and_sanitized_raw(tmp_path: Path) -> None:
    from lidl.receipt_html import ReceiptCoupon

    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-05-05")])
    receipt = ParsedReceipt(
        items=[ReceiptItem("1", "A", 0.5, 10.0, 5.0, is_weight=True, promo="Rabat grupowy")],
        purchased_at="2026-05-05T19:39:20",
        store={"code": "PL0001", "name": "Miasto A, ul. Testowa 1", "address": "ul. Testowa 1",
               "postal": "00-001", "locality": "Miasto A"},
        payment="Karta płatnicza",
        coupons=[ReceiptCoupon("Produkt X", "-15%", "Produkt X", "-15% Rabat")],
    )  # fmt: skip
    h.save_detail("t1", "S", receipt, raw={"id": "t1", "date": "2026-05-05T19:39:20"})
    row = h.ticket_row("t1")
    assert row is not None
    assert (row["purchased_at"], row["store_code"], row["store_locality"], row["payment"]) == (
        "2026-05-05T19:39:20", "PL0001", "Miasto A", "Karta płatnicza",
    )  # fmt: skip
    assert h.coupons("t1") == [
        {"title": "Produkt X", "coupon_title": "-15%", "description": "Produkt X", "discount": "-15% Rabat"}
    ]
    assert h.raw_detail("t1") == {"id": "t1", "date": "2026-05-05T19:39:20"}
    assert h.raw_detail("nope") is None
    h.save_detail("t1", "S", receipt)  # ponowny zapis bez raw nie kasuje kopii
    assert h.raw_detail("t1") is not None


def test_old_parser_version_is_pending_again_and_reparse_uses_local_copy(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-05-05"), _ticket("t2", "2026-05-06")])
    h.save_detail("t1", "S", _with_deposits(), raw={"id": "t1"})
    h.save_detail("t2", "S", _with_deposits())  # bez kopii
    assert h.pending_details("a") == []
    h._db.execute("UPDATE tickets SET detail_version = 2")
    assert sorted(h.pending_details("a")) == ["t1", "t2"]
    seen: list[dict[str, Any]] = []

    def parse(detail: dict[str, Any]) -> ParsedReceipt:
        seen.append(detail)
        return _with_deposits(charged=3.0)

    assert h.reparse(parse) == 1 and seen == [{"id": "t1"}]
    assert h.pending_details("a") == ["t2"]  # t2 nie ma kopii, więc trzeba go pobrać od Lidla
    assert h.purchase_totals().charged == 3.0


def test_v2_database_is_migrated_keeping_items_and_marking_refetch(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "h.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE tickets (id TEXT PRIMARY KEY, account TEXT NOT NULL, day TEXT NOT NULL,
            total REAL NOT NULL, savings REAL NOT NULL, coupons_used INTEGER NOT NULL, store TEXT,
            detail_fetched INTEGER NOT NULL DEFAULT 0, articles INTEGER NOT NULL DEFAULT -1,
            parsed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE items (ticket_id TEXT NOT NULL, line INTEGER NOT NULL, art_id TEXT NOT NULL,
            name TEXT NOT NULL, quantity REAL NOT NULL, unit_price REAL NOT NULL, total REAL NOT NULL,
            discount REAL NOT NULL, coupon REAL NOT NULL DEFAULT 0, PRIMARY KEY (ticket_id, line));
        INSERT INTO tickets VALUES ('t1', 'a', '2026-01-01', 10, 0, 0, 'S', 1, 1, 1);
        INSERT INTO items VALUES ('t1', 0, '1', 'A', 1, 5, 5, 0, 0);
        PRAGMA user_version = 2;
        """
    )
    db.commit()
    db.close()
    h = History(path)
    assert [r.art_id for r in h.ranking()] == ["1"]  # pozycje zostały
    assert h.pending_details("a") == ["t1"]  # ale paragon czeka na ponowne pobranie
    assert h.purchase_totals().with_deposits == 0
    h.save_detail("t1", "S", _with_deposits(charged=1.0))
    assert History(path).pending_details("a") == []


def _seed_candidates(h: History) -> None:
    """Dzień odniesienia 2026-10-07: okno 365 dni zaczyna się 2025-10-07."""
    days = ["2025-10-06", "2025-10-07", "2026-01-01", "2026-05-01", "2026-09-01"]
    h.upsert_tickets("a", [_ticket(f"t{i}", d) for i, d in enumerate(days)])
    h.upsert_tickets("b", [_ticket("b1", "2026-09-02")])
    h.save_detail("t0", "S", _receipt(("n:1", "Mleko", 1, 3.0), ("5", "Ser", 1, 9.0)))
    h.save_detail("t1", "S", _receipt(("n:1", "Mleko", 1, 3.0), ("n:2", "Jaja stare", 1, 8.0)))
    h.save_detail("t2", "S", _receipt(("n:2", "Jaja stare", 1, 8.0), ("5", "Ser", 1, 9.0)))
    h.save_detail("t3", "S", ParsedReceipt(items=[ReceiptItem("7", "mleko", 2, 3.2, 6.4, -2.0, -1.5)]))
    h.save_detail("t4", "S", _receipt(("5", "Ser", 1, 9.0)))
    milk = ReceiptItem("7", "Mleko", 1, 3.2, 3.2, -1.0, -1.0)
    h.save_detail("b1", "S", ParsedReceipt(items=[milk, ReceiptItem("n:2", "Jaja", 1, 8.0, 8.0)]))


def test_coupon_candidates_threshold_window_bridge_and_household(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_candidates(h)
    cands = h.coupon_candidates(today=date(2026, 10, 7))
    by_id = {c.art_id: c for c in cands}
    # Ser: 2 zakupy w oknie (trzeci, t0, jest sprzed 366 dni) — za mało.
    assert set(by_id) == {"7", "n:2"}
    milk = by_id["7"]  # most n:1 → 7 po nazwie, oba konta razem: t1, t3, b1
    assert (milk.name, milk.purchases, milk.last_date) == ("Mleko", 3, "2026-09-02")
    assert (milk.coupon_uses, milk.coupon_saved, milk.promo_saved) == (2, 2.5, 0.5)
    assert (milk.matchable, milk.enabled) == (True, True)
    eggs = by_id["n:2"]
    assert (eggs.purchases, eggs.matchable, eggs.enabled) == (3, False, False)
    assert [c.art_id for c in cands] == ["n:2", "7"]  # po liczbie zakupów, potem nazwie


def _codes(h: History, today: date) -> set[str]:
    return {c.art_id for c in h.coupon_candidates(today) if c.enabled}


def test_opt_out_is_stored_and_excluded_from_auto_activation(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    h = History(path)
    _seed_candidates(h)
    today = date(2026, 10, 7)
    assert _codes(h, today) == {"7"}
    h.set_auto_activate("7", False)
    reopened = History(path)
    assert {c.art_id: c.enabled for c in reopened.coupon_candidates(today=today)}["7"] is False
    assert _codes(reopened, today) == set()
    reopened.set_auto_activate("7", True)
    assert _codes(reopened, today) == {"7"}


def test_ranking_can_be_limited_to_a_date_range(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("old", "2024-12-13"), _ticket("new", "2026-09-01")])
    h.save_detail("old", "S", _receipt(("1", "Stary produkt", 1, 2.0)))
    h.save_detail("new", "S", _receipt(("2", "Nowy produkt", 1, 3.0)))
    assert {r.art_id for r in h.ranking()} == {"1", "2"}
    assert [r.art_id for r in h.ranking(start=date(2025, 11, 1), end=date(2026, 10, 7))] == ["2"]
    assert [r.art_id for r in h.ranking(start=date(2024, 1, 1), end=date(2024, 12, 31))] == ["1"]


def _priced(*items: tuple[str, str, float, float, float]) -> ParsedReceipt:
    """Pozycje (kod, nazwa, ilość, cena półkowa, rabat) — rabat ujemny jak na paragonie."""
    return ParsedReceipt(items=[ReceiptItem(a, n, q, p, round(q * p, 2), d) for a, n, q, p, d in items])


def _seed_prices(h: History) -> None:
    days = ["2024-05-01", "2025-08-01", "2025-08-20", "2025-09-01", "2026-08-15", "2026-09-10"]
    h.upsert_tickets("a", [_ticket(f"t{i}", d) for i, d in enumerate(days)])
    h.save_detail("t0", "S", _priced(("4", "Stary", 1, 5.0, 0.0)))
    h.save_detail("t1", "S", _priced(("1", "Mleko", 1, 3.0, 0.0), ("2", "Chleb", 1, 5.0, 0.0)))
    h.save_detail("t2", "S", _priced(("1", "Mleko", 1, 9.9, 0.0)))  # anomalia: mediana ją pomija
    h.save_detail("t3", "S", _priced(("1", "Mleko", 1, 3.0, 0.0)))
    h.save_detail("t4", "S", _priced(("1", "Mleko", 1, 3.3, -0.6), ("3", "Nowy", 1, 5.0, 0.0)))
    h.save_detail(
        "t5",
        "S",
        _priced(("1", "Mleko", 1, 3.3, 0.0), ("2", "Chleb", 1, 4.0, 0.0), ("4", "Stary", 1, 5.0, 0.0)),
    )


def test_price_changes_compare_medians_year_over_year(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_prices(h)
    changes = h.price_changes(date(2026, 10, 8))
    assert [(c.art_id, c.old, c.new, c.pct, c.spend) for c in changes] == [
        ("1", 3.0, 3.3, 10.0, 6.0),
        ("2", 5.0, 4.0, -20.0, 4.0),
    ]


def test_basket_inflation_is_weighted_by_spend_with_coverage(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_prices(h)
    overview = h.price_overview(date(2026, 10, 8))
    assert overview.changes == h.price_changes(date(2026, 10, 8))
    assert (overview.basket.pct, overview.basket.products, overview.basket.coverage) == (-2.0, 2, 0.5)


def test_price_changes_bridge_names_and_weighed_per_kg(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("old", "2025-09-01"), _ticket("new", "2026-09-01")])
    h.save_detail(
        "old", "S", ParsedReceipt(items=[ReceiptItem("n:1", "Banany  luz", 0.5, 20.0, 10.0, is_weight=True)])
    )
    h.save_detail(
        "new", "S", ParsedReceipt(items=[ReceiptItem("0001", "banany luz", 1.5, 22.0, 33.0, is_weight=True)])
    )
    (bananas,) = h.price_changes(date(2026, 10, 8))
    assert (bananas.art_id, bananas.name, bananas.is_weight, bananas.pct) == (
        "0001",
        "banany luz",
        True,
        10.0,
    )


def test_basket_series_monthly_from_first_comparable_month(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a", [_ticket("t1", "2025-08-01"), _ticket("t2", "2026-08-15"), _ticket("t3", "2026-09-10")]
    )
    h.save_detail("t1", "S", _priced(("1", "Mleko", 1, 3.0, 0.0)))
    h.save_detail("t2", "S", _priced(("1", "Mleko", 1, 3.3, 0.0)))
    h.save_detail("t3", "S", _priced(("1", "Mleko", 1, 3.3, 0.0)))
    series = h.price_overview(date(2026, 10, 8)).series
    assert [(month, b.pct) for month, b in series] == [
        ("2026-08-01", 10.0),
        ("2026-09-01", 10.0),
        ("2026-10-01", 10.0),
    ]


def test_price_history_shelf_and_paid_per_unit(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_prices(h)
    milk = h.product_prices("1", date(2026, 10, 8))
    assert milk is not None and milk.change is not None
    assert (milk.name, milk.weight, milk.change.pct) == ("Mleko", False, 10.0)
    assert h.product_prices("brak") is None
    assert [(p.day, p.shelf, p.paid) for p in milk.points][-2:] == [
        ("2026-08-15", 3.3, 2.7),
        ("2026-09-10", 3.3, 3.3),
    ]


def test_prices_on_empty_database(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    today = date(2026, 10, 8)
    overview = h.price_overview(today)
    assert overview.changes == [] and overview.series == []
    assert (overview.basket.pct, overview.basket.products, overview.basket.coverage) == (None, 0, 0.0)


def test_price_overview_splits_spend_by_why_it_is_not_compared(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed_prices(h)
    h.upsert_tickets("a", [_ticket("t6", "2026-03-01")])
    h.save_detail("t6", "S", _priced(("5", "Rzadki", 1, 7.0, 0.0)))
    h.upsert_tickets("a", [_ticket("t7", "2026-02-01")])
    h.save_detail(
        "t7", "S", _priced(("n:590001", "Ser zolty plastry", 1, 9.0, 0.0), ("n:590002", "Kefir", 1, 2.0, 0.0))
    )
    split = h.price_overview(date(2026, 10, 8)).split
    assert {g: (s.spend, s.products, s.legacy_spend, s.legacy_products) for g, s in split.items()} == {
        "compared": (10.0, 2, 0.0, 0),  # Mleko i Chleb: zakupy w obu oknach
        "no_recent": (18.0, 3, 11.0, 2),  # Rzadki (marzec) i dwa stare kody n: (luty)
        "no_old_window": (5.0, 1, 0.0, 0),  # Stary: kupowany od 2024, ale nie latem 2025
        "no_history": (5.0, 1, 0.0, 0),  # Nowy: pierwszy zakup w ostatnim roku
    }
    assert split["no_recent"].legacy_examples == ["Ser zolty plastry", "Kefir"]  # od największych wydatków
    assert split["no_history"].examples == ["Nowy"]


def test_price_window_is_six_months(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    days = {"a_old": "2025-05-10", "a_new": "2026-05-10", "b_old": "2025-03-01", "b_new": "2026-03-01"}
    h.upsert_tickets("a", [_ticket(t, d) for t, d in days.items()])
    for t in ("a_old", "a_new"):  # ok. 5 mies. przed dniem porównania (i rok wcześniej): w oknie
        h.save_detail(t, "S", _priced(("1", "W oknie", 1, 2.0 if t == "a_old" else 2.2, 0.0)))
    for t in ("b_old", "b_new"):  # ok. 7 mies. przed: poza oknem
        h.save_detail(t, "S", _priced(("2", "Poza oknem", 1, 2.0, 0.0)))
    assert [c.name for c in h.price_changes(date(2026, 10, 8))] == ["W oknie"]


def test_merge_candidates_list_unbridged_old_codes_and_new_codes_without_history(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a", [_ticket("o1", "2025-11-02"), _ticket("o2", "2026-01-10"), _ticket("n1", "2026-05-01")]
    )
    h.save_detail(
        "o1", "S", _priced(("n:1", "Mleko UHT", 1, 3.0, 0.0), ("n:2", "Winog.jas.bezp.500g", 1, 9.0, 0.0))
    )
    h.save_detail(
        "o2",
        "S",
        _priced(("n:2", "Winog.jas.bezp.500", 1, 11.0, 0.0), ("n:2", "Winog.jas.bezp.500g", 1, 10.0, 0.0)),
    )
    h.save_detail(
        "n1",
        "S",
        _priced(("111", "Mleko UHT", 1, 3.2, 0.0), ("222", "Winogrono j.bezp.500", 1, 10.5, 0.0)),
    )
    c = h.merge_candidates()
    assert c["old"] == [
        {
            "code": "n:2",
            "names": ["Winog.jas.bezp.500g", "Winog.jas.bezp.500"],
            "weight": False,
            "price": 10.0,
            "purchases": 2,
            "first": "2025-11-02",
            "last": "2026-01-10",
        }
    ]
    assert [(x["code"], x["bridged"]) for x in c["new"]] == [("111", True), ("222", False)]  # wszystkie nowe


def test_merges_bridge_old_code_before_name_and_replace_all(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("o1", "2025-11-02"), _ticket("n1", "2026-05-01")])
    h.save_detail("o1", "S", _priced(("n:2", "Winog.jas.bezp.500g", 1, 9.0, 0.0)))
    h.save_detail("n1", "S", _priced(("222", "Winogrono j.bezp.500", 1, 10.5, 0.0)))
    assert h.set_merges([("n:2", "222"), ("333", "222")]) == 1  # tylko stare kody `n:`
    assert [x["code"] for x in h.merge_candidates()["old"]] == []
    assert h.set_merges([]) == 0
    assert [x["code"] for x in h.merge_candidates()["old"]] == ["n:2"]


def _receipts(tmp_path: Path) -> History:
    """Dwa konta, dwa sklepy, stary paragon NATIVE (kod `n:` połączony przez `merges`), paragon bez
    szczegółów."""
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "osoba-1", [_ticket("o1", "2025-11-02", total=12.0), _ticket("n1", "2026-05-01", total=9.5)]
    )
    h.upsert_tickets(
        "osoba-2", [_ticket("n2", "2026-05-20", total=4.0), _ticket("p1", "2026-06-01", total=7.0)]
    )
    h.save_detail("o1", None, _receipt(("n:5", "Fil.z ind.XXL", 1, 12.0)))
    h.save_detail(
        "n1",
        None,
        ParsedReceipt(
            items=[
                ReceiptItem(
                    "555",
                    "Filet z indyka XXL",
                    1,
                    11.0,
                    11.0,
                    discount=-2.0,
                    coupon=-2.0,
                    promo="Lidl Plus kupon",
                ),
                ReceiptItem("111", "Mleko UHT", 1, 0.5, 0.5),
            ],
            purchased_at="2026-05-01T19:39:20",
            store={"code": "PL0002", "name": "Miasto A Ulica B", "address": "", "postal": "", "locality": ""},
            payment="Karta płatnicza",
            deposit_charged=0.5,
            deposit_refunded=0.5,
        ),
    )
    h.save_detail(
        "n2",
        None,
        ParsedReceipt(
            items=[ReceiptItem("111", "Mleko UHT", 2, 2.0, 4.0)],
            store={"code": "PL0002", "name": "Miasto A Ulica B", "address": "", "postal": "", "locality": ""},
        ),
    )
    h.set_merges([("n:5", "555")])
    return h


def test_tickets_newest_first_with_store_status_and_savings(tmp_path: Path) -> None:
    from lidl.history import ReceiptFilter

    h = _receipts(tmp_path)
    found, total = h.tickets(ReceiptFilter(), limit=3)
    assert total == 4
    assert [(t.id, t.status) for t in found] == [("p1", "pending"), ("n2", "ok"), ("n1", "ok")]
    n1 = found[2]
    assert (n1.time, n1.store, n1.total, n1.savings, n1.items) == ("19:39", "Miasto A Ulica B", 9.5, 2.0, 2)
    assert found[0].store == "PL0001"  # bez szczegółów: kod sklepu z listy API


def test_tickets_filters_and_month_totals(tmp_path: Path) -> None:
    from lidl.history import ReceiptFilter

    h = _receipts(tmp_path)
    assert [t.id for t in h.tickets(ReceiptFilter(account="osoba-2"), 10)[0]] == ["p1", "n2"]
    assert [t.id for t in h.tickets(ReceiptFilter(store="PL0002"), 10)[0]] == ["n2", "n1"]
    may = ReceiptFilter(start=date(2026, 5, 1), end=date(2026, 5, 31))
    assert [t.id for t in h.tickets(may, 1)[0]] == ["n2"] and h.tickets(may, 1)[1] == 2
    months = {"2025-11": (1, 12.0), "2026-05": (2, 13.5), "2026-06": (1, 7.0)}
    assert h.ticket_months(ReceiptFilter()) == months


def test_unparsed_ticket_is_marked(tmp_path: Path) -> None:
    from lidl.history import ReceiptFilter

    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [_ticket("t1", "2026-01-01", articles=3)])
    h.save_detail("t1", None, ParsedReceipt())
    assert h.tickets(ReceiptFilter(), 10)[0][0].status == "unparsed"


def test_stores_most_frequent_first_with_latest_name(tmp_path: Path) -> None:
    h = _receipts(tmp_path)
    assert [(s.code, s.name, s.tickets) for s in h.stores()] == [
        ("PL0002", "Miasto A Ulica B", 2),
        ("PL0001", "PL0001", 2),
    ]


def test_ticket_detail_lines_resolve_products(tmp_path: Path) -> None:
    h = _receipts(tmp_path)
    d = h.ticket("n1")
    assert d is not None
    assert (d.payment, d.deposit_charged, d.deposit_refunded) == ("Karta płatnicza", 0.5, 0.5)
    assert [(x.product, x.name, x.discount, x.coupon, x.promo) for x in d.lines] == [
        ("555", "Filet z indyka XXL", -2.0, -2.0, "Lidl Plus kupon"),
        ("111", "Mleko UHT", 0.0, 0.0, ""),
    ]
    old = h.ticket("o1")
    assert old is not None and old.lines[0].product == "555"  # stary kod po `merges`
    assert h.ticket("brak") is None


def test_product_purchases_include_bridged_old_receipts(tmp_path: Path) -> None:
    h = _receipts(tmp_path)
    found = h.product_purchases("555")
    assert [(p.ticket.id, p.line.name, p.line.unit_price) for p in found] == [
        ("n1", "Filet z indyka XXL", 11.0),
        ("o1", "Fil.z ind.XXL", 12.0),
    ]
    assert [p.ticket.account for p in h.product_purchases("111")] == ["osoba-2", "osoba-1"]


def test_ranking_query_matches_any_name_of_the_product(tmp_path: Path) -> None:
    h = _receipts(tmp_path)
    assert [(r.art_id, r.name, r.purchases) for r in h.ranking(query="ind")] == [
        ("555", "Filet z indyka XXL", 2)
    ]
    assert [r.art_id for r in h.ranking(query="fil.z")] == ["555"]  # tylko stara nazwa pasuje
    assert h.ranking(query="chleb") == []


def test_product_purchases_split_old_code_by_bridged_name(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a", [_ticket("o1", "2025-01-01"), _ticket("o2", "2025-02-01"), _ticket("n1", "2026-05-01")]
    )
    h.save_detail("o1", None, _receipt(("n:7", "Ser A", 1, 5.0)))
    h.save_detail("o2", None, _receipt(("n:7", "Ser B", 1, 6.0)))
    h.save_detail("n1", None, _receipt(("777", "Ser B", 1, 6.5)))  # „Ser B” łączy się po nazwie z 777
    assert [p.ticket.id for p in h.product_purchases("777")] == ["n1", "o2"]
    assert [(p.ticket.id, p.line.name) for p in h.product_purchases("n:7")] == [("o1", "Ser A")]
    assert h.product_purchases("n:999") == []
