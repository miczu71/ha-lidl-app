"""Dzienny przebieg o stałej godzinie (opcja `run_time`, czas lokalny): paragony, promocje, kupony, nagrody,
powiadomienie; wieczorem (18:00) przypomnienie o zdrapkach wygasających dziś; 1. dnia miesiąca o 10:00
podsumowanie poprzedniego miesiąca (E19); co godzinę w godzinach sklepów sam import paragonów (E24)."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any

import aiohttp

from . import notify
from .accounts import AccountStore
from .coupons import CouponRunner
from .geo import refresh_store_geo
from .history import History, elapsed_ms
from .promotions import Promotion, PromotionRunner
from .rewards import Rewards, RewardsRunner
from .shopdays import is_shopping_day
from .sync import HistorySync

log = logging.getLogger(__name__)

EVENING = time(18, 0)
MONTHLY = time(10, 0)  # po porannym imporcie paragonów (`run_time`)
EVENTS_KEEP = timedelta(days=30)  # dziennik zakładki Status (E23)
SYNC_HOURS = range(7, 24)  # pełne godziny godzinnego importu paragonów (E24): 7:00 … 23:00
STATUS_LABELS = {"activated": "aktywowane", "would": "aktywowałbym", "failed": "nieudane"}


def fmt_decisions(statuses: dict[str, int]) -> str:
    """„aktywowane 5, nieudane 1” — nowe decyzje przebiegu; „bez zmian”, gdy żadnej."""
    return ", ".join(f"{STATUS_LABELS.get(k, k)} {n}" for k, n in statuses.items()) or "bez zmian"


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


def seconds_until_next_hour(now: datetime) -> float:
    """Sekundy do najbliższej pełnej godziny po `now`."""
    return (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1) - now).total_seconds()


def sync_due(at: datetime, run_time: time) -> bool:
    """Czy o pełnej godzinie `at` startuje godzinny import: godziny sklepów, dzień handlowy, a godzinę
    porannego przebiegu (`run_time`) zajmuje poranny import."""
    return at.hour in SYNC_HOURS and at.hour != run_time.hour and is_shopping_day(at.date())


async def hourly_loop(
    job: Callable[[], Awaitable[None]],
    run_time: time,
    *,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """O każdej pełnej godzinie sklepów uruchamia `job`; błąd jednego przebiegu nie zatrzymuje kolejnych."""
    while True:
        started = now()
        target = started.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        await sleep(seconds_until_next_hour(started))
        if not sync_due(target, run_time):  # docelowa godzina: budzik bywa o ułamek sekundy za wcześnie
            continue
        try:
            await job()
        except Exception:
            log.exception("Godzinny import nieudany")


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
        self.running = False  # kupony w toku (rano); panel odświeża się wtedy sam
        self.in_progress = False  # cały poranny przebieg w toku (zakładka Status)

    def _accounts(self) -> list[tuple[str, str]]:
        return [(a.slug, a.label) for a in self._store.list() if a.connected]

    async def __call__(self) -> None:
        """Przebieg z wpisem w dzienniku (E23): wynik kroków albo krok, na którym przerwał."""
        began = monotonic()
        self._history.prune_events(datetime.now() - EVENTS_KEEP)
        accounts = self._accounts()
        report: dict[str, Any] = {"run": "morning", "accounts": len(accounts)}
        step = "paragony"
        self.in_progress = True
        try:
            await self._sync.run_daily([slug for slug, _ in accounts])
            self._history.warm()  # nowe paragony unieważniły wyniki zakładek
            step = "promocje"
            await self._promotions.refresh()
            step = "kupony"  # z nagrodami i powiadomieniem
            report.update(await self._coupons(accounts))
            step = "sklepy"  # nowy sklep z dzisiejszych paragonów, na końcu
            await refresh_store_geo(self._session, self._history)
        except Exception as err:
            self._history.log_event(
                "daily", "error", f"Poranny przebieg przerwany ({step}): {type(err).__name__}: {err}",
                {**report, "step": step}, duration_ms=elapsed_ms(began),
            )  # fmt: skip
            raise
        finally:
            self.in_progress = False
        self._history.log_event(
            "daily", "ok",
            f"Poranny przebieg: kupony {fmt_decisions(report['coupons'])}, promocje {report['promotions']}, "
            + ("powiadomienie wysłane" if report["notified"] else "bez powiadomienia"),
            report, duration_ms=elapsed_ms(began),
        )  # fmt: skip

    async def hourly(self) -> None:
        """Godzinny import paragonów (E24): bez kuponów i powiadomień; pomija, gdy trwa poranny przebieg.
        Nowe paragony unieważniają wyniki zakładek (jak po porannym imporcie)."""
        if self.in_progress:
            return
        if await self._sync.run_hourly([slug for slug, _ in self._accounts()]):
            self._history.warm()

    async def refresh_rewards(self) -> dict[str, Rewards]:
        """Nagrody połączonych kont (też przy starcie add-onu, żeby panel nie czekał do rana)."""
        return await self._rewards.run_all(self._accounts())

    async def evening(self) -> None:
        """Zdrapki wygasające dziś — osobne powiadomienie (nie zastępuje porannego)."""
        message = notify.compose_expiring(await self.refresh_rewards(), date.today())
        sent = await notify.send(self._session, message, tag=notify.TAG_SCRATCH) if message else False
        summary = (
            "przypomnienie wysłane" if sent else "nieudane" if message else "brak zdrapek wygasających dziś"
        )
        level = "warn" if message and not sent else "ok"
        self._history.log_event("daily", level, f"Zdrapki 18:00: {summary}", {"run": "evening"})

    async def monthly(self, today: date | None = None) -> None:
        """1. dnia miesiąca podsumowanie poprzedniego; raz (klucz `s:<RRRR-MM>` w `watched_sent`), bez
        powiadomienia, gdy w miesiącu nie było zakupów."""
        today = today or date.today()
        if today.day != 1:
            return
        month = (today - timedelta(days=1)).strftime("%Y-%m")
        key = f"s:{month}"
        if key in self._history.watched_sent_keys():
            return
        summary = self._history.month_summary(month)
        if summary and await notify.send(self._session, notify.compose_month(summary), tag=notify.TAG_MONTH):
            self._history.mark_watched_sent([key], datetime.now().isoformat())
            self._history.log_event("daily", "ok", f"Podsumowanie {month}: wysłane", {"run": "month"})

    async def _coupons(self, accounts: list[tuple[str, str]]) -> dict[str, Any]:
        """Kupony, nagrody i poranne powiadomienie; zwraca wyniki do wpisu w dzienniku."""
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
        notified = await notify.send(self._session, message) if message else False
        if notified and not self.dry_run:
            self._history.mark_watched_sent(fresh, datetime.now().isoformat())
        await self._watched(dict(accounts), promos, sent)
        statuses = Counter(a.status for r in results.values() for a in r.activations if a.new)
        return {
            "promotions": len(promos),
            "coupons": dict(statuses),
            "rewards": len(rewards),
            "notified": notified,
        }

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
