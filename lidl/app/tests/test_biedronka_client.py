from __future__ import annotations

import base64
import json
import time
from typing import Any

import aiohttp
import pytest

from lidl.client.biedronka import (
    BiedronkaApi,
    BiedronkaLogin,
    auth_code_from_redirect,
    refresh_tokens,
)
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError


def _jwt(exp: float) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


FRESH = _jwt(time.time() + 3600)


class Resp:
    def __init__(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body

    async def text(self) -> str:
        return "" if self._body is None else json.dumps(self._body)

    async def json(self, content_type: Any = None) -> Any:
        return self._body

    async def __aenter__(self) -> Resp:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class FakeSession:
    def __init__(self, gets: list[Any], posts: list[Any] | None = None) -> None:
        self.gets, self.posts = list(gets), list(posts or [])
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kw: Any) -> Resp:
        self.get_calls.append({"url": url, **kw})
        item = self.gets.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[no-any-return]

    def post(self, url: str, **kw: Any) -> Resp:
        self.post_calls.append({"url": url, **kw})
        item = self.posts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[no-any-return]


def _api(session: FakeSession, saved: list[dict[str, str]] | None = None, token: str = FRESH) -> BiedronkaApi:
    async def save(tokens: dict[str, str]) -> None:
        if saved is not None:
            saved.append(tokens)

    return BiedronkaApi(session, token, "r0", save)  # type: ignore[arg-type]


async def test_headers_and_details_path() -> None:
    s = FakeSession([Resp(200, {"id": "1"})])
    assert await _api(s).transaction_details("1") == {"id": "1"}
    call = s.get_calls[0]
    assert call["url"].endswith("/transactions/1/")
    assert call["headers"]["User-Agent"] == "Android/2.56.0"
    assert (
        call["headers"]["Accept-Language"] == "pl-PL"
        and call["headers"]["Authorization"] == f"Bearer {FRESH}"
    )


async def test_401_refreshes_once_saves_rotated_token_and_retries() -> None:
    new = _jwt(time.time() + 3600)
    s = FakeSession(
        [Resp(401), Resp(200, {"ok": 1})], [Resp(200, {"access_token": new, "refresh_token": "r1"})]
    )
    saved: list[dict[str, str]] = []
    assert await _api(s, saved).transactions(1) == {"ok": 1}
    assert saved == [{"access_token": new, "refresh_token": "r1"}]
    assert s.get_calls[1]["headers"]["Authorization"] == f"Bearer {new}"


async def test_second_401_is_auth_error() -> None:
    s = FakeSession([Resp(401), Resp(401)], [Resp(200, {"access_token": FRESH, "refresh_token": "r1"})])
    with pytest.raises(LidlPlusAuthError):
        await _api(s).transactions(1)


async def test_expiring_token_is_refreshed_before_request() -> None:
    s = FakeSession([Resp(200, {})], [Resp(200, {"access_token": FRESH, "refresh_token": "r1"})])
    await _api(s, token=_jwt(time.time() + 10)).transactions(1)
    assert len(s.post_calls) == 1


async def test_426_bumps_version_and_retries() -> None:
    s = FakeSession([Resp(426, None, {"min-supported-version-android": "2.99.1"}), Resp(200, {"ok": 1})])
    api = _api(s)
    assert await api.transactions(1) == {"ok": 1}
    assert api.app_version == "2.99.1" and s.get_calls[1]["headers"]["User-Agent"] == "Android/2.99.1"


async def test_426_without_newer_version_fails() -> None:
    s = FakeSession([Resp(426)])
    with pytest.raises(LidlPlusError) as err:
        await _api(s).transactions(1)
    assert err.value.status == 426


async def test_invalid_grant_is_auth_error() -> None:
    s = FakeSession([], [Resp(400, {"error": "invalid_grant"})])
    with pytest.raises(LidlPlusAuthError):
        await refresh_tokens(s, "r0")  # type: ignore[arg-type]


async def test_network_error_and_http_status_mapping() -> None:
    with pytest.raises(LidlPlusCannotConnect):
        await _api(FakeSession([aiohttp.ClientConnectionError("secret-detail")])).transactions(1)
    with pytest.raises(LidlPlusError) as err:
        await _api(FakeSession([Resp(503)])).transactions(1)
    assert err.value.status == 503 and str(err.value) == "http_503"


async def test_archived_pagination_follows_page_count() -> None:
    s = FakeSession(
        [
            Resp(200, {"transactions": [{"id": "1"}, {"id": "2"}], "page_count": 2}),
            Resp(200, {"transactions": [{"id": "3"}], "page_count": 2}),
        ]
    )
    rows = await _api(s).list_all(archived=True, max_pages=50)
    assert [r["id"] for r in rows] == ["1", "2", "3"]
    assert [c["params"]["page"] for c in s.get_calls] == [1, 2]
    assert "/transactions/archived/" in s.get_calls[0]["url"]


async def test_empty_fresh_list_stops_at_first_page() -> None:
    s = FakeSession([Resp(200, {"transactions": [], "page_count": 0})])
    assert await _api(s).list_all(archived=False, max_pages=20) == []


async def test_exchange_code_and_prepare() -> None:
    s = FakeSession([], [Resp(200, {"access_token": "a", "refresh_token": "r"})])
    login = BiedronkaLogin(s)  # type: ignore[arg-type]
    url = login.prepare()
    assert "client_id=cma20" in url and "code_challenge_method=S256" in url and login.verifier
    assert await login.exchange_code("C", login.verifier) == {"access_token": "a", "refresh_token": "r"}
    assert s.post_calls[0]["data"]["code"] == "C"


def test_auth_code_from_redirect() -> None:
    assert auth_code_from_redirect("app://cma20.biedronka.pl?code=XYZ&state=1") == "XYZ"
    assert auth_code_from_redirect("  XYZ ") == "XYZ"
    with pytest.raises(LidlPlusAuthError):
        auth_code_from_redirect("app://cma20.biedronka.pl?foo=1")
