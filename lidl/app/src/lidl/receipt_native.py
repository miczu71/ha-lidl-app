"""Parser szczegółów paragonu w formacie NATIVE (`itemsLine`) — starsze paragony (do marca 2026).

Kod pozycji (`codeInput`) to EAN albo PLU, nie wewnętrzny numer artykułu z paragonów HTML, więc klucz
produktu ma prefiks `n:`; łączenie z kodami HTML po nazwie robi `History` przy zapytaniach.
"""

from __future__ import annotations

from typing import Any

from .receipt_html import ParsedReceipt, ReceiptItem, add_promo


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return 0.0


def parse_native(detail: dict[str, Any]) -> ParsedReceipt:
    receipt = ParsedReceipt()
    for line in detail.get("itemsLine") or []:
        name = str(line.get("name") or "").strip()
        code = str(line.get("codeInput") or "").strip()
        item = ReceiptItem(
            art_id=f"n:{code or name.lower()}",
            name=name,
            quantity=_num(line.get("quantity") or 1),
            unit_price=_num(line.get("currentUnitPrice")),
            total=_num(line.get("originalAmount")),
            is_weight=bool(line.get("isWeight")),
        )
        for d in line.get("discounts") or []:
            description = str(d.get("description") or "")
            amount = _num(d.get("amount"))
            item.discount = round(item.discount - amount, 2)
            if "lidl plus" in description.lower():
                item.coupon = round(item.coupon - amount, 2)
            add_promo(item, description)
        deposit = line.get("deposit")
        if isinstance(deposit, dict):
            amount = _num(deposit.get("amount"))
            if amount >= 0:
                receipt.deposit_charged = round(receipt.deposit_charged + amount, 2)
            else:
                receipt.deposit_refunded = round(receipt.deposit_refunded - amount, 2)
        receipt.items.append(item)
    receipt.deposit = round(receipt.deposit_charged - receipt.deposit_refunded, 2)
    payments = detail.get("payments")
    if isinstance(payments, list) and payments and isinstance(payments[0], dict):
        receipt.payment = str(payments[0].get("description") or payments[0].get("type") or "") or None
    return receipt
