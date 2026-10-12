"""Alerty techniczne (E23.3): push do usługi z opcji `alert_notify`, raz na problem.

Problemy liczy `web.status.build()` (te same, co werdykt zakładki Status). Wysłany problem ma klucz
`a:<klucz problemu>` w `watched_sent`; gdy problem zniknie, klucz też znika, więc jego powrót da nowy push.
Pusta opcja = tylko kropka przy zakładce Status, bez pusha.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

import aiohttp

from . import notify
from .history import History
from .web.status import Problem, verdict

log = logging.getLogger(__name__)

PREFIX = "a:"
CHECK_EVERY = 15 * 60  # s; pominięty poranny przebieg wychodzi najpóźniej kwadrans po 2 h tolerancji


async def check(
    session: aiohttp.ClientSession, history: History, problems: list[Problem], service: str
) -> None:
    keys = {PREFIX + p.key: p for p in problems}
    known = {k for k in history.watched_sent_keys() if k.startswith(PREFIX)}
    history.unmark_watched_sent(known - set(keys))  # wróciło do normy
    fresh = [p for k, p in keys.items() if k not in known]
    if not fresh or not service:
        return
    title = f"Lidl: {verdict(len(fresh))}"
    body = "\n".join(p.text + (f". {p.fix_text}" if p.fix_text else "") for p in fresh)
    if await notify.send(session, (title, body), tag=notify.TAG_ALERT, service=service):
        history.mark_watched_sent([PREFIX + p.key for p in fresh], datetime.now().isoformat())


async def loop(
    session: aiohttp.ClientSession, history: History, problems: Callable[[], list[Problem]], service: str
) -> None:
    """Co `CHECK_EVERY`, pierwszy raz od razu po starcie; błąd sprawdzenia nie zatrzymuje kolejnych."""
    while True:
        try:
            await check(session, history, problems(), service)
        except Exception:
            log.exception("Alerty: sprawdzenie nieudane")
        await asyncio.sleep(CHECK_EVERY)
