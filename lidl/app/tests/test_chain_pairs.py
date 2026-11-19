from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl import chain_pairs
from lidl.history import History
from lidl.llm import TryLater
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings

EAN = "5900000000017"


def _history(tmp_path: Path) -> History:
    h = History(tmp_path / "h.db")
    h.upsert_tickets("a", [{"id": "l-1", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 11.0}])
    h.save_detail(
        "l-1",
        "S",
        ParsedReceipt(
            items=[
                ReceiptItem("0001", "Mleko 1l", 1, 4.0, 4.0),
                ReceiptItem("0002", "Ser 200g", 1, 7.0, 7.0),
                ReceiptItem(f"n:{EAN}", "Jogurt 150g", 1, 2.0, 2.0),
            ]
        ),
    )
    h.upsert_tickets(
        "a", [{"id": "b-1", "date": "2026-10-02T10:00:00+00:00", "totalAmount": 9.0}], chain="biedronka"
    )
    h.save_detail(
        "b-1",
        "B",
        ParsedReceipt(
            items=[
                ReceiptItem("b:111", "Mleko 1l UHT", 1, 3.0, 3.0),
                ReceiptItem(f"b:{EAN}", "Jogurt naturalny", 1, 2.0, 2.0),
                ReceiptItem("b:222", "Chleb", 1, 4.0, 4.0),
            ]
        ),
    )
    return h


def _settings(tmp_path: Path, key: str = "k") -> Settings:
    return Settings(
        data_dir=tmp_path, log_level="info", dev=True, llm_url="http://llm", llm_key=key,
        llm_vision_models=("m1",), share_dir=tmp_path / "share",
    )  # fmt: skip


def _pairs(h: History) -> dict[str, Any]:
    return {p.b_art_id: p for p in h.chain_pair_list()}


async def test_ean_auto_approves_without_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    h = _history(tmp_path)
    calls: list[Any] = []

    async def fake(*args: Any) -> dict[str, Any]:
        calls.append(args)
        return {"pairs": []}

    monkeypatch.setattr(chain_pairs, "ask_logged", fake)
    async with aiohttp.ClientSession() as session:
        assert await chain_pairs.propose(h, session, _settings(tmp_path, key="")) == 1
    assert calls == []
    p = _pairs(h)[f"b:{EAN}"]
    assert (p.status, p.source, p.lidl_art_id) == ("approved", "ean", f"n:{EAN}")


def test_ean_match_goes_through_merges_to_html_code(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_merges([(f"n:{EAN}", "0099")])
    assert h.ean_matches([f"b:{EAN}", "b:111"]) == {f"b:{EAN}": "0099"}


def test_ean_match_needs_valid_ean_and_lidl_item(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert h.ean_matches(["b:1234567", "b:12345678901234567", "b:5900000000999", "x:" + EAN]) == {}


async def test_llm_proposes_candidates_and_drops_unknown_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _history(tmp_path)
    mleko = next(c.art_id for c in h.chain_catalog("lidl") if c.name == "Mleko 1l")
    calls: list[Any] = []

    async def fake(history: Any, use: str, session: Any, url: str, key: str, model: str, content: Any,
                   name: str, schema: Any) -> dict[str, Any]:  # fmt: skip
        calls.append((use, model, name, content[0]["text"]))
        return {"pairs": [{"name": "Mleko 1l UHT", "ids": [mleko, "9999"]}, {"name": "Chleb", "ids": []}]}

    monkeypatch.setattr(chain_pairs, "ask_logged", fake)
    async with aiohttp.ClientSession() as session:
        assert await chain_pairs.propose(h, session, _settings(tmp_path)) == 3  # EAN + 2 propozycje
        assert await chain_pairs.propose(h, session, _settings(tmp_path)) == 0  # idempotencja
    assert len(calls) == 1 and calls[0][:3] == ("pary-sieci", "m1", "chain_pairs")
    assert f"{mleko}: Mleko 1l" in calls[0][3]
    got = _pairs(h)
    assert (got["b:111"].status, got["b:111"].source, got["b:111"].candidates) == ("proposed", "ai", [mleko])
    assert got["b:222"].candidates == []


async def test_llm_error_saves_nothing_ean_still_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _history(tmp_path)

    async def boom(*args: Any) -> dict[str, Any]:
        raise TryLater("limit")

    monkeypatch.setattr(chain_pairs, "ask_logged", boom)
    async with aiohttp.ClientSession() as session:
        assert await chain_pairs.propose(h, session, _settings(tmp_path)) == 1
    assert set(_pairs(h)) == {f"b:{EAN}"}
    assert {b for b, _n in h.chain_pending()} == {"b:111", "b:222"}


async def test_undo_ean_pair_is_rejected_and_does_not_return(tmp_path: Path) -> None:
    h = _history(tmp_path)
    async with aiohttp.ClientSession() as session:
        await chain_pairs.propose(h, session, _settings(tmp_path, key=""))
        assert h.chain_pair_decide(f"b:{EAN}", "undo") is True
        assert _pairs(h)[f"b:{EAN}"].status == "rejected"
        assert await chain_pairs.propose(h, session, _settings(tmp_path, key="")) == 0
    assert _pairs(h)[f"b:{EAN}"].status == "rejected"


def test_decide_approve_reject_undo_for_ai_pair(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert h.chain_pair_propose("b:111", ["0001"]) is True
    assert h.chain_pair_propose("b:111", ["0002"]) is False
    assert h.chain_pair_decide("b:111", "approve", "0001") is True
    p = _pairs(h)["b:111"]
    assert (p.status, p.source, p.lidl_art_id, p.lidl_name, p.b_name) == (
        "approved", "manual", "0001", "Mleko 1l", "Mleko 1l UHT",
    )  # fmt: skip
    assert h.chain_pair_decide("b:111", "undo") is True
    p = _pairs(h)["b:111"]
    assert (p.status, p.lidl_art_id) == ("proposed", None)
    assert h.chain_pair_decide("b:111", "reject") is True
    assert _pairs(h)["b:111"].status == "rejected"
    assert h.chain_pair_decide("b:nope", "reject") is False


async def test_products_missing_from_reply_are_not_resent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _history(tmp_path)
    calls: list[Any] = []

    async def fake(history: Any, use: str, session: Any, url: str, key: str, model: str, content: Any,
                   name: str, schema: Any) -> dict[str, Any]:  # fmt: skip
        calls.append(1)
        return {"pairs": []}  # model nic nie zwrócił

    monkeypatch.setattr(chain_pairs, "ask_logged", fake)
    async with aiohttp.ClientSession() as session:
        await chain_pairs.propose(h, session, _settings(tmp_path))
        await chain_pairs.propose(h, session, _settings(tmp_path))
    assert len(calls) == 1  # drugi import: nic do wysłania
    assert _pairs(h)["b:222"].status == "proposed" and _pairs(h)["b:222"].candidates == []
