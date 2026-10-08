from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from lidl.history import History
from lidl.leaflet import OVERVIEW_URL, LeafletRunner, find_flyers, page_batches, parse_matches
from lidl.promotions import Promotion, PromotionRunner
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings, load_settings

START, END = date(2026, 10, 8), date(2026, 10, 10)
NOW = datetime(2026, 10, 7, 12, 0)
FLYER_URL = "https://leaflets.example/v4/flyer?id=g1"

OVERVIEW = {
    "categories": [
        {
            "subcategories": [
                {
                    "flyers": [
                        {"id": "g1", "name": "Gazetka", "flyerJson": FLYER_URL,
                         "offerStartDate": "2026-10-08T00:00:00", "offerEndDate": "2026-10-10T00:00:00"},
                        {"id": "k1", "name": "Katalog", "flyerJson": "https://leaflets.example/k1",
                         "offerStartDate": "2026-10-05T00:00:00", "offerEndDate": "2026-10-10T00:00:00"},
                    ]
                }
            ]
        }
    ]
}  # fmt: skip
FLYER = {"flyer": {"pages": [{"number": n, "image": f"https://img.example/p{n}.jpg"} for n in range(1, 8)]}}


def test_find_flyers_takes_only_the_weekly_leaflet() -> None:
    assert [(f.id, f.start, f.end) for f in find_flyers(OVERVIEW)] == [("g1", START, END)]


def test_page_batches_of_five() -> None:
    batches = page_batches(FLYER)
    assert [[p[0] for p in b] for b in batches] == [[1, 2, 3, 4, 5], [6, 7]]


def test_parse_matches_validates_and_skips_lidl_plus_coupons() -> None:
    payload = {
        "matches": [
            {"code": "0000111", "page": 2, "leaflet_name": "Produkt A", "discount": "-38%",
             "valid_from": "9.10", "valid_to": "10.10", "lidl_plus_coupon": False},
            {"code": "0000444", "page": 3, "leaflet_name": "Produkt D", "discount": "1+1 gratis",
             "lidl_plus_coupon": True},
            {"code": "9999999", "page": 2, "leaflet_name": "Obcy", "discount": "-10%",
             "lidl_plus_coupon": False},
            {"code": "0000111", "page": 9, "leaflet_name": "Inna strona", "discount": "-5%",
             "lidl_plus_coupon": False},
        ]
    }  # fmt: skip
    rows = parse_matches(payload, {"0000111", "0000444"}, {1, 2, 3}, START, END)
    assert rows == [Promotion("0000111", "Produkt A", "-38%", date(2026, 10, 9), END)]


def test_parse_matches_falls_back_to_leaflet_dates_and_rolls_over_the_year() -> None:
    m = {"code": "0000111", "page": 1, "leaflet_name": "A", "discount": "-5%", "lidl_plus_coupon": False}
    p = parse_matches({"matches": [m]}, {"0000111"}, {1}, START, END)[0]
    assert (p.start, p.end) == (START, END)
    january = {**m, "valid_from": "2.01", "valid_to": "4.01"}
    rows = parse_matches({"matches": [january]}, {"0000111"}, {1}, date(2026, 12, 28), date(2027, 1, 4))
    assert (rows[0].start, rows[0].end) == (date(2027, 1, 2), date(2027, 1, 4))


def _history(tmp_path: Path) -> History:
    """Produkt A (0000111) i Produkt D (0000444) kupowane 3 razy."""
    h = History(tmp_path / "h.db")
    days = ["2026-09-01", "2026-09-15", "2026-10-01"]
    h.upsert_tickets(
        "a",
        [
            {"id": f"t{n}", "date": f"{d}T10:00:00+00:00", "totalAmount": 9.0, "savings": 0,
             "couponsUsedCount": 0, "articlesCount": 2}
            for n, d in enumerate(days)
        ],
    )  # fmt: skip
    items = [
        ReceiptItem("0000111", "Produkt A", 1, 4.0, 4.0),
        ReceiptItem("0000444", "Produkt D", 1, 5.0, 5.0),
    ]
    for n in range(3):
        h.save_detail(f"t{n}", "S", ParsedReceipt(items=items, store={"code": "PL0001"}))
    return h


class FakeResponse:
    def __init__(self, status: int, payload: Any) -> None:
        self.status, self.payload = status, payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        assert self.status < 400

    async def json(self, content_type: str | None = None) -> Any:
        return self.payload

    async def read(self) -> bytes:
        return b"jpeg"


