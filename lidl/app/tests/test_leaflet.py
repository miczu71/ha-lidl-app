from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from lidl.history import History
from lidl.leaflet import (
    FALLBACK_AFTER,
    MAX_ATTEMPTS,
    OVERVIEW_URL,
    LeafletRunner,
    find_flyers,
    page_batches,
    parse_matches,
    same_product,
)
from lidl.promotions import Promotion, PromotionRunner
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import DEFAULT_FALLBACK_MODELS, Settings, load_settings

START, END = date(2026, 10, 8), date(2026, 10, 10)
NOW = datetime(2026, 10, 7, 12, 0)
START_DT = datetime(2026, 1, 1)
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


def test_page_batches_skip_pages_without_food_offers() -> None:
    alt = [
        "Oferta promocyjna na masło ekstra 83% z kuponem w aplikacji",
        "Informacja o zasadach promocji i regulaminie sklepów",
        "Porównanie cen chleba żytniego w sklepach Lidl i u konkurencji",
        "Oferta odzieży damskiej marki Esmara",
        "Prezentacja odkurzacza do liści marki Parkside",
        "Oferta zniczy i wkładów parafinowych",
        "Artykuły chemii domowej, w tym ręcznik papierowy",  # drogeria zostaje
        "Oferta napojów roślinnych i soków",
        "Strona 96 - Gazetka - 8.10",
        "",  # bez opisu: zostaje
    ]
    flyer = {"flyer": {"pages": [{"number": n, "image": "x", "altText": a} for n, a in enumerate(alt, 1)]}}
    assert [p[0] for b in page_batches(flyer) for p in b] == [1, 7, 8, 10]


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
        llm_vision_models=("model-a", "model-b"), llm_fallback_models=("model-fb",),
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
    assert h.leaflet_matches_active(START) == [
        ("0000111", "Produkt A XXL", "-38%", "2026-10-08", "2026-10-10")
    ]


async def test_all_models_refusing_postpones_the_batch_and_restarts_the_queue(tmp_path: Path) -> None:
    h = _history(tmp_path)
    runner = LeafletRunner(
        FakeSession([(429, ""), (400, ""), (429, "")]),
        h,
        _settings(tmp_path),  # type: ignore[arg-type]
    )
    await runner.step(NOW)
    batch = h.next_leaflet_batch("2026-10-07T18:00:00")
    assert batch is not None and batch["batch"] == 0 and runner._refused == set()


