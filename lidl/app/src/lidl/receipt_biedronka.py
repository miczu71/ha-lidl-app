"""Szczegół transakcji Moja Biedronka (`transactions/{id}/`) → wspólny model paragonu.

Klucz produktu to `b:<EAN>` (brak EAN: `b:<nazwa małymi>`), więc nie koliduje z kodami Lidla (`n:`/HTML).
Kaucja nie jest pozycją: pozycje „kaucja” (ujemna kwota = zwrot) trafiają do sald kaucji.
"""

from __future__ import annotations

from typing import Any

from .receipt_html import ParsedReceipt, ReceiptItem


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0.0


def _lines(detail: dict[str, Any]) -> list[dict[str, Any]]:
    value = detail.get("items")
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def parse_biedronka(detail: dict[str, Any]) -> ParsedReceipt:
    receipt = ParsedReceipt()
    has_deposit_lines = False
    for line in _lines(detail):
        name = str(line.get("name") or "").strip()
        if "kaucj" in name.lower():
            has_deposit_lines = True
            amount = _num(line.get("total_price"))
            if amount >= 0:
                receipt.deposit_charged = round(receipt.deposit_charged + amount, 2)
            else:
                receipt.deposit_refunded = round(receipt.deposit_refunded - amount, 2)
            continue
        ean = str(line.get("ean") or "").strip()
        receipt.items.append(
            ReceiptItem(
                art_id=f"b:{ean or name.lower()}",
                name=name,
                quantity=_num(line.get("quantity") or 1),
                unit_price=_num(line.get("unit_price")),
                total=_num(line.get("total_price_without_discount")),
                discount=-abs(_num(line.get("total_discount"))),  # ujemny, jak rabaty Lidla
                is_weight=str(line.get("measure_unit") or "").upper() == "KG",
            )
        )
    if not has_deposit_lines:
        receipt.deposit_charged = round(_num(detail.get("sold_returnable_packagings_value")), 2)
        receipt.deposit_refunded = round(abs(_num(detail.get("collected_returnable_packagings_value"))), 2)
    receipt.deposit = round(receipt.deposit_charged - receipt.deposit_refunded, 2)
    if detail.get("date"):
        receipt.purchased_at = str(detail["date"])[:19]
    payments = detail.get("payments")
    if isinstance(payments, list) and payments and isinstance(payments[0], dict):
        receipt.payment = str(payments[0].get("name") or "") or None
    raw_store = detail.get("store")
    store: dict[str, Any] = raw_store if isinstance(raw_store, dict) else {}
    receipt.store = {
        "code": str(detail.get("store_id") or "").strip(),
        "name": str(detail.get("store_name") or "").strip(),
        "address": str(store.get("street") or "").strip(),
        "postal": str(store.get("zip_code") or "").strip(),
        "locality": str(store.get("city") or "").strip(),
    }
    return receipt
