"""Poranne powiadomienie na `notify.family` (API Core przez Supervisora, `homeassistant_api`): którą kartę
wziąć na zakupy i jakie kupony są na niej aktywne."""

from __future__ import annotations

import logging
import os
import re
from datetime import date

import aiohttp

from .coupons import AccountReport, ActiveCoupon
from .text import count_text

log = logging.getLogger(__name__)

NOTIFY_URL = "http://supervisor/core/api/services/notify/family"
# panel add-onu w HA: Supervisor nadaje kontenerowi HOSTNAME = slug z „-” zamiast „_” (np. f0987e0f-lidl)
PANEL = "/app/" + os.environ.get("HOSTNAME", "f0987e0f-lidl").replace("-", "_")
TAG = "lidl-kupony"  # nowe powiadomienie zastępuje poprzednie


def _name(c: ActiveCoupon) -> str:
    return c.title.split("|")[0].strip(" *")


def _discount(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("*", "").replace("‎", "")).strip()
    text = re.sub(r"\s*/\s*1\s*", "/", text)
    text = re.sub(r"(\d+)\s*\+\s*(\d+)\s*gratis", r"\1+\2", text)
    text = text.replace(" przy zakupie ", " przy ").replace(" rabatu", "")
    return text.replace("-", "−", 1) if text.startswith("-") else text


def _label(c: ActiveCoupon) -> str:
    threshold = re.search(r"min\.\s*([\d\s,]+zł)", c.title)
    if c.general and threshold:
        return f"{_discount(c.discount)} na zakupy od {threshold.group(1).strip()}"
    return f"{_name(c)} {_discount(c.discount)}"


def compose(
    results: dict[str, AccountReport], *, dry_run: bool, today: date | None = None
) -> tuple[str, str] | None:
    """Tytuł z rekomendacją karty i treść z kuponami per karta; None, gdy żadna karta nie ma aktywnych kuponów
    na nasze produkty."""
    day = (today or date.today()).isoformat()
    shown = {
        label: sorted((c for c in r.active if c.weight or c.general), key=lambda c: (-c.weight, _name(c)))
        for label, r in results.items()
        if r.weighted_count
    }
    if not shown:
        return None
    labels = {label: [_label(c) for c in cs] for label, cs in shown.items()}
    common = set.intersection(*map(set, labels.values())) if len(labels) > 1 else set()
    lines = [f"{label}: " + " · ".join(x for x in ls if x not in common) for label, ls in labels.items()]
    lines = [line for line in lines if not line.endswith(": ")]
    if common:
        lines.append("Obie: " + " · ".join(x for x in next(iter(labels.values())) if x in common))
    ending = dict.fromkeys(_name(c) for cs in shown.values() for c in cs if c.valid_to == day)
    if ending:
        lines.append("Koniec dziś: " + ", ".join(ending))
    failed = [
        f"{a.title} ({label})"
        for label, r in results.items()
        for a in r.activations
        if a.new and a.status == "failed"
    ]
    if failed:
        lines.append("Nie udało się: " + ", ".join(failed))
    best = max(results, key=lambda label: results[label].score)
    count = count_text(results[best].weighted_count, "kupon", "kupony", "kuponów") + " na Wasze produkty"
    tie = sum(r.score == results[best].score for r in results.values()) > 1
    title = f"obie karty podobnie ({count})" if tie else f"dziś karta {best} ({count})"
    return ("Lidl (tryb próbny): " if dry_run else "Lidl: ") + title, "\n".join(lines)


async def send(session: aiohttp.ClientSession, message: tuple[str, str]) -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Brak SUPERVISOR_TOKEN (tryb dev) — powiadomienie tylko w logu: %s", message[0])
        return
    title, body = message
    payload = {"title": title, "message": body, "data": {"clickAction": PANEL, "url": PANEL, "tag": TAG}}
    try:
        async with session.post(
            NOTIFY_URL, json=payload, headers={"Authorization": f"Bearer {token}"}
        ) as response:
            if response.status >= 400:
                log.warning("Powiadomienie nieudane: HTTP %s", response.status)
    except aiohttp.ClientError as err:
        log.warning("Powiadomienie nieudane: %s", err)
