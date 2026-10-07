"""Polskie teksty wspólne dla panelu i powiadomień: odmiana liczebników, krótkie daty."""

from __future__ import annotations

from datetime import date

SHORT_MONTHS = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]


def plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count_text(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {plural(n, one, few, many)}"


def fmt_day_month(d: date) -> str:
    return f"{d.day} {SHORT_MONTHS[d.month - 1]}"
