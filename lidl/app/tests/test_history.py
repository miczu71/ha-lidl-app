from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem


def _ticket(
    tid: str, day: str, total: float = 10.0, savings: float = 0.0, coupons: int = 0
) -> dict[str, Any]:
    return {
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


def test_savings_kpi_total_and_last_12_months(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [
            _ticket("old", "2024-01-01", savings=10.0, coupons=1),
            _ticket("new1", "2026-03-01", savings=5.5, coupons=2),
            _ticket("new2", "2026-09-01", savings=4.5),
        ],
    )
    kpi = h.savings_kpi(today=date(2026, 10, 7))
    assert (kpi.tickets, kpi.total, kpi.last_12m, kpi.coupons_used) == (3, 20.0, 10.0, 3)
    assert (kpi.first_date, kpi.last_date) == ("2024-01-01", "2026-09-01")


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
