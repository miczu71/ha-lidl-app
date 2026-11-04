from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from lidl.history import History, ReceiptFilter
from lidl.receipt_html import ParsedReceipt, ReceiptCoupon, ReceiptItem
from lidl.savings import classify_promo, is_coupon_label, match_title, promo_group, split_promo


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


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Rabat -15%", ("Rabat procentowy", "Rabat -15%")),
        ("rabat  -5%", ("Rabat procentowy", "rabat -5%")),
        ("Rabat -7,5%", ("Rabat procentowy", "Rabat -7,5%")),
        ("Rabat grupowy", ("Rabat grupowy", "Rabat grupowy")),
        ("RABAT GRUPOWY", ("Rabat grupowy", "RABAT GRUPOWY")),
        ("Taniej za 2", ("Taniej za N", "Taniej za 2")),
        ("Taniej za 3", ("Taniej za N", "Taniej za 3")),
        ("Lidl Plus rabat", ("Lidl Plus rabat", "Lidl Plus rabat")),
        ("Lidl Plus kupon", ("Kupon", "Lidl Plus kupon")),
        ("Nieznana etykieta XYZ", ("Inne", "Nieznana etykieta XYZ")),
    ],
)
def test_classify_promo_table(label: str, expected: tuple[str, str]) -> None:
    assert classify_promo(label) == expected


def test_coupon_labels_are_recognised_and_not_promotions() -> None:
    assert is_coupon_label("Lidl Plus kupon")
    assert is_coupon_label("lidl plus VOUCHER")
    assert not is_coupon_label("Lidl Plus rabat")
    assert not is_coupon_label("Rabat grupowy")


def test_split_promo_by_semicolon() -> None:
    assert split_promo("Lidl Plus kupon; Rabat grupowy") == ["Lidl Plus kupon", "Rabat grupowy"]
    assert split_promo("Taniej za 2") == ["Taniej za 2"]
    assert split_promo("") == []


def test_promo_group_single_multiple_and_empty() -> None:
    assert promo_group(["Rabat -10%"]) == ("Rabat procentowy", "Rabat -10%")
    assert promo_group(["Rabat grupowy", "Taniej za 2"]) == (
        "Kilka promocji naraz",
        "Rabat grupowy; Taniej za 2",
    )
    assert promo_group([]) == ("Inne", "(bez etykiety)")


_COUPONS = [
    {"title": "Produkt", "coupon_title": "-10%", "description": "Produkt", "discount": "-10% Rabat"},
    {"title": "Produkt X", "coupon_title": "-15%", "description": "Produkt X", "discount": "-15% Rabat"},
    {"title": "Mleko Łaciate 3,2%", "coupon_title": "-2 zł", "description": "Mleko", "discount": "-2 zł"},
]


def test_match_title_prefers_equal_then_contained_ignoring_case_and_diacritics() -> None:
    assert match_title("produkt x", _COUPONS) == _COUPONS[1]
    assert match_title("PRODUKT X 500 g", _COUPONS) == _COUPONS[0]
    assert match_title("Mleko laciate 3,2% 1 l", _COUPONS) == _COUPONS[2]
    assert match_title("Chleb", _COUPONS) is None
    assert match_title("Chleb", []) is None


def _receipt(*items: ReceiptItem, coupons: list[ReceiptCoupon] | None = None) -> ParsedReceipt:
    return ParsedReceipt(items=list(items), coupons=coupons or [])


