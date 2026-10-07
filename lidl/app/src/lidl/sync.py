"""Import historii paragonów: ręczny pełny (wszystkie lata) i dzienny (tylko bieżący rok + nowe).

Import jest sekwencyjny i z pauzą między paragonami (nie obciążamy API Lidla). Postęp żyje w bazie
(paragon bez `detail_fetched` czeka w kolejce), więc przerwanie — błąd sieci, limit żądań, restart —
nic nie psuje, a kolejny przebieg bierze tylko to, co zostało.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from .history import History
from .receipt import parse_detail, sanitize_detail
from .receipt_html import ParsedReceipt

log = logging.getLogger(__name__)

MAX_YEAR_OFFSET = 10  # bezpiecznik; zwykle historia kończy się HTTP 400 przy yearOffset=6


class TicketSource(Protocol):
    async def tickets(self, slug: str, year_offset: int) -> list[dict[str, Any]]: ...

    async def ticket(self, slug: str, ticket_id: str) -> dict[str, Any]: ...


@dataclass
class SyncProgress:
    running: bool = False
    done: int = 0
    total: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SyncResult:
    new_tickets: int
    details: int
    skipped: int
    stopped: str | None
    unparsed: int = 0


def _fatal(err: LidlPlusError) -> bool:
    """Błąd, po którym dalsze żądania nie mają sensu (autoryzacja, sieć, limit, awaria serwera)."""
    if isinstance(err, (LidlPlusAuthError, LidlPlusCannotConnect)) or err.status is None:
        return True
    return err.status == 429 or err.status >= 500


class HistorySync:
    def __init__(
        self,
        source: TicketSource,
        history: History,
        *,
        pause: float = 2.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._source = source
        self._history = history
        self._pause = pause
        self._sleep = sleep
        self._progress: dict[str, SyncProgress] = {}
        self._tasks: dict[str, asyncio.Task[SyncResult]] = {}

    @property
    def pause(self) -> float:
        return self._pause

    def progress(self, slug: str) -> SyncProgress:
        return self._progress.setdefault(slug, SyncProgress())

    def start(self, slug: str, *, full: bool) -> bool:
        """Uruchamia import w tle; False, jeśli to konto już się synchronizuje."""
        progress = self.progress(slug)
        if progress.running:
            return False
        progress.running = True
        self._tasks[slug] = asyncio.create_task(self.import_account(slug, full=full))
        return True

    async def close(self) -> None:
        """Przerywa trwające importy (zamykanie add-onu); postęp zostaje w bazie."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def wait(self, slug: str) -> None:
        task = self._tasks.get(slug)
        if task:
            await task

    async def run_daily(self, slugs: list[str]) -> None:
        """Dzienny przebieg; konta, których nikt jeszcze ręcznie nie zaimportował, pomija."""
        for slug in slugs:
            if self._history.ticket_count(slug) > 0 and self.start(slug, full=False):
                await self.wait(slug)

    async def daily_loop(
        self, slugs: Callable[[], list[str]], *, first_delay: float = 300.0, interval: float = 86400.0
    ) -> None:
        """Dzienny przebieg w tle (anulowany przy zamykaniu add-onu)."""
        await self._sleep(first_delay)
        while True:
            await self.run_daily(slugs())
            await self._sleep(interval)

    async def import_account(self, slug: str, *, full: bool) -> SyncResult:
        progress = self.progress(slug)
        progress.running, progress.done, progress.total, progress.error = True, 0, 0, None
        new = details = skipped = unparsed = 0
        stopped: str | None = None
        try:
            try:
                new = await self._import_lists(slug, full)
                pending = self._history.pending_details(slug)
                progress.total = len(pending)
                for ticket_id in pending:
                    await self._sleep(self._pause)
                    try:
                        detail = await self._source.ticket(slug, ticket_id)
                    except LidlPlusError as err:
                        if _fatal(err):
                            raise
                        skipped += 1
                        self._history.save_detail(ticket_id, None, ParsedReceipt())
                        continue
                    parsed = parse_detail(detail)
                    if not self._history.save_detail(
                        ticket_id, _store_name(detail), parsed, raw=sanitize_detail(detail)
                    ):
                        unparsed += 1
                    details += 1
                    progress.done = details
            except LidlPlusError as err:
                stopped = str(err) or type(err).__name__
                progress.error = stopped
                log.warning("Import konta %s przerwany: %s", slug, stopped)
        finally:
            progress.running = False
        log.info(
            "Import konta %s: %d nowych, %d szczegółów, %d pominiętych, %d nierozpoznanych",
            slug, new, details, skipped, unparsed,
        )  # fmt: skip
        return SyncResult(new, details, skipped, stopped, unparsed)

    async def _import_lists(self, slug: str, full: bool) -> int:
        new = 0
        for offset in range(MAX_YEAR_OFFSET if full else 1):
            try:
                batch = await self._source.tickets(slug, offset)
            except LidlPlusError as err:
                if err.status == 400 and offset > 0:
                    break  # koniec historii
                raise
            new += self._history.upsert_tickets(slug, batch)
        return new


def _store_name(detail: dict[str, Any]) -> str | None:
    store = detail.get("store")
    name = store.get("name") if isinstance(store, dict) else None
    return str(name) if name else None
