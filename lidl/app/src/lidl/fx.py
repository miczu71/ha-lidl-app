"""Waluty i kursy NBP dla paragonów zagranicznych.

Kurs paragonu = średni kurs NBP (tabela A) z ostatniego dnia roboczego PRZED dniem zakupu. Pobierany
asynchronicznie przed zapisem (`prefetch`), a `History.upsert_tickets` czyta go synchronicznie z bazy.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import date, timedelta
from typing import Any, Protocol

import aiohttp

log = logging.getLogger(__name__)

NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json"
LOOKBACK_DAYS = 10  # zapas na weekend i święta

COUNTRY_CURRENCY = {
    "CZ": "CZK", "IT": "EUR", "SK": "EUR", "DE": "EUR", "AT": "EUR", "HU": "HUF",
    "RO": "RON", "HR": "EUR", "FR": "EUR", "ES": "EUR", "GB": "GBP",
}  # fmt: skip
_CODE_RE = re.compile(r"[A-Z]{3}")  # kod trafia do ścieżki URL NBP
_CODE_KEYS = ("code", "currencyCode", "isoCode")


def currency_code(raw: Any, country: str) -> str:
    """Kod waluty z pola `currency` listy paragonów (tekst albo słownik); inaczej mapa kraju."""
    if isinstance(raw, str) and _CODE_RE.fullmatch(raw.strip().upper()):
        return raw.strip().upper()
    if isinstance(raw, dict):
        for key in _CODE_KEYS:
            value = raw.get(key)
            if isinstance(value, str) and _CODE_RE.fullmatch(value.strip().upper()):
                return value.strip().upper()
    if raw is not None:
        shape = f"dict{sorted(str(k) for k in raw)}" if isinstance(raw, dict) else type(raw).__name__
        log.warning("Nieznany kształt pola currency (%s), waluta z mapy kraju %s", shape, country)
    return COUNTRY_CURRENCY.get(country.upper(), "EUR")


class RateStore(Protocol):
    def fx_get(self, code: str, day: str) -> float | None: ...

    def fx_put(self, code: str, day: str, mid: float) -> None: ...


Fetch = Callable[[str, aiohttp.ClientSession | None], Awaitable[dict[str, Any] | None]]


async def _http_fetch(url: str, session: aiohttp.ClientSession | None) -> dict[str, Any] | None:
    if session is None:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                log.warning("NBP: HTTP %s dla %s", resp.status, url)
                return None
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        log.warning("NBP: %s dla %s", type(err).__name__, url)
        return None
    return data if isinstance(data, dict) else None


class NbpRates:
    def __init__(self, store: RateStore, fetch: Fetch = _http_fetch) -> None:
        self._store = store
        self._fetch = fetch

    def cached(self, code: str, day: str) -> float | None:
        """Kurs z bazy (do `upsert_tickets`); PLN zawsze 1."""
        return 1.0 if code == "PLN" else self._store.fx_get(code, day)

    async def rate(self, code: str, day: str, session: aiohttp.ClientSession | None = None) -> float | None:
        if code == "PLN":
            return 1.0
        known = self._store.fx_get(code, day)
        if known is not None:
            return known
        end = date.fromisoformat(day) - timedelta(days=1)
        start = end - timedelta(days=LOOKBACK_DAYS - 1)
        data = await self._fetch(
            NBP_URL.format(code=code, start=start.isoformat(), end=end.isoformat()), session
        )
        try:
            rates = data["rates"] if data else None
            mid = float(rates[-1]["mid"]) if rates else None
        except (KeyError, IndexError, TypeError, ValueError):
            mid = None
        if mid is None:
            return None
        self._store.fx_put(code, day, mid)
        return mid

    async def prefetch(
        self, pairs: Iterable[tuple[str, str]], session: aiohttp.ClientSession | None = None
    ) -> None:
        """Pobiera brakujące kursy (waluta, dzień zakupu) do bazy; nieudane zostają bez kursu."""
        for code, day in sorted(set(pairs)):
            await self.rate(code, day, session)
