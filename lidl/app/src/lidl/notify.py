"""Powiadomienia na `notify.family` (API Core przez Supervisora, `homeassistant_api`): poranne — którą kartę
wziąć na zakupy, jakie kupony są na niej aktywne, jakie promocje na nasze produkty startują dziś i jakie
zdrapki czekają; wieczorne — zdrapki wygasające
dziś."""

from __future__ import annotations

import logging
import os
import re
from datetime import date

import aiohttp

from .coupons import AccountReport, ActiveCoupon
from .history import WatchedCoupon
from .promotions import Promotion
from .rewards import Rewards
from .text import count_text, fmt_until, plural

log = logging.getLogger(__name__)

NOTIFY_URL = "http://supervisor/core/api/services/notify/family"
# panel add-onu w HA: Supervisor nadaje kontenerowi HOSTNAME = slug z „-” zamiast „_” (np. f0987e0f-lidl)
PANEL = "/app/" + os.environ.get("HOSTNAME", "f0987e0f-lidl").replace("-", "_")
TAG = "lidl-kupony"  # nowe powiadomienie zastępuje poprzednie
TAG_SCRATCH = "lidl-zdrapki"  # wieczorne przypomnienie nie zastępuje porannego
TAG_WATCHED = "lidl-obserwowane"  # obserwowane produkty (E15) obok porannego, nie zamiast niego


def _name(c: ActiveCoupon | WatchedCoupon) -> str:
    return c.title.split("|")[0].strip(" *")


def _discount(text: str) -> str:
    text = re.sub(r"\s+", " ", text.replace("*", "").replace("‎", "")).strip()
    text = re.sub(r"\s*/\s*1\s*", "/", text)
    text = re.sub(r"(\d+)\s*\+\s*(\d+)\s*gratis", r"\1+\2", text)
    text = text.replace(" przy zakupie ", " przy ").replace(" rabatu", "")
    return text.replace("-", "−", 1) if text.startswith("-") else text


def _offer(name: str, discount: str, end: date, today: date) -> str:
    return f"{name} {discount} (do {fmt_until(end, today)})"


def _label(c: ActiveCoupon) -> str:
    threshold = re.search(r"min\.\s*([\d\s,]+zł)", c.title)
    if c.general and threshold:
        return f"{_discount(c.discount)} na zakupy od {threshold.group(1).strip()}"
    return f"{_name(c)} {_discount(c.discount)}"


def compose(
    results: dict[str, AccountReport],
    rewards: dict[str, Rewards] | None = None,
    *,
    dry_run: bool,
    today: date | None = None,
    promos: list[Promotion] | None = None,
) -> tuple[str, str] | None:
    """Tytuł z rekomendacją karty i treść z kuponami per karta, nowymi promocjami i zdrapkami; None, gdy
    żadna karta nie ma aktywnych kuponów na nasze produkty, a nie ma też promocji ani zdrapek."""
    today = today or date.today()
    prefix = "Lidl (tryb próbny): " if dry_run else "Lidl: "
    cards = [
        f"{label} do {fmt_until(c.expires.astimezone().date(), today)}"
        for label, r in (rewards or {}).items()
        for c in r.scratch_cards
    ]
    promo = " · ".join(_offer(p.title, _discount(p.discount), p.end, today) for p in promos or [])
    tail = ([f"Nowe promocje: {promo}"] if promo else []) + (
        [f"Zdrapki: {' · '.join(cards)}"] if cards else []
    )
    shown = {
        label: sorted((c for c in r.active if c.weight or c.general), key=lambda c: (-c.weight, _name(c)))
        for label, r in results.items()
        if r.weighted_count
    }
    if not shown:
        if cards:
            title = plural(len(cards), "zdrapka", "zdrapki", "zdrapek") + " do zdrapania"
        elif promos:
            title = count_text(len(promos), "promocja", "promocje", "promocji") + " na Wasze produkty"
        else:
            return None
        return prefix + title, "\n".join(tail)
    labels = {label: [_label(c) for c in cs] for label, cs in shown.items()}
    common = set.intersection(*map(set, labels.values())) if len(labels) > 1 else set()
    lines = [f"{label}: " + " · ".join(x for x in ls if x not in common) for label, ls in labels.items()]
    lines = [line for line in lines if not line.endswith(": ")]
    if common:
        lines.append("Obie: " + " · ".join(x for x in next(iter(labels.values())) if x in common))
    ending = dict.fromkeys(_name(c) for cs in shown.values() for c in cs if c.valid_to == today.isoformat())
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
    lines += tail
    best = max(results, key=lambda label: results[label].score)
    count = count_text(results[best].weighted_count, "kupon", "kupony", "kuponów") + " na Wasze produkty"
    tie = sum(r.score == results[best].score for r in results.values()) > 1
    title = f"obie karty podobnie ({count})" if tie else f"dziś karta {best} ({count})"
    return prefix + title, "\n".join(lines)


