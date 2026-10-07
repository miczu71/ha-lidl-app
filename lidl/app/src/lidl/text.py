"""Polskie teksty wspólne dla panelu i powiadomień: odmiana liczebników, krótkie daty."""

from __future__ import annotations

from datetime import date, datetime

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


def fmt_date(d: date) -> str:
    return f"{fmt_day_month(d)} {d.year}"


def fmt_recent(d: date) -> str:
    """„13 gru” w bieżącym roku, „13 gru 2024” w innym."""
    return fmt_day_month(d) if d.year == date.today().year else fmt_date(d)


def fmt_time_day_month(dt: datetime) -> str:
    return f"{dt:%H:%M}, {fmt_day_month(dt.date())}"
