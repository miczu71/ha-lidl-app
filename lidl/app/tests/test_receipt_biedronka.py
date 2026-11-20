from __future__ import annotations

import copy
from typing import Any

from lidl.receipt import sanitize_detail
from lidl.receipt_biedronka import parse_biedronka

DETAIL: dict[str, Any] = {
    "id": "1001",
    "date": "2026-10-05T19:39:20+02:00",
    "total_price": 9.2,
    "store_id": "1234",
    "store_name": "Sklep X",
    "store": {"street": "ul. Testowa 1", "zip_code": "00-001", "city": "Miasto A"},
    "payments": [{"name": "Karta płatnicza"}],
    "receipt_barcode": "999",
    "extended_transaction_number": "1",
    "cashier_id": "7",
    "basket_id": "8",
    "invoice_id": "9",
    "id_from_receipt": "10",
    "items": [
        {
            "ean": "5900000000001",
            "name": "Mleko",
            "quantity": 2,
            "unit_price": 3.0,
            "total_price_without_discount": 6.0,
            "total_discount": 1.0,
            "total_price": 5.0,
            "measure_unit": "SZT",
        },
        {
            "ean": "5900000000002",
            "name": "Jabłka",
            "quantity": 0.5,
            "unit_price": 8.0,
            "total_price_without_discount": 4.0,
            "total_discount": 0.0,
            "total_price": 4.0,
            "measure_unit": "KG",
        },
        {
            "ean": "",
            "name": "Bułka",
            "quantity": 1,
            "unit_price": 0.0,
            "total_price_without_discount": 0.0,
            "total_discount": 0.0,
            "total_price": 0.0,
            "measure_unit": "SZT",
        },
        {
            "ean": "5900000000009",
            "name": "Kaucja za butelkę",
            "quantity": 1,
            "unit_price": 0.5,
            "total_price_without_discount": 0.5,
            "total_discount": 0,
            "total_price": 0.5,
            "measure_unit": "SZT",
        },
        {
            "ean": "5900000000010",
            "name": "KAUCJA zwrot",
            "quantity": 1,
            "unit_price": -0.3,
            "total_price_without_discount": -0.3,
            "total_discount": 0,
            "total_price": -0.3,
            "measure_unit": "SZT",
        },
    ],
}


def test_items_discount_weight_and_keys() -> None:
    r = parse_biedronka(DETAIL)
    assert [i.art_id for i in r.items] == ["b:5900000000001", "b:5900000000002", "b:bułka"]
    milk, apples, _ = r.items
    assert (milk.quantity, milk.unit_price, milk.total, milk.discount) == (
        2,
        3.0,
        6.0,
        -1.0,
    )  # rabat ujemny jak w Lidlu
    assert not milk.is_weight and apples.is_weight
    assert milk.coupon == 0 and milk.promo == ""


def test_deposit_lines_are_not_items() -> None:
    r = parse_biedronka(DETAIL)
    assert all("kaucj" not in i.name.lower() for i in r.items)
    assert (r.deposit_charged, r.deposit_refunded, r.deposit) == (0.5, 0.3, 0.2)


def test_deposit_from_summary_fields_when_no_lines() -> None:
    d = {
        **DETAIL,
        "items": DETAIL["items"][:2],
        "sold_returnable_packagings_value": 1.0,
        "collected_returnable_packagings_value": 0.4,
    }
    r = parse_biedronka(d)
    assert (r.deposit_charged, r.deposit_refunded, r.deposit) == (1.0, 0.4, 0.6)


def test_payment_store_and_time() -> None:
    r = parse_biedronka(DETAIL)
    assert r.payment == "Karta płatnicza" and r.purchased_at == "2026-10-05T19:39:20"
    assert r.store == {
        "code": "1234",
        "name": "Sklep X",
        "address": "ul. Testowa 1",
        "postal": "00-001",
        "locality": "Miasto A",
    }


def test_totals_add_up_to_receipt_total() -> None:
    r = parse_biedronka(DETAIL)
    assert round(sum(i.total + i.discount for i in r.items) + r.deposit, 2) == DETAIL["total_price"]


def test_sanitize_drops_identifiers() -> None:
    before = copy.deepcopy(DETAIL)
    clean = sanitize_detail(DETAIL)
    for k in (
        "receipt_barcode",
        "extended_transaction_number",
        "cashier_id",
        "basket_id",
        "invoice_id",
        "id_from_receipt",
    ):
        assert k not in clean
    assert clean["store_id"] == "1234" and DETAIL == before
