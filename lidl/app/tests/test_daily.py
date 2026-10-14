from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from lidl import notify
from lidl.accounts import Account
from lidl.coupons import AccountReport, Activation, ActiveCoupon
from lidl.daily import DailyJob, at_time_loop, hourly_loop, next_hour, seconds_until, sync_due
from lidl.history import History, WatchedCoupon
from lidl.promotions import Promotion
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.rewards import Rewards, ScratchCard
from lidl.text import fmt_until


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 7, 6, 30), 30 * 60),  # dziś o 7:00
        (datetime(2026, 10, 7, 7, 0), 24 * 3600),  # właśnie minęła — jutro
        (datetime(2026, 10, 7, 22, 15), 8 * 3600 + 45 * 60),  # jutro o 7:00
    ],
)
def test_seconds_until_next_run(now: datetime, expected: float) -> None:
    assert seconds_until(now, time(7, 0)) == expected


async def test_loop_sleeps_until_run_time_and_survives_job_errors() -> None:
    waits: list[float] = []
    calls = 0

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    async def job() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("awaria jednego przebiegu")

    with pytest.raises(asyncio.CancelledError):
        await at_time_loop(time(7, 0), job, now=lambda: datetime(2026, 10, 7, 6, 0), sleep=sleep)
    assert waits == [3600, 3600, 3600] and calls == 2


class FakeStore:
    def list(self) -> list[Account]:
        return [Account("osoba-1", "Osoba 1", refresh_token="r"), Account("osoba-2", "Osoba 2")]


class FakeSync:
    def __init__(self, log: list[str], imported: int = 0) -> None:
        self.log, self.imported = log, imported

    async def run_daily(self, slugs: list[str]) -> None:
        self.log.append(f"paragony {slugs}")

    async def run_hourly(self, slugs: list[str]) -> int:
        self.log.append(f"godzinny {slugs}")
        return self.imported


class FakeRunner:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def run_all(self, accounts: list[tuple[str, str]], *, dry_run: bool) -> dict[str, AccountReport]:
        self.log.append(f"kupony {accounts} próbnie={dry_run}")
        active = [ActiveCoupon("Produkt A", "-30%", "2026-10-10", 5, False)]
        return {
            "Osoba 1": AccountReport([Activation("Produkt A", "-30%", "2026-10-10", "would", True)], active)
        }


class FakeRewards:
    def __init__(self, log: list[str], expires: datetime | None = None) -> None:
        self.log, self.expires = log, expires

    async def run_all(self, accounts: list[tuple[str, str]]) -> dict[str, Rewards]:
        self.log.append(f"nagrody {accounts}")
        cards = (ScratchCard("Scratch", datetime(2026, 10, 5, 19, 0), self.expires),) if self.expires else ()
        return {"Osoba 1": Rewards(cards, None)}


class FakePromotions:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def refresh(self) -> None:
        self.log.append("promocje")

    def active(self, today: date) -> list[Promotion]:
        return [Promotion("0000111", "Produkt B", "-40%", today, today + timedelta(days=2))]


class FakeHistory:
    """Obserwowane (E15): kody, kupony z bazy i klucze już wysłanych powiadomień."""

    def __init__(self, watched: set[str] | None = None, coupons: list[WatchedCoupon] | None = None) -> None:
        self.watched, self.coupons, self.sent = watched or set(), coupons or [], set[str]()
        self.events: list[tuple[str, str, str, dict[str, Any]]] = []

    def warm(self) -> None:
        self.warmed = getattr(self, "warmed", 0) + 1

    def log_event(self, area: str, level: str, summary: str, detail: Any = None, **_: Any) -> None:
        self.events.append((area, level, summary, detail or {}))

    def prune_events(self, before: datetime) -> None:
        pass

    def watched_codes(self) -> set[str]:
        return self.watched

    def watched_coupons(self, today: date) -> list[WatchedCoupon]:
        return self.coupons

    def watched_sent_keys(self) -> set[str]:
        return set(self.sent)

    def mark_watched_sent(self, keys: list[str], sent_at: str) -> None:
        self.sent.update(keys)

    def stores_without_geo(self) -> set[str]:
        return set()  # współrzędne komplet → bez zapytania do Lidla


