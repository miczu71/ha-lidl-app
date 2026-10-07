"""Model paragonu i parser HTML-owego paragonu Lidl Plus (`htmlPrintedReceipt`).

Każdy artykuł to dwa spany z tym samym `data-art-id`: linia nazwy i linia „ilość * cena suma”.
Rabat (`class="discount"`) dotyczy artykułu bezpośrednio przed nim. Kaucje są tylko w podsumowaniu:
pod „Opakowania zwrotne wydania” to kaucje pobrane, pod „…przyjęcia” zwroty (kaucji i opakowań bez kaucji).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")
_DETAIL_LINE = re.compile(r"^\d[\d.,]*\s*(?:kg|szt|g|l)?\s*[*x]\s*\d[\d.,]*\s+-?\d[\d.,]*(?:\s+[A-Z])?$")
_DEPOSIT_LINE = re.compile(r"\d\s*\*\s*[\d.,]+\s+-?\d[\d.,]*$")
_PAYMENT = re.compile(r"^Płatność\s+(.+?)\s+-?\d[\d.,]*$")
_TRAILING_AMOUNT = re.compile(r"\s*-?\d[\d.,]*\s*$")


@dataclass
class ReceiptItem:
    art_id: str
    name: str
    quantity: float
    unit_price: float
    total: float
    discount: float = 0.0
    coupon: float = 0.0  # część `discount` z kuponów Lidl Plus (opis zawiera „Lidl Plus”)
    is_weight: bool = False
    promo: str = ""  # opisy rabatów przy pozycji, np. „Lidl Plus kupon; Rabat grupowy”


@dataclass
class ReceiptCoupon:
    title: str
    coupon_title: str
    description: str
    discount: str


@dataclass
class ParsedReceipt:
    items: list[ReceiptItem] = field(default_factory=list)
    deposit: float = 0.0  # saldo kaucji: pobrane minus zwrócone
    deposit_charged: float = 0.0
    deposit_refunded: float = 0.0
    purchased_at: str | None = None  # czas lokalny z paragonu, np. 2026-10-05T19:39:20
    store: dict[str, str] | None = None
    payment: str | None = None
    coupons: list[ReceiptCoupon] = field(default_factory=list)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _last_number(text: str) -> float | None:
    found = _NUMBER.findall(text)
    return _num(found[-1]) if found else None


def add_promo(item: ReceiptItem, description: str) -> None:
    description = description.strip()
    if description and description not in item.promo.split("; "):
        item.promo = f"{item.promo}; {description}" if item.promo else description


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.receipt = ParsedReceipt()
        self._attrs: dict[str, str] | None = None
        self._text: list[str] = []
        self._section: str | None = None  # "issued" | "received" w podsumowaniu opakowań

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
            self._discount(text)
        else:
            self._summary(text)

    def _discount(self, text: str) -> None:
        amount = _last_number(text)
        if self.receipt.items and amount is not None:
            item = self.receipt.items[-1]
            item.discount = round(item.discount + amount, 2)
            if "lidl plus" in text.lower():
                item.coupon = round(item.coupon + amount, 2)
            add_promo(item, _TRAILING_AMOUNT.sub("", text))

    def _summary(self, text: str) -> None:
        receipt = self.receipt
        if text.startswith("Opakowania zwrotne wydania"):
            self._section = "issued"
        elif text.startswith("Opakowania zwrotne przyjęcia"):
            self._section = "received"
        elif text.startswith("Opakowania zwrotne suma"):
            receipt.deposit = _last_number(text) or 0.0
            self._section = None
        elif self._section and _DEPOSIT_LINE.search(text):
            amount = _last_number(text) or 0.0
            if self._section == "issued":
                receipt.deposit_charged = round(receipt.deposit_charged + abs(amount), 2)
            else:
                receipt.deposit_refunded = round(receipt.deposit_refunded + abs(amount), 2)
        elif (m := _PAYMENT.match(text)) and receipt.payment is None:
            receipt.payment = m.group(1).strip()

    def _article(self, attrs: dict[str, str], text: str) -> None:
        items = self.receipt.items
        if _DETAIL_LINE.match(text):
            total = _last_number(text.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ ").strip())
            if items and total is not None:
                items[-1].total = total
                items[-1].is_weight = bool(re.search(r"\dkg\b|\d\s+kg\b", text))
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
    receipt = parser.receipt
    if abs((receipt.deposit_charged - receipt.deposit_refunded) - receipt.deposit) > 0.015:
        # linie opakowań nie zgadzają się z linią „suma” — ufamy sumie
        receipt.deposit_charged = max(receipt.deposit, 0.0)
        receipt.deposit_refunded = max(-receipt.deposit, 0.0)
    return receipt
