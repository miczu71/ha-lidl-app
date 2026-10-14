from __future__ import annotations

from datetime import date

import pytest

from lidl.shopdays import easter, is_shopping_day, is_trading_sunday


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
    ],
)
def test_easter(year: int, expected: date) -> None:
    assert easter(year) == expected


TRADING = [
    # 2026: ostatnia niedziela stycznia/kwietnia/czerwca/sierpnia, przed Wielkanocą, 3 przed Bożym Narodzeniem
    date(2026, 1, 25), date(2026, 3, 29), date(2026, 4, 26), date(2026, 6, 28), date(2026, 8, 30),
    date(2026, 12, 6), date(2026, 12, 13), date(2026, 12, 20),
    # 2027 (Wielkanoc 28.03)
    date(2027, 1, 31), date(2027, 3, 21), date(2027, 4, 25), date(2027, 6, 27), date(2027, 8, 29),
    date(2027, 12, 5), date(2027, 12, 12), date(2027, 12, 19),
]  # fmt: skip


@pytest.mark.parametrize("day", TRADING)
def test_trading_sundays(day: date) -> None:
    assert is_trading_sunday(day) and is_shopping_day(day)


def test_every_year_has_eight_trading_sundays() -> None:
    for year in (2026, 2027, 2028, 2029):
        days = [
            d for n in range(366) if (d := date.fromordinal(date(year, 1, 1).toordinal() + n)).year == year
        ]
        assert sum(is_trading_sunday(d) for d in days) == 8, year


@pytest.mark.parametrize(
    "day",
    [
        date(2026, 1, 4), date(2026, 1, 18), date(2026, 3, 22), date(2026, 4, 5),  # 5.04 = Wielkanoc
        date(2026, 4, 19), date(2026, 10, 18), date(2026, 11, 29), date(2026, 12, 27),
    ],
)  # fmt: skip
def test_ordinary_sundays_are_closed(day: date) -> None:
    assert day.weekday() == 6 and not is_trading_sunday(day) and not is_shopping_day(day)


def test_weekdays_and_saturdays_are_shopping_days_and_never_trading_sundays() -> None:
    assert all(is_shopping_day(date(2026, 10, d)) for d in range(12, 18))  # pn–sob
    assert not is_trading_sunday(date(2026, 10, 14))