def _job(
    log: list[str],
    expires: datetime | None = None,
    history: FakeHistory | None = None,
    *,
    dry_run: bool = True,
) -> DailyJob:
    return DailyJob(
        FakeStore(),  # type: ignore[arg-type]
        FakeSync(log),  # type: ignore[arg-type]
        FakeRunner(log),  # type: ignore[arg-type]
        FakeRewards(log, expires),  # type: ignore[arg-type]
        FakePromotions(log),  # type: ignore[arg-type]
        history or FakeHistory(),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        dry_run=dry_run,
    )


async def test_daily_job_runs_receipts_then_coupons_for_connected_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []

    async def send(session: Any, message: tuple[str, str]) -> None:
        log.append(f"powiadomienie {message[0]}")
        log.append(message[1].splitlines()[-1])

    monkeypatch.setattr(notify, "send", send)
    await _job(log)()
    assert log == [
        "paragony ['osoba-1']",
        "promocje",
        "kupony [('osoba-1', 'Osoba 1')] próbnie=True",
        "nagrody [('osoba-1', 'Osoba 1')]",
        "powiadomienie Lidl (tryb próbny): dziś karta Osoba 1 (1 kupon na Wasze produkty)",
        "Nowe promocje: Produkt B −40% (do "
        + fmt_until(date.today() + timedelta(days=2), date.today())
        + ")",
    ]


