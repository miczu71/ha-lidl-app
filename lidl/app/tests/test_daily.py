from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Any

import pytest

from lidl import notify
from lidl.accounts import Account
from lidl.coupons import AccountReport, Activation
from lidl.daily import DailyJob, at_time_loop, seconds_until


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
        return {"Osoba 1": AccountReport([Activation("Produkt A", "-30%", "2026-10-10", "would", True)], [])}


async def test_daily_job_runs_receipts_then_coupons_for_connected_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []

    async def send(session: Any, message: tuple[str, str]) -> None:
        log.append(f"powiadomienie {message[0]}")

    monkeypatch.setattr(notify, "send", send)
    job = DailyJob(FakeStore(), FakeSync(log), FakeRunner(log), None, dry_run=True)  # type: ignore[arg-type]
    await job()
    assert log == [
        "paragony ['osoba-1']",
        "kupony [('osoba-1', 'Osoba 1')] próbnie=True",
        "powiadomienie Lidl (tryb próbny): aktywowałbym 1 kupon",
    ]


async def test_start_coupons_reports_running_at_once_and_only_one_run() -> None:
    log: list[str] = []
    job = DailyJob(FakeStore(), FakeSync(log), FakeRunner(log), None, dry_run=True)  # type: ignore[arg-type]
    assert job.start_coupons() is True and job.running is True
    assert job.start_coupons() is False
    await job.close()