async def test_bad_key_is_retried_not_treated_as_a_rate_limit(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession([(401, ""), (401, "")])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert session.models == ["model-a"] and runner._refused == set()
    assert h.has_pending_leaflet(START)


async def test_overloaded_model_falls_through_to_the_next_one(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession([(503, ""), _answer()])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert session.models == ["model-a", "model-b"] and runner._refused == set()  # model-a wraca w następnej
    assert h.next_leaflet_batch(NOW.isoformat())["batch"] == 1  # type: ignore[index]


async def test_runner_retries_the_same_batch_later_on_overload(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession([(503, ""), (502, "")])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert h.next_leaflet_batch(NOW.isoformat()) is not None  # paczka 2 czeka od razu
    batch = h.next_leaflet_batch("2026-10-07T12:10:00")
    assert batch is not None and batch["batch"] == 0 and batch["attempts"] == 1


def test_active_merges_leaflet_matches_without_duplicates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.add_leaflet("g1", [], START, END)
    h.save_leaflet_matches("g1", [
        Promotion("0000111", "Produkt A z gazetki", "-38%", START, END),
        Promotion("0000444", "Produkt D", "-20% przy zakupie 2", START, END),
    ])  # fmt: skip
    runner = PromotionRunner(None, h)  # type: ignore[arg-type]
    runner.latest = [Promotion("0000111", "Produkt A (lidl.pl)", "-38%", START, END)]
    assert [p.title for p in runner.active(START)] == ["Produkt A (lidl.pl)", "Produkt D"]


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
    assert (s.llm_enabled, s.llm_vision_models) == (enabled, ("m1",))
    assert "llm_key" not in repr(s)  # klucz nie trafia do repr/logów
    if enabled:
        assert s.llm_url == "http://x/v1"


def test_leaflet_match_started_earlier_is_still_active_until_its_end(tmp_path: Path) -> None:
    """Gazetka przetworzona po 07:00 dnia startu: trafienie trafia do porannego dnia następnego."""
    h = _history(tmp_path)
    h.add_leaflet("g1", [], START, END)
    h.save_leaflet_matches("g1", [Promotion("0000111", "Produkt A z gazetki", "-38%", START, END)])
    runner = PromotionRunner(None, h)  # type: ignore[arg-type]
    assert [p.title for p in runner.active(START + timedelta(days=1))] == ["Produkt A z gazetki"]
    assert runner.active(END + timedelta(days=1)) == []


async def test_each_model_attempt_and_batch_lands_in_event_log(tmp_path: Path) -> None:
    h = _history(tmp_path)
    runner = LeafletRunner(FakeSession([(429, ""), _answer()]), h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    ai = [(e.detail["model"], e.detail["outcome"], e.level) for e in reversed(h.events(START_DT, area="ai"))]
    assert ai == [("model-a", "refused", "warn"), ("model-b", "ok", "ok")]
    leaflet = [e.summary for e in reversed(h.events(START_DT, area="leaflet"))]
    assert leaflet[0].startswith("Nowa gazetka") and leaflet[1].startswith("Paczka 1 ")


async def test_rejected_key_is_marked_in_event_log(tmp_path: Path) -> None:
    h = _history(tmp_path)
    runner = LeafletRunner(FakeSession([(401, ""), (401, "")]), h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert {e.detail["outcome"] for e in h.events(START_DT, area="ai")} == {"key"}
    assert all(e.level == "error" for e in h.events(START_DT, area="ai"))
    assert len(h.events(START_DT, area="ai")) == 1  # zły klucz: bez kolejnych modeli
    batch = h.next_leaflet_batch("2026-10-07T12:10:00")
    assert batch is not None and batch["attempts"] == 0  # i bez zużycia próby paczki
    assert await runner.step(NOW + timedelta(minutes=30)) is False  # cała gazetka czeka na poprawny klucz


async def _exhaust_first_batch(h: History, tmp_path: Path) -> LeafletRunner:
    """Paczka 1 po `MAX_ATTEMPTS` nieudanych próbach (wszystkie modele przeciążone, awaryjny od próby 3)."""
    session = FakeSession([(503, "")] * 5 + [_answer()])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)  # odkrycie gazetki + próba 1
    fid = h.leaflet_progress()[0].flyer_id
    h.set_leaflet_batch(fid, 0, "pending", MAX_ATTEMPTS - 1, "")
    await runner.step(NOW)  # próba 30
    return runner


async def test_batch_is_postponed_to_next_morning_after_max_attempts(tmp_path: Path) -> None:
    h = _history(tmp_path)
    await _exhaust_first_batch(h, tmp_path)
    assert h.leaflet_progress()[0].failed == 1
    assert h.revive_leaflet_batches("2026-10-08T05:59:00") == 0  # jeszcze przed 6:00 następnego dnia
    assert h.revive_leaflet_batches("2026-10-08T06:00:00") == 1
    batch = h.next_leaflet_batch("2026-10-08T06:00:00")
    assert batch is not None and batch["batch"] == 0 and batch["attempts"] == 0
    assert any(e.level == "warn" and "do jutra" in e.summary for e in h.events(START_DT, area="leaflet"))


async def test_runner_step_revives_postponed_batch_the_next_day(tmp_path: Path) -> None:
    h = _history(tmp_path)
    runner = await _exhaust_first_batch(h, tmp_path)
    assert await runner.step(datetime(2026, 10, 8, 6, 5)) is True
    progress = h.leaflet_progress()[0]
    assert progress.failed == 0 and progress.done == 1


async def test_batches_of_an_ended_leaflet_are_neither_revived_nor_processed(tmp_path: Path) -> None:
    h = _history(tmp_path)
    await _exhaust_first_batch(h, tmp_path)
    assert h.revive_leaflet_batches("2026-10-11T06:00:00") == 0  # gazetka skończyła się 10.10
    assert h.next_leaflet_batch("2026-10-11T06:00:00") is None  # paczka 2 czeka, ale na nic już nie wpłynie


def test_parse_matches_with_names_requires_a_shared_word_and_a_discount() -> None:
    names = {"0000111": "Mleko UHT 1,5%", "0000444": "Banany luz"}

    def offer(code: str, name: str, discount: str) -> dict[str, Any]:
        return {
            "code": code,
            "page": 1,
            "leaflet_name": name,
            "discount": discount,
            "lidl_plus_coupon": False,
        }

    payload = {
        "matches": [
            offer("0000111", "Bułka fitness", "-20%"),  # inna nazwa niż nasz produkt
            offer("0000444", "Banany, luzem", "-30%"),
            offer("0000444", "Banany luzem", ""),  # bez rabatu
        ]
    }
    promos = parse_matches(payload, set(names), {1}, START, END, names=names)
    assert [(p.art_id, p.title) for p in promos] == [("0000444", "Banany, luzem")]
    assert (
        len(parse_matches(payload, set(names), {1}, START, END)) == 3
    )  # bez nazw (modele Google): bez filtra


async def test_fallback_model_is_used_only_after_failed_rounds_and_its_matches_are_filtered(
    tmp_path: Path,
) -> None:
    h = _history(tmp_path)
    right = {"code": "0000111", "page": 2, "leaflet_name": "Produkt A XXL", "discount": "-38%",
             "valid_from": "08.10", "valid_to": "10.10", "lidl_plus_coupon": False}  # fmt: skip
    wrong = {**right, "code": "0000444", "leaflet_name": "Bułka fitness"}
    session = FakeSession([(503, "")] * 4 + [_answer(right, wrong)])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)
    assert session.models == ["model-a", "model-b"]  # pierwsza runda tylko modele Google
    fid = h.leaflet_progress()[0].flyer_id
    h.set_leaflet_batch(fid, 0, "pending", FALLBACK_AFTER, "")
    await runner.step(NOW)
    assert session.models[2:] == ["model-a", "model-b", "model-fb"]  # Google ponownie, potem awaryjny
    assert [m[0] for m in h.leaflet_matches_active(START)] == ["0000111"]


def test_fallback_models_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options = tmp_path / "options.json"
    monkeypatch.setenv("LIDL_OPTIONS_PATH", str(options))
    options.write_text(json.dumps({"llm_url": "http://x/v1", "llm_key": "k"}))
    assert load_settings().llm_fallback_models == DEFAULT_FALLBACK_MODELS
    options.write_text(json.dumps({"llm_fallback_models": ["m9"]}))
    assert load_settings().llm_fallback_models == ("m9",)
    options.write_text(json.dumps({"llm_fallback_models": []}))
    assert load_settings().llm_fallback_models == ()  # pusta lista wyłącza modele awaryjne


async def test_fallback_model_joins_at_once_when_the_primary_models_hit_their_limits(tmp_path: Path) -> None:
    h = _history(tmp_path)
    right = {"code": "0000111", "page": 2, "leaflet_name": "Produkt A XXL", "discount": "-38%",
             "valid_from": "08.10", "valid_to": "10.10", "lidl_plus_coupon": False}  # fmt: skip
    wrong = {**right, "code": "0000444", "leaflet_name": "Bułka fitness"}
    session = FakeSession([(429, ""), (429, ""), _answer(right, wrong)])
    runner = LeafletRunner(session, h, _settings(tmp_path))  # type: ignore[arg-type]
    await runner.step(NOW)  # limity dzienne Google: bez czekania 6 h i bez 3 nieudanych rund
    assert session.models == ["model-a", "model-b", "model-fb"]
    assert [m[0] for m in h.leaflet_matches_active(START)] == ["0000111"]
    assert h.leaflet_progress()[0].done == 1


def test_has_pending_leaflet_ignores_ended_flyers(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.add_leaflet("g1", [[[1, "u"]]], START, END)
    assert h.has_pending_leaflet(END) and not h.has_pending_leaflet(END + timedelta(days=1))


def test_normalization_keeps_polish_l_so_stems_still_match() -> None:
    assert same_product("Płatki owsiane", "Płatki owsiane 500g") and same_product(
        "Łosoś wędzony", "Losos wedz."
    )
