"""Klient modelu językowego (API zgodne z OpenAI) wspólny dla gazetek (E4) i kategorii produktów (E6)."""

from __future__ import annotations

import json
from time import monotonic
from typing import TYPE_CHECKING, Any

import aiohttp

from . import __version__
from .history import elapsed_ms

if TYPE_CHECKING:
    from .history import History

LLM_TIMEOUT = aiohttp.ClientTimeout(total=180)


class ModelRefused(Exception):
    """Model odmówił (limit, brak obsługi obrazów, za duże zapytanie) — spróbuj następnego."""


class TryLater(Exception):
    """Przeciążenie albo sieć — spróbuj później."""


class KeyRejected(TryLater):
    """Zły klucz (401/403) — błąd konfiguracji, nie limit modelu; alert w zakładce Status (E23)."""


def _log_attempt(history: History, use: str, model: str, began: float, err: Exception | None) -> None:
    outcome, level = (
        ("ok", "ok") if err is None
        else ("key", "error") if isinstance(err, KeyRejected)
        else ("refused", "warn") if isinstance(err, ModelRefused)
        else ("overloaded", "warn")
    )  # fmt: skip
    history.log_event(
        "ai", level, f"{use}: {model} — " + (str(err) if err else "OK"),
        {"use": use, "model": model, "outcome": outcome}, duration_ms=elapsed_ms(began),
    )  # fmt: skip


async def ask_logged(
    history: History,
    use: str,
    session: aiohttp.ClientSession,
    url: str,
    key: str,
    model: str,
    content: list[dict[str, Any]],
    name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """`ask_json` z wpisem w dzienniku (E23) o wyniku i czasie; `use` = gazetka | kategorie."""
    began = monotonic()
    try:
        payload = await ask_json(session, url, key, model, content, name, schema)
    except (ModelRefused, TryLater) as err:
        _log_attempt(history, use, model, began, err)
        raise
    _log_attempt(history, use, model, began, None)
    return payload


async def ask_json(
    session: aiohttp.ClientSession,
    url: str,
    key: str,
    model: str,
    content: list[dict[str, Any]],
    name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Jedno zapytanie do modelu (API zgodne z OpenAI) z odpowiedzią JSON wg `schema`."""
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
    }
    headers = {"Authorization": f"Bearer {key}", "User-Agent": f"ha-lidl/{__version__}"}
    try:
        async with session.post(
            f"{url}/chat/completions", json=body, headers=headers, timeout=LLM_TIMEOUT
        ) as r:
            if r.status >= 500:
                raise TryLater(f"HTTP {r.status}")
            if r.status in (401, 403):  # zły klucz — to błąd konfiguracji, nie limit modelu
                raise KeyRejected(f"klucz odrzucony (HTTP {r.status}), sprawdź opcję llm_key")
            if r.status >= 400:
                raise ModelRefused(f"HTTP {r.status}")
            out = await r.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:  # ValueError: treść nie jest JSON-em
        raise TryLater(type(err).__name__) from err
    if not isinstance(out, dict):
        raise TryLater("odpowiedź bez obiektu JSON")
    text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        payload = json.loads(text)
    except ValueError as err:
        raise TryLater("odpowiedź nie jest JSON-em") from err
    return payload if isinstance(payload, dict) else {}
