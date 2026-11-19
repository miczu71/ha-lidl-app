"""Widok zakładki „Oszczędzanie” (E28.5.2): vouchery, oferty i Shakeomat Biedronki z migawki."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from lidl.chain_savings import URGENT_DAYS, SavedSaving, local_date
from lidl.text import fmt_pln

MESSAGES = {
    "shake_ok": ("ok", "Shakeomat odsłonięty. Nowe oferty widać niżej po odświeżeniu migawki."),
    "shake_none": ("info", "Brak dzisiejszego Shakeomatu do odsłonięcia."),
    "shake_noacc": ("err", "Konto Biedronki nie jest połączone. Zaloguj się ponownie w ustawieniach konta."),
    "shake_err": ("err", "Nie wszystko się udało. Szczegóły są w zakładce Status."),
}


@dataclass
class SavingsView:
    vouchers: list[dict[str, Any]] = field(default_factory=list)
    offers: list[dict[str, Any]] = field(default_factory=list)
    shakeomat: bool = False
    urgent_count: int = 0


def _entry(row: SavedSaving, today: date) -> dict[str, Any] | None:
    end = local_date(row.valid_to)
    if end is not None and end < today:
        return None
    days = (end - today).days if end else None
    pct = None
    if row.price is not None and row.regular_price and row.regular_price > row.price:
        pct = round((row.regular_price - row.price) / row.regular_price * 100)
    return {
        "name": row.name,
        "price": fmt_pln(row.price, 2) if row.price is not None else "",
        "regular": fmt_pln(row.regular_price, 2)
        if row.regular_price is not None and row.price is not None
        else "",
        "pct": pct,
        "until": f"do {end.day:02d}.{end.month:02d}" if end else "",
        "days_left": days,
        "urgent": days is not None and days <= URGENT_DAYS,
        "card_only": bool(row.extra.get("card_only")),
        "limit": row.extra.get("limit") or "",
        "_end": end or date.max,
    }


def build(rows: list[SavedSaving], today: date) -> SavingsView:
    view = SavingsView()
    for row in rows:
        entry = _entry(row, today)
        if entry is None:
            continue
        if row.kind == "shakeomat":
            view.shakeomat = True
        elif row.kind == "voucher":
            view.vouchers.append(entry)
        elif row.kind == "offer":
            view.offers.append(entry)
    for group in (view.vouchers, view.offers):
        group.sort(key=lambda e: (e["_end"], e["name"]))
    for entry in view.vouchers + view.offers:
        del entry["_end"]
    view.urgent_count = sum(1 for v in view.vouchers if v["urgent"])
    return view
