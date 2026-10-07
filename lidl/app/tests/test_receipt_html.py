from __future__ import annotations

from lidl.receipt_html import parse_receipt


def _article(
    line: int, art_id: str, name: str, unit: str, qty: str | None, detail: str, tax: str = "C"
) -> str:
    q = f' data-art-quantity="{qty}"' if qty else ""
    attrs = (
        f'class="article" data-art-id="{art_id}"{q} data-unit-price="{unit}"'
        f' data-tax-type="{tax}" data-art-description="{name}"'
    )
    return (
        f'<span id="purchase_list_line_{line}" {attrs}>{name:<30}</span>\n'
        f'<span id="purchase_list_line_{line + 1}" {attrs}>{detail:>36}</span>\n'
    )


def _discount(line: int, promo: str, label: str, amount: str) -> str:
    return (
        f'<span id="purchase_list_line_{line}" class="discount" data-promotion-id="{promo}">'
        f"   {label:<24}{amount}</span>\n"
    )


RECEIPT = (
    '<span class="header" data-till-country="PL"><span id="header_line_1"></span>\n'
    '<span class="purchase_list">'
    '<span id="purchase_list_line_1" class="currency" data-currency="zł">2026-01-02</span>\n'
    '<span id="purchase_list_line_2"></span>\n'
    + _article(3, "0100001", "Produkt A", "6,89", "3", "3 * 6.89 20.67 A", "A")
    + _discount(5, "111", "Rabat grupowy", "-6,88")
    + _article(6, "0100002", "Produkt B", "17,99", None, "1 * 17.99 17.99 C")
    + _discount(8, "100001006-PL-TEMPLATE-X-1", "Lidl Plus kupon", "-2,70")
    + _article(9, "0100003", "Produkt C luz", "14,99", "0,448", "0,448kg x 14.99 6.72 C")
    + _article(11, "0100001", "Produkt A", "6,89", None, "1 * 6.89 6.89 A", "A")
    + '<span class="vat_info"><span id="vat_info_line_1" data-tax-type="A">PTU A   21,77</span>\n'
    '<span class="purchase_summary"><span id="purchase_summary_1" class="css_big">Suma PLN</span>\n'
    '<span id="purchase_summary_1" class="css_big">43,69</span>\n'
    '<span id="purchase_summary_3">Opakowania zwrotne wydania             </span>\n'
    '<span id="purchase_summary_4">   Kaucja puszk            2 * 0.5 1.0</span>\n'
    '<span id="purchase_summary_5">Opakowania zwrotne suma           1,00</span>\n'
)


def test_each_article_is_listed_once_with_quantity_and_total() -> None:
    parsed = parse_receipt(RECEIPT)
    assert [(i.art_id, i.name, i.quantity, i.unit_price, i.total) for i in parsed.items] == [
        ("0100001", "Produkt A", 3.0, 6.89, 20.67),
        ("0100002", "Produkt B", 1.0, 17.99, 17.99),
        ("0100003", "Produkt C luz", 0.448, 14.99, 6.72),
        ("0100001", "Produkt A", 1.0, 6.89, 6.89),
    ]


def test_discount_attaches_to_preceding_article() -> None:
    parsed = parse_receipt(RECEIPT)
    assert [i.discount for i in parsed.items] == [-6.88, -2.7, 0.0, 0.0]


def test_deposit_is_read_from_summary() -> None:
    assert parse_receipt(RECEIPT).deposit == 1.0


def test_items_minus_discounts_match_receipt_total() -> None:
    parsed = parse_receipt(RECEIPT)
    assert round(sum(i.total + i.discount for i in parsed.items) + parsed.deposit, 2) == 43.69


def test_unknown_or_empty_html_gives_no_items() -> None:
    parsed = parse_receipt("<div>brak</div>")
    assert parsed.items == []
    assert parsed.deposit == 0.0


def test_several_discounts_on_one_article_are_summed() -> None:
    html = (
        _article(1, "0100009", "Produkt D", "10,00", None, "1 * 10.00 10.00 C")
        + _discount(3, "1", "Lidl Plus kupon", "-3,00")
        + _discount(4, "2", "Rabat Lidl Plus", "-0,50")
    )
    (item,) = parse_receipt(html).items
    assert item.discount == -3.5


def parse_native_html(html: str):  # noqa: ANN201
    return parse_receipt(html).items


def test_lidl_plus_discounts_are_coupons_others_are_not() -> None:
    html = (
        _article(1, "0100009", "Produkt D", "10,00", None, "1 * 10.00 10.00 C")
        + _discount(3, "1", "Lidl Plus kupon", "-3,00")
        + _discount(4, "2", "Taniej za 2", "-0,50")
        + _article(5, "0100010", "Produkt E", "5,00", None, "1 * 5.00 5.00 C")
        + _discount(7, "3", "Lidl Plus voucher", "-1,00")
    )
    a, b = parse_native_html(html)
    assert (a.discount, a.coupon) == (-3.5, -3.0)
    assert (b.discount, b.coupon) == (-1.0, -1.0)


def _summary(*lines: str) -> str:
    return "".join(f'<span id="purchase_summary_{n}">{line}</span>' for n, line in enumerate(lines, start=3))


def test_deposits_are_split_into_charged_and_refunded_by_section() -> None:
    parsed = parse_receipt(
        _summary(
            "Opakowania zwrotne wydania",
            "   Kaucja PET              4 * 0.5 2.0",
            "Opakowania zwrotne przyjęcia",
            "   Zwrot kaucji           1 * 7.0 -7.0",
            "   Opak bez kau           1 * 0.2 -0.2",
            "Opakowania zwrotne suma          -5,20",
        )
    )
    assert (parsed.deposit, parsed.deposit_charged, parsed.deposit_refunded) == (-5.2, 2.0, 7.2)


def test_charged_only_deposit_and_inconsistent_lines_fall_back_to_the_sum_line() -> None:
    charged = parse_receipt(
        _summary(
            "Opakowania zwrotne wydania",
            "   Kaucja puszk            2 * 0.5 1.0",
            "Opakowania zwrotne suma           1,00",
        )
    )
    assert (charged.deposit_charged, charged.deposit_refunded) == (1.0, 0.0)
    odd = parse_receipt(
        _summary(
            "Opakowania zwrotne wydania",
            "   Kaucja puszk            2 * 0.5 1.0",
            "Opakowania zwrotne suma          -5,00",
        )
    )
    assert (odd.deposit_charged, odd.deposit_refunded) == (0.0, 5.0)


def test_payment_weight_flag_and_discount_description() -> None:
    parsed = parse_receipt(RECEIPT + _summary("Płatność        Karta płatnicza 43,69"))
    assert parsed.payment == "Karta płatnicza"
    assert [i.is_weight for i in parsed.items] == [False, False, True, False]
    assert [i.promo for i in parsed.items] == ["Rabat grupowy", "Lidl Plus kupon", "", ""]
