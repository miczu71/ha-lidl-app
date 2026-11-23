"""Most do Diety (E2): `GET /api/v1/purchases` — agregat per produkt, token Bearer, poza Ingressem."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings
from lidl.web.app import create_app

TOKEN = "t0ken-for-tests"
TODAY = date(2026, 11, 22)


def _ticket(tid: str, day: str) -> dict[str, object]:
    return {
        "id": tid,
        "date": f"{day}T10:00:00+00:00",
        "totalAmount": 20.0,
        "savings": 0.0,
        "couponsUsedCount": 0,
        "articlesCount": 1,
        "storeCode": "PL0001",
    }


def _seed(h: History) -> None:
    h.upsert_tickets(
        "a", [_ticket("t1", "2026-02-03"), _ticket("t2", "2026-11-20"), _ticket("t4", "2026-11-20")]
    )
    h.upsert_tickets("b", [_ticket("t3", "2026-10-01")], chain="biedronka")
    h.upsert_tickets("a", [_ticket("t0", "2025-01-01")])  # poza oknem 12 miesięcy
    h.save_detail(
        "t1",
        "S",
        ParsedReceipt(
            items=[ReceiptItem("111", "Twaróg klinek", 1, 6.0, 6.0), ReceiptItem("900", "Płyn", 1, 9.0, 9.0)]
        ),
    )
    h.save_detail("t2", "S", ParsedReceipt(items=[ReceiptItem("111", "Twaróg klinek półtł.", 2, 6.5, 13.0)]))
    h.save_detail("t4", "S", ParsedReceipt(items=[ReceiptItem("111", "Twaróg klinek półtł.", 1, 6.5, 6.5)]))
    # stary kod `n:` połączony z 111 (scalony kod) + produkt biedronkowy
    h.save_detail(
        "t3", "S", ParsedReceipt(items=[ReceiptItem("n:0001", "Twaróg klinek półtł.", 1, 5.0, 5.0)])
    )
    h.save_detail("t0", "S", ParsedReceipt(items=[ReceiptItem("777", "Dawny", 1, 1.0, 1.0)]))
    h.set_merges([("n:0001", "111")])
    h.set_categories([("900", "drugstore")], "manual")


@pytest.fixture
def prod(tmp_path: Path) -> Iterator[TestClient]:
    s = Settings(
        data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share", api_token=TOKEN
    )
    with TestClient(create_app(s)) as c:
        _seed(c.app.state.history)  # type: ignore[attr-defined]
        yield c


def test_aggregates_per_product(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed(h)
    by = {p["code"]: p for p in h.purchase_aggregates(12, TODAY)}
    assert set(by) == {"111", "900"}  # 777 poza oknem
    milk = by["111"]
    assert milk["purchases"] == 3 and milk["spend"] == 30.5
    assert (milk["first"], milk["last"]) == ("2026-02-03", "2026-11-20")
    assert milk["dates"] == ["2026-02-03", "2026-10-01", "2026-11-20"]
    assert milk["name"] == "Twaróg klinek półtł." and milk["chain"] == "lidl"
    assert set(milk["names"]) == {"Twaróg klinek", "Twaróg klinek półtł."}
    assert milk["category"] == "food"
    assert by["900"]["category"] == "drugstore"


def test_spend_is_net_of_discount(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _seed(h)
    h._db.execute("UPDATE items SET discount = -2 WHERE ticket_id = 't4'")
    by = {p["code"]: p for p in h.purchase_aggregates(12, TODAY)}
    assert by["111"]["spend"] == 28.5


@pytest.mark.parametrize(
    ("today", "months", "first_day", "excluded_day"),
    [
        (date(2026, 3, 31), 1, "2026-02-28", "2026-02-27"),  # przycięcie dnia do końca lutego
        (date(2026, 1, 15), 1, "2025-12-15", "2025-12-14"),  # przeskok roku, granica włączna
    ],
)
def test_window_boundaries(
    tmp_path: Path, today: date, months: int, first_day: str, excluded_day: str
) -> None:
    h = History(tmp_path / "h.db")
    h.upsert_tickets(
        "a", [_ticket("in", first_day), _ticket("out", excluded_day), _ticket("end", today.isoformat())]
    )
    for tid in ("in", "out", "end"):
        h.save_detail(tid, "S", ParsedReceipt(items=[ReceiptItem("5", "Mleko", 1, 3.0, 3.0)]))
    (p,) = h.purchase_aggregates(months, today)
    assert p["dates"] == sorted({first_day, today.isoformat()})


def test_aggregates_exclude_foreign_items(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h._db.execute(
        "INSERT INTO tickets (id, account, day, total, savings, coupons_used)"
        " VALUES ('f', 'a', '2026-11-01', 1, 0, 0)"
    )
    h._db.execute(
        "INSERT INTO foreign_items (ticket_id, line, art_id, name, quantity, unit_price, total, discount)"
        " VALUES ('f', 1, 'CZ:1', 'Obcy', 1, 1, 1, 0)"
    )
    assert h.purchase_aggregates(12, TODAY) == []


def test_requires_token(prod: TestClient) -> None:
    assert prod.get("/api/v1/purchases").status_code == 401
    r = prod.get("/api/v1/purchases", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert prod.get("/api/v1/purchases", headers={"Authorization": TOKEN}).status_code == 401


def test_disabled_without_configured_token(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share")
    with TestClient(create_app(s)) as c:
        r = c.get("/api/v1/purchases", headers={"Authorization": "Bearer "})
        assert r.status_code == 503
        assert c.get("/api/v1/purchases").status_code == 503


def test_ok_with_token_and_no_store(tmp_path: Path) -> None:
    s = Settings(
        data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share", api_token=TOKEN
    )
    with TestClient(create_app(s)) as c:
        h: History = c.app.state.history  # type: ignore[attr-defined]
        recent = (date.today() - timedelta(days=3)).isoformat()
        h.upsert_tickets("a", [_ticket("r1", recent)])
        h.save_detail("r1", "S", ParsedReceipt(items=[ReceiptItem("5", "Chleb", 1, 4.0, 4.0)]))
        r = c.get("/api/v1/purchases?months=6", headers={"Authorization": f"Bearer {TOKEN}"})
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        body = r.json()
        assert body["months"] == 6 and "generated_at" in body
        assert [p["code"] for p in body["products"]] == ["5"]
        assert body["products"][0]["dates"] == [recent]


def test_other_paths_still_ingress_only(prod: TestClient) -> None:
    assert prod.get("/produkty").status_code == 403
    assert prod.get("/produkty", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 403


def _unit_history(tmp_path: Path, items: list[tuple[str, str, ReceiptItem]]) -> History:
    h = History(tmp_path / "u.db")
    h.upsert_tickets("a", [_ticket(tid, day) for tid, day, _ in items])
    for tid, _, it in items:
        h.save_detail(tid, "S", ParsedReceipt(items=[it]))
    return h


def test_unit_price_weight_item_per_kg_with_discount(tmp_path: Path) -> None:
    it = ReceiptItem("w1", "Jabłka", 0.5, 8.0, 4.0, discount=-1.0, is_weight=True)
    h = _unit_history(tmp_path, [("w", "2026-11-01", it)])
    (p,) = h.purchase_aggregates(12, TODAY)
    assert p["unit_price"] == 6.0 and p["last_unit_price"] == 6.0 and p["is_weight"] is True


def test_unit_price_packaged_per_piece(tmp_path: Path) -> None:
    h = _unit_history(tmp_path, [("p", "2026-11-01", ReceiptItem("p1", "Mleko", 2, 3.0, 6.0))])
    (p,) = h.purchase_aggregates(12, TODAY)
    assert p["unit_price"] == 3.0 and p["is_weight"] is False


def test_unit_price_median_robust_to_one_promo(tmp_path: Path) -> None:
    items = [
        ("a", "2026-09-01", ReceiptItem("m", "Masło", 1, 6.0, 6.0)),
        ("b", "2026-10-01", ReceiptItem("m", "Masło", 1, 6.0, 6.0)),
        ("c", "2026-11-01", ReceiptItem("m", "Masło", 1, 6.0, 6.0, discount=-3.0)),
    ]
    (p,) = _unit_history(tmp_path, items).purchase_aggregates(12, TODAY)
    assert p["unit_price"] == 6.0 and p["last_unit_price"] == 3.0


def test_unit_price_skips_zero_quantity(tmp_path: Path) -> None:
    items = [
        ("a", "2026-10-01", ReceiptItem("z", "Kaucja", 0, 0.0, 0.0, discount=-1.0)),
        ("b", "2026-11-01", ReceiptItem("z", "Kaucja", 0, 0.0, 0.0)),
    ]
    (p,) = _unit_history(tmp_path, items).purchase_aggregates(12, TODAY)
    assert p["unit_price"] is None and p["last_unit_price"] is None and p["is_weight"] is None
    assert p["purchases"] == 2


def test_unit_fields_additive_and_in_api(prod: TestClient) -> None:
    r = prod.get("/api/v1/purchases", headers={"Authorization": f"Bearer {TOKEN}"})
    milk = next(p for p in r.json()["products"] if p["code"] == "111")
    assert {"unit_price", "last_unit_price", "is_weight"} <= set(milk)
    assert milk["spend"] == 30.5 and milk["purchases"] == 3
