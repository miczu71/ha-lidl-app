from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl import pairs
from lidl.history import History
from lidl.llm import TryLater
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings


def _history(tmp_path: Path) -> History:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [{"id": "pl-1", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 11.0}])
    h.save_detail(
        "pl-1",
        "S",
        ParsedReceipt(
            items=[
                ReceiptItem("0001", "Mleko 1 l", 1, 4.0, 4.0),
                ReceiptItem("0002", "Ser 200 g", 1, 7.0, 7.0),
            ]
        ),
    )
    h.upsert_tickets(
        "a",
        [{"id": "cz-1", "date": "2026-10-02T10:00:00+00:00", "totalAmount": 100.0, "currency": "CZK"}],
        country="CZ",
        fx=lambda cur, day: 0.2,
    )
    h.save_detail(
        "cz-1",
        None,
        ParsedReceipt(
            items=[ReceiptItem("1", "Mléko 1 l", 1, 60.0, 60.0), ReceiptItem("2", "Sýr 200 g", 1, 40.0, 40.0)]
        ),
        country="CZ",
    )
    return h


def _settings(tmp_path: Path, key: str = "k") -> Settings:
    return Settings(
        data_dir=tmp_path, log_level="info", dev=True, llm_url="http://llm", llm_key=key,
        llm_vision_models=("m1",), share_dir=tmp_path / "share",
    )  # fmt: skip


def _id(h: History, name: str) -> str:
    return next(c.art_id for c in h.pl_catalog() if c.name == name)


async def test_pending_and_catalog(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert h.pair_pending() == [("CZ", "mléko", "Mléko 1 l"), ("CZ", "sýr", "Sýr 200 g")]
    assert h.pair_pending("IT") == []
    assert {c.name for c in h.pl_catalog()} == {"Mleko 1 l", "Ser 200 g"}
    assert h.pl_catalog()[0].name == "Ser 200 g"  # większy wydatek pierwszy
    assert len(h.pl_catalog(limit=1)) == 1


async def test_propose_stores_proposed_with_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _history(tmp_path)
    mleko = _id(h, "Mleko 1 l")
    calls: list[Any] = []

    async def fake(history: Any, use: str, session: Any, url: str, key: str, model: str, content: Any,
                   name: str, schema: Any) -> dict[str, Any]:  # fmt: skip
        calls.append((use, model, content[0]["text"]))
        return {"pairs": [{"name": "mléko", "ids": [mleko, "9999"]}, {"name": "sýr", "ids": []}]}

    monkeypatch.setattr(pairs, "ask_logged", fake)
    async with aiohttp.ClientSession() as session:
        assert await pairs.propose(h, session, _settings(tmp_path)) == 2
        assert await pairs.propose(h, session, _settings(tmp_path)) == 0  # nic nie czeka
    assert len(calls) == 1 and calls[0][:2] == ("pary", "m1")
    assert f"{mleko}: Mleko 1 l" in calls[0][2]
    got = {p["foreign_name"]: p for p in h.pair_list("proposed")}
    assert got["mléko"]["candidates"] == [mleko]  # id spoza katalogu odrzucone
    assert got["sýr"]["candidates"] == []


async def test_llm_error_saves_nothing_and_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _history(tmp_path)

    async def boom(*args: Any) -> dict[str, Any]:
        raise TryLater("limit")

    monkeypatch.setattr(pairs, "ask_logged", boom)
    async with aiohttp.ClientSession() as session:
        assert await pairs.propose(h, session, _settings(tmp_path)) == 0
    assert h.pair_list("proposed") == []
    assert len(h.pair_pending()) == 2


async def test_no_key_means_no_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    h = _history(tmp_path)
    calls: list[Any] = []

    async def fake(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"pairs": []}

    monkeypatch.setattr(pairs, "ask_logged", fake)
    async with aiohttp.ClientSession() as session:
        assert await pairs.propose(h, session, _settings(tmp_path, key="")) == 0
    assert calls == []


def test_pair_propose_is_idempotent_and_decide_undo(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert h.pair_propose("CZ", "mléko", ["1"]) is True
    assert h.pair_propose("CZ", "mléko", ["2"]) is False
    assert h.pair_list("proposed")[0]["candidates"] == ["1"]
    assert h.pair_decide("CZ", "mléko", "approved", "1") is True
    [row] = h.pair_list("approved")
    assert row["pl_art_id"] == "1" and row["decided_at"]
    assert h.pair_pending() == [("CZ", "sýr", "Sýr 200 g")]
    assert h.pair_decide("CZ", "mléko", "proposed") is True
    [row] = h.pair_list("proposed")
    assert row["pl_art_id"] is None and row["decided_at"] is None
    assert h.pair_decide("CZ", "nie ma", "rejected") is False
    h.pair_propose("CZ", "sýr", [])
    assert h.pair_decide("CZ", "sýr", "rejected") is True
    assert [p["foreign_name"] for p in h.pair_list("rejected")] == ["sýr"]
