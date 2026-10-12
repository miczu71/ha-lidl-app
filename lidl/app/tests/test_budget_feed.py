from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl import budget_feed
from lidl.budget_feed import BudgetFeed, write_export
from lidl.history import History
from lidl.llm import ModelRefused
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings


def _history(tmp_path: Path) -> History:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a",
        [
            {"id": "old", "date": "2025-01-05T10:00:00+00:00", "totalAmount": 5.0},
            {"id": "new", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 12.0},
        ],
    )
    h.save_detail("old", "S", ParsedReceipt(items=[ReceiptItem("0001", "Chleb", 1, 5.0, 5.0)]))
    h.save_detail(
        "new",
        "S",
        ParsedReceipt(
            items=[ReceiptItem("0002", "Mydlo", 1, 4.0, 4.0), ReceiptItem("0003", "Pieluszki", 1, 8.0, 8.0)]
        ),
    )
    return h


def _settings(tmp_path: Path, key: str = "k") -> Settings:
    return Settings(
        data_dir=tmp_path, log_level="info", dev=True, llm_url="http://llm", llm_key=key,
        llm_vision_models=("m1", "m2"), share_dir=tmp_path / "share",
    )  # fmt: skip


def test_write_export_is_atomic_json(tmp_path: Path) -> None:
    path = tmp_path / "share" / "lidl" / "receipts.json"
    assert write_export(_history(tmp_path), path) == 2
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and [r["id"] for r in data["receipts"]] == ["old", "new"]
    assert not path.with_suffix(".tmp").exists()


async def test_refresh_classifies_only_new_products_and_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    async def fake_ask(_s: Any, _u: str, _k: str, model: str, content: list[dict[str, Any]], *_: Any) -> Any:
        asked.append(model)
        if model == "m1":
            raise ModelRefused("HTTP 429")
        assert "0001" not in content[0]["text"]  # chleb kupiony przed oknem „nowych”
        pairs = [("0002", "drugstore"), ("0003", "kids"), ("9999", "food"), ("0002", "toys")]
        return {"items": [{"code": c, "category": k} for c, k in pairs]}

    monkeypatch.setattr(budget_feed, "ask_json", fake_ask)
    h = _history(tmp_path)
    async with aiohttp.ClientSession() as session:
        feed = BudgetFeed(session, h, _settings(tmp_path))
        await feed.refresh(date(2026, 10, 12))
    assert asked == ["m1", "m2"]
    since = datetime(2000, 1, 1)
    assert [e.detail["outcome"] for e in reversed(h.events(since, area="ai"))] == ["refused", "ok"]
    assert [e.detail for e in h.events(since, area="budget")] == [{"receipts": 2}]
    assert (h.category_of("0002"), h.category_of("0003")) == (("drugstore", "ai"), ("kids", "ai"))
    receipts = json.loads(feed.path.read_text(encoding="utf-8"))["receipts"]
    assert receipts[1]["parts"] == {"drugstore": 4.0, "kids": 8.0}


async def test_refresh_without_models_answer_keeps_products_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*_: Any) -> Any:
        raise ModelRefused("HTTP 429")

    monkeypatch.setattr(budget_feed, "ask_json", refuse)
    h = _history(tmp_path)
    async with aiohttp.ClientSession() as session:
        feed = BudgetFeed(session, h, _settings(tmp_path))
        await feed.refresh(date(2026, 10, 12))
    assert list(h.uncategorized()) == ["0001", "0002", "0003"]
    assert feed.path.exists()  # plik i tak powstaje (wszystko jako food)


async def test_classification_error_does_not_block_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> Any:
        raise AttributeError("'list' object has no attribute 'get'")

    monkeypatch.setattr(budget_feed, "ask_json", broken)
    async with aiohttp.ClientSession() as session:
        feed = BudgetFeed(session, _history(tmp_path), _settings(tmp_path))
        await feed.refresh(date(2026, 10, 12))
    assert feed.path.exists()
