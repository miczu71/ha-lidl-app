"""Dzienny przebieg o stałej godzinie (opcja `run_time`, czas lokalny): paragony, kupony, powiadomienie."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta

import aiohttp

from . import notify
from .accounts import AccountStore
from .coupons import CouponRunner
from .sync import HistorySync

log = logging.getLogger(__name__)


def seconds_until(now: datetime, at: time) -> float:
    """Sekundy do najbliższego `at` po `now` (gdy dziś już minęło albo trwa — jutro)."""
    target = datetime.combine(now.date(), at)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def at_time_loop(
    at: time,
    job: Callable[[], Awaitable[None]],
    *,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Codziennie o `at` uruchamia `job`; błąd jednego przebiegu nie zatrzymuje kolejnych."""
    while True:
        await sleep(seconds_until(now(), at))
        try:
            await job()
        except Exception:
            log.exception("Dzienny przebieg nieudany")


class DailyJob:
    """Nowe paragony, potem kupony wszystkich połączonych kont i jedno powiadomienie o nowych decyzjach."""

    def __init__(
        self,
        store: AccountStore,
        sync: HistorySync,
        runner: CouponRunner,
        session: aiohttp.ClientSession,
        *,
        dry_run: bool,
    ) -> None:
        self._store, self._sync, self._runner, self._session = store, sync, runner, session
        self._dry_run = dry_run

    async def __call__(self) -> None:
        accounts = [a for a in self._store.list() if a.connected]
        await self._sync.run_daily([a.slug for a in accounts])
        await self._coupons([(a.slug, a.label) for a in accounts])

    async def coupons(self) -> None:
        await self._coupons([(a.slug, a.label) for a in self._store.list() if a.connected])

    async def _coupons(self, accounts: list[tuple[str, str]]) -> None:
        results = await self._runner.run_all(accounts, dry_run=self._dry_run)
        message = notify.compose(results, dry_run=self._dry_run)
        if message:
            await notify.send(self._session, message)
