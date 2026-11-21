"""Zakładka „Sieci” (E28.4.2): zatwierdzanie par produktów Biedronka → Lidl."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from lidl.history import ChainPair, History, PlPrice, ShelfPrice
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.web.chains import compare

HX = {"hx-request": "true"}
EAN = "5900000000017"


def _hist(client: TestClient) -> History:
    return client.app.state.history  # type: ignore[attr-defined,no-any-return]


def _lidl(client: TestClient) -> None:
    h = _hist(client)
    h.upsert_tickets("a", [{"id": "l-1", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 13.0}])
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


def _both(client: TestClient) -> str:
    """Lidl + Biedronka; zwraca kod mleka Lidla. Biedronka: b:111 Mleko UHT, b:EAN Jogurt, b:222 Chleb."""
    _lidl(client)
    h = _hist(client)
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
    mleko = next(c.art_id for c in h.chain_catalog("lidl") if c.name == "Mleko 1l")
    h.chain_pair_propose("b:111", [mleko])
    return mleko


def _pairs(client: TestClient) -> dict[str, tuple[str, str | None, str | None]]:
    return {p.b_art_id: (p.status, p.lidl_art_id, p.source) for p in _hist(client).chain_pair_list()}


def _post(client: TestClient, b: str, action: str, lidl: str = "", **kw: dict[str, str]) -> int:
    data = {"b_art_id": b, "action": action}
    if lidl:
        data["lidl_art_id"] = lidl
    return client.post("/sieci/para", data=data, **kw).status_code


def test_page_404_with_single_chain(client: TestClient) -> None:
    _lidl(client)
    assert client.get("/sieci").status_code == 404
    assert client.get("/sieci/szukaj?q=mleko").status_code == 404
    assert _post(client, "b:111", "reject") == 404
    assert 'href="/sieci"' not in client.get("/kupony").text  # chip tylko przy ≥2 sieciach


def test_page_lists_proposal_and_pending(client: TestClient) -> None:
    mleko = _both(client)
    r = client.get("/sieci")
    assert r.status_code == 200
    assert "Mleko 1l UHT" in r.text
    assert "Chleb" in r.text  # bez wiersza: do ręcznego sparowania
    assert f'value="{mleko}"' in r.text  # kandydat AI jako przycisk
    # wyzwalacz wyszukiwarki musi słuchać pola szukania, nie pierwszego (ukrytego) inputu formularza
    assert "from:find input[type=search]" in r.text
    assert 'href="/sieci"' in client.get("/ceny").text
    assert "\\/sieci" in client.get("/kupony").text  # regex głębokiego linku z Budżetu


def test_approve_manual_pair_and_undo(client: TestClient) -> None:
    mleko = _both(client)
    assert _post(client, "b:111", "approve", mleko) == 303
    assert _pairs(client)["b:111"] == ("approved", mleko, "manual")
    page = client.get("/sieci").text
    assert "Mleko 1l UHT" in page and "Mleko 1l" in page
    assert _post(client, "b:111", "undo") == 303
    assert _pairs(client)["b:111"][0] == "proposed"


def test_approve_without_row_creates_pair(client: TestClient) -> None:
    mleko = _both(client)
    assert _post(client, "b:222", "approve", mleko) == 303  # „Chleb” nie ma propozycji
    assert _pairs(client)["b:222"] == ("approved", mleko, "manual")


def test_approve_rejects_foreign_ids(client: TestClient) -> None:
    mleko = _both(client)
    _post(client, "b:111", "approve", "b:222")  # kod Biedronki zamiast Lidla
    _post(client, "b:111", "approve", "nie-ma-w-katalogu")
    _post(client, "b:999", "approve", mleko)  # nieznany produkt Biedronki
    _post(client, "b:999", "reject")
    pairs = _pairs(client)
    assert pairs["b:111"][0] == "proposed"
    assert "b:999" not in pairs


def test_reject_and_undo(client: TestClient) -> None:
    _both(client)
    assert _post(client, "b:222", "reject") == 303
    assert _pairs(client)["b:222"][0] == "rejected"
    assert "Bez odpowiednika" in client.get("/sieci").text
    assert _post(client, "b:222", "undo") == 303
    assert _pairs(client)["b:222"][0] == "proposed"


def test_undo_ean_pair_becomes_rejected(client: TestClient) -> None:
    _both(client)
    h = _hist(client)
    lidl = next(c.art_id for c in h.chain_catalog("lidl") if c.name == "Jogurt 150g")
    h.chain_pair_approve(f"b:{EAN}", lidl, "ean")
    assert "EAN" in client.get("/sieci").text
    assert _post(client, f"b:{EAN}", "undo") == 303
    assert _pairs(client)[f"b:{EAN}"][0] == "rejected"


def test_search_only_lidl_catalog(client: TestClient) -> None:
    _both(client)
    r = client.get("/sieci/szukaj", params={"b": "b:222", "q": "mleko"}, headers=HX)
    assert r.status_code == 200
    assert "Mleko 1l" in r.text and "UHT" not in r.text  # produkty Lidla, nie Biedronki
    assert "Nic nie pasuje" in client.get("/sieci/szukaj", params={"b": "b:222", "q": "zzz"}).text


def test_htmx_returns_partial(client: TestClient) -> None:
    mleko = _both(client)
    r = client.post(
        "/sieci/para", data={"b_art_id": "b:111", "action": "approve", "lidl_art_id": mleko}, headers=HX
    )
    assert r.status_code == 200
    assert 'id="sieci-body"' in r.text and "<html" not in r.text


def test_bad_pair_shows_a_message_instead_of_silent_ok(client: TestClient) -> None:
    mleko = _both(client)
    assert (
        _post(client, "b:111", "approve", "b:222", headers=HX) == 200
    )  # kod Biedronki zamiast produktu Lidla
    r = client.post(
        "/sieci/para", data={"b_art_id": "b:111", "action": "approve", "lidl_art_id": "b:222"}, headers=HX
    )
    assert "Nie zapisano pary" in r.text and _pairs(client)["b:111"][0] == "proposed"
    r = client.post("/sieci/para", data={"b_art_id": "b:nope", "action": "undo"}, headers=HX)
    assert "Nie zapisano pary" in r.text  # pary nie ma
    r = client.post("/sieci/para", data={"b_art_id": "b:111", "action": "approve", "lidl_art_id": "b:222"})
    assert r.status_code == 303 and r.headers["location"].endswith("/sieci?m=pair_bad")
    assert "Nie zapisano pary" in client.get("/sieci", params={"m": "pair_bad"}).text
    assert (
        "Nie zapisano pary"
        not in client.post(
            "/sieci/para", data={"b_art_id": "b:111", "action": "approve", "lidl_art_id": mleko}, headers=HX
        ).text
    )


# --- compare (E28.4.3): today = 2026-11-19, okno 90 d od 2026-08-21, okno 365 d od 2025-11-19 ---
TODAY = date(2026, 11, 19)


def _pair(b: str = "b:1", lidl: str = "l:1", status: str = "approved") -> ChainPair:
    return ChainPair(b, "Prod B", status, lidl, "Prod L", "manual", [])


def _row(
    art: str,
    day: str,
    price: float,
    paid: float | None = None,
    qty: float = 1,
    name: str = "Chleb",
    w: bool = False,
) -> PlPrice:
    chain = "biedronka" if art.startswith("b:") else "lidl"
    return PlPrice(
        art, name, date.fromisoformat(day), price, qty, w, price * qty if paid is None else paid, chain
    )


def test_compare_piece_even_median_and_savings_both_ways() -> None:
    # Lidl: 4,00 (10-01), 6,00 x2 zapłacone 11,00 (11-01): last 6,00, mediana (4+6)/2 = 5,00.
    # Biedronka: 5,00 (10-10), 7,00 (11-10): last 7,00, mediana 6,00. Różnica 6/5-1 = 20%, tańszy Lidl.
    # Oszczędność: zakupy Lidla vs med B 6,00: 4,00 i 11/2=5,50 < 6,00 -> 0.
    # Zakupy B vs med L 5,00: 5,00 nie więcej, 7,00 -> 1 x (7-5) = 2,00.
    rows = [
        _row("l:1", "2026-10-01", 4.0),
        _row("l:1", "2026-11-01", 6.0, paid=11.0, qty=2),
        _row("b:1", "2026-10-10", 5.0),
        _row("b:1", "2026-11-10", 7.0),
    ]
    c = compare([_pair()], rows, {"b:1": "food"}, TODAY)
    (r,) = c.rows
    assert (r.unit, r.wide) == ("szt", False)
    assert (r.lidl.last, r.lidl.median, r.biedronka.last, r.biedronka.median) == (6.0, 5.0, 7.0, 6.0)
    assert (r.cheaper, r.diff_pct) == ("lidl", pytest.approx(20.0))
    assert c.savings == {"lidl": 0.0, "biedronka": pytest.approx(2.0)}
    assert c.savings_total == pytest.approx(2.0)


def test_compare_odd_median() -> None:
    # Lidl 4,00, 6,00, 5,00 -> mediana 5,00 (środkowa po posortowaniu), last = 5,00 (ostatni z datą).
    rows = [
        _row("l:1", "2026-09-01", 4.0),
        _row("l:1", "2026-10-01", 6.0),
        _row("l:1", "2026-11-01", 5.0),
        _row("b:1", "2026-11-02", 5.0),
    ]
    (r,) = compare([_pair()], rows, {}, TODAY).rows
    assert (r.lidl.median, r.lidl.last) == (5.0, 5.0)
    assert (r.cheaper, r.diff_pct) == ("", 0.0)


def test_compare_weighted_kg() -> None:
    # Obie ważone: Lidl 10,00/kg (0,5 kg, 5,00 zł), Biedronka 12,00/kg (0,25 kg, 3,00 zł). Różnica 20%.
    # Zakup B: 3,00/0,25 = 12,00 > med L 10,00 -> 0,25 x 2,00 = 0,50. Zakup Lidla: med B 12 > 10 -> 0.
    rows = [
        _row("l:1", "2026-11-01", 10.0, paid=5.0, qty=0.5, w=True),
        _row("b:1", "2026-11-02", 12.0, paid=3.0, qty=0.25, w=True),
    ]
    c = compare([_pair()], rows, {}, TODAY)
    assert c.rows[0].unit == "kg"
    assert c.rows[0].diff_pct == pytest.approx(20.0)
    assert c.savings_total == pytest.approx(0.5)
    assert c.savings["lidl"] == 0.0


def test_compare_mixed_weighted_and_piece_is_incomparable() -> None:
    # Lidl ważone 10,00 zł/kg, Biedronka na sztuki 4,00 zł: zł/kg ≠ zł/szt -> „Bez ceny”, oszczędność 0.
    rows = [
        _row("l:1", "2026-11-01", 10.0, paid=5.0, qty=0.5, w=True),
        _row("b:1", "2026-11-02", 4.0),
    ]
    c = compare([_pair()], rows, {}, TODAY)
    assert c.rows == []
    assert len(c.no_price) == 1
    assert c.savings_total == 0.0


def test_compare_pack_size_500g_vs_1kg() -> None:
    # Lidl „Ser 500g” 4,00 -> 8,00/kg; Biedronka „Ser 1kg” 10,00 -> 10,00/kg; różnica 25%, tańszy Lidl.
    # Zakup B: 2 szt. za 18,00 -> 9,00/kg, ilość 2 kg; med L 8,00 -> 2 x (9-8) = 2,00.
    rows = [
        _row("l:1", "2026-11-01", 4.0, name="Ser 500g"),
        _row("b:1", "2026-11-02", 10.0, paid=18.0, qty=2, name="Ser 1kg"),
    ]
    c = compare([_pair()], rows, {}, TODAY)
    (r,) = c.rows
    assert (r.unit, r.lidl.last, r.biedronka.last) == ("kg", 8.0, 10.0)
    assert (r.cheaper, r.diff_pct) == ("lidl", pytest.approx(25.0))
    assert c.savings == {"lidl": 0.0, "biedronka": pytest.approx(2.0)}


def test_compare_wide_fallback_and_no_price() -> None:
    # Lidl tylko w 2026-03/04 (poza 90 d, w 365 d): 5,00 i 7,00 -> mediana 6,00, wide; last 7,00.
    # Biedronka 6,00 (11-01) -> mediana 6,00. Zakup Lidla 7,00 > 6,00 -> 1,00; Biedronka 6,00 nie więcej.
    # Para b:2/l:2: Lidl tylko 2025-01-01 (poza 365 d) -> „Bez ceny”.
    rows = [
        _row("l:1", "2026-03-01", 5.0),
        _row("l:1", "2026-04-01", 7.0),
        _row("b:1", "2026-11-01", 6.0),
        _row("l:2", "2025-01-01", 3.0),
        _row("b:2", "2026-11-01", 3.0),
    ]
    c = compare([_pair(), _pair("b:2", "l:2")], rows, {}, TODAY)
    (r,) = c.rows
    assert r.wide and r.lidl.wide and not r.biedronka.wide
    assert (r.lidl.median, r.lidl.last, r.biedronka.median) == (6.0, 7.0, 6.0)
    assert c.savings_total == pytest.approx(1.0)
    assert [n.b_art_id for n in c.no_price] == ["b:2"]


def test_compare_ignores_unapproved_and_filters_category() -> None:
    # Pokrycie produktów: B w 365 d to b:1, b:2, b:3; w zatwierdzonych parach b:1, b:2 -> 2 z 3.
    # Wydatki 12 mies.: 4+6+10+20+30+40 = 110; pary (l:1,b:1,l:2,b:2) = 40; stary wiersz 2025-01-01 pominięty.
    rows = [
        _row("l:1", "2026-11-01", 4.0),
        _row("b:1", "2026-11-01", 6.0),
        _row("l:2", "2026-11-01", 10.0),
        _row("b:2", "2026-11-01", 20.0),
        _row("b:3", "2026-11-01", 30.0),
        _row("l:9", "2026-11-01", 40.0),
        _row("b:1", "2025-01-01", 99.0),
    ]
    pairs = [_pair(), _pair("b:2", "l:2"), _pair("b:3", "l:9", status="proposed")]
    cats = {"b:1": "food", "b:2": "kids", "b:3": "food"}
    all_ = compare(pairs, rows, cats, TODAY)
    assert [r.b_art_id for r in all_.rows] == ["b:1", "b:2"]
    assert (all_.covered_products, all_.total_products) == (2, 3)
    assert (all_.covered_spend, all_.total_spend) == (pytest.approx(40.0), pytest.approx(110.0))
    kids = compare(pairs, rows, cats, TODAY, category="kids")
    assert [r.b_art_id for r in kids.rows] == ["b:2"]
    assert (kids.covered_products, kids.total_products) == (2, 3)  # pokrycie liczone bez filtra


def test_page_comparison_shows_amounts(client: TestClient) -> None:
    mleko = _both(client)
    _hist(client).chain_pair_approve("b:111", mleko, "manual")
    # Lidl „Mleko 1l” 4,00/l, Biedronka „Mleko 1l UHT” 3,00/l: różnica 4/3-1 = 33,3%, oszczędność 1,00 zł.
    r = client.get("/sieci")
    assert r.status_code == 200
    assert "Porównanie" in r.text
    assert "+33,3%" in r.text
    assert "4,00" in r.text and "3,00" in r.text and "1,00 zł" in r.text
    assert "Bez ceny" not in r.text
    assert client.get("/sieci?kat=nonfood").status_code == 200
    assert client.get("/sieci?kat=bogus").status_code == 200


def test_compare_one_sided_pack_size_is_incomparable() -> None:
    # „Masło 200g” vs „Masło extra” (bez gramatury): cena za sztukę byłaby fałszywą oszczędnością.
    rows = [
        _row("l:1", "2026-11-01", 5.0, name="Masło extra"),
        _row("b:1", "2026-11-02", 4.0, name="Masło 200g"),
    ]
    c = compare([_pair()], rows, {}, TODAY)
    assert c.rows == [] and len(c.no_price) == 1 and c.savings_total == 0.0


def test_unknown_pair_action_is_400(client: TestClient) -> None:
    _both(client)
    assert _post(client, "b:111", "bogus") == 400


def test_restore_offered_and_works_for_rejected_ean_pair(client: TestClient) -> None:
    _both(client)
    h = _hist(client)
    lidl = next(c.art_id for c in h.chain_catalog("lidl") if c.name == "Jogurt 150g")
    h.chain_pair_approve(f"b:{EAN}", lidl, "ean")
    assert _post(client, f"b:{EAN}", "undo") == 303
    assert "Przywróć" in client.get("/sieci").text
    assert _post(client, f"b:{EAN}", "restore") == 303
    assert _pairs(client)[f"b:{EAN}"][0:2] == ("approved", lidl)


def test_pair_action_keeps_category_filter(client: TestClient) -> None:
    mleko = _both(client)
    r = client.post(
        "/sieci/para",
        data={"b_art_id": "b:111", "action": "approve", "lidl_art_id": mleko, "kat": "food"},
        headers=HX,
    )
    assert r.status_code == 200
    assert 'name="kat" value="food"' in r.text


def _shelf(ean: str, price: float, promo: bool = False, store: str = "0001") -> ShelfPrice:
    return ShelfPrice(
        store, ean, price, 5.0, 4.5, "od 16.11 do 22.11" if promo else None, None, False, promo,
        "2026-11-21T07:00:00",
    )  # fmt: skip


def test_page_comparison_shelf_column(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    assert "Dziś na półce" not in client.get("/sieci").text  # bez sklepu w ustawieniach kolumny nie ma
    h.set_setting("biedronka_store", "0001")
    assert "Dziś na półce" not in client.get("/sieci").text  # sklep jest, odczytów jeszcze nie
    h.shelf_replace("0001", [_shelf("111", 2.79, promo=True), _shelf("999", 1.0, store="0001")])
    h.shelf_replace("0002", [_shelf("111", 9.99)])  # inny sklep nie wchodzi
    text = client.get("/sieci").text
    assert "Dziś na półce" in text and "2,79" in text and "promocja" in text and "9,99" not in text
    assert "21 lis" in text  # data odczytu


def test_page_comparison_shelf_dash_for_unread_product(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    h.set_setting("biedronka_store", "0001")
    h.shelf_replace("0001", [_shelf("999", 1.0)])
    text = client.get("/sieci").text
    assert "Dziś na półce" in text and "2,79" not in text and "—" in text


def _shelf_stock(ean: str, price: float | None, stock: str | None, promo: bool = False) -> ShelfPrice:
    return ShelfPrice(
        "0001", ean, price, 5.0, 4.5, "od 16.11 do 22.11" if promo else None, None, False, promo,
        "2026-11-21T07:00:00", stock,
    )  # fmt: skip


def test_page_comparison_shelf_stock_no_tag_next_to_promo(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    h.set_setting("biedronka_store", "0001")
    h.shelf_replace("0001", [_shelf_stock("111", 2.79, "no", promo=True)])
    text = client.get("/sieci").text
    assert "brak na półce" in text and "promocja" in text and "2,79" in text


def test_page_comparison_shelf_stock_low_alone_without_price(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    h.set_setting("biedronka_store", "0001")
    h.shelf_replace("0001", [_shelf_stock("111", None, "low")])  # stan znany, cena nie
    text = client.get("/sieci").text
    assert "mało" in text and "21 lis" in text and "2,79" not in text


def test_page_comparison_shelf_stock_yes_has_no_tag(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    h.set_setting("biedronka_store", "0001")
    h.shelf_replace("0001", [_shelf_stock("111", 2.79, "yes")])
    text = client.get("/sieci").text
    assert "2,79" in text and "brak na półce" not in text and "mało" not in text


def test_page_comparison_shelf_stock_yes_without_price_says_jest(client: TestClient) -> None:
    mleko = _both(client)
    h = _hist(client)
    h.chain_pair_approve("b:111", mleko, "manual")
    h.set_setting("biedronka_store", "0001")
    h.shelf_replace("0001", [_shelf_stock("111", None, "yes")])  # stan znany, cena nie
    text = client.get("/sieci").text
    assert 'jest <span class="meta">odczyt 21 lis' in text and "2,79" not in text
