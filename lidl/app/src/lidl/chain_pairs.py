"""Pary „produkt Biedronki → produkt Lidla” (E28.4, docs/PLAN_E28_4.md).

Po imporcie: (a) EAN — `b:<EAN>` z `n:<EAN>` w Lidlu zatwierdzamy sami (bez klucza LLM); (b) reszta
idzie porcjami do modelu, który wybiera ≤3 odpowiedniki z katalogu Lidla. Wynik modelu to tylko
propozycja (`proposed`) — zatwierdza użytkownik. Do modelu idą wyłącznie nazwy produktów. Błąd lub
limit: log, nic nie zapisujemy, wrócimy przy następnym przebiegu.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .history import History
from .llm import KeyRejected, ModelRefused, TryLater, ask_logged
from .settings import Settings

log = logging.getLogger(__name__)

CHUNK = 40  # produktów Biedronki w jednym zapytaniu
MAX_CANDIDATES = 3
PROMPT = (
    "Nazwy produktów z paragonów Biedronki (skrócone jak na paragonie). Do każdej nazwy wybierz z "
    "katalogu produktów Lidla do {max} odpowiedników o porównywalnym opakowaniu (produkt do kupienia "
    "zamiast niego), od najbliższego. Jeśli nic nie pasuje, zwróć pustą listę. Zwróć JSON "
    '{{"pairs": [{{"name", "ids"}}]}} dla wszystkich nazw, "ids" to identyfikatory z katalogu.\n\n'
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
    """Zapisuje pary EAN i propozycje AI dla nowych produktów Biedronki; zwraca liczbę zapisanych."""
    pending = history.chain_pending()
    if not pending:
        return 0
    saved = 0
    matches = history.ean_matches([b for b, _n in pending])
    for b_id, lidl_id in matches.items():
        history.chain_pair_approve(b_id, lidl_id, "ean")
        saved += 1
    if not settings.llm_enabled:
        return saved
    rest = [(b, n) for b, n in pending if b not in matches]
    if not rest:
        return saved
    catalog = history.chain_catalog("lidl")
    if not catalog:
        log.info("Pary sieci: brak katalogu Lidla, %d produktów czeka", len(rest))
        return saved
    valid = {c.art_id for c in catalog}
    listing = "\n".join(f"{c.art_id}: {c.name}" for c in catalog)
    for start in range(0, len(rest), CHUNK):
        chunk = rest[start : start + CHUNK]
        ids_of: dict[str, list[str]] = {}
        for b_id, name in chunk:
            ids_of.setdefault(name, []).append(b_id)
        text = (
            PROMPT.format(max=MAX_CANDIDATES)
            + "Katalog Lidla:\n"
            + listing
            + "\n\nProdukty Biedronki:\n"
            + "\n".join(name for _b, name in chunk)
        )
        content = [{"type": "text", "text": text}]
        try:
            payload = await _ask(history, session, settings, content)
        except KeyRejected as err:  # zły klucz — kolejne porcje też go dostaną
            log.warning("Pary sieci: %s", err)
            break
        if payload is None:
            log.info("Pary sieci: żaden model nie odpowiedział, %d produktów w porcji czeka", len(chunk))
            continue
        for item in payload.get("pairs") or []:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("name")
            ids = item.get("ids")
            if not isinstance(raw_name, str) or raw_name not in ids_of or not isinstance(ids, list):
                continue
            picked = [i for i in dict.fromkeys(ids) if isinstance(i, str) and i in valid][:MAX_CANDIDATES]
            for b_id in ids_of[raw_name]:
                if history.chain_pair_propose(b_id, picked):
                    saved += 1
    log.info("Pary sieci: %d zapisanych z %d nowych produktów", saved, len(pending))
    return saved


async def _ask(
    history: History, session: aiohttp.ClientSession, s: Settings, content: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Odpowiedź pierwszego modelu z kolejki, który odpowie; None, gdy żaden (KeyRejected leci wyżej)."""
    for model in s.llm_vision_models:
        try:
            return await ask_logged(
                history, "pary-sieci", session, s.llm_url, s.llm_key, model, content, "chain_pairs", SCHEMA
            )
        except KeyRejected:
            raise
        except (ModelRefused, TryLater) as err:
            log.info("Pary sieci: model %s: %s, następny", model, err)
    return None
