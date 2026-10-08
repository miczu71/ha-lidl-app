"""Widok „Paragony” (E8): lista paragonów po miesiącach z filtrami, szczegół paragonu i zakupy produktu."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from lidl.history import Purchase, RankedProduct, ReceiptFilter, ReceiptLine, TicketDetail, TicketSummary
from lidl.text import count_text, fmt_date, fmt_day_month, fmt_recent

from .chart import fmt_month_year, fmt_pln, fmt_qty

TICKETS_LIMIT = 30  # paragonów na start i na każde „Pokaż więcej”
SEARCH_LIMIT = 20  # produktów w wynikach Szukaj
_WEEKDAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
_STATUS = {"pending": "Bez pozycji", "unparsed": "Nierozpoznany"}


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_filter(params: Mapping[str, str], accounts: set[str]) -> tuple[ReceiptFilter, bool]:
    """Filtry z adresu; nieznane konto i błędne daty pomijamy. Drugi element: „Od” później niż „Do”."""
    start, end = _date(params.get("od")), _date(params.get("do"))
    account = params.get("konto") or None
    f = ReceiptFilter(
        account=account if account in accounts else None,
        store=params.get("sklep") or None,
        start=start,
        end=end,
    )
    return f, bool(start and end and start > end)


def parse_tickets_limit(raw: str | None) -> int:
    try:
        return max(int(raw or TICKETS_LIMIT), 1)
    except ValueError:
        return TICKETS_LIMIT


def minus(value: float) -> str:
    """Rabat jako „−2,00 zł” (zawsze z minusem typograficznym)."""
    return "−" + fmt_pln(abs(value), 2)


def _when(t: TicketSummary, year: bool = False) -> str:
    d = date.fromisoformat(t.day)
    text = f"{_WEEKDAYS[d.weekday()]} {fmt_date(d) if year else fmt_day_month(d)}"
    return f"{text}, {t.time}" if t.time else text


def _ticket_meta(t: TicketSummary, labels: Mapping[str, str]) -> list[str]:
    meta = [t.store or "Sklep nieznany", labels.get(t.account, t.account)]
    if t.status == "ok":
        meta.append(count_text(t.items, "pozycja", "pozycje", "pozycji"))
    return meta


def ticket_row(t: TicketSummary, labels: Mapping[str, str], href: str) -> dict[str, Any]:
    return {
        "when": _when(t),
        "meta": _ticket_meta(t, labels),
        "total": fmt_pln(t.total, 2),
        "savings": f"taniej o {fmt_pln(t.savings, 2)}" if t.savings > 0 else None,
        "status": _STATUS.get(t.status),
        "href": href,
    }


def month_groups(
    tickets: list[TicketSummary],
    months: Mapping[str, tuple[int, float]],
    labels: Mapping[str, str],
    href: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Paragony pogrupowane po miesiącach; liczba i suma z całego miesiąca (nie tylko z pokazanych)."""
    groups: list[dict[str, Any]] = []
    for t in tickets:
        key = t.day[:7]
        if not groups or groups[-1]["key"] != key:
            count, total = months.get(key, (0, 0.0))
            groups.append(
                {
                    "key": key,
                    "title": fmt_month_year(date.fromisoformat(f"{key}-01")),
                    "meta": f"{count_text(count, 'paragon', 'paragony', 'paragonów')} · {fmt_pln(total, 2)}",
                    "rows": [],
                }
            )
        groups[-1]["rows"].append(ticket_row(t, labels, href(t.id)))
    return groups


def _qty(line: ReceiptLine) -> str | None:
    """„2 × 3,49 zł”, „0,532 kg × 12,99 zł/kg”; przy jednej sztuce nic (cena = wartość)."""
    if line.is_weight:
        return f"{fmt_qty(line.quantity)} kg × {fmt_pln(line.unit_price, 2)}/kg"
    if line.quantity == 1:
        return None
    return f"{fmt_qty(line.quantity)} × {fmt_pln(line.unit_price, 2)}"


def discounts(line: ReceiptLine) -> list[dict[str, str]]:
    """Rabaty pozycji: kupon Lidl Plus i reszta (promocja, z opisem z paragonu, gdy jest)."""
    out = []
    if line.coupon < 0:
        out.append({"label": "Kupon Lidl Plus", "amount": minus(line.coupon)})
    promo = round(line.discount - line.coupon, 2)
    if promo < 0:
        names = [p for p in line.promo.split("; ") if p and "lidl plus" not in p.casefold()]
        out.append({"label": ", ".join(names) or "Promocja", "amount": minus(promo)})
    return out


