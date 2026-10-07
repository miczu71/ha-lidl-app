"""Szczegół paragonu → wspólny model (HTML albo NATIVE) plus oczyszczanie kopii surowej do zapisu.

`PARSER_VERSION` rośnie, gdy zmienia się to, co wyciągamy z paragonu; paragony zapisane starszym parserem
są przetwarzane ponownie z lokalnej kopii (a bez kopii pobierane od nowa).
"""

from __future__ import annotations

import re
from typing import Any

from .receipt_html import ParsedReceipt, ReceiptCoupon, parse_receipt
from .receipt_native import parse_native

PARSER_VERSION = 3

# Dane osobowe i techniczne, których nie potrzebujemy (karta, kasjer, dane fiskalne, kody kreskowe).
_DROP_KEYS = {
    "cardInfo", "rawPaymentInformationHTML", "operatorId", "isEmployee", "fiscalDataAt", "fiscalDataCZ",
    "fiscalDataDe", "ustIdNr", "barCode", "codes", "logoUrl", "watermarkUrl",
}  # fmt: skip
_CARD_NUMBER = re.compile(r"\*{2,}\s?\d{2,4}|(?:\d{4}[ -]){3}\d{2,4}")


def parse_detail(detail: dict[str, Any]) -> ParsedReceipt:
    """Starsze paragony to `itemsLine` (NATIVE), nowsze HTML; nieznany format daje pusty wynik."""
    html = detail.get("htmlPrintedReceipt")
    if isinstance(detail.get("itemsLine"), list):
        receipt = parse_native(detail)
    elif isinstance(html, str):
        receipt = parse_receipt(html)
    else:
        receipt = ParsedReceipt()
    if detail.get("date"):
        receipt.purchased_at = str(detail["date"])[:19]
    store = detail.get("store")
    if isinstance(store, dict):
        receipt.store = {
            "code": str(store.get("id") or "").strip(),
            "name": str(store.get("name") or "").strip(),
            "address": str(store.get("address") or "").strip(),
            "postal": str(store.get("postalCode") or "").strip(),
            "locality": str(store.get("locality") or "").strip(),
        }
    for c in detail.get("couponsUsed") or []:
        if isinstance(c, dict):
            receipt.coupons.append(
                ReceiptCoupon(
                    title=str(c.get("title") or "").strip(),
                    coupon_title=str(c.get("couponTitle") or "").strip(),
                    description=str(c.get("couponDescription") or "").strip(),
                    discount=str(c.get("discount") or "").replace("‎", "").strip(),
                )
            )
    return receipt


def sanitize_detail(detail: Any) -> Any:
    """Kopia szczegółu bez danych osobowych (nie zmienia wejścia)."""
    if isinstance(detail, dict):
        return {
            k: (
                _CARD_NUMBER.sub("****", v)
                if k == "htmlPrintedReceipt" and isinstance(v, str)
                else sanitize_detail(v)
            )
            for k, v in detail.items()
            if k not in _DROP_KEYS
        }
    if isinstance(detail, list):
        return [sanitize_detail(v) for v in detail]
    return detail