async def test_morning_reports_each_promotion_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Promocja trwa kilka dni — w porannym tylko raz (klucz `m:` w `watched_sent`), poza trybem próbnym."""
    bodies: list[str] = []

    async def send(session: Any, message: tuple[str, str], *, tag: str = notify.TAG) -> bool:
        bodies.append(message[1])
        return True

    monkeypatch.setattr(notify, "send", send)
    history = FakeHistory()
    job = _job([], history=history, dry_run=False)
    await job()
    await job()  # następny dzień albo „Sprawdź teraz”: kupony zostają, promocji już nie ma
    assert ["Nowe promocje" in b for b in bodies] == [True, False]
    assert history.sent == {f"m:0000111:{date.today().isoformat()}"}


def _watched_history() -> FakeHistory:
    end = date.today() + timedelta(days=3)
    return FakeHistory(
        {"0000111", "222"},
        [
            WatchedCoupon("osoba-1", "p1", "Kawa X | 500 g", "-30%", end),
            WatchedCoupon("osoba-2", "p1", "Kawa X | 500 g", "-30%", end),  # konto niepołączone
        ],
    )


@pytest.mark.parametrize(("ok", "dry_run", "pushes"), [(True, False, 1), (True, True, 2), (False, False, 2)])
async def test_watched_products_get_a_separate_push_once(
    monkeypatch: pytest.MonkeyPatch, ok: bool, dry_run: bool, pushes: int
) -> None:
    log: list[str] = []
    sent: list[tuple[str, str, str]] = []

    async def send(session: Any, message: tuple[str, str], *, tag: str = notify.TAG) -> bool:
        if tag == notify.TAG_WATCHED:
            sent.append((message[0], message[1], tag))
        return ok

    monkeypatch.setattr(notify, "send", send)
    job = _job(log, history=_watched_history(), dry_run=dry_run)
    await job()
    await job()  # drugi przebieg tego dnia („Sprawdź teraz”) nie powtarza, chyba że próbny albo nieudany
    assert len(sent) == pushes
    title, body, _ = sent[0]
    assert title == "Lidl: 2 obserwowane produkty z rabatem"
    end = fmt_until(date.today() + timedelta(days=3), date.today())
    assert body.splitlines() == [
        f"Kawa X −30% (do {end}) · kupon Osoba 1",
        f"Produkt B −40% (do {fmt_until(date.today() + timedelta(days=2), date.today())}) · promocja od dziś",
    ]


async def test_nothing_watched_sends_no_extra_push(monkeypatch: pytest.MonkeyPatch) -> None:
    tags: list[str] = []

    async def send(session: Any, message: tuple[str, str], *, tag: str = notify.TAG) -> bool:
        tags.append(tag)
        return True

    monkeypatch.setattr(notify, "send", send)
    await _job([], dry_run=False)()
    assert tags == [notify.TAG]


@pytest.mark.parametrize(("days", "sent"), [(0, True), (1, False)])
async def test_evening_reminds_only_about_cards_expiring_today(
    monkeypatch: pytest.MonkeyPatch, days: int, sent: bool
) -> None:
    log: list[str] = []

    async def send(session: Any, message: tuple[str, str], *, tag: str) -> None:
        log.append(f"powiadomienie {message[0]} [{tag}]")

    monkeypatch.setattr(notify, "send", send)
    expires = datetime.combine(date.today() + timedelta(days=days), time(23, 59, 59))
    await _job(log, expires).evening()
    reminder = "powiadomienie Lidl: zdrapka wygasa dziś o 23:59 [lidl-zdrapki]"
    assert log == ["nagrody [('osoba-1', 'Osoba 1')]"] + ([reminder] if sent else [])


def _month_history(tmp_path: Path) -> History:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "osoba-1",
        [
            {"id": "a", "date": "2026-08-10T10:00:00+00:00", "totalAmount": 40.0},
            {"id": "s", "date": "2026-09-10T10:00:00+00:00", "totalAmount": 50.0},
        ],
    )
    h.save_detail("s", "Sklep X", ParsedReceipt(items=[ReceiptItem("1", "Produkt A", 2, 25.0, 50.0, -5.0)]))
    return h


async def test_monthly_summary_on_the_first_once_and_not_for_empty_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str, str]] = []

    async def send(session: Any, message: tuple[str, str], *, tag: str) -> bool:
        sent.append((*message, tag))
        return True

    monkeypatch.setattr(notify, "send", send)
    job = _job([], history=_month_history(tmp_path))  # type: ignore[arg-type]
    await job.monthly(date(2026, 10, 2))  # nie 1. dnia
    assert sent == []
    await job.monthly(date(2026, 10, 1))
    await job.monthly(date(2026, 10, 1))  # restart tego samego dnia: bez powtórki
    assert [(title, tag) for title, _, tag in sent] == [("Lidl: podsumowanie miesiąca", "lidl-podsumowanie")]
    assert sent[0][1].splitlines()[:2] == [
        "We wrześniu wydaliśmy 50,00 zł w 1 wizycie (+25,0% niż w sierpniu)",
        "Najwięcej na: Produkt A (45,00 zł)",
    ]
    await job.monthly(date(2026, 8, 1))  # lipiec bez zakupów
    assert len(sent) == 1


async def test_morning_run_lands_in_event_log(monkeypatch: pytest.MonkeyPatch) -> None:
    async def send(session: Any, message: tuple[str, str], *, tag: str = notify.TAG) -> bool:
        return True

    monkeypatch.setattr(notify, "send", send)
    history = FakeHistory()
    await _job([], history=history)()
    (event,) = [e for e in history.events if e[0] == "daily"]
    assert event[1] == "ok"
    assert event[3] == {
        "run": "morning", "accounts": 1, "promotions": 1, "coupons": {"would": 1}, "rewards": 1,
        "notified": True,
    }  # fmt: skip


async def test_failed_morning_step_is_logged_as_error_and_reraised() -> None:
    history = FakeHistory()
    job = _job([], history=history)

    async def boom() -> None:
        raise RuntimeError("lidl.pl leży")

    job._promotions.refresh = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await job()
    ((area, level, summary, detail),) = history.events
    assert (area, level, detail["step"]) == ("daily", "error", "promocje")
    assert "lidl.pl leży" in summary


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 14, 6, 59, 59), False),  # przed sklepami
        (datetime(2026, 10, 14, 7, 0), False),  # godzina porannego przebiegu (run_time 7:00)
        (datetime(2026, 10, 14, 8, 0), True),
        (datetime(2026, 10, 14, 23, 0), True),  # ostatni sync dnia
        (datetime(2026, 10, 15, 0, 0), False),
        (datetime(2026, 10, 17, 12, 0), True),  # sobota
        (datetime(2026, 10, 18, 12, 0), False),  # zwykła niedziela
        (datetime(2026, 12, 13, 12, 0), True),  # niedziela handlowa
    ],
)
def test_sync_due(now: datetime, expected: bool) -> None:
    assert sync_due(now, time(7, 0)) is expected


def test_sync_due_skips_whole_hour_of_a_later_morning_run() -> None:
    assert not sync_due(datetime(2026, 10, 14, 7, 0), time(7, 30))  # poranny import o 7:30 pokrywa tę godzinę
    assert sync_due(datetime(2026, 10, 14, 8, 0), time(7, 30))


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 14, 9, 30), datetime(2026, 10, 14, 10, 0)),
        (datetime(2026, 10, 14, 9, 0), datetime(2026, 10, 14, 10, 0)),  # pełna godzina → następna
        (datetime(2026, 10, 14, 23, 59, 30), datetime(2026, 10, 15, 0, 0)),
    ],
)
def test_next_hour(now: datetime, expected: datetime) -> None:
    assert next_hour(now) == expected


async def test_hourly_loop_runs_on_full_hours_and_survives_errors() -> None:
    waits: list[float] = []
    calls = 0

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    async def job() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("awaria jednego przebiegu")

    with pytest.raises(asyncio.CancelledError):
        await hourly_loop(job, time(7, 0), now=lambda: datetime(2026, 10, 14, 9, 30), sleep=sleep)
    assert waits == [1800, 5400, 9000] and calls == 2  # kolejne pełne godziny: 10:00, 11:00, 12:00


async def test_hourly_loop_skips_closed_days() -> None:
    waits: list[float] = []
    calls = 0

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 2:
            raise asyncio.CancelledError

    async def job() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(asyncio.CancelledError):
        await hourly_loop(
            job, time(7, 0), now=lambda: datetime(2026, 10, 18, 9, 30), sleep=sleep
        )  # niedziela
    assert calls == 0


async def test_hourly_job_syncs_only_connected_accounts_and_warms_cache_on_news() -> None:
    log: list[str] = []
    history = FakeHistory()
    job = _job(log, history=history)
    job._sync.imported = 2  # type: ignore[attr-defined]
    await job.hourly()
    assert log == ["godzinny ['osoba-1']"]
    assert getattr(history, "warmed", 0) == 1
    log.clear()
    job._sync.imported = 0  # type: ignore[attr-defined]
    await job.hourly()
    assert getattr(history, "warmed", 0) == 1  # bez nowych paragonów cache zostaje


async def test_hourly_job_does_nothing_during_morning_run() -> None:
    log: list[str] = []
    job = _job(log)
    job.in_progress = True
    await job.hourly()
    assert log == []


async def test_hourly_loop_does_not_repeat_an_hour_when_woken_early() -> None:
    clock = [datetime(2026, 10, 14, 8, 30)]
    waits: list[float] = []
    calls = 0

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError
        clock[0] += timedelta(seconds=seconds - 0.1)  # budzik 100 ms przed pełną godziną

    async def job() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(asyncio.CancelledError):
        await hourly_loop(job, time(7, 0), now=lambda: clock[0], sleep=sleep)
    assert calls == 2 and waits[1] > 3500  # po 9:00 czekamy do 10:00, nie 0,1 s do „tej samej” 9:00
