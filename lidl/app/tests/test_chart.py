from __future__ import annotations

from datetime import date

from lidl.history import SpendBucket
from lidl.web.chart import build_chart, fmt_pln, fmt_qty, parse_chart_query

TODAY = date(2026, 10, 7)
NBSP = " "


def test_default_is_last_12_months_monthly() -> None:
    q = parse_chart_query({}, TODAY, None)
    assert (q.start, q.end, q.step, q.metric, q.preset) == (
        date(2025, 11, 1),
        date(2026, 10, 31),
        "month",
        "spend",
        "12m",
    )
    assert q.art_id is None and q.error is None and not q.truncated


def test_unknown_step_falls_back_and_metric_and_product_are_read() -> None:
    q = parse_chart_query({"krok": "day", "miara": "sztuki", "produkt": " 0123659 "}, TODAY, None)
    assert (q.step, q.metric, q.art_id) == ("month", "qty", "0123659")
    assert parse_chart_query({"krok": "week"}, TODAY, None).step == "week"


def test_custom_range_and_missing_end_defaults_to_today() -> None:
    q = parse_chart_query({"od": "2026-01-15", "do": "2026-03-01"}, TODAY, None)
    assert (q.start, q.end, q.preset, q.error) == (date(2026, 1, 15), date(2026, 3, 1), None, None)
    q = parse_chart_query({"od": "2026-01-15"}, TODAY, None)
    assert q.end == TODAY


def test_reversed_range_is_an_error_and_garbage_dates_are_ignored() -> None:
    q = parse_chart_query({"od": "2026-05-01", "do": "2026-01-01"}, TODAY, None)
    assert q.error == "range"
    q = parse_chart_query({"od": "nie-data", "do": "2026-13-45"}, TODAY, None)
    assert q.error is None and q.preset == "12m"


def test_all_preset_starts_at_first_receipt() -> None:
    q = parse_chart_query({"zakres": "all"}, TODAY, date(2019, 5, 10))
    assert (q.start, q.end, q.preset) == (date(2019, 5, 10), TODAY, "all")
    q = parse_chart_query({"zakres": "all"}, TODAY, None)
    assert q.start == date(2025, 11, 1)


def test_12m_preset_overrides_dates() -> None:
    q = parse_chart_query({"zakres": "12m", "od": "2020-01-01"}, TODAY, None)
    assert q.start == date(2025, 11, 1) and q.preset == "12m"


def test_huge_weekly_range_is_truncated() -> None:
    q = parse_chart_query({"od": "1990-01-01", "do": "2026-01-01", "krok": "week"}, TODAY, None)
    assert q.truncated and (q.end - q.start).days <= 400 * 7


def test_money_and_quantity_formatting() -> None:
    assert fmt_pln(1842.3, 2) == f"1{NBSP}842,30 zł"
    assert fmt_pln(14830) == f"14{NBSP}830 zł"
    assert fmt_pln(0) == "0 zł"
    assert fmt_qty(12.0) == "12" and fmt_qty(0.448) == "0,448"


def _buckets(values: list[float], start_month: int = 1) -> list[SpendBucket]:
    return [SpendBucket(f"2026-{start_month + i:02d}-01", v, 1.0, 1) for i, v in enumerate(values)]


def test_axis_uses_nice_round_numbers_and_percent_heights() -> None:
    chart = build_chart(_buckets([1180, 1640]), "month", "spend")
    assert chart.ticks == [f"2{NBSP}000 zł", f"1{NBSP}500 zł", f"1{NBSP}000 zł", "500 zł", "0"]
    assert [b.height for b in chart.bars] == ["59%", "82%"]
    assert chart.total == f"2{NBSP}820 zł"
    assert chart.average == f"1{NBSP}410 zł" and chart.per == "miesięcznie"
    assert not chart.empty


def test_labels_and_aria_for_months() -> None:
    chart = build_chart(_buckets([10, 20]), "month", "spend")
    assert [b.label for b in chart.bars] == ["sty", "lut"]
    assert chart.bars[0].aria == "styczeń 2026: 10 zł"


def test_many_buckets_show_every_nth_label() -> None:
    values = [1.0] * 24
    buckets = [SpendBucket(f"{2024 + i // 12}-{i % 12 + 1:02d}-01", v, 1.0, 1) for i, v in enumerate(values)]
    labels = [b.label for b in build_chart(buckets, "month", "spend").bars]
    assert labels[0] == "sty" and labels[1] == "" and labels[2] == "mar"
    assert len([x for x in labels if x]) == 12


def test_week_quarter_and_year_labels() -> None:
    week = build_chart([SpendBucket("2026-01-05", 5.0, 1.0, 1)], "week", "spend").bars[0]
    assert (week.label, week.aria) == ("5 sty", "tydzień od 5 stycznia 2026: 5 zł")
    quarter = build_chart([SpendBucket("2026-04-01", 5.0, 1.0, 1)], "quarter", "spend").bars[0]
    assert (quarter.label, quarter.aria) == ("II kw.", "II kwartał 2026: 5 zł")
    year = build_chart([SpendBucket("2025-01-01", 5.0, 1.0, 1)], "year", "spend").bars[0]
    assert (year.label, year.aria) == ("2025", "2025: 5 zł")


def test_quantity_metric_and_empty_chart() -> None:
    chart = build_chart([SpendBucket("2026-01-01", 99.0, 3.0, 1)], "month", "qty")
    assert chart.total == "3 szt." and chart.ticks[-1] == "0" and chart.ticks[0] == "4"
    empty = build_chart(_buckets([0.0, 0.0]), "month", "spend")
    assert empty.empty


def test_day_month_and_genitive_month_year() -> None:
    from lidl.web.chart import fmt_day_month, fmt_month_year_genitive

    assert fmt_day_month(date(2026, 10, 5)) == "5 paź"
    assert fmt_month_year_genitive(date(2019, 5, 10)) == "maja 2019"
