from __future__ import annotations

import copy
from typing import Any

from lidl.receipt import PARSER_VERSION, parse_detail, sanitize_detail

STORE = {
    "id": "PL0001", "name": "Miasto A, ul. Testowa 1", "address": "ul. Testowa 1",
    "postalCode": "00-001", "locality": "Miasto A", "schedule": "",
}  # fmt: skip
COUPONS = [
    {"title": "Produkt X", "couponTitle": "-15%", "couponDescription": "Produkt X", "discount": "-15% Rabat ‎"}
]
NATIVE: dict[str, Any] = {
    "ticketType": "NATIVE",
    "date": "2026-03-20T16:35:06",
    "store": STORE,
    "couponsUsed": COUPONS,
    "payments": [
        {
            "type": "CreditCard", "description": "Karta płatnicza",
            "cardInfo": {"accountNumber": "123"}, "amount": "5,00",
        }
    ],
    "operatorId": "42",
    "itemsLine": [
        {"codeInput": "1", "name": "P", "quantity": "1", "currentUnitPrice": "5,00", "originalAmount": "5,00",
         "isWeight": False, "discounts": [], "deposit": None}
    ],
}  # fmt: skip


def test_parser_version_is_3() -> None:
    assert PARSER_VERSION == 3


def test_native_detail_gets_envelope_fields() -> None:
    parsed = parse_detail(NATIVE)
    assert len(parsed.items) == 1
    assert parsed.purchased_at == "2026-03-20T16:35:06"
    assert parsed.store == {
        "code": "PL0001", "name": "Miasto A, ul. Testowa 1", "address": "ul. Testowa 1",
        "postal": "00-001", "locality": "Miasto A",
    }  # fmt: skip
    assert [(c.title, c.coupon_title, c.description, c.discount) for c in parsed.coupons] == [
        ("Produkt X", "-15%", "Produkt X", "-15% Rabat")
    ]
    assert parsed.payment == "Karta płatnicza"


def test_html_detail_is_parsed_and_unknown_format_gives_no_items() -> None:
    attrs = 'class="article" data-art-id="1" data-unit-price="2,00" data-art-description="A"'
    html = (
        f"<span {attrs}>A</span>"
        f"<span {attrs}>1 * 2.00 2.00 C</span>"
        '<span id="purchase_summary_3">Płatność        Karta płatnicza 2,00</span>'
    )
    parsed = parse_detail({"date": "2026-10-05T19:39:20", "store": STORE, "htmlPrintedReceipt": html})
    assert [i.art_id for i in parsed.items] == ["1"] and parsed.payment == "Karta płatnicza"
    assert parsed.purchased_at == "2026-10-05T19:39:20"
    empty = parse_detail({"ticketType": "PDF", "date": "2020-01-01T10:00:00"})
    assert empty.items == [] and empty.purchased_at == "2020-01-01T10:00:00" and empty.store is None


def test_sanitize_removes_personal_fields_without_mutating_input() -> None:
    original = copy.deepcopy(NATIVE)
    clean = sanitize_detail(NATIVE)
    assert NATIVE == original
    assert "operatorId" not in clean and "cardInfo" not in clean["payments"][0]
    assert clean["payments"][0]["description"] == "Karta płatnicza"
    assert clean["itemsLine"] == NATIVE["itemsLine"] and clean["store"] == STORE


def test_sanitize_strips_card_numbers_and_fiscal_keys_from_html() -> None:
    detail = {
        "htmlPrintedReceipt": "<span>Karta **** 1234 AID A000</span><span>Razem 5,00</span>",
        "barCode": "888",
        "fiscalDataAt": {"x": 1},
        "ustIdNr": "PL123",
        "isEmployee": False,
    }
    clean = sanitize_detail(detail)
    assert "1234" not in clean["htmlPrintedReceipt"] and "Razem 5,00" in clean["htmlPrintedReceipt"]
    assert not {"barCode", "fiscalDataAt", "ustIdNr", "isEmployee"} & set(clean)
