"""Widok „Paragony” (E8): lista paragonów po miesiącach z filtrami, szczegół paragonu i zakupy produktu."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from lidl.history import Purchase, RankedProduct, ReceiptFilter, ReceiptLine, TicketDetail, TicketSummary
from lidl.text import count_text, fmt_date, fmt_day_month

from .chart import fmt_month_year, fmt_pln, fmt_qty, parse_date
from .prices import fmt_price
from .products import purchases_meta

TICKETS_LIMIT = 30  # paragonów na start i na każde „Pokaż więcej”
SEARCH_LIMIT = 20  # produktów w wynikach Szukaj
_WEEKDAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
_STATUS = {"pending": "Bez pozycji", "unparsed": "Nierozpoznany"}


def parse_filter(params: Mapping[str, str], accounts: set[str]) -> tuple[ReceiptFilter, bool]:
    """Filtry z adresu; nieznane konto i błędne daty pomijamy. Drugi element: „Od” później niż „Do”."""
    start, end = parse_date(params.get("od")), parse_date(params.get("do"))
    account = params.get("konto") or None
    f = ReceiptFilter(
        account=account if account in accounts else None,
        store=params.get("sklep") or None,
        start=start,
        end=end,
    )
    return f, bool(start and end and start > end)


def minus(value: float) -> str:
    """Rabat jako „−2,00 zł” (zawsze z minusem typograficznym)."""
    return "−" + fmt_pln(abs(value), 2)


def _when(t: TicketSummary, year: bool = False) -> str:
    d = date.fromisoformat(t.day)
    text = f"{_WEEKDAYS[d.weekday()]} {fmt_date(d) if year else fmt_day_month(d)}"
    return f"{text}, {t.time}" if t.time else text


def _where(t: TicketSummary, labels: Mapping[str, str]) -> list[str]:
    return [t.store or "Sklep nieznany", labels.get(t.account, t.account)]


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
        meta = _where(t, labels)
        if t.status == "ok":
            meta.append(count_text(t.items, "pozycja", "pozycje", "pozycji"))
        groups[-1]["rows"].append(
            {
                "when": _when(t),
                "meta": meta,
                "notes": [f"taniej o {fmt_pln(t.savings, 2)}"] if t.savings > 0 else [],
                "status": _STATUS.get(t.status),
                "total": fmt_pln(t.total, 2),
                "href": href(t.id),
            }
        )
    return groups


def _qty(line: ReceiptLine) -> str | None:
    """„2 × 3,49 zł”, „0,532 kg × 12,99 zł/kg”; przy jednej sztuce nic (cena = wartość)."""
    if line.is_weight:
        return f"{fmt_qty(line.quantity)} kg × {fmt_price(line.unit_price, True)}"
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
    lines: list[dict[str, Any]] = []
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
                "anchor": hit and not any(x["hit"] for x in lines),
            }
        )
    coupon = sum(x.coupon for x in d.lines)
    promo = sum(x.discount for x in d.lines) - coupon
    summary = [{"label": "Suma pozycji", "value": fmt_pln(sum(x.total for x in d.lines), 2)}]
    if coupon < 0:
        summary.append({"label": "Kupony Lidl Plus", "value": minus(coupon)})
    if promo < -0.004:
        summary.append({"label": "Promocje", "value": minus(promo)})
    if d.deposit_charged:
        summary.append({"label": "Kaucje pobrane", "value": "+" + fmt_pln(d.deposit_charged, 2)})
    if d.deposit_refunded:
        summary.append({"label": "Kaucje i opakowania zwrócone", "value": minus(d.deposit_refunded)})
    store, account = _where(t, labels)
    return {
        "when": _when(t, year=True),
        "store": store,
        "account": account,
        "payment": d.payment,
        "total": fmt_pln(t.total, 2),
        "savings": fmt_pln(t.savings, 2) if t.savings > 0 else None,
        "status": t.status,
        "positions": count_text(len(d.lines), "pozycja", "pozycje", "pozycji"),
        "lines": lines,
        "hits": any(x["hit"] for x in lines),
        "summary": summary,
        "coupons": d.coupons,
    }


def purchases_view(
    purchases: list[Purchase], labels: Mapping[str, str], ticket_href: Callable[[str], str]
) -> dict[str, Any]:
    """Zakupy produktu: podsumowanie i wiersze od najnowszych (zapłacono = wartość po rabatach pozycji)."""
    weight = any(p.line.is_weight for p in purchases)
    prices = [p.line.unit_price for p in purchases if p.line.unit_price > 0]
    low, high = (min(prices), max(prices)) if prices else (0.0, 0.0)
    qty = fmt_qty(sum(p.line.quantity for p in purchases))
    names = list(dict.fromkeys(p.line.name for p in purchases))
    rows = [
        {
            "when": _when(p.ticket, year=True),
            "meta": [*_where(p.ticket, labels), _qty(p.line) or fmt_price(p.line.unit_price, weight)],
            "notes": [f"{x['label']} {x['amount']}" for x in discounts(p.line)],
            "total": fmt_pln(p.line.paid, 2),
            "href": ticket_href(p.ticket.id),
        }
        for p in purchases
    ]
    return {
        "name": names[0],
        "other_names": names[1:],
        "count": count_text(len({p.ticket.id for p in purchases}), "paragonie", "paragonach", "paragonach"),
        "quantity": f"{qty} kg" if weight else f"{qty} szt.",
        "spent": fmt_pln(sum(p.line.paid for p in purchases), 2),
        "price": (
            fmt_price(low, weight)
            if low == high
            else f"{fmt_pln(low, 2).removesuffix(' zł')}–{fmt_price(high, weight)}"
        ),
        "last": fmt_date(date.fromisoformat(purchases[0].ticket.day)),
        "rows": rows,
    }


def product_rows(found: list[RankedProduct], href: Callable[[str], str]) -> list[dict[str, Any]]:
    """Wyniki Szukaj: produkt → jego zakupy."""
    return [
        {"name": p.name, "meta": purchases_meta(p.purchases, p.last_date), "href": href(p.art_id)}
        for p in found[:SEARCH_LIMIT]
    ]
