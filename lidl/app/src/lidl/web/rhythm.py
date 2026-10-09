"""Widok „Rytm” (E9/E10): kiedy (dzień tygodnia × godzina) i gdzie (sklepy, mapa) robimy zakupy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from lidl.history import Rhythm, StoreStats
from lidl.text import count_text, fmt_pln, fmt_recent, plural

DAYS = ["Pn", "Wt", "Śr", "Cz", "Pt", "So", "Nd"]
_DAYS_FULL = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
_ON_DAY = ["poniedziałek", "wtorek", "środę", "czwartek", "piątek", "sobotę", "niedzielę"]
LEVELS = 5  # odcienie heatmapy poza pustą komórką
HOUR_LABEL_STEP = 3


def heatmap(r: Rhythm, spend: bool) -> dict[str, Any] | None:
    """Siatka dni × godzin (tylko godziny z zakupami) z poziomem koloru; None bez paragonów z godziną."""
    data: Mapping[tuple[int, int], float] = r.spend if spend else r.visits
    if not data:
        return None
    first, last = min(h for _, h in data), max(h for _, h in data)
    top = max(data, key=lambda k: (data[k], -k[0], -k[1]))  # remis: wcześniejszy dzień i godzina
    peak = data[top]

    def cell(d: int, h: int) -> dict[str, Any]:
        v = data.get((d, h), 0)
        amount = fmt_pln(v) if spend else count_text(int(v), "wizyta", "wizyty", "wizyt")
        return {
            "level": min(LEVELS, 1 + int(v / peak * LEVELS)) if v else 0,
            "label": f"{_DAYS_FULL[d]} {h}:00–{h + 1}:00: {amount}",
            "top": (d, h) == top,
        }

    day, hour = top
    return {
        "hours": [str(h) if (h - first) % HOUR_LABEL_STEP == 0 else "" for h in range(first, last + 1)],
        "rows": [{"day": DAYS[d], "cells": [cell(d, h) for h in range(first, last + 1)]} for d in range(7)],
        "say": "Najwięcej wydajemy" if spend else "Najczęściej kupujemy",
        "on": "we" if day == 1 else "w",  # „we wtorek”
        "day": _ON_DAY[day],
        "between": f"{hour} a {hour + 1}",
    }


def store_rows(
    stores: list[StoreStats], labels: Mapping[str, str], href: Callable[[str], str]
) -> list[dict[str, Any]]:
    """Wiersze listy sklepów; podział na konta tylko przy więcej niż jednym koncie (zera zostają, żeby
    kolory pasków odpowiadały kontom)."""
    rows = []
    for s in stores:
        split = [(label, s.accounts.get(slug, 0)) for slug, label in labels.items()]
        rows.append(
            {
                "name": s.name,
                "address": s.address,
                "located": s.location is not None,
                "visits": s.tickets,
                "visits_word": plural(s.tickets, "wizyta", "wizyty", "wizyt"),
                "paid": fmt_pln(s.paid),
                "average": fmt_pln(s.average),
                "savings": fmt_pln(s.savings) if s.savings > 0 else None,
                "last": fmt_recent(date.fromisoformat(s.last_day)),
                "split": split if len(labels) > 1 else [],
                "href": href(s.code),
            }
        )
    return rows


def map_points(stores: list[StoreStats], href: Callable[[str], str]) -> list[dict[str, Any]]:
    """Punkty mapy (dane dla Leaflet w szablonie); sklepy bez współrzędnych pomijamy."""
    return [
        {
            "name": s.name,
            "lat": s.location[0],
            "lon": s.location[1],
            "visits": s.tickets,
            "meta": f"{count_text(s.tickets, 'wizyta', 'wizyty', 'wizyt')} · {fmt_pln(s.paid)}",
            "href": href(s.code),
        }
        for s in stores
        if s.location
    ]
