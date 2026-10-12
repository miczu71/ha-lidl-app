from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time

from lidl.history import Event, LeafletProgress
from lidl.sync import SyncProgress
from lidl.web.status import Snapshot, build

NOW = datetime(2026, 10, 12, 12, 0)


def _ev(hour: int, area: str, level: str, summary: str = "x", day: int = 12, **detail: object) -> Event:
    return Event(datetime(2026, 10, day, hour, 0), area, level, summary, dict(detail), None)


MORNING = _ev(
    7, "daily", "ok", "Poranny przebieg", run="morning", accounts=2, coupons={"activated": 3}, promotions=67,
    notified=True, rewards=2,
)  # fmt: skip


def _snap(**over: object) -> Snapshot:
    base = Snapshot(
        now=NOW, started=datetime(2026, 10, 10, 6, 58), version="0.20.0", run_time=time(7, 0),
        accounts=[("osoba-1", "Osoba 1", True), ("osoba-2", "Osoba 2", True)],
        events=[MORNING], progress={}, daily_running=False, leaflets=[], refused=set(), llm_enabled=True,
        tickets=526, last_ticket=date(2026, 10, 11), db_bytes=40_000_000,
    )  # fmt: skip
    return replace(base, **over)  # type: ignore[arg-type]


def _area(view: object, key: str) -> object:
    return next(a for a in view.areas if a.key == key)  # type: ignore[attr-defined]


def test_quiet_day_has_no_problems() -> None:
    view = build(_snap())
    assert view.problems == []
    assert {a.key: a.level for a in view.areas} == {
        "system": "ok", "ai": "ok", "leaflet": "ok", "daily": "ok", "sync": "ok"
    }  # fmt: skip


def test_auth_error_flags_the_account_until_a_later_success() -> None:
    expired = _ev(7, "coupons", "error", account="osoba-2", auth=True)
    view = build(_snap(events=[expired, MORNING]))
    (p,) = view.problems
    assert (p.key, p.area, p.fix_href) == ("session:osoba-2", "system", "/konta")
    assert "Osoba 2" in p.text
    fixed = _ev(9, "account", "ok", account="osoba-2", auth=False)
    assert build(_snap(events=[fixed, expired, MORNING])).problems == []


def test_failed_morning_run_and_missed_run_are_problems() -> None:
    failed = _ev(7, "daily", "error", "Poranny przebieg przerwany (promocje)", run="morning", step="promocje")
    assert [p.key for p in build(_snap(events=[failed])).problems] == ["daily"]
    yesterday = replace(MORNING, ts=datetime(2026, 10, 11, 7, 0))
    assert [p.key for p in build(_snap(events=[yesterday])).problems] == ["daily"]  # 12:00, dziś brak
    early = NOW.replace(hour=8)
    assert build(_snap(events=[yesterday], now=early)).problems == []  # jeszcze w tolerancji
    assert build(_snap(events=[])).problems == []  # pierwszy dzień po aktualizacji: brak wpisów


def test_rejected_key_is_a_problem_and_limit_only_a_warning() -> None:
    key = _ev(11, "ai", "error", use="gazetka", model="m1", outcome="key")
    view = build(_snap(events=[key, MORNING]))
    assert [p.key for p in view.problems] == ["ai-key"]
    limited = build(_snap(refused={"m1"}))
    assert limited.problems == [] and _area(limited, "ai").level == "warn"  # type: ignore[attr-defined]


def test_leaflet_progress_and_abandoned_batches() -> None:
    busy = LeafletProgress(
        "f1", date(2026, 10, 13), date(2026, 10, 15), 8, 7, 0, datetime(2026, 10, 12, 12, 40), 5
    )
    area = _area(build(_snap(leaflets=[busy])), "leaflet")
    assert (area.level, area.progress) == ("busy", (8, 15))  # type: ignore[attr-defined]
    failed = replace(busy, pending=0, failed=2)
    assert [p.key for p in build(_snap(leaflets=[failed])).problems] == ["leaflet:f1"]


def test_running_import_shows_progress() -> None:
    area = _area(build(_snap(progress={"osoba-1": SyncProgress(True, 3, 10)})), "sync")
    assert (area.level, area.progress) == ("busy", (3, 10))  # type: ignore[attr-defined]


def test_timeline_groups_by_day_and_filters_by_area() -> None:
    events = [_ev(12, "ai", "warn"), MORNING, _ev(18, "daily", "ok", day=11)]
    view = build(_snap(events=events))
    assert [(d.label, len(d.rows)) for d in view.days] == [
        ("Dziś, 12 października", 2),
        ("Wczoraj, 11 października", 1),
    ]
    only = build(_snap(events=events), area="ai")
    assert [len(d.rows) for d in only.days] == [1]
