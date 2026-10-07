"""Powiadomienie o kuponach na `notify.family` (API Core przez Supervisora, `homeassistant_api`)."""

from __future__ import annotations

import logging
import os
from datetime import date

import aiohttp

from .coupons import Activation
from .text import count_text, fmt_day_month

log = logging.getLogger(__name__)

NOTIFY_URL = "http://supervisor/core/api/services/notify/family"


def compose(results: dict[str, list[Activation]], *, dry_run: bool) -> tuple[str, str] | None:
    """Tytuł i treść o nowych decyzjach; None, gdy nie ma nic nowego."""
    done = "would" if dry_run else "activated"
    lines, failed, count = [], [], 0
    for label, items in results.items():
        fresh = [a for a in items if a.new and a.status == done]
        failed += [f"{a.title} ({label})" for a in items if a.new and a.status == "failed"]
        if fresh:
            count += len(fresh)
            lines.append(
                f"{label}: "
                + "; ".join(
                    f"{a.title}, {a.discount} (do {fmt_day_month(date.fromisoformat(a.valid_to))})"
                    for a in fresh
                )
            )
    if failed:
        lines.append("Nie udało się: " + ", ".join(failed))
    if not lines:
        return None
    word = count_text(count, "kupon", "kupony", "kuponów")
    title = f"Lidl (tryb próbny): aktywowałbym {word}" if dry_run else f"Lidl: aktywowano {word}"
    return title, "\n".join(lines)


async def send(session: aiohttp.ClientSession, message: tuple[str, str]) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Brak SUPERVISOR_TOKEN (tryb dev) — powiadomienie tylko w logu: %s", message[0])
        return
    title, body = message
    try:
        async with session.post(
            NOTIFY_URL, json={"title": title, "message": body}, headers={"Authorization": f"Bearer {token}"}
        ) as response:
            if response.status >= 400:
                log.warning("Powiadomienie nieudane: HTTP %s", response.status)
    except aiohttp.ClientError as err:
        log.warning("Powiadomienie nieudane: %s", err)
