"""Widok zakładki „Kupony Biedronki” (E28.5.2): vouchery, oferty i Shakeomat Biedronki z migawki."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from lidl.chain_savings import URGENT_DAYS, SavedSaving, local_date, local_hhmm, shake_state
from lidl.text import fmt_pln

MESSAGES = {
    "shake_ok": ("ok", "Shakeomat odsłonięty."),
    "shake_wait": (
        "info",
        "Ten Shakeomat jest już odsłonięty albo jeszcze niedostępny. "
        "Jeśli czeka na godzinę, przycisk się odblokuje.",
    ),
    "shake_none": ("info", "Brak Shakeomatu do odsłonięcia."),
    "shake_noacc": ("err", "Konto Biedronki nie jest połączone. Zaloguj się ponownie w ustawieniach konta."),
    "shake_err": ("err", "Nie wszystko się udało. Szczegóły są w zakładce Status."),
}


STALE_AFTER = timedelta(hours=36)


@dataclass
class SavingsView:
    vouchers: list[dict[str, Any]] = field(default_factory=list)
    offers: list[dict[str, Any]] = field(default_factory=list)
    shakeomat: bool = False  # jest kafelek Shakeomatu ważny dziś (karta widoczna)
    shake_state: str = "none"  # none | ready | wait | done (chain_savings.shake_state)
    shake_next_label: str = ""  # „13:47” (czas polski), gdy wait
    shake_ready_at: str = ""  # ISO UTC dla skryptu odblokowującego przycisk
    shake_offers: list[str] = field(default_factory=list)  # oferty oznaczone jako z Shakeomatu
    shake_drawn: list[str] = field(default_factory=list)  # „Mleko — 3,49 zł (zamiast 4,99 zł), do 25.11”
    urgent_count: int = 0
    fetched_label: str = ""  # „Dane z 20.11, 07:02” albo „Jeszcze bez danych”
    stale: bool = False  # migawka starsza niż STALE_AFTER (pominięty poranny przebieg)


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
        "shake": bool(row.extra.get("from_shakeomat")),
        "_end": end or date.max,
    }


def drawn_line(item: dict[str, Any]) -> str:
    """Jedna linia wyniku Shakeomatu: „Mleko 1l — 3,49 zł (zamiast 4,99 zł), do 25.11”."""
    line = str(item.get("name", ""))
    price, regular, end = item.get("price"), item.get("regular_price"), local_date(item.get("end"))
    if price is not None:
        line += f" — {fmt_pln(price, 2)}"
        if regular and regular > price:
            line += f" (zamiast {fmt_pln(regular, 2)})"
    if end is not None:
        line += f", do {end.day:02d}.{end.month:02d}"
    return line


def build(
    rows: list[SavedSaving],
    today: date,
    fetched: datetime | None = None,
    now: datetime | None = None,
    drawn: list[dict[str, Any]] | None = None,
) -> SavingsView:
    view = SavingsView()
    if fetched is None:
        view.fetched_label = "Jeszcze bez danych"
    else:
        view.fetched_label = f"Dane z {fetched:%d.%m, %H:%M}"
        local_now = now.astimezone().replace(tzinfo=None) if now and now.tzinfo else now or datetime.now()
        view.stale = local_now - fetched > STALE_AFTER
    moment = now if now is not None and now.tzinfo is not None else datetime.now(UTC)
    view.shake_state, ready_at = shake_state(rows, today, moment)
    view.shake_drawn = [drawn_line(d) for d in drawn or []]
    if view.shake_drawn and view.shake_state == "none":  # kafelek zniknął po odsłonięciu, wynik zostaje
        view.shake_state = "done"
    view.shakeomat = view.shake_state != "none"
    if ready_at is not None:
        view.shake_next_label = local_hhmm(ready_at)
        view.shake_ready_at = ready_at.isoformat()
    for row in rows:
        if row.kind == "shakeomat":  # karta Shakeomatu liczy się z `shake_state`, nie z listy
            continue
        entry = _entry(row, today)
        if entry is None:
            continue
        if row.kind == "offer" and row.extra.get("from_shakeomat"):
            view.shake_offers.append(row.name)
        if row.kind == "voucher":
            view.vouchers.append(entry)
        elif row.kind == "offer":
            view.offers.append(entry)
    for group in (view.vouchers, view.offers):
        group.sort(key=lambda e: (e["_end"], e["name"]))
    for entry in view.vouchers + view.offers:
        del entry["_end"]
    view.urgent_count = sum(1 for v in view.vouchers if v["urgent"])
    return view
