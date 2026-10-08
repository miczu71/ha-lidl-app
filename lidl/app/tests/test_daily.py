from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest

from lidl import notify
from lidl.accounts import Account
from lidl.coupons import AccountReport, Activation, ActiveCoupon
from lidl.daily import DailyJob, at_time_loop, seconds_until
from lidl.history import WatchedCoupon
from lidl.promotions import Promotion
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
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def run_daily(self, slugs: list[str]) -> None:
        self.log.append(f"paragony {slugs}")


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

    def starting(self, today: date) -> list[Promotion]:
        return [Promotion("0000111", "Produkt B", "-40%", today, today + timedelta(days=2))]


class FakeHistory:
    """Obserwowane (E15): kody, kupony z bazy i klucze już wysłanych powiadomień."""

    def __init__(self, watched: set[str] | None = None, coupons: list[WatchedCoupon] | None = None) -> None:
        self.watched, self.coupons, self.sent = watched or set(), coupons or [], set[str]()

    def watched_codes(self) -> set[str]:
        return self.watched

    def watched_coupons(self, today: date) -> list[WatchedCoupon]:
        return self.coupons

    def watched_sent_keys(self) -> set[str]:
        return set(self.sent)

    def mark_watched_sent(self, keys: list[str], sent_at: str) -> None:
        self.sent.update(keys)


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
        "Promocje od dziś: Produkt B −40% (do "
        + fmt_until(date.today() + timedelta(days=2), date.today())
        + ")",
    ]


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


async def test_start_coupons_reports_running_at_once_and_only_one_run() -> None:
    log: list[str] = []
    job = _job(log)
    assert job.start_coupons() is True and job.running is True
    assert job.start_coupons() is False
    await job.close()


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