def compose_expiring(rewards: dict[str, Rewards], today: date | None = None) -> tuple[str, str] | None:
    """Wieczorne przypomnienie: zdrapki wygasające dziś (kto ma je zdrapać); None, gdy żadnej."""
    today = today or date.today()
    labels = [
        label
        for label, r in rewards.items()
        for c in r.scratch_cards
        if c.expires.astimezone().date() == today
    ]
    if not labels:
        return None
    title = "zdrapka wygasa" if len(labels) == 1 else "zdrapki wygasają"
    return f"Lidl: {title} dziś o 23:59", ", ".join(labels) + " — zdrap w aplikacji Lidl Plus"


def compose_watched(
    coupons: list[tuple[str, WatchedCoupon]], promos: list[Promotion], today: date
) -> tuple[str, str] | None:
    """Obserwowane produkty (E15): kupony (para etykieta konta, kupon) i trwające promocje, linia na rzecz;
    ten sam kupon na obu kontach to jedna linia. None, gdy nic."""
    who: dict[tuple[str, str, date], list[str]] = {}
    for label, c in coupons:
        who.setdefault((_name(c), _discount(c.discount), c.valid_to), []).append(label)
    rows = [(name, "kupon", disc, end, "obie karty" if len(labels) > 1 else labels[0])
            for (name, disc, end), labels in who.items()]  # fmt: skip
    rows += [
        (p.title, "promocja", _discount(p.discount), p.end, f"od {fmt_until(p.start, today)}") for p in promos
    ]
    if not rows:
        return None
    if len(rows) == 1:
        name, kind, disc, _, _ = rows[0]
        title = f"{name} — {kind} {disc}"
    else:
        n = len({row[0] for row in rows})
        title = (
            count_text(n, "obserwowany produkt", "obserwowane produkty", "obserwowanych produktów")
            + " z rabatem"
        )
    body = [f"{_offer(name, disc, end, today)} · {kind} {note}" for name, kind, disc, end, note in rows]
    return "Lidl: " + title, "\n".join(body)


async def send(session: aiohttp.ClientSession, message: tuple[str, str], *, tag: str = TAG) -> bool:
    """True, gdy HA przyjął powiadomienie (w trybie dev — tylko log, też True)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        log.info("Brak SUPERVISOR_TOKEN (tryb dev) — powiadomienie tylko w logu: %s", message[0])
        return True
    title, body = message
    payload = {"title": title, "message": body, "data": {"clickAction": PANEL, "url": PANEL, "tag": tag}}
    try:
        async with session.post(
            NOTIFY_URL, json=payload, headers={"Authorization": f"Bearer {token}"}
        ) as response:
            if response.status >= 400:
                log.warning("Powiadomienie nieudane: HTTP %s", response.status)
                return False
            return True
    except aiohttp.ClientError as err:
        log.warning("Powiadomienie nieudane: %s", err)
        return False
