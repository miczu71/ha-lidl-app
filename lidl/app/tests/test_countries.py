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


# --- K6c: koszyk porównawczy (compare) ---------------------------------------------------------
from datetime import date  # noqa: E402

from lidl.history import PairLine, PlPrice  # noqa: E402
from lidl.web.countries import compare  # noqa: E402

D = date(2026, 10, 10)


def _line(
    country: str,
    name: str,
    art: str,
    qty: float,
    price: float,
    fx: float,
    weight: bool = False,
    day: date = D,
) -> PairLine:
    base = name.lower().split(" ")[0]
    return PairLine(country, base, art, name, day, qty, price, fx, weight)


def _pl(art: str, name: str, day: date, price: float, qty: float, weight: bool = False) -> PlPrice:
    return PlPrice(art, name, day, price, qty, weight)


def test_compare_piece_czk_weighted_pl_average() -> None:
    # CZK 0,1755: 40 CZK × 0,1755 = 7,02 zł/szt, ilość 2 → 14,04 zł
    # PL: (4,00 × 1 + 6,00 × 3) / 4 = 5,50 zł; koszt PL 2 × 5,50 = 11,00 zł; różnica 14,04 / 11 − 1 = +27,6%
    c = compare(
        [_line("CZ", "Chléb", "a", 2, 40.0, 0.1755)],
        [_pl("a", "Chleb", date(2026, 9, 1), 4.0, 1), _pl("a", "Chleb", date(2026, 9, 15), 6.0, 3)],
        {"CZ": 1},
    )
    (r,) = c.rows
    assert (r.unit, r.foreign_price, r.pl_price, r.diff_pct, r.diff) == (
        "szt",
        "7,02 zł",
        "5,50 zł",
        27.6,
        "+27,6%",
    )
    (b,) = c.baskets
    assert (b.foreign_total, b.pl_total, b.diff_pct, b.covered, b.total) == (
        "14,04 zł",
        "11,00 zł",
        27.6,
        1,
        1,
    )


def test_compare_piece_eur() -> None:
    # EUR 4,2: 2,50 × 4,2 = 10,50 zł; PL 7,00 zł → 10,5 / 7 − 1 = +50,0%
    c = compare(
        [_line("IT", "Burro", "b", 1, 2.5, 4.2)], [_pl("b", "Masło", date(2026, 9, 1), 7.0, 1)], {"IT": 1}
    )
    assert (c.rows[0].foreign_price, c.rows[0].pl_price, c.rows[0].diff) == ("10,50 zł", "7,00 zł", "+50,0%")
    assert c.baskets[0].country == "IT" and c.baskets[0].diff == "+50,0%"


def test_compare_weighted_per_kg() -> None:
    # 20 EUR/kg × 4,2 = 84 zł/kg, 0,3 kg → 25,20 zł; PL 60 zł/kg → 18,00 zł; +40,0%
    c = compare(
        [_line("IT", "Prosciutto", "p", 0.3, 20.0, 4.2, weight=True)],
        [_pl("p", "Szynka", date(2026, 9, 1), 60.0, 1.0, weight=True)],
        {"IT": 1},
    )
    r = c.rows[0]
    assert (r.unit, r.foreign_price, r.pl_price, r.diff) == ("kg", "84,00 zł", "60,00 zł", "+40,0%")
    assert (c.baskets[0].foreign_total, c.baskets[0].pl_total) == ("25,20 zł", "18,00 zł")


def test_compare_pack_size_grams_to_kg_and_basket_coverage() -> None:
    # Máslo 500 g: 50 CZK × 0,2 = 10 zł/opak. → 20 zł/kg, ilość 2 × 0,5 = 1 kg → 20,00 zł
    # PL „Masło 1 kg” 30 zł/kg → 30,00 zł; −33,3%
    # Chléb (sztuka): 14,04 vs 11,00 zł. Koszyk: 34,04 vs 41,00 → 34,04 / 41 − 1 = −17,0%
    # trzecia linia (Mléko) ma zakup PL tego samego dnia = poza oknem → „brak ceny PL”, koszyk 2 z 4
    lines = [
        _line("CZ", "Máslo 500 g", "m", 2, 50.0, 0.2),
        _line("CZ", "Chléb", "a", 2, 40.0, 0.1755),
        _line("CZ", "Mléko", "x", 1, 20.0, 0.2),
        _line("CZ", "Mléko", "x", 1, 20.0, 0.2, day=date(2026, 10, 9)),
    ]
    prices = [
        _pl("m", "Masło 1 kg", date(2026, 9, 1), 30.0, 1),
        _pl("a", "Chleb", date(2026, 9, 1), 4.0, 1),
        _pl("a", "Chleb", date(2026, 9, 15), 6.0, 3),
        _pl("x", "Mleko", D, 3.0, 1),  # ten sam dzień = poza oknem
        _pl("x", "Mleko", date(2026, 10, 11), 3.0, 1),  # po dniu zakupu
    ]
    c = compare(lines, prices, {"CZ": 4})
    by = {r.foreign_name: r for r in c.rows}
    assert (by["máslo"].unit, by["máslo"].foreign_price, by["máslo"].pl_price, by["máslo"].diff) == (
        "kg", "20,00 zł", "30,00 zł", "−33,3%",
    )  # fmt: skip
    (b,) = c.baskets
    assert (b.foreign_total, b.pl_total, b.diff, b.covered, b.total) == (
        "34,04 zł",
        "41,00 zł",
        "−17,0%",
        2,
        4,
    )
    assert [(m.name, m.lines) for m in c.missing] == [("mléko", 2)]


def test_compare_mixed_pack_units_fall_back_to_piece() -> None:
    # zagr. 1 l vs PL bez gramatury → sztuka: 5 zł (1 × 25 × 0,2) vs 4 zł → +25,0%
    c = compare(
        [_line("CZ", "Mléko 1 l", "z", 1, 25.0, 0.2)],
        [_pl("z", "Mleko", date(2026, 9, 1), 4.0, 1)],
        {"CZ": 1},
    )
    assert (c.rows[0].unit, c.rows[0].diff) == ("szt", "+25,0%")


def test_compare_empty() -> None:
    c = compare([], [], {})
    assert (c.rows, c.baskets, c.missing) == ([], [], [])


def test_page_shows_comparison_for_approved_pair(cz_settings: Settings) -> None:
    # CZ: Mléko 1 l 60 CZK × 0,2 = 12 zł/l; PL „Mleko łaciate 1 l” 4 zł/l → +200,0%, koszyk 1 z 2 pozycji
    with TestClient(create_app(cz_settings), follow_redirects=False) as c:
        mleko = _seed(c)
        assert "Zatwierdź pierwszą parę" in c.get("/kraje").text
        c.post(
            "/kraje/para",
            data={"country": "CZ", "foreign_name": "mléko", "action": "approve", "pl_art_id": mleko},
        )
        r = c.get("/kraje")
    assert r.status_code == 200
    assert "Porównanie cen" in r.text and "+200,0%" in r.text and "1 z 2 pozycji" in r.text
    assert "12,00 zł/l" in r.text and "4,00 zł/l" in r.text
