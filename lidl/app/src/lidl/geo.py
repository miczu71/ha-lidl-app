"""Współrzędne sklepów do mapy w zakładce Rytm (E9; rozpoznanie w docs/PLAN_E9_rytm.md).

Publiczna lista sklepów Lidl Plus (bez logowania, ~1000 sklepów) ma `storeKey` = `store_code` z paragonów
i `location`. Pobieramy ją tylko, gdy pojawi się sklep jeszcze niesprawdzony, i zapisujemy tylko nasze
sklepy — zamknięty sklep znika z listy Lidla, ale zostaje na mapie; sklep spoza listy dostaje wpis bez
współrzędnych. Błąd sieci nie przerywa przebiegu.
"""

from __future__ import annotations

import logging

import aiohttp

from .history import History
from .settings import COUNTRY

log = logging.getLogger(__name__)

STORES_URL = "https://stores.lidlplus.com/api/v2/{country}"


async def refresh_store_geo(session: aiohttp.ClientSession, history: History) -> int:
    """Uzupełnia `store_geo`; zwraca liczbę nowo zapisanych sklepów."""
    missing = history.stores_without_geo()
    if not missing:
        return 0
    try:
        async with session.get(STORES_URL.format(country=COUNTRY)) as response:
            response.raise_for_status()
            found = {
                s["storeKey"]: (s["location"]["latitude"], s["location"]["longitude"])
                for s in await response.json(content_type=None)
                if s.get("location")
            }
    except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as err:
        log.warning("Sklepy: lista Lidla nieosiągalna (%s)", err)
        return 0
    # sklep spoza listy zapisujemy bez współrzędnych — inaczej lista szłaby co dzień od nowa
    rows = [(code, *found.get(code, (None, None))) for code in sorted(missing)]
    history.save_store_geo(rows)
    located = sum(code in found for code in missing)
    log.info("Sklepy: współrzędne %d z %d nowych", located, len(missing))
    return located