class FakeSession:
    """GET: overview, JSON gazetki, obrazy; POST: kolejne odpowiedzi modelu (status, treść)."""

    def __init__(self, answers: list[tuple[int, Any]]) -> None:
        self.answers, self.models = answers, []  # type: ignore[var-annotated]

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return FakeResponse(200, OVERVIEW if url == OVERVIEW_URL else FLYER if url == FLYER_URL else None)

    def post(self, url: str, *, json: dict[str, Any], **kwargs: Any) -> FakeResponse:
        self.models.append(json["model"])
        status, content = self.answers.pop(0)
        return FakeResponse(status, {"choices": [{"message": {"content": content}}]})


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path, log_level="info", dev=True, llm_url="http://llm.example/v1", llm_key="k",
        llm_vision_models=("model-a", "model-b"),
    )  # fmt: skip


def _answer(*matches: dict[str, Any]) -> tuple[int, str]:
    return 200, "```json\n" + json.dumps({"matches": list(matches)}) + "\n```"


async def test_runner_moves_to_next_model_on_rate_limit_and_saves_matches(tmp_path: Path) -> None:
    h = _history(tmp_path)
    hit = {"code": "0000111", "page": 2, "leaflet_name": "Produkt A XXL", "discount": "-38%",
           "valid_from": "08.10", "valid_to": "10.10", "lidl_plus_coupon": False}  # fmt: skip
    session = FakeSession([(429, ""), _answer(hit), _answer()])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    assert await runner.step(NOW) is True  # odkrycie gazetki + paczka 1 (model-a: 429 → model-b)
    assert await runner.step(NOW) is True  # paczka 2 od razu na model-b (model-a ma wyczerpany limit)
    assert await runner.step(NOW) is False  # nic nie czeka
    assert session.models == ["model-a", "model-b", "model-b"]
    assert h.leaflet_matches_starting(START) == [
        ("0000111", "Produkt A XXL", "-38%", "2026-10-08", "2026-10-10")
    ]


async def test_all_models_refusing_postpones_the_batch_and_restarts_the_queue(tmp_path: Path) -> None:
    h = _history(tmp_path)
    runner = LeafletRunner(FakeSession([(429, ""), (400, "")]), h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    batch = h.next_leaflet_batch("2026-10-07T18:00:00")
    assert batch is not None and batch["batch"] == 0 and runner._model == 0


async def test_bad_key_is_retried_not_treated_as_a_rate_limit(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession([(401, "")])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert session.models == ["model-a"] and runner._model == 0
    assert h.has_pending_leaflet()


async def test_runner_retries_the_same_batch_later_on_overload(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession([(503, "")])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert h.next_leaflet_batch(NOW.isoformat()) is not None  # paczka 2 czeka od razu
    batch = h.next_leaflet_batch("2026-10-07T12:10:00")
    assert batch is not None and batch["batch"] == 0 and batch["attempts"] == 1


def test_starting_merges_leaflet_matches_without_duplicates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.add_leaflet("g1", [], START, END)
    h.save_leaflet_matches("g1", [
        Promotion("0000111", "Produkt A z gazetki", "-38%", START, END),
        Promotion("0000444", "Produkt D", "-20% przy zakupie 2", START, END),
    ])  # fmt: skip
    runner = PromotionRunner(None, h)  # type: ignore[arg-type]
    runner.latest = [Promotion("0000111", "Produkt A (lidl.pl)", "-38%", START, END)]
    assert [p.title for p in runner.starting(START)] == ["Produkt A (lidl.pl)", "Produkt D"]


@pytest.mark.parametrize(
    ("url", "key", "enabled"), [("http://x/v1/", "k", True), ("", "k", False), ("u", "", False)]
)
def test_llm_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str, key: str, enabled: bool
) -> None:
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"llm_url": url, "llm_key": key, "llm_vision_models": ["m1"]}))
    monkeypatch.setenv("LIDL_OPTIONS_PATH", str(options))
    s = load_settings()
    assert (s.leaflet_enabled, s.llm_vision_models) == (enabled, ("m1",))
    assert "llm_key" not in repr(s)  # klucz nie trafia do repr/logów
    if enabled:
        assert s.llm_url == "http://x/v1"
