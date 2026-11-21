"""Klient API Moja Biedronka (api.prod.biedronka.cloud v7): logowanie PKCE i odczyt zakupów.

Przycięty i przepisany z integracji Przemko92/home-assistant-mojabiedronka (MIT). Logowanie (captcha + SMS)
odbywa się w przeglądarce użytkownika; add-on dostaje tylko adres `app://…?code=…` i wymienia kod na tokeny.
Błędy mapują się na wyjątki klienta Lidla, żeby synchronizacja i alerty działały bez zmian.
Nigdzie nie logujemy tokenów, nagłówków, adresów z `code=` ani treści odpowiedzi.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import aiohttp

from .auth import generate_pkce, jwt_payload
from .exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError

API_BASE = "https://api.prod.biedronka.cloud/api/v7"
AUTH_BASE = "https://konto.biedronka.pl"
REALM = "loyalty"
CLIENT_ID = "cma20"
REDIRECT_URI = "app://cma20.biedronka.pl"
API_APP_VERSION = "2.56.0"
ACCEPT_LANGUAGE = "pl-PL"
TOKEN_URL = f"{AUTH_BASE}/realms/{REALM}/protocol/openid-connect/token"
AUTH_URL = f"{AUTH_BASE}/realms/{REALM}/protocol/openid-connect/auth"
MIN_VERSION_HEADER = "min-supported-version-android"
_TOKEN_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36"
)
_VERSION_IN_TEXT = re.compile(r"(\d+(?:\.\d+)+)")

SaveTokens = Callable[[dict[str, str]], Awaitable[None]]

__all__ = [
    "BiedronkaApi",
    "BiedronkaLogin",
    "auth_code_from_redirect",
    "authorization_url",
    "generate_pkce",
    "jwt_payload",
    "refresh_tokens",
]


def authorization_url(challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _code_from_redirect(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if not query.get("code") and parsed.fragment:
        query = parse_qs(parsed.fragment)
    code = (query.get("code") or [None])[0]
    if not code:
        raise LidlPlusAuthError("missing_auth_code")
    return code


def auth_code_from_redirect(value: str) -> str:
    """Kod OAuth z wklejonego `app://…?code=…` albo sam kod."""
    raw = value.strip().strip('"').strip("'")
    if not raw:
        raise LidlPlusAuthError("missing_auth_code")
    idx = raw.find("app://")
    if idx >= 0:
        raw = raw[idx:].split()[0].rstrip(".,;\"'")
    if "://" in raw or "code=" in raw:
        return _code_from_redirect(raw)
    return raw


async def _token_request(
    session: aiohttp.ClientSession, data: dict[str, str], previous: str | None
) -> dict[str, str]:
    try:
        async with session.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": _TOKEN_USER_AGENT},
        ) as resp:
            status = resp.status
            try:
                payload = await resp.json(content_type=None)
            except ValueError:
                payload = None  # np. 502 z HTML: o błędzie decyduje status
    except TimeoutError as err:
        raise LidlPlusCannotConnect("timeout") from err
    except aiohttp.ClientError as err:
        raise LidlPlusCannotConnect(type(err).__name__) from err
    if status >= 500:
        raise LidlPlusError(f"http_{status}", status=status)
    if status >= 400 or not isinstance(payload, dict):
        raise LidlPlusAuthError("token_rejected")
    access = payload.get("access_token")
    refresh = payload.get("refresh_token") or previous
    if not access or not refresh:
        raise LidlPlusAuthError("token_rejected")
    return {"access_token": str(access), "refresh_token": str(refresh)}


async def refresh_tokens(session: aiohttp.ClientSession, refresh_token: str) -> dict[str, str]:
    data = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "refresh_token": refresh_token,
    }
    return await _token_request(session, data, refresh_token)


class BiedronkaLogin:
    """Sesja PKCE: użytkownik loguje się w przeglądarce, add-on wymienia kod z adresu `app://…`."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.verifier: str | None = None
        self.auth_url: str | None = None

    def prepare(self) -> str:
        if not self.verifier or not self.auth_url:
            self.verifier, challenge = generate_pkce()
            self.auth_url = authorization_url(challenge)
        return self.auth_url

    async def exchange_code(self, code: str, verifier: str) -> dict[str, str]:
        data = {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }
        return await _token_request(self._session, data, None)


def _version_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version or not re.fullmatch(r"\d+(?:\.\d+)*", version.strip()):
        return None
    return tuple(int(p) for p in version.strip().split("."))


def _required_version(headers: Any, body: str) -> str | None:
    header = headers.get(MIN_VERSION_HEADER) if headers is not None else None
    if _version_tuple(header):
        return str(header).strip()
    match = _VERSION_IN_TEXT.search(body or "")
    return match.group(1) if match and _version_tuple(match.group(1)) else None


class BiedronkaApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str,
        save_tokens: SaveTokens | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._save_tokens = save_tokens
        self._app_version = API_APP_VERSION

    @property
    def app_version(self) -> str:
        return self._app_version

    async def ensure_fresh_token(self) -> None:
        exp = jwt_payload(self._access_token).get("exp")
        if isinstance(exp, (int, float)) and exp - 60 > time.time():
            return
        await self._refresh()

    async def _refresh(self) -> None:
        tokens = await refresh_tokens(self._session, self._refresh_token)
        self._access_token = tokens["access_token"]
        self._refresh_token = tokens["refresh_token"]
        if self._save_tokens:
            await self._save_tokens(tokens)

    async def request(self, path: str, params: dict[str, Any] | None = None, *, method: str = "GET") -> Any:
        await self.ensure_fresh_token()
        return await self._get(path, params, refreshed=False, upgraded=False, method=method)

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None,
        *,
        refreshed: bool,
        upgraded: bool,
        method: str = "GET",
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": f"Android/{self._app_version}",
            "Accept-Language": ACCEPT_LANGUAGE,
            "Accept": "application/json",
        }
        try:
            async with self._session.request(
                method, f"{API_BASE}/{path.lstrip('/')}", params=params, headers=headers
            ) as resp:
                status = resp.status
                resp_headers = resp.headers
                body = await resp.text()
        except TimeoutError as err:
            raise LidlPlusCannotConnect("timeout") from err
        except aiohttp.ClientError as err:
            raise LidlPlusCannotConnect(type(err).__name__) from err
        if status == 401:
            if refreshed:
                raise LidlPlusAuthError("unauthorized")
            await self._refresh()
            return await self._get(path, params, refreshed=True, upgraded=upgraded, method=method)
        if status == 426:
            wanted = _required_version(resp_headers, body)
            if (
                not upgraded
                and wanted
                and (_version_tuple(wanted) or ()) > (_version_tuple(self._app_version) or ())
            ):
                self._app_version = wanted
                return await self._get(path, params, refreshed=refreshed, upgraded=True, method=method)
            raise LidlPlusError("upgrade_required", status=426)
        if status >= 400:
            raise LidlPlusError(f"http_{status}", status=status)
        if not body:
            return None
        try:
            return json.loads(body)
        except ValueError as err:
            raise LidlPlusError("bad_json", status=status) from err

    async def transactions(self, page: int = 1) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("transactions/", {"page": page})
        return result

    async def archived(self, page: int = 1) -> dict[str, Any]:
        result: dict[str, Any] = await self.request("transactions/archived/", {"page": page})
        return result

    async def transaction_details(self, transaction_id: str) -> dict[str, Any]:
        result: dict[str, Any] = await self.request(f"transactions/{transaction_id}/")
        return result

    async def coupons(self) -> Any:
        return await self.request("promos/coupons/")

    async def dashboard(self) -> Any:
        return await self.request("dashboards/dashboard/")

    async def carousel(self, carousel_id: str) -> Any:
        return await self.request(f"promos/carousels/{quote(carousel_id, safe='')}/")

    async def product_price(self, store: str, ean: str) -> dict[str, Any]:
        """Cena półkowa produktu w sklepie („jak po zeskanowaniu kodu”, E29.1)."""
        data = await self.request(f"products/price/{quote(store, safe='')}/{quote(ean, safe='')}/")
        if not isinstance(data, dict):
            raise LidlPlusError("bad_shape")
        return data

    async def product_stock(self, store: str, ean: str) -> dict[str, Any]:
        """Stan na półce produktu w sklepie (`coverage`, E30.1)."""
        data = await self.request(f"products/stock/{quote(store, safe='')}/{quote(ean, safe='')}/")
        if not isinstance(data, dict):
            raise LidlPlusError("bad_shape")
        return data

    async def reveal_and_activate(self, offer_id: str) -> Any:
        """Odsłania i aktywuje ofertę Shakeomatu/Shakeomarki (zapis na koncie, PATCH)."""
        return await self.request(f"offers/{quote(offer_id, safe='')}/reveal-and-activate/", method="PATCH")

    async def list_all(self, *, archived: bool, max_pages: int) -> list[dict[str, Any]]:
        """Wszystkie strony listy (do `page_count`, najwyżej `max_pages`)."""
        out: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            data = await (self.archived(page) if archived else self.transactions(page))
            rows = data.get("transactions") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                break
            out.extend(r for r in rows if isinstance(r, dict))
            count = data.get("page_count")
            if not isinstance(count, int) or page >= count:
                break
        return out
