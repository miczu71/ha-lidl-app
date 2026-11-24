"""E6c: twarde limity feedu Frisco, walidacja `store` w POST /api/v1/shelf, ścisły `_ean`."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lidl import catalog, frisco_feed
from lidl.history import History
from lidl.settings import Settings
from lidl.web.app import create_app

TOKEN = "t0ken-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 11, 23, 3, 0)


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _n: int) -> Any:
        for c in self._chunks:
            yield c


class _Resp:
    def __init__(self, chunks: list[bytes], content_length: int | None) -> None:
        self.content = _Content(chunks)
        self.content_length = content_length

    def raise_for_status(self) -> None:
        return None

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *_a: object) -> None:
        return None


class _Session:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    def get(self, *_a: Any, **_k: Any) -> _Resp:
        return self._resp


async def test_fetch_rejects_content_length_over_limit(tmp_path: Path) -> None:
    resp = _Resp([b"x"], frisco_feed.MAX_FEED_BYTES + 1)
    fetch = frisco_feed.downloader(_Session(resp))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="za duży"):
        await fetch(tmp_path / "f.tmp")
    assert not (tmp_path / "f.tmp").exists()


async def test_fetch_rejects_stream_over_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(frisco_feed, "MAX_FEED_BYTES", 10)
    resp = _Resp([b"x" * 6, b"x" * 6], None)
    fetch = frisco_feed.downloader(_Session(resp))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="za duży"):
        await fetch(tmp_path / "f.tmp")


async def test_fetch_accepts_feed_within_limit(tmp_path: Path) -> None:
    resp = _Resp([b"abc", b"def"], 6)
    await frisco_feed.downloader(_Session(resp))(tmp_path / "f.tmp")  # type: ignore[arg-type]
    assert (tmp_path / "f.tmp").read_bytes() == b"abcdef"


async def test_empty_feed_is_error_and_logged(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")

    async def empty(dest: Path) -> None:
        dest.write_text('{"products": []}')

    res = await frisco_feed.refresh(h, empty, tmp_path / "catalog", now=NOW)
    assert "feed bez produktów" in res.error
    assert h.events(datetime(2026, 1, 1), area="catalog")[0].level == "error"
    assert not list((tmp_path / "catalog").glob("*.tmp"))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    s = Settings(
        data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share", api_token=TOKEN
    )
    with TestClient(create_app(s)) as c:
        yield c


@pytest.mark.parametrize("store", ["a b", "x" * 40, "../x", "a/b"])
def test_shelf_post_rejects_bad_store(client: TestClient, store: str) -> None:
    r = client.post("/api/v1/shelf", json={"eans": ["5900000000011"], "store": store}, headers=AUTH)
    assert r.status_code == 400


def test_shelf_post_accepts_store_code(client: TestClient) -> None:
    r = client.post("/api/v1/shelf", json={"eans": ["5900000000011"], "store": "0001"}, headers=AUTH)
    assert r.status_code != 400


def test_ean_is_8_to_13_digits() -> None:
    assert catalog._ean("b:12345678901234") is None
    assert catalog._ean("b:5900000000000") == "5900000000000"
    assert catalog._ean("b:1234567") is None
