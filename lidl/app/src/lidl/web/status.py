"""Zakładka Status (E23): bieżący stan add-onu i dziennik 30 dni (docs/PLAN_E23_status.md).

`build()` to czysta funkcja migawki stanu (`Snapshot`) — bez bazy i sieci, więc reguły „co jest problemem”
są testowalne i te same dla strony, kropki na chipie i alertów (E23.3). Problem = coś, co wymaga działania
albo zatrzymało pracę add-onu: wygasła sesja, nieudany lub pominięty poranny przebieg, odrzucony klucz AI,
porzucona paczka gazetki. Limit modelu AI czy przerwany import (ponowi się sam) to tylko „Uwaga”.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from lidl.daily import EVENING, MONTHLY, STATUS_LABELS
from lidl.history import Event, LeafletProgress
from lidl.sync import SyncProgress
from lidl.text import count_text, fmt_day_month

MISSED_AFTER = timedelta(hours=2)  # poranny przebieg trwa minuty; po 2 h bez wpisu uznajemy go za pominięty
LEVELS = {"ok": "Działa", "busy": "W toku", "warn": "Uwaga", "err": "Wymaga działania"}
_RANK = {"err": 0, "warn": 1, "busy": 2, "ok": 3}
_GEN_MONTHS = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]  # fmt: skip
# filtr osi czasu → obszary dziennika (kupony kont to część porannego przebiegu)
FILTERS: dict[str, tuple[str, set[str]]] = {
    "daily": ("Przebiegi", {"daily", "coupons"}),
    "sync": ("Paragony", {"sync"}),
    "leaflet": ("Gazetka", {"leaflet"}),
    "ai": ("AI", {"ai"}),
    "system": ("System", {"system", "account", "budget"}),
}
_LEVEL_OF_EVENT = {"ok": "ok", "warn": "warn", "error": "err"}


@dataclass(frozen=True)
class Snapshot:
    now: datetime
    started: datetime
    version: str
    run_time: time
    accounts: list[tuple[str, str, bool]]  # slug, nazwa, połączone
    events: list[Event]  # 30 dni, najnowsze pierwsze
    progress: dict[str, SyncProgress]
    daily_running: bool
    leaflets: list[LeafletProgress]
    refused: set[str]  # modele z wyczerpanym limitem (gazetka)
    llm_enabled: bool
    tickets: int
    last_ticket: str | None
    db_bytes: int


@dataclass(frozen=True)
class Problem:
    key: str  # stały klucz alertu (E23.3): jeden push na problem
    area: str
    text: str
    fix_text: str = ""
    fix_href: str = ""


@dataclass
class Area:
    key: str
    name: str
    level: str
    say: str
    next: str = ""
    progress: tuple[int, int] | None = None
    steps: list[tuple[str, str]] = field(default_factory=list)
    models: list[tuple[str, int, int, int, str]] = field(default_factory=list)
    facts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LEVELS[self.level]


@dataclass(frozen=True)
class Row:
    time: str
    level: str
    summary: str
    duration: str


@dataclass(frozen=True)
class Day:
    label: str
    rows: list[Row]


@dataclass(frozen=True)
class StatusView:
    areas: list[Area]
    problems: list[Problem]
    days: list[Day]
    busy: bool


def fmt_duration(ms: int | None) -> str:
    if ms is None:
        return ""
    s = round(ms / 1000)
    return f"{s} s" if s < 120 else f"{s // 60} min"


def _when(dt: datetime, now: datetime) -> str:
    if dt.date() == now.date():
        return f"dziś {dt:%H:%M}"
    if dt.date() == now.date() - timedelta(days=1):
        return f"wczoraj {dt:%H:%M}"
    return f"{fmt_day_month(dt.date())} {dt:%H:%M}"


def _day_label(d: date, today: date) -> str:
    text = f"{d.day} {_GEN_MONTHS[d.month - 1]}"
    return "Dziś, " + text if d == today else "Wczoraj, " + text if d == today - timedelta(days=1) else text


def _next_at(now: datetime, at: time) -> datetime:
    target = datetime.combine(now.date(), at)
    return target if target > now else target + timedelta(days=1)


def _latest(events: list[Event], areas: set[str], pred: Any = None) -> Event | None:
    return next((e for e in events if e.area in areas and (pred is None or pred(e))), None)


def _account_event(s: Snapshot, areas: set[str], slug: str) -> Event | None:
    return _latest(s.events, areas, lambda e: e.detail.get("account") == slug)


def _system(s: Snapshot, problems: list[Problem]) -> Area:
    facts = []
    for slug, label, connected in s.accounts:
        last = _account_event(s, {"sync", "coupons", "account"}, slug)
        if not connected:
            facts.append((label, "niezalogowane"))
        elif last is not None and last.detail.get("auth"):
            facts.append((label, f"sesja wygasła ({_when(last.ts, s.now)})"))
            problems.append(
                Problem(f"session:{slug}", "system",
                        f"Sesja konta {label} wygasła — kupony i paragony tego konta stoją",
                        "Zaloguj ponownie na Kontach", "/konta")
            )  # fmt: skip
        else:
            facts.append((label, "sesja działa"))
    up = s.now - s.started
    facts += [
        ("Wersja", s.version),
        ("Działa od", f"{up.days} d {up.seconds // 3600} h" if up.days
                      else f"{up.seconds // 3600} h {up.seconds % 3600 // 60} min"),
        ("Baza", f"{s.db_bytes / 1_000_000:.1f} MB".replace(".", ",")),
    ]  # fmt: skip
    budget = _latest(s.events, {"budget"})
    if budget is not None:
        facts.append(("Plik dla Budżetu", f"{budget.summary.split(': ', 1)[-1]}, {_when(budget.ts, s.now)}"))
    mine = [p for p in problems if p.area == "system"]
    level = "err" if mine else "ok"
    say = (
        mine[0].text.split(" — ")[0]
        if mine
        else f"{count_text(sum(c for *_, c in s.accounts), 'konto', 'konta', 'kont')} połączone"
    )
    return Area("system", "Konta i system", level, say, facts=facts)


def _ai(s: Snapshot, problems: list[Problem]) -> Area:
    if not s.llm_enabled:
        return Area("ai", "Zapytania AI", "ok", "Wyłączone (brak opcji llm_url i llm_key)")
    today = [e for e in s.events if e.area == "ai" and e.ts.date() == s.now.date()]
    last = _latest(s.events, {"ai"})
    if last is not None and last.detail.get("outcome") == "key":
        problems.append(Problem("ai-key", "ai", "Klucz AI odrzucony — gazetka i kategorie stoją",
                                "Sprawdź opcję llm_key add-onu"))  # fmt: skip
    per: dict[str, Counter[str]] = {}
    times: dict[str, list[int]] = {}
    for e in today:
        model = str(e.detail.get("model"))
        per.setdefault(model, Counter())[str(e.detail.get("outcome"))] += 1
        if e.duration_ms is not None and e.detail.get("outcome") == "ok":
            times.setdefault(model, []).append(e.duration_ms)
    models = [
        (m, c["ok"], c["refused"], c["overloaded"] + c["key"],
         fmt_duration(sum(times[m]) // len(times[m])) if times.get(m) else "—")
        for m, c in per.items()
    ]  # fmt: skip
    total = sum((c for c in per.values()), Counter())
    if any(p.area == "ai" for p in problems):
        level, say = "err", "Klucz AI odrzucony"
    elif s.refused:
        level, say = "warn", f"Limit dnia: {', '.join(sorted(s.refused))}"
    else:
        level = "ok"
        say = f"Dziś {total['ok']} OK" + (
            f", {total['refused'] + total['overloaded']} nieudanych" if len(total) > 1 else ""
        )
    facts = [
        (
            "Dziś",
            f"{total['ok']} OK · {count_text(total['refused'], 'odmowa', 'odmowy', 'odmów')} · "
            f"{count_text(total['overloaded'], 'przeciążenie', 'przeciążenia', 'przeciążeń')}",
        )
    ]
    cat = _latest(s.events, {"ai"}, lambda e: e.detail.get("use") == "kategorie")
    if cat is not None:
        facts.append(("Kategorie produktów", f"ostatnio {_when(cat.ts, s.now)}"))
    return Area("ai", "Zapytania AI", level, say, models=models, facts=facts)


def _leaflet(s: Snapshot, problems: list[Problem]) -> Area:
    if not s.leaflets:
        return Area(
            "leaflet", "Gazetka", "ok", "Brak bieżącej gazetki" if s.llm_enabled else "Wyłączona (bez AI)"
        )
    cur = s.leaflets[0]
    for f in s.leaflets:
        if f.failed:
            problems.append(Problem(
                f"leaflet:{f.flyer_id}", "leaflet",
                f"Gazetka {fmt_day_month(f.start)}: porzucone paczki {f.failed} z {f.total} — "
                "część promocji nie trafi do porannego",
            ))  # fmt: skip
    facts = [
        ("Gazetka", f"{fmt_day_month(cur.start)}–{fmt_day_month(cur.end)}"),
        (
            "Paczki",
            f"{cur.done} z {cur.total} zrobione" + (f", {cur.failed} porzucone" if cur.failed else ""),
        ),
        ("Trafienia", str(cur.matches)),
    ]
    nxt = f"następna paczka {cur.next_try:%H:%M}" if cur.pending and cur.next_try else ""
    if cur.failed:
        return Area(
            "leaflet",
            "Gazetka",
            "err",
            f"Porzucone paczki: {cur.failed}",
            nxt,
            (cur.done, cur.total),
            facts=facts,
        )
    if cur.pending:
        return Area(
            "leaflet",
            "Gazetka",
            "busy",
            f"Paczka {cur.done + 1} z {cur.total}",
            nxt,
            (cur.done, cur.total),
            facts=facts,
        )
    return Area(
        "leaflet",
        "Gazetka",
        "ok",
        f"Gotowa: {count_text(cur.matches, 'trafienie', 'trafienia', 'trafień')}",
        facts=facts,
    )


def _daily(s: Snapshot, problems: list[Problem]) -> Area:
    morning = _latest(s.events, {"daily"}, lambda e: "accounts" in e.detail)
    due = datetime.combine(s.now.date(), s.run_time)
    nxt = _next_label(s)
    steps: list[tuple[str, str]] = []
    if morning is not None:
        d = morning.detail
        if "coupons" in d:
            steps = [
                ("Kupony", ", ".join(f"{STATUS_LABELS.get(k, k)} {n}" for k, n in d["coupons"].items())
                           or "bez zmian"),
                ("Promocje", str(d.get("promotions", "—"))),
                ("Nagrody", count_text(int(d.get("rewards", 0)), "konto", "konta", "kont")),
                ("Powiadomienie", "wysłane" if d.get("notified") else "brak"),
            ]  # fmt: skip
    facts = [(e.summary.split(": ", 1)[0], e.summary.split(": ", 1)[-1])
             for e in s.events if e.area == "daily" and "accounts" not in e.detail][:2]  # fmt: skip
    if s.daily_running:
        return Area(
            "daily", "Przebiegi zaplanowane", "busy", "Poranny przebieg w toku", nxt, steps=steps, facts=facts
        )
    if morning is not None and morning.level == "error" and morning.ts >= due - timedelta(hours=12):
        step = morning.detail.get("step", "")
        problems.append(Problem("daily", "daily", f"Poranny przebieg przerwany na kroku „{step}”",
                                "Szczegóły w osi czasu niżej"))  # fmt: skip
        return Area(
            "daily", "Przebiegi zaplanowane", "err", f"Przerwany: {step}", nxt, steps=steps, facts=facts
        )
    if s.now >= due + MISSED_AFTER and (morning is None or morning.ts < due):
        problems.append(
            Problem(
                "daily", "daily", f"Poranny przebieg {s.run_time:%H:%M} się nie odbył (add-on nie działał?)"
            )
        )
        return Area(
            "daily",
            "Przebiegi zaplanowane",
            "err",
            f"Dziś {s.run_time:%H:%M} się nie odbył",
            nxt,
            steps=steps,
            facts=facts,
        )
    if morning is None:
        return Area("daily", "Przebiegi zaplanowane", "ok", "Jeszcze bez przebiegu", nxt, facts=facts)
    say = f"{_when(morning.ts, s.now).capitalize()} gotowe" + (
        f" w {fmt_duration(morning.duration_ms)}" if morning.duration_ms else ""
    )
    return Area("daily", "Przebiegi zaplanowane", "ok", say, nxt, steps=steps, facts=facts)


def _next_label(s: Snapshot) -> str:
    """Najbliższe zaplanowane: poranny, zdrapki 18:00, podsumowanie 1. dnia miesiąca."""
    plan = [(_next_at(s.now, s.run_time), "poranny"), (_next_at(s.now, EVENING), "zdrapki")]
    first = (s.now.date().replace(day=1) + timedelta(days=32)).replace(day=1)
    plan.append((datetime.combine(first, MONTHLY), "podsumowanie miesiąca"))
    return " · ".join(f"{_when(at, s.now)} {what}" for at, what in sorted(plan)[:2])


def _sync(s: Snapshot) -> Area:
    running = [(slug, p) for slug, p in s.progress.items() if p.running]
    facts = []
    for slug, label, _ in s.accounts:
        last = _account_event(s, {"sync"}, slug)
        if last is not None:
            facts.append((label, f"{last.summary.split(': ', 1)[-1]} ({_when(last.ts, s.now)})"))
    say = f"{s.tickets} w bazie" + (
        f", ostatni {fmt_day_month(date.fromisoformat(s.last_ticket[:10]))}" if s.last_ticket else ""
    )
    if running:
        done, total = sum(p.done for _, p in running), sum(p.total for _, p in running)
        return Area(
            "sync",
            "Paragony",
            "busy",
            f"Import: {done} z {total} szczegółów",
            progress=(done, total),
            facts=facts,
        )
    failed = [
        e for slug, *_ in s.accounts
        if (e := _account_event(s, {"sync"}, slug)) and e.level == "error" and not e.detail.get("auth")
    ]  # fmt: skip
    nxt = f"{_when(_next_at(s.now, s.run_time), s.now)} z porannym"
    return Area("sync", "Paragony", "warn" if failed else "ok", say, nxt, facts=facts)


def build(s: Snapshot, area: str = "") -> StatusView:
    problems: list[Problem] = []
    areas = [_system(s, problems), _ai(s, problems), _leaflet(s, problems), _daily(s, problems), _sync(s)]
    areas.sort(key=lambda a: _RANK[a.level])
    wanted = FILTERS[area][1] if area in FILTERS else None
    days: dict[date, list[Row]] = {}
    for e in s.events:
        if wanted is None or e.area in wanted:
            days.setdefault(e.ts.date(), []).append(
                Row(f"{e.ts:%H:%M}", _LEVEL_OF_EVENT[e.level], e.summary, fmt_duration(e.duration_ms))
            )
    return StatusView(
        areas,
        problems,
        [Day(_day_label(d, s.now.date()), rows) for d, rows in days.items()],
        any(a.level == "busy" for a in areas),
    )
