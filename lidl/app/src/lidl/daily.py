"""Dzienny przebieg o stałej godzinie (opcja `run_time`, czas lokalny): paragony, promocje, kupony, nagrody,
powiadomienie; wieczorem (18:00) przypomnienie o zdrapkach wygasających dziś."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import date, datetime, time, timedelta

import aiohttp

from . import notify
from .accounts import AccountStore
from .coupons import CouponRunner
from .history import History
from .promotions import Promotion, PromotionRunner
from .rewards import Rewards, RewardsRunner
from .sync import HistorySync

log = logging.getLogger(__name__)

EVENING = time(18, 0)


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


def _unsent(prefix: str, promos: list[Promotion], sent: set[str]) -> dict[str, Promotion]:
    """Promocje jeszcze niezgłoszone, po kluczu w `watched_sent` (`<prefix>:<kod>:<start>`)."""
    return {k: p for p in promos if (k := f"{prefix}:{p.art_id}:{p.start.isoformat()}") not in sent}


class DailyJob:
    """Nowe paragony i promocje, potem kupony i nagrody wszystkich połączonych kont i jedno powiadomienie."""

    def __init__(
        self,
        store: AccountStore,
        sync: HistorySync,
        runner: CouponRunner,
        rewards: RewardsRunner,
        promotions: PromotionRunner,
        history: History,
        session: aiohttp.ClientSession,
        *,
        dry_run: bool,
    ) -> None:
        self._store, self._sync, self._runner, self._rewards = store, sync, runner, rewards
        self._promotions, self._history = promotions, history
        self._session = session
        self.dry_run = dry_run
        self.last_check: datetime | None = None
        self.running = False  # kupony w toku (rano albo „Sprawdź teraz”)
        self._task: asyncio.Task[None] | None = None

    def _accounts(self) -> list[tuple[str, str]]:
        return [(a.slug, a.label) for a in self._store.list() if a.connected]

    async def __call__(self) -> None:
        accounts = self._accounts()
        await self._sync.run_daily([slug for slug, _ in accounts])
        await self._promotions.refresh()
        await self._coupons(accounts)

    async def refresh_rewards(self) -> dict[str, Rewards]:
        """Nagrody połączonych kont (też przy starcie add-onu, żeby panel nie czekał do rana)."""
        return await self._rewards.run_all(self._accounts())

    async def evening(self) -> None:
        """Zdrapki wygasające dziś — osobne powiadomienie (nie zastępuje porannego)."""
        message = notify.compose_expiring(await self.refresh_rewards(), date.today())
        if message:
            await notify.send(self._session, message, tag=notify.TAG_SCRATCH)

    def start_coupons(self) -> bool:
        """„Sprawdź teraz” w panelu: kupony w tle; False, gdy przebieg już trwa."""
        if self.running:
            return False
        self.running = True  # panel od razu pokazuje „sprawdzam”, zanim zadanie ruszy
        self._task = asyncio.create_task(self._coupons(self._accounts()))
        return True

    async def close(self) -> None:
        """Przerywa kupony uruchomione z panelu (zamykanie add-onu)."""
        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _coupons(self, accounts: list[tuple[str, str]]) -> None:
        self.running = True
        try:
            results = await self._runner.run_all(accounts, dry_run=self.dry_run)
            rewards = await self._rewards.run_all(accounts)
        finally:
            self.running = False
        self.last_check = datetime.now()
        promos = self._promotions.active(date.today())
        sent = self._history.watched_sent_keys()
        fresh = _unsent("m", promos, sent)  # poranne: każda promocja raz, choć trwa kilka dni
        message = notify.compose(results, rewards, dry_run=self.dry_run, promos=list(fresh.values()))
        if message and await notify.send(self._session, message) and not self.dry_run:
            self._history.mark_watched_sent(fresh, datetime.now().isoformat())
        await self._watched(dict(accounts), promos, sent)

    async def _watched(self, labels: dict[str, str], promos: list[Promotion], sent: set[str]) -> None:
        """Osobne powiadomienie o kuponach i promocjach na obserwowane produkty (E15); każdy kupon konta
        i każda promocja tylko raz (`watched_sent`; w trybie próbnym bez zapisu)."""
        watched = self._history.watched_codes()
        if not watched:
            return
        today = date.today()
        coupons = {
            key: (labels[c.account], c)
            for c in self._history.watched_coupons(today)
            if c.account in labels and (key := f"c:{c.account}:{c.promotion_id}") not in sent
        }
        found = _unsent("p", [p for p in promos if p.art_id in watched], sent)
        message = notify.compose_watched(list(coupons.values()), list(found.values()), today)
        if not message:
            return
        if await notify.send(self._session, message, tag=notify.TAG_WATCHED) and not self.dry_run:
            self._history.mark_watched_sent([*coupons, *found], datetime.now().isoformat())
