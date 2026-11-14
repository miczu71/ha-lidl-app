from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lidl.fx import NbpRates, currency_code
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
