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
