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
from .client.exceptions import LidlPlusAuthError
from .settings import COUNTRY, LANGUAGE


class LidlService:
    def __init__(self, store: AccountStore, session: aiohttp.ClientSession) -> None:
        self.store = store
        self._session = session
        self._apis: dict[str, LidlPlusApi] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, OAuthLogin] = {}

    def _lock(self, slug: str) -> asyncio.Lock:
        return self._locks.setdefault(slug, asyncio.Lock())

    def begin_login(self, slug: str) -> str:
        """Nowa sesja PKCE dla konta; zwraca adres logowania na stronie Lidla."""
        self.store.get(slug)
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
        code = auth_code_from_redirect(pasted)
        tokens = await login.exchange_code(code, login.verifier)
        async with self._lock(slug):
            self.store.save_tokens(slug, tokens)
            self._apis.pop(slug, None)
        self._pending.pop(slug, None)
        await self.check(slug)

    async def _api(self, slug: str) -> LidlPlusApi:
        api = self._apis.get(slug)
        if api is None:
            account = self.store.get(slug)
            if not account.connected or not account.refresh_token:
                raise LidlPlusAuthError("not_connected")

            async def save(tokens: dict[str, str]) -> None:
                self.store.save_tokens(slug, tokens)

            api = LidlPlusApi(
                self._session,
                account.access_token or "",
                account.refresh_token,
                country=COUNTRY,
                language=LANGUAGE,
                save_tokens=save,
            )
            self._apis[slug] = api
        return api

    async def check(self, slug: str) -> None:
        """Odświeża token w razie potrzeby i pyta o kartę lojalnościową (sprawdza sesję)."""
        async with self._lock(slug):
            api = await self._api(slug)
            if not await api.loyalty_id():
                raise LidlPlusAuthError("no_loyalty_card")

    async def tickets(self, slug: str, year_offset: int) -> list[dict[str, Any]]:
        async with self._lock(slug):
            return await (await self._api(slug)).tickets(year_offset)

    async def ticket(self, slug: str, ticket_id: str) -> dict[str, Any]:
        async with self._lock(slug):
            return await (await self._api(slug)).ticket(ticket_id)

    async def promotions(self, slug: str) -> dict[str, Any]:
        async with self._lock(slug):
            return await (await self._api(slug)).promotions_list()

    async def lotteries(self, slug: str) -> Any:
        async with self._lock(slug):
            return await (await self._api(slug)).lotteries()

    async def coupon_plus(self, slug: str) -> Any:
        async with self._lock(slug):
            return await (await self._api(slug)).coupon_plus()

    async def activate(self, slug: str, coupon_id: str) -> None:
        async with self._lock(slug):
            await (await self._api(slug)).activate_promotion(coupon_id)

    async def delete(self, slug: str) -> None:
        async with self._lock(slug):
            self.store.delete(slug)
            self._apis.pop(slug, None)
        self._pending.pop(slug, None)
