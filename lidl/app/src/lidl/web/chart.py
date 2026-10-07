"""Zapytanie i dane wykresu wydatków (ekran „Produkty”): parsowanie parametrów GET, oś, etykiety, formaty."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from lidl.history import SpendBucket

STEPS = ("week", "month", "quarter", "year")
MAX_BUCKETS = 400
MAX_LABELS = 12
_STEP_DAYS = {"week": 7, "month": 31, "quarter": 92, "year": 366}
_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]
_FULL = [
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
]  # fmt: skip
_GENITIVE = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]  # fmt: skip
_ROMAN = ["I", "II", "III", "IV"]
_PER = {"week": "tygodniowo", "month": "miesięcznie", "quarter": "kwartalnie", "year": "rocznie"}


@dataclass(frozen=True)
class ChartQuery:
    start: date
    end: date
    step: str
    art_id: str | None
    metric: str  # "spend" | "qty"
    preset: str | None  # "12m" | "all" | None (daty własne)
    error: str | None
    truncated: bool


@dataclass(frozen=True)
class Bar:
    height: str
    label: str
    aria: str


@dataclass(frozen=True)
class Chart:
    bars: list[Bar]
    ticks: list[str]
    total: str
    average: str
    per: str
    empty: bool


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _last_12_months(today: date) -> tuple[date, date]:
    month = today.month - 11
    year = today.year + (month - 1) // 12
    start = date(year, (month - 1) % 12 + 1, 1)
    nxt = date(today.year + today.month // 12, today.month % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def parse_chart_query(params: Mapping[str, str], today: date, first_day: date | None) -> ChartQuery:
    step = params.get("krok", "")
    step = step if step in STEPS else "month"
    metric = "qty" if params.get("miara") == "sztuki" else "spend"
    art_id = (params.get("produkt") or "").strip() or None
    od, do = _date(params.get("od")), _date(params.get("do"))
    zakres = params.get("zakres")
    default_start, default_end = _last_12_months(today)
    if zakres == "all":
        start, end, preset = first_day or default_start, today, "all"
    elif zakres == "12m" or (od is None and do is None):
        start, end, preset = default_start, default_end, "12m"
    else:
        start, end, preset = od or first_day or default_start, do or today, None
    error = "range" if start > end else None
    truncated = False
    if error is None and (end - start).days / _STEP_DAYS[step] > MAX_BUCKETS:
        start, truncated = end - timedelta(days=MAX_BUCKETS * _STEP_DAYS[step]), True
    return ChartQuery(start, end, step, art_id, metric, preset, error, truncated)


def fmt_day_month(d: date) -> str:
    return f"{d.day} {_SHORT[d.month - 1]}"


def fmt_month_year_genitive(d: date) -> str:
    return f"{_GENITIVE[d.month - 1]} {d.year}"


def _group(value: str) -> str:
    return value.replace(",", " ")


def fmt_pln(value: float, decimals: int = 0) -> str:
    text = _group(f"{value:,.{decimals}f}")
    return f"{text.replace('.', ',')} zł"


def fmt_qty(value: float) -> str:
    return _group(f"{value:,.3f}").rstrip("0").rstrip(".").replace(".", ",")


def _nice_axis_max(top: float) -> float:
    """Najmniejsza „ładna” wartość osi (4 równe odstępy: 1, 2, 2,5, 5 × 10^k)."""
    if top <= 0:
        return 4.0
    raw = top / 4
    magnitude = float(10 ** math.floor(math.log10(raw)))
    for factor in (1, 2, 2.5, 5, 10):
        if factor * magnitude >= raw:
            return factor * magnitude * 4
    return 10 * magnitude * 4  # pragmatycznie nieosiągalne


def _label(step: str, d: date) -> str:
    if step == "week":
        return f"{d.day} {_SHORT[d.month - 1]}"
    if step == "month":
        return _SHORT[d.month - 1]
    if step == "quarter":
        return f"{_ROMAN[(d.month - 1) // 3]} kw."
    return str(d.year)


def _aria(step: str, d: date, value: str) -> str:
    if step == "week":
        return f"tydzień od {d.day} {_GENITIVE[d.month - 1]} {d.year}: {value}"
    if step == "month":
        return f"{_FULL[d.month - 1]} {d.year}: {value}"
    if step == "quarter":
        return f"{_ROMAN[(d.month - 1) // 3]} kwartał {d.year}: {value}"
    return f"{d.year}: {value}"


def build_chart(buckets: list[SpendBucket], step: str, metric: str) -> Chart:
    values = [b.spend if metric == "spend" else b.quantity for b in buckets]
    axis_max = _nice_axis_max(max(values, default=0.0))

    def fmt(v: float) -> str:
        return fmt_pln(v) if metric == "spend" else fmt_qty(v)

    every = max(1, math.ceil(len(buckets) / MAX_LABELS))
    bars = []
    for i, (b, v) in enumerate(zip(buckets, values, strict=True)):
        d = date.fromisoformat(b.start)
        aria_value = fmt_pln(v) if metric == "spend" else f"{fmt_qty(v)} szt."
        bars.append(
            Bar(
                height=f"{v / axis_max * 100:.1f}".rstrip("0").rstrip(".") + "%",
                label=_label(step, d) if i % every == 0 else "",
                aria=_aria(step, d, aria_value),
            )
        )
    ticks = [fmt(axis_max * k / 4) for k in (4, 3, 2, 1)] + ["0"]
    total = sum(values)
    average = total / len(values) if values else 0.0
    suffix = "" if metric == "spend" else " szt."
    return Chart(
        bars=bars,
        ticks=ticks,
        total=fmt(total) + suffix,
        average=fmt(average) + suffix,
        per=_PER[step],
        empty=total == 0,
    )
