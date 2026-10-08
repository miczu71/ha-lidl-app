"""Promocje w sklepach na nasze produkty (E4; rozpoznanie w docs/PLAN_E4_gazetki.md).

Dwa publiczne źródła (bez logowania) z kodami artykułów — tymi samymi co na paragonach i w kuponach:
- lidl.pl, kategoria „Żywność i napoje” (`q/api/search`): hity gazetki z ceną i oknem promocji. Pozycje
  z ceną Lidl Plus (`lidlPlus`) pomijamy — to kupony, aktywuje je E3.
- oferty sklepu (`offers.lidlplus.com`, najczęstszy sklep z paragonów): promocje wielosztukowe
  („-20% przy zakupie 2 szt.”, „2 + 1 gratis”).
Błąd źródła nie przerywa porannego przebiegu — wtedy po prostu nie ma linii z promocjami. Lista żyje w pamięci
do następnego porannego przebiegu (jedyny czytelnik to powiadomienie; po restarcie pusta do rana).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import aiohttp

from .history import History
from .settings import COUNTRY, LANGUAGE

log = logging.getLogger(__name__)

WEB_URL = "https://www.lidl.pl/q/api/search"
WEB_PARAMS = {
    "assortment": COUNTRY,
    "locale": LANGUAGE.replace("-", "_"),
    "version": "v2.0.0",
    "category.id": "10068374",  # Żywność i napoje
    "fetchsize": "1000",
}
OFFERS_URL = "https://offers.lidlplus.com/app/api/v4/{country}/{store}/offers"
HEADERS = {"Accept": "application/json", "Accept-Language": LANGUAGE, "User-Agent": "Mozilla/5.0"}


@dataclass(frozen=True)
class Promotion:
    art_id: str
    title: str
    discount: str
    start: date
    end: date


def _code(value: Any) -> str:
    return str(value).zfill(7)  # paragony i kupony: kody 7-cyfrowe z zerami z przodu


def parse_web(payload: dict[str, Any]) -> list[Promotion]:
    out = []
    for item in payload.get("items") or []:
        g = (item.get("gridbox") or {}).get("data") or {}
        price = g.get("price") or {}
        percent = (price.get("discount") or {}).get("percentageDiscount")
        window = ((g.get("stockAvailability") or {}).get("badgeInfoV2") or [{}])[0]
        if g.get("lidlPlus") or not percent or not window.get("validUntil"):
            continue
        start = datetime.fromtimestamp(window["validFrom"]).date()  # czas lokalny add-onu (TZ = PL)
        end = datetime.fromtimestamp(window["validUntil"]).date()
        out += [Promotion(_code(a), g["fullTitle"], f"-{percent}%", start, end) for a in g["ians"]]
    return out


def parse_offers(payload: dict[str, Any]) -> list[Promotion]:
    out = []
    for o in payload.get("offers") or []:
        box = o.get("priceBox") or {}
        main = box.get("largePartString") or box.get("largePartNumeric") or ""
        discount = " ".join(str(x) for x in (main, box.get("discountMessage")) if x)
        # daty lokalne z mylną końcówką „+00:00” (jak na paragonach) — bierzemy sam dzień
        start = date.fromisoformat(o["startValidityDate"][:10])
        end = date.fromisoformat(o["endValidityDate"][:10])
        out += [Promotion(_code(a), o["title"], discount, start, end) for a in o.get("productIds") or []]
    return out


class PromotionRunner:
    def __init__(self, session: aiohttp.ClientSession, history: History) -> None:
        self._session, self._history = session, history
        self.latest: list[Promotion] = []

    async def refresh(self) -> None:
        """Pobiera oba źródła naraz; błąd jednego źródła nie blokuje drugiego."""
        gets = [self._get("lidl.pl", WEB_URL, parse_web, WEB_PARAMS)]
        store = self._history.main_store()
        if store:
            gets.append(
                self._get("oferty sklepu", OFFERS_URL.format(country=COUNTRY, store=store), parse_offers)
            )
        self.latest = [p for found in await asyncio.gather(*gets) for p in found]
        log.info("Promocje: %d pozycji", len(self.latest))

    def starting(self, today: date) -> list[Promotion]:
        """Promocje zaczynające się dziś na produkty z listy „Kupowane regularnie” (włączone), bez powtórzeń
        oferty obejmującej kilka naszych kodów."""
        codes = self._history.enabled_codes(today)
        found = [p for p in self.latest if p.start == today and p.art_id in codes]
        return list({(p.title, p.discount): p for p in found}.values())

    async def _get(
        self,
        name: str,
        url: str,
        parse: Callable[[dict[str, Any]], list[Promotion]],
        params: dict[str, str] | None = None,
    ) -> list[Promotion]:
        try:
            async with self._session.get(url, params=params, headers=HEADERS) as response:
                response.raise_for_status()
                return parse(await response.json(content_type=None))
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError) as err:
            log.warning("Promocje (%s): odczyt nieudany (%s)", name, err)
            return []
