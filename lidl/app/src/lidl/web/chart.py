"""Wykresy panelu: słupki wydatków („Produkty”: parametry GET, oś, etykiety, formaty) i linie cen („Ceny”)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from lidl.history import SpendBucket
from lidl.text import SHORT_MONTHS as _SHORT
from lidl.text import fmt_day_month as fmt_day_month

STEPS = ("week", "month", "quarter", "year")
MAX_BUCKETS = 400
MAX_LABELS = 12
_STEP_DAYS = {"week": 7, "month": 31, "quarter": 92, "year": 366}
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
        start, end = od or first_day or default_start, do or today
        if (start, end) == (default_start, default_end):  # np. daty dołączone przez wyszukiwanie na żywo
            preset = "12m"
        elif first_day and (start, end) == (first_day, today):
            preset = "all"
        else:
            preset = None
    error = "range" if start > end else None
    truncated = False
    if error is None and (end - start).days / _STEP_DAYS[step] > MAX_BUCKETS:
        start, truncated = end - timedelta(days=MAX_BUCKETS * _STEP_DAYS[step]), True
    return ChartQuery(start, end, step, art_id, metric, preset, error, truncated)


def fmt_month_year_genitive(d: date) -> str:
    return f"{_GENITIVE[d.month - 1]} {d.year}"


def fmt_month_year(d: date) -> str:
    """„Październik 2026” (nagłówek miesiąca)."""
    return f"{_FULL[d.month - 1].capitalize()} {d.year}"


def _group(value: str) -> str:
    return value.replace(",", " ")


def fmt_pln(value: float, decimals: int = 0) -> str:
    text = _group(f"{value:,.{decimals}f}")
    return f"{text.replace('.', ',')} zł"


def fmt_qty(value: float) -> str:
    return _group(f"{value:,.3f}").rstrip("0").rstrip(".").replace(".", ",")


def _nice_axis_max(top: float) -> float:
    """Najmniejsza „ładna” wartość osi od zera (4 równe odstępy: 1, 2, 2,5, 5 × 10^k)."""
    return 4 * _nice_range(0.0, top)[1] if top > 0 else 4.0


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


# --- Wykres liniowy (ekran „Ceny”, E7) ---------------------------------------------------------------
# SVG w viewBox 1000×200 rozciągany na szerokość (preserveAspectRatio="none", kreski non-scaling-stroke);
# punkty to odcinki zerowej długości z okrągłymi końcami, więc nie zamieniają się w elipsy. Osie w HTML
# (ta sama siatka 4 odstępów co słupki).
LINE_W, LINE_H = 1000, 200
MAX_TIME_LABELS = 6


@dataclass(frozen=True)
class LineChart:
    line: str
    dots: list[str]
    end: str
    zero: str | None  # linia 0, gdy oś obejmuje wartości ujemne
    ticks: list[str]  # od góry, 5 wartości
    labels: list[tuple[str, str]]  # (pozycja w %, etykieta) na osi czasu
    aria: str


def _nice_range(lo: float, hi: float) -> tuple[float, float]:
    """Dół osi i krok: 4 równe „ładne” odstępy (1, 2, 2,5, 5 × 10^k) obejmujące `lo`–`hi`."""
    hi = max(hi, lo + 0.01)
    magnitude = float(10 ** math.floor(math.log10((hi - lo) / 4)))
    for factor in (1, 2, 2.5, 5, 10, 20):
        step = factor * magnitude
        bottom = math.floor(lo / step + 1e-9) * step
        if bottom + 4 * step >= hi - 1e-9:
            return bottom, step
    return math.floor(lo / (50 * magnitude)) * 50 * magnitude, 50 * magnitude  # pragmatycznie nieosiągalne


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def _time_labels(first: date, last: date) -> list[tuple[str, str]]:
    """Lata (1 stycznia) przy zakresie ponad 2 lata, inaczej co kilka miesięcy; bez etykiet przy brzegach."""
    span = max((last - first).days, 1)
    if span > 730:
        marks = [(date(y, 1, 1), str(y)) for y in range(first.year + 1, last.year + 1)]
    else:
        months = []
        d = _next_month(first)
        while d <= last:
            months.append(d)
            d = _next_month(d)
        every = max(1, math.ceil(len(months) / MAX_TIME_LABELS))
        marks = [(d, f"{_SHORT[d.month - 1]} {d:%y}") for d in months[::every]]
    out = []
    for d, text in marks:
        pos = (d - first).days / span * 100
        if 4 <= pos <= 96:
            out.append((f"{pos:.1f}", text))
    return out


def build_line(
    points: list[tuple[date, float]],
    fmt: Callable[[float], str],
    aria: str,
    *,
    dots: list[tuple[date, float]] | None = None,
    step: bool = False,
    zero: bool = False,
    last: date | None = None,
) -> LineChart:
    """Linia `points` (rosnące daty), opcjonalnie schodkowa (cena obowiązuje do następnej zmiany) i
    przedłużona do `last`; `dots` to osobne punkty (np. ceny zapłacone); `zero` dokłada 0 do osi."""
    dots = dots or []
    values = [v for _, v in points] + [v for _, v in dots] + ([0.0] if zero else [])
    bottom, size = _nice_range(min(values), max(values))
    top = bottom + 4 * size
    first = min(d for d, _ in points + dots)
    end = max([last or first] + [d for d, _ in points + dots])
    span = max((end - first).days, 1)

    def x(d: date) -> str:
        return f"{(d - first).days / span * LINE_W:.1f}"

    def y(v: float) -> str:
        return f"{(top - v) / (top - bottom) * LINE_H:.1f}"

    path = f"M{x(points[0][0])},{y(points[0][1])}"
    for d, v in points[1:]:
        path += f"H{x(d)}V{y(v)}" if step else f"L{x(d)},{y(v)}"
    tail_x = x(end) if step else x(points[-1][0])
    if step:
        path += f"H{tail_x}"
    return LineChart(
        line=path,
        dots=[f"M{x(d)},{y(v)}h0" for d, v in dots],
        end=f"M{tail_x},{y(points[-1][1])}h0",
        zero=f"M0,{y(0.0)}H{LINE_W}" if bottom < 0 < top else None,
        ticks=[fmt(top - k * size) for k in range(5)],
        labels=_time_labels(first, end),
        aria=aria,
    )
