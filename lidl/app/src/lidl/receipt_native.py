"""Parser szczegółów paragonu w formacie NATIVE (`itemsLine`) — starsze paragony (do marca 2026).

Kod pozycji (`codeInput`) to EAN albo PLU, nie wewnętrzny numer artykułu z paragonów HTML, więc klucz
produktu ma prefiks `n:`; łączenie z kodami HTML po nazwie robi `History` przy zapytaniach.
"""

from __future__ import annotations

from typing import Any

from .receipt_html import ParsedReceipt, ReceiptItem


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
        discount = coupon = 0.0
        for d in line.get("discounts") or []:
            amount = _num(d.get("amount"))
            discount -= amount
            if "lidl plus" in str(d.get("description") or "").lower():
                coupon -= amount
        deposit = line.get("deposit")
        if isinstance(deposit, dict):
            receipt.deposit = round(receipt.deposit + _num(deposit.get("amount")), 2)
        receipt.items.append(
            ReceiptItem(
                art_id=f"n:{code or name.lower()}",
                name=name,
                quantity=_num(line.get("quantity") or 1),
                unit_price=_num(line.get("currentUnitPrice")),
                total=_num(line.get("originalAmount")),
                discount=round(discount, 2),
                coupon=round(coupon, 2),
            )
        )
    return receipt
