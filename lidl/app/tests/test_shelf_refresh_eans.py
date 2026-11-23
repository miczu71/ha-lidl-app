"""Zlecenia cen Biedronki po EAN (E6b.3b): migracja v17, `refresh_eans`, `POST /api/v1/shelf`."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lidl import chain_savings, shelf_prices
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from lidl.history import SCHEMA_VERSION, History, ShelfPrice
from lidl.service import LidlService
from lidl.settings import Settings
from lidl.shelf_prices import BATCH_PAUSE_S, REQUEST_PAUSE_S, refresh_eans
from lidl.web.app import create_app

NOW = datetime(2026, 11, 23, 3, 0, 0)
TOKEN = "t0ken-for-tests"
PRICE = {"price": "3.20", "regular_price": "3.20", "is_promotion": False}


def _eans(n: int, start: int = 0) -> list[str]:
    return [f"590000000{i:04d}" for i in range(start, start + n)]


class FakeApi:
    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.errors = errors or {}
        self.calls: list[str] = []
        self.stock_calls = 0

    async def product_price(self, store: str, ean: str) -> Any:
        self.calls.append(ean)
        if ean in self.errors:
            raise self.errors[ean]
        return PRICE

    async def product_stock(self, store: str, ean: str) -> Any:
        self.stock_calls += 1
        return {"coverage": 3}


class Sleeps:
    def __init__(self) -> None:
        self.values: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.values.append(seconds)


def _row(ean: str, fetched: datetime) -> ShelfPrice:
    return ShelfPrice("6308", ean, 1.0, 1.0, None, None, None, False, False, fetched.isoformat(), None)


def test_schema_v17_and_migration_from_v16_keeps_backup_once(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    h = History(path)
    assert SCHEMA_VERSION == 17
    del h
    db = sqlite3.connect(path)
    db.execute("DROP TABLE shelf_absent")
    db.execute("PRAGMA user_version = 16")
    db.commit()
    db.close()
    h = History(path)
    assert h._db.execute("PRAGMA user_version").fetchone()[0] == 17
    assert (tmp_path / "h.db.pre-absent").exists()
    assert h._db.execute("SELECT COUNT(*) FROM shelf_absent").fetchone()[0] == 0
    (tmp_path / "h.db.pre-absent").unlink()
    del h
    History(path)  # druga migracja nie następuje: kopii nie ma
    assert not (tmp_path / "h.db.pre-absent").exists()


def test_fresh_database_makes_no_absent_backup(tmp_path: Path) -> None:
    History(tmp_path / "h.db")
    assert not (tmp_path / "h.db.pre-absent").exists()


def test_absent_mark_list_clear(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.shelf_absent_mark("6308", ["b", "a"], NOW)
    h.shelf_absent_mark("6308", ["old"], NOW - timedelta(days=40))
    h.shelf_absent_mark("1111", ["other"], NOW)
    assert h.shelf_absent_list("6308", NOW - timedelta(days=30)) == ["a", "b"]
    h.shelf_absent_clear("6308", ["a"])
    assert h.shelf_absent_list("6308", NOW - timedelta(days=30)) == ["b"]


async def test_probe_429_stops_everything(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(5)
    api = FakeApi({eans[0]: LidlPlusError("za dużo", status=429)})
    sleeps = Sleeps()
    res = await refresh_eans(h, api, "6308", eans, sleep=sleeps, now=NOW)
    assert api.calls == [eans[0]] and sleeps.values == []
    assert res.failed == 1 and res.ok == 0
    assert h.shelf_list("6308") == []


async def test_probe_other_error_also_aborts(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(3)
    api = FakeApi({eans[0]: LidlPlusError("503", status=503)})
    res = await refresh_eans(h, api, "6308", eans, sleep=Sleeps(), now=NOW)
    assert api.calls == [eans[0]] and res.failed == 1


async def test_probe_404_does_not_abort(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(3)
    api = FakeApi({eans[0]: LidlPlusError("nie ma", status=404)})
    res = await refresh_eans(h, api, "6308", eans, sleep=Sleeps(), now=NOW)
    assert api.calls == eans and res.skipped == 1 and res.ok == 2
    assert h.shelf_absent_list("6308", NOW - timedelta(days=1)) == [eans[0]]


async def test_batches_20_20_5_with_pauses(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(45)
    api, sleeps = FakeApi(), Sleeps()
    res = await refresh_eans(h, api, "6308", eans, sleep=sleeps, now=NOW)
    assert res.ok == 45 and api.calls == eans and api.stock_calls == 0
    assert len(sleeps.values) == 44  # brak pauzy po ostatnim
    assert sleeps.values.count(BATCH_PAUSE_S) == 2 and sleeps.values.count(REQUEST_PAUSE_S) == 42
    assert [i + 1 for i, v in enumerate(sleeps.values) if v == BATCH_PAUSE_S] == [20, 40]
    assert len(h.shelf_list("6308")) == 45


async def test_skips_fresh_and_recent_absent_but_retries_old_absent(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    fresh, stale, absent_new, absent_old, plain = _eans(5)
    h.shelf_replace("6308", [_row(fresh, NOW - timedelta(days=6)), _row(stale, NOW - timedelta(days=8))])
    h.shelf_absent_mark("6308", [absent_new], NOW - timedelta(days=29))
    h.shelf_absent_mark("6308", [absent_old], NOW - timedelta(days=31))
    api = FakeApi()
    await refresh_eans(
        h, api, "6308", [fresh, stale, absent_new, absent_old, plain, plain], now=NOW, sleep=Sleeps()
    )
    assert api.calls == [stale, absent_old, plain]


async def test_404_marks_absent_and_price_clears_it(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    gone, back = _eans(2)
    h.shelf_absent_mark("6308", [back], NOW - timedelta(days=31))
    api = FakeApi({gone: LidlPlusError("404", status=404)})
    res = await refresh_eans(h, api, "6308", [gone, back], now=NOW, sleep=Sleeps())
    assert res.skipped == 1 and res.ok == 1
    assert h.shelf_absent_list("6308", NOW - timedelta(days=30)) == [gone]
    assert [r.ean for r in h.shelf_list("6308")] == [back]


async def test_mid_run_429_and_connection_errors_abort_and_keep_reads(tmp_path: Path) -> None:
    for err in (LidlPlusError("429", status=429), LidlPlusAuthError("a"), LidlPlusCannotConnect("c")):
        h = History(tmp_path / f"{type(err).__name__}{err.status}.db")
        eans = _eans(5)
        api = FakeApi({eans[2]: err})
        res = await refresh_eans(h, api, "6308", eans, sleep=Sleeps(), now=NOW)
        assert api.calls == eans[:3] and res.failed == 1 and res.ok == 2
        assert [r.ean for r in h.shelf_list("6308")] == eans[:2]


async def test_mid_run_503_continues(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(4)
    api = FakeApi({eans[2]: LidlPlusError("503", status=503)})
    res = await refresh_eans(h, api, "6308", eans, sleep=Sleeps(), now=NOW)
    assert api.calls == eans and res.failed == 1 and res.ok == 3


# --- POST /api/v1/shelf ---------------------------------------------------------------------------------


@pytest.fixture
def prod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(shelf_prices, "REQUEST_PAUSE_S", 0.0)
    s = Settings(
        data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share", api_token=TOKEN
    )
    with TestClient(create_app(s)) as c:
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _ready(prod: TestClient, monkeypatch: pytest.MonkeyPatch, api: FakeApi) -> History:
    h: History = prod.app.state.history  # type: ignore[attr-defined]
    h.set_setting("biedronka_store", "6308")
    monkeypatch.setattr(chain_savings, "_bdr_slugs", lambda service: ["osoba-b"])

    async def fake_chain_api(self: LidlService, slug: str) -> FakeApi:
        return api

    monkeypatch.setattr(LidlService, "chain_api", fake_chain_api)
    return h


def _wait_tasks(prod: TestClient) -> None:
    tasks = prod.app.state.shelf_tasks  # type: ignore[attr-defined]
    deadline = time.monotonic() + 5
    while tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not tasks


def test_post_requires_token(prod: TestClient) -> None:
    assert prod.post("/api/v1/shelf", json={"eans": _eans(1)}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"eans": []},
        {"eans": "5900000000001"},
        {"eans": ["123"]},
        {"eans": ["59000000000011"]},
        {"eans": ["abcdefgh"]},
        {"eans": [5900000000001]},
        {"eans": _eans(101)},
        {"eans": _eans(1), "store": 5},
        [],
    ],
)
def test_post_400(prod: TestClient, monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    _ready(prod, monkeypatch, FakeApi())
    assert prod.post("/api/v1/shelf", json=body, headers=AUTH).status_code == 400


def test_post_400_on_non_json(prod: TestClient) -> None:
    assert prod.post("/api/v1/shelf", content=b"nie json", headers=AUTH).status_code == 400


def test_post_409_no_store_and_no_account(prod: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = prod.post("/api/v1/shelf", json={"eans": _eans(1)}, headers=AUTH)
    assert r.status_code == 409 and r.json()["reason"] == "no_store"
    prod.app.state.history.set_setting("biedronka_store", "6308")  # type: ignore[attr-defined]
    r = prod.post("/api/v1/shelf", json={"eans": _eans(1)}, headers=AUTH)
    assert r.status_code == 409 and r.json()["reason"] == "no_account"


def test_post_409_busy(prod: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    _ready(prod, monkeypatch, FakeApi())
    lock = prod.app.state.shelf_lock  # type: ignore[attr-defined]
    asyncio.run(lock.acquire())
    try:
        r = prod.post("/api/v1/shelf", json={"eans": _eans(1)}, headers=AUTH)
    finally:
        lock.release()
    assert r.status_code == 409 and r.json()["reason"] == "busy"


def test_post_202_counts_runs_in_background_and_get_has_absent(
    prod: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh, gone, absent, todo = _eans(4)
    api = FakeApi({gone: LidlPlusError("404", status=404)})
    h = _ready(prod, monkeypatch, api)
    now = datetime.now()
    h.shelf_replace("6308", [_row(fresh, now)])
    h.shelf_absent_mark("6308", [absent], now - timedelta(days=2))
    r = prod.post("/api/v1/shelf", json={"eans": [fresh, gone, absent, todo, todo]}, headers=AUTH)
    assert r.status_code == 202
    assert r.json() == {"accepted": 2, "skipped_fresh": 1, "skipped_absent": 1}
    _wait_tasks(prod)
    assert api.calls == [gone, todo]
    assert not prod.app.state.shelf_lock.locked()  # type: ignore[attr-defined]
    body = prod.get("/api/v1/shelf", headers=AUTH).json()
    assert body["absent"] == sorted([absent, gone])
    assert {i["ean"] for i in body["items"]} == {fresh, todo}


def test_get_absent_empty_without_store(prod: TestClient) -> None:
    assert prod.get("/api/v1/shelf", headers=AUTH).json()["absent"] == []


def test_post_background_failure_releases_lock(prod: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _ready(prod, monkeypatch, FakeApi())

    async def boom(self: LidlService, slug: str) -> FakeApi:
        raise RuntimeError("token=sekret")

    monkeypatch.setattr(LidlService, "chain_api", boom)
    assert prod.post("/api/v1/shelf", json={"eans": _eans(1)}, headers=AUTH).status_code == 202
    _wait_tasks(prod)
    assert not prod.app.state.shelf_lock.locked()  # type: ignore[attr-defined]


class _OddShapeApi(FakeApi):
    async def product_price(self, store: str, ean: str) -> Any:
        self.calls.append(ean)
        return []  # zmieniony format odpowiedzi


async def test_probe_unknown_shape_aborts(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    eans = _eans(4)
    api = _OddShapeApi()
    res = await refresh_eans(h, api, "6308", eans, sleep=Sleeps(), now=NOW)
    assert api.calls == [eans[0]] and res.failed == 1


async def test_priceless_reading_is_marked_absent_not_requeued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = History(tmp_path / "h.db")
    (ean,) = _eans(1)
    monkeypatch.setattr(shelf_prices, "parse_price", lambda *a, **k: None)
    res = await refresh_eans(h, FakeApi(), "6308", [ean], sleep=Sleeps(), now=NOW)
    assert res.ok == 1
    assert h.shelf_absent_list("6308", NOW - timedelta(days=1)) == [ean]
