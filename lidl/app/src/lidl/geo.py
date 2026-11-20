"""Współrzędne sklepów do mapy w zakładce Rytm (E9; rozpoznanie w docs/PLAN_E9_rytm.md).

Publiczna lista sklepów Lidl Plus (bez logowania, ~1000 sklepów) ma `storeKey` = `store_code` z paragonów
i `location`. Pobieramy ją tylko, gdy pojawi się sklep jeszcze niesprawdzony, i zapisujemy tylko nasze
sklepy — zamknięty sklep znika z listy Lidla, ale zostaje na mapie; sklep spoza listy dostaje wpis bez
współrzędnych. Błąd sieci nie przerywa przebiegu.
"""

from __future__ import annotations

import asyncio
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


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# generyczny agent (polityka Nominatim wymaga identyfikacji aplikacji); bez danych użytkownika
NOMINATIM_HEADERS = {"User-Agent": "ha-shopping-addon-store-map/1.0"}
NOMINATIM_PAUSE = 1.1  # s między zapytaniami (limit publicznej instancji: 1/s)
NOMINATIM_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def refresh_store_geo_biedronka(
    session: aiohttp.ClientSession, history: History, pause: float = NOMINATIM_PAUSE
) -> int:
    """Geokoduje adresy sklepów Biedronki w Nominatim (tylko publiczny adres sklepu: ulica, kod, miasto).

    Brak trafienia albo adresu = zapis bez współrzędnych (nie pytamy ponownie); błąd sieci przerywa przebieg
    bez zapisu tego sklepu, więc kolejny dzień ponowi. Zwraca liczbę sklepów z nowym punktem."""
    missing = history.biedronka_stores_without_geo()
    located = 0
    first = True
    for code, (street, postal, city) in sorted(missing.items()):
        if not street or not city:
            history.save_store_geo([(code, None, None)])
            continue
        if not first:
            await asyncio.sleep(pause)
        first = False
        params = {
            "format": "jsonv2", "limit": "1", "countrycodes": "pl",
            "street": street, "postalcode": postal, "city": city,
        }  # fmt: skip
        try:
            async with session.get(
                NOMINATIM_URL, params=params, headers=NOMINATIM_HEADERS, timeout=NOMINATIM_TIMEOUT
            ) as response:
                response.raise_for_status()
                hits = await response.json(content_type=None)
            point = (float(hits[0]["lat"]), float(hits[0]["lon"])) if hits else (None, None)
        except (aiohttp.ClientError, TimeoutError) as err:
            log.warning("Sklepy Biedronki: Nominatim nieosiągalny (%s) — ponowię jutro", err)
            return located
        except (ValueError, KeyError, IndexError, TypeError) as err:
            log.warning("Sklepy Biedronki: nieznany kształt odpowiedzi Nominatim dla %s (%s)", code, err)
            point = (None, None)
        history.save_store_geo([(code, *point)])
        located += point[0] is not None
    if missing:
        log.info("Sklepy Biedronki: punkty %d z %d nowych", located, len(missing))
    return located


async def refresh_all_store_geo(session: aiohttp.ClientSession, history: History) -> None:
    """Oba źródła współrzędnych; błąd jednego nie blokuje drugiego."""
    for refresh in (refresh_store_geo, refresh_store_geo_biedronka):
        try:
            await refresh(session, history)
        except Exception:
            log.exception("Sklepy: %s nieudane", refresh.__name__)
