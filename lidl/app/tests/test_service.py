from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl.accounts import AccountStore
from lidl.client.exceptions import LidlPlusAuthError
from lidl.service import LidlService


async def test_finish_login_saves_tokens_and_checks(tmp_path: Path, monkeypatch) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    async with aiohttp.ClientSession() as session:
        svc = LidlService(store, session)
        svc.begin_login(acc.slug)
        login = svc._pending[acc.slug]

        async def exchange(code: str, verifier: str) -> dict[str, str]:
            assert code == "ABC" and verifier == login.verifier
            return {"access_token": "a", "refresh_token": "r"}

        checked: list[str] = []

        async def check(slug: str) -> None:
            checked.append(slug)

        monkeypatch.setattr(login, "exchange_code", exchange)
        monkeypatch.setattr(svc, "check", check)
        await svc.finish_login(acc.slug, "com.lidlplus.app://callback?code=ABC&state=x")
        assert store.get(acc.slug).refresh_token == "r"
        assert checked == [acc.slug] and acc.slug not in svc._pending


async def test_finish_login_without_pending_fails(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(LidlPlusAuthError, match="no_pending_login"):
            await LidlService(store, session).finish_login(acc.slug, "ABC")


async def test_check_without_tokens_fails(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    async with aiohttp.ClientSession() as session:
        with pytest.raises(LidlPlusAuthError, match="not_connected"):
            await LidlService(store, session).check(acc.slug)


class _FakeApi:
    instances: list[_FakeApi] = []

    def __init__(self, session: object, access: str, refresh: str, **kwargs: Any) -> None:
        self.access, self.refresh = access, refresh
        self.kwargs = kwargs
        _FakeApi.instances.append(self)


async def test_api_language_and_cache_per_country(tmp_path: Path, monkeypatch) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    store.save_tokens(acc.slug, {"access_token": "a", "refresh_token": "r"})
    _FakeApi.instances.clear()
    monkeypatch.setattr("lidl.service.LidlPlusApi", _FakeApi)
    async with aiohttp.ClientSession() as session:
        svc = LidlService(store, session)
        cz = await svc._api(acc.slug, "CZ")
        assert cz.kwargs["language"] == "cs-CZ" and cz.kwargs["country"] == "CZ"
        assert await svc._api(acc.slug, "CZ") is cz
        it = await svc._api(acc.slug, "IT")
        assert it.kwargs["language"] == "it-IT" and it is not cz
        xx = await svc._api(acc.slug, "XX")
        assert xx.kwargs["language"] == "en-GB"
        assert len(_FakeApi.instances) == 3


async def test_drop_apis_keeps_other_accounts(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    a = store.create("Osoba 1")
    b = store.create("Osoba 2")
    async with aiohttp.ClientSession() as session:
        svc = LidlService(store, session)
        svc._apis = {(a.slug, "PL"): object(), (a.slug, "CZ"): object(), (b.slug, "PL"): object()}  # type: ignore[dict-item]
        svc._drop_apis(a.slug)
        assert list(svc._apis) == [(b.slug, "PL")]


async def test_api_save_tokens_callback_stores_and_clears_cache(tmp_path: Path, monkeypatch) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 1")
    store.save_tokens(acc.slug, {"access_token": "a", "refresh_token": "r"})
    _FakeApi.instances.clear()
    monkeypatch.setattr("lidl.service.LidlPlusApi", _FakeApi)
    async with aiohttp.ClientSession() as session:
        svc = LidlService(store, session)
        pl = await svc._api(acc.slug, "PL")
        await svc._api(acc.slug, "CZ")
        await pl.kwargs["save_tokens"]({"access_token": "a2", "refresh_token": "r2"})
        assert store.get(acc.slug).refresh_token == "r2"
        assert svc._apis == {}
