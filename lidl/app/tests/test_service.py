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


class _FakeBiedronka:
    instances: list[_FakeBiedronka] = []

    def __init__(self, session: object, access: str, refresh: str, save: Any = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        _FakeBiedronka.instances.append(self)

    async def list_all(self, *, archived: bool, max_pages: int) -> list[dict[str, Any]]:
        self.calls.append(("list", archived, max_pages))
        return [{"id": 5, "date": "2026-10-05T10:00:00+02:00", "total_price": 9.5}, {"id": None}]

    async def transaction_details(self, tid: str) -> dict[str, Any]:
        self.calls.append(("detail", tid))
        return {"id": tid}

    async def transactions(self, page: int) -> dict[str, Any]:
        self.calls.append(("check", page))
        return {}


async def _biedronka_service(
    tmp_path: Path, monkeypatch, session: aiohttp.ClientSession
) -> tuple[LidlService, str]:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 2", chain="biedronka")
    store.save_tokens(acc.slug, {"access_token": "a", "refresh_token": "r"})
    _FakeBiedronka.instances.clear()
    monkeypatch.setattr("lidl.service.BiedronkaApi", _FakeBiedronka)
    return LidlService(store, session), acc.slug


async def test_biedronka_tickets_routing_and_end_of_history(tmp_path: Path, monkeypatch) -> None:
    from lidl.client.exceptions import LidlPlusError

    async with aiohttp.ClientSession() as session:
        svc, slug = await _biedronka_service(tmp_path, monkeypatch, session)
        fresh = await svc.tickets(slug, 0)
        assert fresh == [
            {
                "id": "b:5",
                "date": "2026-10-05T10:00:00+02:00",
                "totalAmount": 9.5,
                "savings": 0,
                "couponsUsedCount": 0,
                "storeCode": None,
                "articlesCount": -1,
            }
        ]
        await svc.tickets(slug, 1)
        api = _FakeBiedronka.instances[0]
        assert api.calls == [("list", False, 20), ("list", True, 50)]
        with pytest.raises(LidlPlusError) as err:
            await svc.tickets(slug, 2)
        assert err.value.status == 400


async def test_biedronka_ticket_strips_prefix_and_check_lists_page(tmp_path: Path, monkeypatch) -> None:
    async with aiohttp.ClientSession() as session:
        svc, slug = await _biedronka_service(tmp_path, monkeypatch, session)
        assert await svc.ticket(slug, "b:5") == {"id": "5"}
        await svc.check(slug)
        assert _FakeBiedronka.instances[0].calls == [("detail", "5"), ("check", 1)]


async def test_biedronka_account_rejects_lidl_only_calls(tmp_path: Path, monkeypatch) -> None:
    from lidl.client.exceptions import LidlPlusError

    async with aiohttp.ClientSession() as session:
        svc, slug = await _biedronka_service(tmp_path, monkeypatch, session)
        for call in (
            svc.promotions(slug),
            svc.lotteries(slug),
            svc.coupon_plus(slug),
            svc.activate(slug, "c"),
        ):
            with pytest.raises(LidlPlusError, match="not_supported"):
                await call


async def test_chain_api_only_for_biedronka_accounts(tmp_path: Path, monkeypatch) -> None:
    from lidl.client.exceptions import LidlPlusError

    async with aiohttp.ClientSession() as session:
        svc, slug = await _biedronka_service(tmp_path, monkeypatch, session)
        assert isinstance(await svc.chain_api(slug), _FakeBiedronka)
        lidl = svc.store.create("Osoba 1")
        svc.store.save_tokens(lidl.slug, {"access_token": "a", "refresh_token": "r"})
        with pytest.raises(LidlPlusError, match="not_supported"):
            await svc.chain_api(lidl.slug)


async def test_biedronka_login_uses_biedronka_pkce(tmp_path: Path) -> None:
    store = AccountStore(tmp_path)
    acc = store.create("Osoba 2", chain="biedronka")
    async with aiohttp.ClientSession() as session:
        svc = LidlService(store, session)
        assert "konto.biedronka.pl" in svc.begin_login(acc.slug)
