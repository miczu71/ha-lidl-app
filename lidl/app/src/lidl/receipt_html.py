"""Parser HTML-owego paragonu Lidl Plus (`htmlPrintedReceipt`).

Każdy artykuł to dwa spany z tym samym `data-art-id`: linia nazwy i linia „ilość * cena suma”.
Rabat (`class="discount"`) dotyczy artykułu bezpośrednio przed nim. Kaucja jest tylko w podsumowaniu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_DETAIL_LINE = re.compile(r"^\d[\d.,]*\s*(?:kg|szt|g|l)?\s*[*x]\s*\d[\d.,]*\s+-?\d[\d.,]*(?:\s+[A-Z])?$")


@dataclass
class ReceiptItem:
    art_id: str
    name: str
    quantity: float
    unit_price: float
    total: float
    discount: float = 0.0
    coupon: float = 0.0  # część `discount` z kuponów Lidl Plus (opis zawiera „Lidl Plus”)


@dataclass
class ParsedReceipt:
    items: list[ReceiptItem] = field(default_factory=list)
    deposit: float = 0.0


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _last_number(text: str) -> float | None:
    found = _NUMBER.findall(text)
    return _num(found[-1]) if found else None


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.receipt = ParsedReceipt()
        self._attrs: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "span":
            return
        a = {k: v or "" for k, v in attrs}
        kind = a.get("class", "").split()
        if "article" in kind or "discount" in kind or a.get("id", "").startswith("purchase_summary"):
            self._attrs, self._text = a, []

    def handle_data(self, data: str) -> None:
        if self._attrs is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "span" or self._attrs is None:
            return
        attrs, text = self._attrs, "".join(self._text).strip()
        self._attrs = None
        kind = attrs.get("class", "").split()
        if "article" in kind:
            self._article(attrs, text)
        elif "discount" in kind:
            amount = _last_number(text)
            if self.receipt.items and amount is not None:
                item = self.receipt.items[-1]
                item.discount = round(item.discount + amount, 2)
                if "lidl plus" in text.lower():
                    item.coupon = round(item.coupon + amount, 2)
        elif text.startswith("Opakowania zwrotne suma"):
            self.receipt.deposit = _last_number(text) or 0.0

    def _article(self, attrs: dict[str, str], text: str) -> None:
        items = self.receipt.items
        if _DETAIL_LINE.match(text):
            total = _last_number(text.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ ").strip())
            if items and total is not None:
                items[-1].total = total
            return
        quantity = _num(attrs.get("data-art-quantity") or "1")
        unit = _num(attrs.get("data-unit-price") or "0")
        items.append(
            ReceiptItem(
                art_id=attrs.get("data-art-id", ""),
                name=attrs.get("data-art-description", "").strip(),
                quantity=quantity,
                unit_price=unit,
                total=round(quantity * unit, 2),
            )
        )


def parse_receipt(html: str) -> ParsedReceipt:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.receipt
