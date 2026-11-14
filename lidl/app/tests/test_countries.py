from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lidl import pairs
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings
from lidl.web.app import create_app

HX = {"hx-request": "true"}


@pytest.fixture
def cz_settings(settings: Settings) -> Settings:
    return Settings(
        data_dir=settings.data_dir,
        log_level="info",
        dev=True,
        share_dir=settings.share_dir,
        extra_countries=("CZ",),
        llm_url="http://llm",
        llm_key="k",
        llm_vision_models=("m1",),
    )


def _seed(client: TestClient) -> str:
    """Paragon PL (Mleko, Ser) i CZ (Mléko, Sýr) z propozycją dla „mléko”; zwraca id mleka PL."""
    h = client.app.state.history  # type: ignore[attr-defined]
    h.upsert_tickets("osoba-1", [{"id": "pl-1", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 11.0}])
    h.save_detail(
        "pl-1",
        "S",
        ParsedReceipt(
            items=[
                ReceiptItem("0001", "Mleko łaciate 1 l", 1, 4.0, 4.0),
                ReceiptItem("0002", "Ser 200 g", 1, 7.0, 7.0),
            ]
        ),
    )
    h.upsert_tickets(
        "osoba-1",
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
    mleko = next(c.art_id for c in h.pl_catalog() if c.name.startswith("Mleko"))
    h.pair_propose("CZ", "mléko", [mleko, "brak-w-katalogu"])
    return str(mleko)


def _status(client: TestClient, status: str) -> list[tuple[str, str | None]]:
    return [(p["foreign_name"], p["pl_art_id"]) for p in client.app.state.history.pair_list(status)]  # type: ignore[attr-defined]


def test_empty_states_and_chip(client: TestClient) -> None:
    r = client.get("/kraje")
    assert r.status_code == 200
    assert "extra_countries" in r.text and "Sprawdź teraz" not in r.text
    assert 'aria-current="page"' in r.text and ">Kraje</a>" in r.text


def test_no_llm_and_no_foreign_receipts_messages(settings: Settings) -> None:
    s = Settings(data_dir=settings.data_dir, log_level="info", dev=True, extra_countries=("CZ",))
    with TestClient(create_app(s)) as c:
        text = c.get("/kraje").text
    assert "wymagają klucza" in text and "Brak zagranicznych paragonów" in text


def test_page_shows_proposal_with_price_and_catalog_candidates(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        _seed(c)
        text = c.get("/kraje").text
    assert "Czechy" in text and "mléko" in text and "Mléko 1 l" in text and "12,00 zł" in text
    assert "Mleko łaciate 1 l" in text and "4,00 zł" in text
    assert "brak-w-katalogu" not in text
    assert "sýr" in text  # nazwa bez propozycji: ręczne parowanie


def test_approve_reject_undo(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        mleko = _seed(c)
        data = {"country": "CZ", "foreign_name": "mléko", "action": "approve", "pl_art_id": mleko}
        r = c.post("/kraje/para", data=data, headers={"x-ingress-path": "/i"})
        assert (r.status_code, r.headers["location"]) == (303, "/i/kraje")
        assert _status(c, "approved") == [("mléko", mleko)]
        r = c.post("/kraje/para", data={**data, "action": "undo"}, headers=HX)
        assert r.status_code == 200 and 'id="kraje-body"' in r.text
        assert _status(c, "approved") == [] and _status(c, "proposed") == [("mléko", None)]
        c.post("/kraje/para", data={**data, "action": "reject"})
        assert _status(c, "rejected") == [("mléko", None)]
        assert "Bez odpowiednika" in c.get("/kraje").text


def test_approve_outside_catalog_changes_nothing(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        _seed(c)
        data = {"country": "CZ", "foreign_name": "mléko", "action": "approve", "pl_art_id": "nie-ma"}
        assert c.post("/kraje/para", data=data).status_code == 303
        assert _status(c, "approved") == [] and _status(c, "proposed") == [("mléko", None)]


def test_manual_pair_for_name_without_proposal(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        _seed(c)
        ser = next(x.art_id for x in c.app.state.history.pl_catalog() if x.name == "Ser 200 g")  # type: ignore[attr-defined]
        c.post(
            "/kraje/para",
            data={"country": "CZ", "foreign_name": "sýr", "action": "approve", "pl_art_id": ser},
        )
        assert _status(c, "approved") == [("sýr", ser)]
        assert "Ser 200 g" in c.get("/kraje").text


def test_search_ignores_diacritics_and_empty_query(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        _seed(c)
        text = c.get("/kraje/szukaj", params={"country": "CZ", "name": "mléko", "q": "lacia"}).text
        assert "Mleko łaciate 1 l" in text and "Wybierz" in text
        assert (
            "Wybierz" not in c.get("/kraje/szukaj", params={"country": "CZ", "name": "mléko", "q": ""}).text
        )
        assert "Nic nie pasuje" in c.get("/kraje/szukaj", params={"q": "xyz"}).text


def test_check_now_starts_incremental_sync_with_countries(cz_settings: Settings, monkeypatch) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        store = c.app.state.service.store  # type: ignore[attr-defined]
        slug = store.create("Osoba 1").slug
        store.save_tokens(slug, {"access_token": "a", "refresh_token": "r"})
        store.save_tokens(store.create("Osoba 2").slug, {"access_token": "a", "refresh_token": "r"})
        _seed(c)
        started: list[Any] = []
        monkeypatch.setattr(c.app.state.sync, "start", lambda s, **kw: started.append((s, kw)) or True)  # type: ignore[attr-defined]
        r = c.post("/kraje/sprawdz", headers={"x-ingress-path": "/i"})
        assert (r.status_code, r.headers["location"]) == (303, "/i/kraje")
        assert started == [(slug, {"full": False, "countries": ("PL", "CZ")})]
        assert "Import trwa" in c.post("/kraje/sprawdz", headers=HX).text


def test_after_import_survives_propose_failure(cz_settings: Settings, monkeypatch) -> None:
    refreshed: list[bool] = []

    async def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("model padł")

    async def refresh(self: Any) -> None:
        refreshed.append(True)

    monkeypatch.setattr(pairs, "propose", boom)
    monkeypatch.setattr("lidl.budget_feed.BudgetFeed.refresh", refresh)
    with TestClient(create_app(cz_settings)) as c:
        import asyncio

        asyncio.run(c.app.state.sync._after())  # type: ignore[attr-defined]
    assert refreshed


def test_unknown_name_creates_no_row(cz_settings: Settings) -> None:
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        _seed(c)
        c.post("/kraje/para", data={"country": "CZ", "foreign_name": "śmieć", "action": "reject"})
        assert _status(c, "rejected") == []
