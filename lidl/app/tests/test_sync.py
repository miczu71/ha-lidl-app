from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from lidl.history import History
from lidl.sync import HistorySync


def _html(art_id: str, name: str) -> str:
    attrs = f'class="article" data-art-id="{art_id}" data-unit-price="2,00" data-art-description="{name}"'
    return (
        f"<span {attrs}>{name}</span><span {attrs}>1 * 2.00 2.00 C</span>"
        '<span id="purchase_summary_5">Opakowania zwrotne suma           0,00</span>'
    )


class FakeSource:
    """Lata: offset -> paragony; offset spoza słownika kończy historię (HTTP 400)."""

    def __init__(self, years: dict[int, list[str]]) -> None:
        self.years = years
        self.list_calls: list[int] = []
        self.detail_calls: list[str] = []
        self.fail_detail: dict[str, Exception] = {}
        self.fail_list: Exception | None = None

    async def tickets(self, slug: str, year_offset: int) -> list[dict[str, Any]]:
        self.list_calls.append(year_offset)
        if self.fail_list:
            raise self.fail_list
        if year_offset not in self.years:
            raise LidlPlusError("http_400", status=400)
        return [
            {"id": t, "date": f"{2026 - year_offset}-05-0{n + 1}T10:00:00+00:00", "totalAmount": 2.0}
            for n, t in enumerate(self.years[year_offset])
        ]

    async def ticket(self, slug: str, ticket_id: str) -> dict[str, Any]:
        self.detail_calls.append(ticket_id)
        if ticket_id in self.fail_detail:
            raise self.fail_detail[ticket_id]
        return {"store": {"name": "Sklep X"}, "htmlPrintedReceipt": _html("1", f"Produkt {ticket_id}")}


@pytest.fixture
def history(tmp_path: Path) -> History:
    return History(tmp_path / "h.db")


def _sync(source: FakeSource, history: History) -> tuple[HistorySync, list[float]]:
    pauses: list[float] = []

    async def sleep(seconds: float) -> None:
        pauses.append(seconds)

    return HistorySync(source, history, pause=2.5, sleep=sleep), pauses


async def test_full_import_walks_years_until_http_400(history: History) -> None:
    src = FakeSource({0: ["a", "b"], 1: ["c"]})
    sync, pauses = _sync(src, history)
    result = await sync.import_account("osoba-1", full=True)
    assert src.list_calls == [0, 1, 2]
    assert (result.new_tickets, result.details, result.stopped) == (3, 3, None)
    assert history.pending_details("osoba-1") == []
    assert len(pauses) == 3
    assert [p.purchases for p in history.ranking()] == [3]


async def test_second_run_adds_nothing_and_fetches_no_details(history: History) -> None:
    src = FakeSource({0: ["a", "b"]})
    sync, _ = _sync(src, history)
    await sync.import_account("osoba-1", full=True)
    src.detail_calls.clear()
    result = await sync.import_account("osoba-1", full=True)
    assert (result.new_tickets, result.details) == (0, 0)
    assert src.detail_calls == []
    assert history.ticket_count() == 2


async def test_daily_mode_asks_only_for_current_year(history: History) -> None:
    src = FakeSource({0: ["a"], 1: ["b"]})
    sync, _ = _sync(src, history)
    await sync.import_account("osoba-1", full=False)
    assert src.list_calls == [0]


async def test_rate_limit_stops_import_and_resume_fetches_only_pending(history: History) -> None:
    src = FakeSource({0: ["a", "b", "c"]})
    src.fail_detail["b"] = LidlPlusError("http_429", status=429)
    sync, _ = _sync(src, history)
    first = await sync.import_account("osoba-1", full=True)
    assert first.stopped == "http_429" and first.details == 1
    assert len(history.pending_details("osoba-1")) == 2
    del src.fail_detail["b"]
    src.detail_calls.clear()
    second = await sync.import_account("osoba-1", full=True)
    assert second.stopped is None and second.details == 2
    assert src.detail_calls == ["b", "a"]  # kolejka od najnowszych


async def test_other_client_error_on_one_ticket_is_skipped_not_retried(history: History) -> None:
    src = FakeSource({0: ["a", "b"]})
    src.fail_detail["a"] = LidlPlusError("http_404", status=404)
    sync, _ = _sync(src, history)
    result = await sync.import_account("osoba-1", full=True)
    assert (result.details, result.skipped, result.stopped) == (1, 1, None)
    assert history.pending_details("osoba-1") == []


@pytest.mark.parametrize("error", [LidlPlusAuthError("unauthorized"), LidlPlusCannotConnect("timeout")])
async def test_auth_or_network_error_on_list_stops_cleanly(history: History, error: Exception) -> None:
    src = FakeSource({0: ["a"]})
    src.fail_list = error
    sync, _ = _sync(src, history)
    result = await sync.import_account("osoba-1", full=True)
    assert result.stopped == str(error) and result.new_tickets == 0


async def test_start_refuses_second_run_and_reports_progress(history: History) -> None:
    gate = asyncio.Event()
    src = FakeSource({0: ["a"]})
    original = src.tickets

    async def slow(slug: str, year_offset: int) -> list[dict[str, Any]]:
        await gate.wait()
        return await original(slug, year_offset)

    src.tickets = slow  # type: ignore[method-assign]
    sync, _ = _sync(src, history)
    assert sync.start("osoba-1", full=True) is True
    assert sync.start("osoba-1", full=True) is False
    assert sync.progress("osoba-1").running is True
    gate.set()
    await sync.wait("osoba-1")
    progress = sync.progress("osoba-1")
    assert (progress.running, progress.done, progress.error) == (False, 1, None)


async def test_daily_run_skips_accounts_never_imported(history: History) -> None:
    src = FakeSource({0: ["a"]})
    sync, _ = _sync(src, history)
    await sync.import_account("osoba-1", full=True)
    src.list_calls.clear()
    await sync.run_daily(["osoba-1", "osoba-2"])
    assert src.list_calls == [0]


async def test_daily_loop_waits_then_runs_every_interval(history: History) -> None:
    src = FakeSource({0: ["a"]})
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    sync = HistorySync(src, history, pause=0, sleep=sleep)
    await sync.import_account("osoba-1", full=True)
    src.list_calls.clear()
    waits.clear()
    with pytest.raises(asyncio.CancelledError):
        await sync.daily_loop(lambda: ["osoba-1"], first_delay=300, interval=86400)
    assert waits[0] == 300
    assert 86400 in waits
    assert src.list_calls == [0, 0]
