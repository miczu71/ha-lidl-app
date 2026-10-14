"""Dni, w które sklepy są otwarte: pn–sob oraz niedziele handlowe (E24).

Lidl nie podaje godzin otwarcia w publicznym API (`schedule` jest puste), więc niedziele handlowe wyliczamy
z ustawy o ograniczeniu handlu w niedzielę: ostatnia niedziela stycznia, kwietnia, czerwca i sierpnia,
niedziela przed Wielkanocą oraz trzy niedziele przed Bożym Narodzeniem (od 2025). Święta w dni robocze
pomijamy — godzinny sync w takim dniu jest tani i po prostu nic nie znajduje.
"""

from __future__ import annotations

from datetime import date, timedelta

SUNDAY = 6


def easter(year: int) -> date:
    """Niedziela Wielkanocna (algorytm anonimowy gregoriański, Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _last_sunday(year: int, month: int) -> date:
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - SUNDAY) % 7)


def is_trading_sunday(day: date) -> bool:
    if day.weekday() != SUNDAY:
        return False
    year = day.year
    if day in {_last_sunday(year, m) for m in (1, 4, 6, 8)}:
        return True
    if day == easter(year) - timedelta(days=7):
        return True
    christmas = date(year, 12, 25)
    last_before = christmas - timedelta(days=(christmas.weekday() - SUNDAY) % 7 or 7)
    return day in {last_before - timedelta(days=7 * n) for n in range(3)}


def is_shopping_day(day: date) -> bool:
    return day.weekday() != SUNDAY or is_trading_sunday(day)