@pytest.fixture
def seeded(tmp_path: Path) -> History:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [
            _ticket("t1", "2026-05-05", total=30.0, savings=8.0, coupons=1),
            _ticket("t2", "2026-06-06", total=20.0, savings=0.0, coupons=1),
            _ticket("t4", "2024-01-10", total=5.0, savings=0.0, coupons=1),
            _ticket("t5", "2026-06-08", total=7.0, savings=3.0),  # bez szczegółów
        ],
    )
    h.upsert_tickets("b", [_ticket("t3", "2026-06-07", total=10.0, savings=4.0)])
    h.save_detail(
        "t1",
        "S",
        _receipt(
            ReceiptItem(
                "1",
                "Produkt X",
                1,
                10.0,
                10.0,
                discount=-5.0,
                coupon=-3.0,
                promo="Lidl Plus kupon; Rabat grupowy",
            ),
            ReceiptItem("2", "Mleko", 1, 4.0, 4.0, discount=-1.0, promo="Taniej za 2"),
            coupons=[ReceiptCoupon("Produkt X", "-15%", "Produkt X", "-15% Rabat")],
        ),
    )
    h.save_detail(
        "t2",
        "S",
        _receipt(
            ReceiptItem("1", "Produkt X", 1, 10.0, 10.0, discount=-4.0, coupon=-4.0, promo="Lidl Plus kupon")
        ),
    )
    h.save_detail(
        "t3",
        "S",
        _receipt(
            ReceiptItem("3", "Pieczywo", 1, 4.0, 4.0, discount=-1.0, promo="Lidl Plus rabat; Taniej za 2")
        ),
    )
    h.save_detail(
        "t4",
        "S",
        _receipt(ReceiptItem("4", "Stary", 1, 5.0, 5.0, discount=-2.0, coupon=-2.0, promo="Lidl Plus kupon")),
    )
    return h


def test_coupon_rows_close_to_coupons_total(seeded: History) -> None:
    b = seeded.savings_breakdown()
    assert sum(r.amount for r in b.coupon_rows) == pytest.approx(b.coupons_total)
    assert b.coupons_total == pytest.approx(9.0)
    by_id = {r.art_id: r for r in b.coupon_rows}
    assert by_id["1"].amount == pytest.approx(7.0)
    assert by_id["1"].uses == 2
    assert (by_id["1"].title, by_id["1"].discount) == ("Produkt X", "-15% Rabat")
    assert by_id["1"].last_day == "2026-06-06"
    assert by_id["4"].uses == 1
    assert by_id["4"].title is None and by_id["4"].discount is None


def test_promo_groups_close_to_promos_total(seeded: History) -> None:
    b = seeded.savings_breakdown()
    assert b.promos_total == pytest.approx(4.0)
    assert sum(g.amount for g in b.groups) == pytest.approx(b.promos_total)
    names = {g.name: g.amount for g in b.groups}
    assert names == pytest.approx({"Rabat grupowy": 2.0, "Taniej za N": 1.0, "Kilka promocji naraz": 1.0})


def test_repeat_products_counts_products_with_two_or_more_receipts(seeded: History) -> None:
    b = seeded.savings_breakdown()
    assert b.repeat_products == 1


def test_general_coupons_are_separate_and_zero_without_difference(seeded: History) -> None:
    b = seeded.savings_breakdown()
    # t1: 8 − 6 = 2; t2: 0 − 4 < 0 → 0; t3: 4 − 1 = 3; t4: 0 − 2 < 0 → 0; t5 bez szczegółów → 0
    assert b.general_coupons_amount == pytest.approx(5.0)
    assert b.coupons_total + b.promos_total == pytest.approx(seeded.savings_kpi().total)
    only_t3 = seeded.savings_breakdown(ReceiptFilter(account="b"))
    assert only_t3.general_coupons_amount == pytest.approx(3.0)
    assert (only_t3.coupons_total, only_t3.promos_total) == (0.0, 1.0)
    zero = seeded.savings_breakdown(ReceiptFilter(start=date(2026, 6, 6), end=date(2026, 6, 6)))
    assert zero.general_coupons_amount == 0.0


def test_filters_narrow_both_sums(seeded: History) -> None:
    b = seeded.savings_breakdown(ReceiptFilter(account="b"))
    assert (b.coupons_total, b.promos_total, b.spend_total) == (0.0, 1.0, 10.0)
    period = seeded.savings_breakdown(ReceiptFilter(start=date(2026, 1, 1), end=date(2026, 12, 31)))
    assert period.coupons_total == pytest.approx(7.0)
    assert period.promos_total == pytest.approx(4.0)
    assert period.spend_total == pytest.approx(67.0)  # 30 + 20 + 10 + 7 (także bez szczegółów)


def test_monthly_trend_splits_coupons_and_promos(seeded: History) -> None:
    b = seeded.savings_breakdown()
    assert [(m.month, round(m.coupons, 2), round(m.promos, 2)) for m in b.months] == [
        ("2024-01", 2.0, 0.0),
        ("2026-05", 3.0, 3.0),
        ("2026-06", 4.0, 1.0),
    ]
