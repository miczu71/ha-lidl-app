"""Warstwa usługi: logowanie kont i dostęp do API Lidl Plus.

Refresh token rotuje — odświeżenie jednego konta musi iść jednym torem, inaczej drugi
równoległy refresh użyje już unieważnionego tokenu. Stąd blokada per konto.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .accounts import AccountStore
from .client.api import LidlPlusApi
from .client.auth import OAuthLogin, auth_code_from_redirect
from .client.biedronka import BiedronkaApi, BiedronkaLogin
from .client.biedronka import auth_code_from_redirect as biedronka_code
from .client.exceptions import LidlPlusAuthError, LidlPlusError
from .settings import COUNTRY, LANGUAGE

BIEDRONKA_FRESH_PAGES = 20  # limit stron listy świeżych zakupów
BIEDRONKA_ARCHIVE_PAGES = 50  # limit stron archiwum
COUNTRY_LANGUAGE = {"PL": LANGUAGE, "CZ": "cs-CZ", "IT": "it-IT"}  # reszta: en-GB


class LidlService:
    def __init__(self, store: AccountStore, session: aiohttp.ClientSession) -> None:
        self.store = store
        self._session = session
        self._apis: dict[tuple[str, str], LidlPlusApi | BiedronkaApi] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, OAuthLogin | BiedronkaLogin] = {}

    def _lock(self, slug: str) -> asyncio.Lock:
        return self._locks.setdefault(slug, asyncio.Lock())

    def begin_login(self, slug: str) -> str:
        """Nowa sesja PKCE dla konta; zwraca adres logowania na stronie Lidla."""
        account = self.store.get(slug)
        login: OAuthLogin | BiedronkaLogin
        if account.chain == "biedronka":
            login = BiedronkaLogin(self._session)
        else:
            login = OAuthLogin(self._session, country=COUNTRY, language=LANGUAGE)
        self._pending[slug] = login
        return login.prepare()

    def pending_url(self, slug: str) -> str | None:
        login = self._pending.get(slug)
        return login.auth_url if login else None

    async def finish_login(self, slug: str, pasted: str) -> None:
        """Wymienia wklejony adres callback (lub sam kod) na tokeny i sprawdza połączenie."""
        login = self._pending.get(slug)
        if login is None or login.verifier is None:
            raise LidlPlusAuthError("no_pending_login")
        chain = self.store.get(slug).chain
        code = biedronka_code(pasted) if chain == "biedronka" else auth_code_from_redirect(pasted)
        tokens = await login.exchange_code(code, login.verifier)
        async with self._lock(slug):
            self.store.save_tokens(slug, tokens)
            self._drop_apis(slug)
        self._pending.pop(slug, None)
        await self.check(slug)

    def _drop_apis(self, slug: str) -> None:
        for key in [k for k in self._apis if k[0] == slug]:
            del self._apis[key]

    async def _api(self, slug: str, country: str = COUNTRY) -> Any:
        api = self._apis.get((slug, country))
        if api is None:
            account = self.store.get(slug)
            if not account.connected or not account.refresh_token:
                raise LidlPlusAuthError("not_connected")
            if account.chain == "biedronka":

                async def save_b(tokens: dict[str, str]) -> None:
                    self.store.save_tokens(slug, tokens)
                    self._drop_apis(slug)

                api = BiedronkaApi(self._session, account.access_token or "", account.refresh_token, save_b)
                self._apis[(slug, country)] = api
                return api

            async def save(tokens: dict[str, str]) -> None:
                self.store.save_tokens(slug, tokens)
                self._drop_apis(slug)  # refresh token rotuje: pozostałe kraje czytają świeży z magazynu

            api = LidlPlusApi(
                self._session,
                account.access_token or "",
                account.refresh_token,
                country=country,
                language=COUNTRY_LANGUAGE.get(country, "en-GB"),
                save_tokens=save,
            )
            self._apis[(slug, country)] = api
        return api

    async def _lidl_api(self, slug: str) -> LidlPlusApi:
        """API Lidla; konto Biedronki nie ma kuponów, loterii ani nagród."""
        if self.store.get(slug).chain == "biedronka":
            raise LidlPlusError("not_supported")
        api = await self._api(slug)
        assert isinstance(api, LidlPlusApi)
        return api

    async def check(self, slug: str) -> None:
        """Odświeża token w razie potrzeby i pyta o kartę lojalnościową (sprawdza sesję)."""
        async with self._lock(slug):
            api = await self._api(slug)
            if isinstance(api, BiedronkaApi):
                await api.transactions(1)
                return
            if not await api.loyalty_id():
                raise LidlPlusAuthError("no_loyalty_card")

    async def tickets(self, slug: str, year_offset: int, country: str = COUNTRY) -> list[dict[str, Any]]:
        async with self._lock(slug):
            api = await self._api(slug, country)
            if isinstance(api, BiedronkaApi):
                return await _biedronka_tickets(api, year_offset)
            return await api.tickets(year_offset)  # type: ignore[no-any-return]

    async def ticket(self, slug: str, ticket_id: str, country: str = COUNTRY) -> dict[str, Any]:
        async with self._lock(slug):
            api = await self._api(slug, country)
            if isinstance(api, BiedronkaApi):
                return await api.transaction_details(ticket_id.removeprefix("b:"))
            return await api.ticket(ticket_id)  # type: ignore[no-any-return]

    async def promotions(self, slug: str) -> dict[str, Any]:
        async with self._lock(slug):
            return await (await self._lidl_api(slug)).promotions_list()

    async def lotteries(self, slug: str) -> Any:
        async with self._lock(slug):
            return await (await self._lidl_api(slug)).lotteries()

    async def coupon_plus(self, slug: str) -> Any:
        async with self._lock(slug):
            return await (await self._lidl_api(slug)).coupon_plus()

    async def activate(self, slug: str, coupon_id: str) -> None:
        async with self._lock(slug):
            await (await self._lidl_api(slug)).activate_promotion(coupon_id)

    async def delete(self, slug: str) -> None:
        async with self._lock(slug):
            self.store.delete(slug)
            self._drop_apis(slug)
        self._pending.pop(slug, None)


async def _biedronka_tickets(api: BiedronkaApi, year_offset: int) -> list[dict[str, Any]]:
    """Offset 0 = świeże zakupy, 1 = archiwum, dalej koniec historii (HTTP 400 jak u Lidla)."""
    if year_offset > 1:
        raise LidlPlusError("http_400", status=400)
    archived = year_offset == 1
    rows = await api.list_all(
        archived=archived, max_pages=BIEDRONKA_ARCHIVE_PAGES if archived else BIEDRONKA_FRESH_PAGES
    )
    return [
        {
            "id": f"b:{r['id']}",
            "date": r.get("date"),
            "totalAmount": r.get("total_price"),
            "savings": 0,
            "couponsUsedCount": 0,
            "storeCode": None,
            "articlesCount": -1,
        }
        for r in rows
        if r.get("id") is not None and r.get("date")
    ]
