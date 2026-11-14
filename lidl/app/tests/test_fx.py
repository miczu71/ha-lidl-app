from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl.fx import NbpRates, _http_fetch, currency_code
from lidl.history import History


def test_currency_code_from_text_dict_and_fallback(caplog: pytest.LogCaptureFixture) -> None:
    assert currency_code("czk", "CZ") == "CZK"
    assert currency_code({"currencyCode": "eur"}, "IT") == "EUR"
    assert currency_code({"code": "CZK"}, "CZ") == "CZK"
    assert "currency" not in caplog.text
    assert currency_code(None, "CZ") == "CZK"
    assert caplog.text == ""
    assert currency_code({"secret": "x"}, "IT") == "EUR"
    assert (
        "secret" in caplog.text and "'x'" not in caplog.text and " x" not in caplog.text.replace("secret", "")
    )
    assert currency_code(12, "GB") == "GBP"


class Fetcher:
    def __init__(self, payload: dict[str, Any] | None) -> None:
        self.payload = payload
        self.urls: list[str] = []

    async def __call__(self, url: str, session: Any) -> dict[str, Any] | None:
        self.urls.append(url)
        return self.payload


async def test_rate_uses_last_entry_before_the_day_and_caches(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    fetch = Fetcher({"rates": [{"mid": 0.18}, {"mid": 0.19}]})
    rates = NbpRates(h, fetch)
    # poniedziałek 2026-05-04: zakres 10 dni do niedzieli 05-03, ostatni wpis (piątek) wygrywa
    assert await rates.rate("CZK", "2026-05-04") == 0.19
    assert fetch.urls == [
        "https://api.nbp.pl/api/exchangerates/rates/a/CZK/2026-04-24/2026-05-03/?format=json"
    ]
    assert await rates.rate("CZK", "2026-05-04") == 0.19
    assert len(fetch.urls) == 1
    assert rates.cached("CZK", "2026-05-04") == 0.19
    assert rates.cached("CZK", "2026-05-05") is None


async def test_rate_missing_returns_none_and_pln_is_one(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    rates = NbpRates(h, Fetcher(None))
    assert await rates.rate("EUR", "2026-05-04") is None
    assert await NbpRates(h, Fetcher({"rates": []})).rate("EUR", "2026-05-04") is None
    assert await rates.rate("PLN", "2026-05-04") == 1.0
    assert rates.cached("PLN", "2026-05-04") == 1.0


async def test_prefetch_fills_cache_once_per_pair(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    fetch = Fetcher({"rates": [{"mid": 4.3}]})
    rates = NbpRates(h, fetch)
    await rates.prefetch([("EUR", "2026-05-04"), ("EUR", "2026-05-04")])
    assert len(fetch.urls) == 1 and rates.cached("EUR", "2026-05-04") == 4.3


class _Resp:
    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    async def json(self, content_type: Any = None) -> Any:
        return self._payload

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Session:
    def __init__(self, resp: _Resp | None = None, exc: BaseException | None = None) -> None:
        self._resp = resp
        self._exc = exc

    def get(self, url: str, **kwargs: Any) -> _Resp:
        if self._exc is not None:
            raise self._exc
        assert self._resp is not None
        return self._resp


async def test_http_fetch_without_session_returns_none() -> None:
    assert await _http_fetch("https://example.test", None) is None


async def test_http_fetch_non_200_returns_none_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        assert await _http_fetch("https://example.test/x", _Session(_Resp(status=404))) is None  # type: ignore[arg-type]
    assert "HTTP 404" in caplog.text


async def test_http_fetch_client_error_and_timeout_return_none(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        assert await _http_fetch("https://e.test", _Session(exc=aiohttp.ClientError())) is None  # type: ignore[arg-type]
        assert await _http_fetch("https://e.test", _Session(exc=TimeoutError())) is None  # type: ignore[arg-type]
    assert "ClientError" in caplog.text and "TimeoutError" in caplog.text


async def test_http_fetch_returns_dict_only() -> None:
    assert await _http_fetch("https://e.test", _Session(_Resp(payload={"rates": []}))) == {"rates": []}  # type: ignore[arg-type]
    assert await _http_fetch("https://e.test", _Session(_Resp(payload=[1, 2]))) is None  # type: ignore[arg-type]
