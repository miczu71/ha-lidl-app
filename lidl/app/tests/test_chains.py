"""Zakładka „Sieci” (E28.4.2): zatwierdzanie par produktów Biedronka → Lidl."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem

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
    assert 'href="/sieci"' in client.get("/kupony").text
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