def detail_view(
    d: TicketDetail, labels: Mapping[str, str], product: str | None, product_href: Callable[[str], str]
) -> dict[str, Any]:
    """Szczegół paragonu: pozycje z rabatami (szukany produkt wyróżniony) i rozliczenie do zapłaty."""
    t = d.ticket
    lines, first_hit = [], True
    for line in d.lines:
        hit = product is not None and line.product == product
        lines.append(
            {
                "name": line.name,
                "href": product_href(line.product),
                "qty": _qty(line),
                "total": fmt_pln(line.total, 2),
                "discounts": discounts(line),
                "hit": hit,
                "anchor": hit and first_hit,
            }
        )
        first_hit = first_hit and not hit
    gross = sum(x.total for x in d.lines)
    coupon = sum(x.coupon for x in d.lines)
    promo = sum(x.discount for x in d.lines) - coupon
    summary = [{"label": "Suma pozycji", "value": fmt_pln(gross, 2)}]
    if coupon < 0:
        summary.append({"label": "Kupony Lidl Plus", "value": minus(coupon)})
    if promo < -0.004:
        summary.append({"label": "Promocje", "value": minus(promo)})
    if d.deposit_charged:
        summary.append({"label": "Kaucje pobrane", "value": "+" + fmt_pln(d.deposit_charged, 2)})
    if d.deposit_refunded:
        summary.append({"label": "Kaucje i opakowania zwrócone", "value": minus(d.deposit_refunded)})
    return {
        "when": _when(t, year=True),
        "store": t.store or "Sklep nieznany",
        "account": labels.get(t.account, t.account),
        "payment": d.payment,
        "total": fmt_pln(t.total, 2),
        "savings": fmt_pln(t.savings, 2) if t.savings > 0 else None,
        "status": t.status,
        "positions": count_text(len(d.lines), "pozycja", "pozycje", "pozycji"),
        "lines": lines,
        "hits": sum(x["hit"] for x in lines),
        "summary": summary,
        "coupons": d.coupons,
    }


def purchases_view(
    purchases: list[Purchase], labels: Mapping[str, str], ticket_href: Callable[[str], str]
) -> dict[str, Any]:
    """Zakupy produktu: podsumowanie i wiersze od najnowszych (zapłacono = wartość po rabatach pozycji)."""
    weight = any(p.line.is_weight for p in purchases)
    prices = [p.line.unit_price for p in purchases if p.line.unit_price > 0]
    unit = "/kg" if weight else ""
    spent = sum(p.line.total + p.line.discount for p in purchases)
    qty = sum(p.line.quantity for p in purchases)
    names = list(dict.fromkeys(p.line.name for p in purchases))
    tickets = {p.ticket.id for p in purchases}
    rows = []
    for p in purchases:
        price = fmt_pln(p.line.unit_price, 2) + unit
        rows.append(
            {
                "when": _when(p.ticket, year=True),
                "meta": [
                    p.ticket.store or "Sklep nieznany",
                    labels.get(p.ticket.account, p.ticket.account),
                    _qty(p.line) or price,
                ],
                "discounts": discounts(p.line),
                "paid": fmt_pln(p.line.total + p.line.discount, 2),
                "href": ticket_href(p.ticket.id),
            }
        )
    low, high = (min(prices), max(prices)) if prices else (0.0, 0.0)
    return {
        "name": names[0],
        "other_names": names[1:],
        "count": count_text(len(tickets), "paragonie", "paragonach", "paragonach"),
        "quantity": f"{fmt_qty(qty)} kg" if weight else f"{fmt_qty(qty)} szt.",
        "spent": fmt_pln(spent, 2),
        "price": (
            f"{fmt_pln(low, 2)}{unit}"
            if low == high
            else f"{fmt_pln(low, 2).removesuffix(' zł')}–{fmt_pln(high, 2)}{unit}"
        ),
        "last": fmt_date(date.fromisoformat(purchases[0].ticket.day)),
        "rows": rows,
    }


def product_rows(found: list[RankedProduct], href: Callable[[str], str]) -> list[dict[str, Any]]:
    """Wyniki Szukaj: produkt → jego zakupy."""
    return [
        {
            "name": p.name,
            "meta": [
                count_text(p.purchases, "zakup", "zakupy", "zakupów"),
                "ostatnio " + fmt_recent(date.fromisoformat(p.last_date)),
            ],
            "href": href(p.art_id),
        }
        for p in found[:SEARCH_LIMIT]
    ]
