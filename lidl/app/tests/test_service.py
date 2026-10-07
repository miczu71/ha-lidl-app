from __future__ import annotations

from pathlib import Path

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
