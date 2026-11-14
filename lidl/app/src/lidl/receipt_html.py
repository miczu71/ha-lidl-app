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
# druga linia pozycji (ilość/waga) per locale; PL ma własną logikę, bo niesie kwotę; nie tworzy pozycji
_FOREIGN_DETAIL = {
    "cs": re.compile(r"^\d[\d.,]*\s*(?:ks|kg)\s+x\s+\d[\d.,]*\s+\S+/(?:ks|kg)$"),
    "it": re.compile(r"^(?:\d[\d.,]*\s*kg\s+x\s+\d[\d.,]*\s+\S+/kg|Cad\s+\d[\d.,]*\s+Pz\.\s+\d+)$"),
}
# CZ: pozycje ważone bez class=article — „Banány   16,20 B” i następna linia „N   0,406 kg   x 39,90  Kč/kg”
_CS_WEIGHT_HEAD = re.compile(r"^(?P<name>.+?)\s+(?P<amount>-?\d[\d.,]*)\s+[A-Z]$")
_CS_WEIGHT_LINE = re.compile(r"^[A-Z]\s+(?P<qty>\d[\d.,]*)\s*kg\s+x\s+(?P<unit>\d[\d.,]*)\s+\S+/kg$")
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
    def __init__(self, locale: str = "pl") -> None:
        super().__init__(convert_charrefs=True)
        self._locale = locale
        self._weight_open = False  # CZ: ostatnia pozycja czeka na linię „N 0,406 kg x …”
        self.receipt = ParsedReceipt()
        self._attrs: dict[str, str] | None = None
        self._text: list[str] = []
        self._section: str | None = None  # "issued" | "received" w podsumowaniu opakowań

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "span":
            return
        a = {k: v or "" for k, v in attrs}
        kind = a.get("class", "").split()
        plain = self._locale == "cs" and a.get("id", "").startswith("purchase_list_line")
        if "article" in kind or "discount" in kind or a.get("id", "").startswith("purchase_summary") or plain:
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
        elif attrs.get("id", "").startswith("purchase_list_line"):
            self._plain(text)
        else:
            if self._locale != "pl" and attrs.get("data-tender-description") and self.receipt.payment is None:
                self.receipt.payment = attrs["data-tender-description"].strip()
            self._summary(text)

    def _plain(self, text: str) -> None:
        """CZ: zwykłe linie listy — pozycje ważone; „Cena po slevě N” i reszta są ignorowane."""
        items = self.receipt.items
        if self._weight_open and items and (m := _CS_WEIGHT_LINE.match(text)):
            items[-1].quantity, items[-1].unit_price = _num(m.group("qty")), _num(m.group("unit"))
            self._weight_open = False
        elif not text.startswith("Cena po slev") and (m := _CS_WEIGHT_HEAD.match(text)):
            amount = _num(m.group("amount"))
            items.append(ReceiptItem("", m.group("name").strip(), 1.0, amount, amount, is_weight=True))
            self._weight_open = True

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
        self._weight_open = False
        if self._locale != "pl":
            self._foreign_article(attrs, text)
            return
        if _DETAIL_LINE.match(text):
            total = _last_number(text.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ ").strip())
            if items and total is not None:
                items[-1].total = total
                items[-1].is_weight = bool(re.search(r"\dkg\b|\d\s+kg\b", text))
            return
        self._add_article(
            attrs,
            round(_num(attrs.get("data-art-quantity") or "1") * _num(attrs.get("data-unit-price") or "0"), 2),
        )

    def _add_article(self, attrs: dict[str, str], total: float) -> None:
        self.receipt.items.append(
            ReceiptItem(
                art_id=attrs.get("data-art-id", ""),
                name=attrs.get("data-art-description", "").strip(),
                quantity=_num(attrs.get("data-art-quantity") or "1"),
                unit_price=_num(attrs.get("data-unit-price") or "0"),
                total=total,
            )
        )

    def _foreign_article(self, attrs: dict[str, str], text: str) -> None:
        pattern = _FOREIGN_DETAIL.get(self._locale)
        if pattern is not None and pattern.match(text):
            if self.receipt.items and re.search(r"\bkg\b", text):
                self.receipt.items[-1].is_weight = True
            return
        total = _last_number(text.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ ").strip())
        quantity = _num(attrs.get("data-art-quantity") or "1")
        unit = _num(attrs.get("data-unit-price") or "0")
        self._add_article(attrs, total if total is not None else round(quantity * unit, 2))


def parse_receipt(html: str, locale: str = "pl") -> ParsedReceipt:
    parser = _Parser(locale)
    parser.feed(html)
    parser.close()
    receipt = parser.receipt
    if abs((receipt.deposit_charged - receipt.deposit_refunded) - receipt.deposit) > 0.015:
        # linie opakowań nie zgadzają się z linią „suma” — ufamy sumie
        receipt.deposit_charged = max(receipt.deposit, 0.0)
        receipt.deposit_refunded = max(-receipt.deposit, 0.0)
    return receipt
