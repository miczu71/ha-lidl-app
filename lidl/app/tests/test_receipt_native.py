from __future__ import annotations

from typing import Any

from lidl.receipt_native import parse_native


def _line(
    code: str | None, name: str, qty: str, unit: str, amount: str, discounts=(), deposit=None, weight=False
):
    return {
        "codeInput": code,
        "name": name,
        "quantity": qty,
        "currentUnitPrice": unit,
        "originalAmount": amount,
        "isWeight": weight,
        "taxGroupName": "C",
        "discounts": [{"description": d, "amount": a} for d, a in discounts],
        "deposit": deposit,
        "giftSerialNumber": None,
    }


DETAIL: dict[str, Any] = {
    "ticketType": "NATIVE",
    "totalAmountString": "43,69",
    "itemsLine": [
        _line("5900000000011", "Produkt A", "3", "6,89", "20,67", [("Rabat grupowy", "6,88")]),
        _line(
            "57490", "Produkt B ", "1", "17,99", "17,99",
            [("Lidl Plus kupon", "2,70"), ("950_5536263", "0,50")],
        ),
        _line("5900000000028", "Produkt C luz", "0,448", "14,99", "6,72", weight=True),
        _line(
            None, "Napój kaucja", "2", "3,00", "6,00",
            deposit={"quantity": 2, "amount": "1,00", "unitPrice": "0,50"},
        ),
    ],
}  # fmt: skip


def test_items_quantities_prices_and_totals() -> None:
    parsed = parse_native(DETAIL)
    assert [(i.art_id, i.name, i.quantity, i.unit_price, i.total) for i in parsed.items] == [
        ("n:5900000000011", "Produkt A", 3.0, 6.89, 20.67),
        ("n:57490", "Produkt B", 1.0, 17.99, 17.99),
        ("n:5900000000028", "Produkt C luz", 0.448, 14.99, 6.72),
        ("n:napój kaucja", "Napój kaucja", 2.0, 3.0, 6.0),
    ]


def test_discounts_are_negative_and_coupons_split_out() -> None:
    items = parse_native(DETAIL).items
    assert [i.discount for i in items] == [-6.88, -3.2, 0.0, 0.0]
    assert [i.coupon for i in items] == [0.0, -2.7, 0.0, 0.0]


def test_deposit_and_receipt_sum() -> None:
    parsed = parse_native(DETAIL)
    assert parsed.deposit == 1.0
    gross = 20.67 + 17.99 + 6.72 + 6.00
    assert round(sum(i.total + i.discount for i in parsed.items) + parsed.deposit, 2) == round(
        gross - 6.88 - 3.2 + 1.0, 2
    )


def test_voucher_counts_as_coupon_and_missing_lines_give_no_items() -> None:
    detail = {"itemsLine": [_line("1", "P", "1", "10,00", "10,00", [("Lidl Plus voucher", "1,01")])]}
    (item,) = parse_native(detail).items
    assert (item.discount, item.coupon) == (-1.01, -1.01)
    assert parse_native({}).items == []
