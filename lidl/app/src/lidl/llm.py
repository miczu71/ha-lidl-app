"""Klient modelu językowego (API zgodne z OpenAI) wspólny dla gazetek (E4) i kategorii produktów (E6)."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

LLM_TIMEOUT = aiohttp.ClientTimeout(total=180)


class ModelRefused(Exception):
    """Model odmówił (limit, brak obsługi obrazów, za duże zapytanie) — spróbuj następnego."""


class TryLater(Exception):
    """Przeciążenie albo sieć — spróbuj później."""


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
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with session.post(
            f"{url}/chat/completions", json=body, headers=headers, timeout=LLM_TIMEOUT
        ) as r:
            if r.status >= 500:
                raise TryLater(f"HTTP {r.status}")
            if r.status in (401, 403):  # zły klucz — to błąd konfiguracji, nie limit modelu
                raise TryLater(f"klucz odrzucony (HTTP {r.status}), sprawdź opcję llm_key")
            if r.status >= 400:
                raise ModelRefused(f"HTTP {r.status}")
            out = await r.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise TryLater(type(err).__name__) from err
    text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        payload = json.loads(text)
    except ValueError as err:
        raise TryLater("odpowiedź nie jest JSON-em") from err
    return payload if isinstance(payload, dict) else {}
