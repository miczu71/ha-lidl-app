"""Pary „produkt zagraniczny → produkt PL” (K6a, docs/PLAN_COUNTRIES_K6.md).

Po imporcie nowe nazwy z paragonów zagranicznych idą do modelu porcjami; model wybiera do 3 najbliższych
odpowiedników z katalogu PL. Wynik to tylko propozycja (`proposed`) — zatwierdza użytkownik. Do modelu
idą wyłącznie nazwy produktów. Błąd lub limit: log, nic nie zapisujemy, wrócimy przy następnym przebiegu.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .history import History
from .llm import KeyRejected, ModelRefused, TryLater, ask_logged
from .settings import Settings

log = logging.getLogger(__name__)

CHUNK = 40  # nazw zagranicznych w jednym zapytaniu
MAX_CANDIDATES = 3
PROMPT = (
    "Nazwy produktów z paragonów zagranicznych sklepu Lidl są po czesku lub włosku (skrócone jak na "
    "paragonie). Do każdej nazwy wybierz z katalogu produktów polskich do {max} najbliższych odpowiedników "
    "(porównywalny produkt do kupienia zamiast niego), od najbliższego. Jeśli nic nie pasuje, zwróć pustą "
    'listę. Zwróć JSON {{"pairs": [{{"name", "ids"}}]}} dla wszystkich nazw, "ids" to identyfikatory z '
    "katalogu.\n\n"
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pairs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "ids"],
            },
        }
    },
    "required": ["pairs"],
}


async def propose(history: History, session: aiohttp.ClientSession, settings: Settings) -> int:
    """Zapisuje propozycje par dla nowych nazw zagranicznych; zwraca liczbę zapisanych."""
    if not settings.llm_enabled:
        return 0
    pending = history.pair_pending()
    if not pending:
        return 0
    catalog = history.pl_catalog()
    if not catalog:
        log.info("Pary produktów: brak katalogu PL, %d nazw czeka", len(pending))
        return 0
    valid = {c.art_id for c in catalog}
    listing = "\n".join(f"{c.art_id}: {c.name}" for c in catalog)
    saved = 0
    for start in range(0, len(pending), CHUNK):
        chunk = pending[start : start + CHUNK]
        names: dict[str, list[str]] = {}
        for country, name, _example in chunk:
            names.setdefault(name, []).append(country)
        text = (
            PROMPT.format(max=MAX_CANDIDATES)
            + "Katalog PL:\n"
            + listing
            + "\n\nNazwy zagraniczne:\n"
            + "\n".join(name for _country, name, _example in chunk)
        )
        content = [{"type": "text", "text": text}]
        try:
            payload = await _ask(history, session, settings, content)
        except KeyRejected as err:  # zły klucz — kolejne porcje też go dostaną
            log.warning("Pary produktów: %s", err)
            break
        if payload is None:
            log.info("Pary produktów: żaden model nie odpowiedział, %d nazw w porcji czeka", len(chunk))
            continue
        for item in payload.get("pairs") or []:
            if not isinstance(item, dict):
                continue
            foreign = item.get("name")
            ids = item.get("ids")
            if not isinstance(foreign, str) or foreign not in names or not isinstance(ids, list):
                continue
            picked = [i for i in dict.fromkeys(ids) if isinstance(i, str) and i in valid][:MAX_CANDIDATES]
            for ctry in names[foreign]:
                if history.pair_propose(ctry, foreign, picked):
                    saved += 1
    log.info("Pary produktów: %d propozycji z %d nowych nazw", saved, len(pending))
    return saved


async def _ask(
    history: History, session: aiohttp.ClientSession, s: Settings, content: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Odpowiedź pierwszego modelu z kolejki, który odpowie; None, gdy żaden (KeyRejected leci wyżej)."""
    for model in s.llm_vision_models:
        try:
            return await ask_logged(
                history, "pary", session, s.llm_url, s.llm_key, model, content, "pairs", SCHEMA
            )
        except KeyRejected:
            raise
        except (ModelRefused, TryLater) as err:
            log.info("Pary produktów: model %s: %s, następny", model, err)
    return None
