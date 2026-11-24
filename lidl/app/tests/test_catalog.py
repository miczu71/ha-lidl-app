"""Katalog cen (E6b.1): schemat v16, ingest paragonów i feedu Frisco, `/api/v1/catalog`, `/api/v1/shelf`."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lidl import catalog, frisco_feed
from lidl.history import SCHEMA_VERSION, History, ShelfPrice
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.settings import Settings
from lidl.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "frisco_feed_small.json"
TOKEN = "t0ken-for-tests"
NOW = datetime(2026, 11, 23, 3, 0)


def _ticket(tid: str, day: str) -> dict[str, Any]:
    return {
        "id": tid,
        "date": f"{day}T10:00:00+00:00",
        "totalAmount": 20.0,
        "savings": 0.0,
        "couponsUsedCount": 0,
        "articlesCount": 1,
        "storeCode": "PL0001",
    }


def _save(h: History, tid: str, day: str, *items: ReceiptItem, chain: str = "lidl") -> None:
    h.upsert_tickets("a", [_ticket(tid, day)], chain=chain)
    h.save_detail(tid, "S", ParsedReceipt(items=list(items)))


async def _fetch_fixture(dest: Path) -> None:
    shutil.copyfile(FIXTURE, dest)


def _obs(h: History, source: str | None = None) -> list[tuple[Any, ...]]:
    sql = "SELECT product_id, source, price, regular, observed_at FROM catalog_obs"
    if source:
        sql += f" WHERE source = '{source}'"
    return h._db.execute(sql + " ORDER BY id").fetchall()


def test_schema_v16_creates_tables(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    assert SCHEMA_VERSION == 17
    assert h._db.execute("PRAGMA user_version").fetchone()[0] == 17
    cols = {r[1] for r in h._db.execute("PRAGMA table_info(catalog_products)")}
    assert cols == {
        "id",
        "ean",
        "name",
        "brand",
        "size",
        "size_unit",
        "frisco_id",
        "sap",
        "lidl_art",
        "aliases",
    }
    cols = {r[1] for r in h._db.execute("PRAGMA table_info(catalog_obs)")}
    assert cols == {
        "id", "product_id", "source", "store", "price", "regular", "promo_from", "promo_to", "observed_at"
    }  # fmt: skip
    idx = [r[1] for r in h._db.execute("PRAGMA index_list(catalog_obs)")]
    assert any(h._db.execute(f"PRAGMA index_info({i})").fetchall()[0][2] == "product_id" for i in idx)


def test_migrate_v15_keeps_backup_and_adds_tables(tmp_path: Path) -> None:
    path = tmp_path / "h.db"
    h = History(path)
    h.upsert_tickets("a", [_ticket("t1", "2026-01-01")])
    del h
    db = sqlite3.connect(path)
    db.execute("DROP TABLE catalog_obs")
    db.execute("DROP TABLE catalog_products")
    db.execute("PRAGMA user_version = 15")
    db.commit()
    db.close()

    h = History(path)
    assert (tmp_path / "h.db.pre-catalog").exists()
    assert h._db.execute("PRAGMA user_version").fetchone()[0] == 17
    assert h._db.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0] == 0
    old = sqlite3.connect(tmp_path / "h.db.pre-catalog")
    assert old.execute("SELECT id FROM tickets").fetchall() == [("t1",)]
    old.close()


def test_fresh_database_makes_no_catalog_backup(tmp_path: Path) -> None:
    History(tmp_path / "h.db")
    assert not (tmp_path / "h.db.pre-catalog").exists()


def test_receipt_ingest_biedronka_by_ean_and_lidl_by_art(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _save(
        h, "b1", "2026-11-01", ReceiptItem("b:5900000000011", "Mleko", 2, 3.5, 7.0, -1.0), chain="biedronka"
    )
    _save(h, "l1", "2026-11-02", ReceiptItem("0193875", "Bagietka", 1, 2.5, 2.5))
    _save(h, "b2", "2026-11-03", ReceiptItem("b:mleko bez kodu", "Mleko luz", 1, 3.0, 3.0), chain="biedronka")
    by_ean = h._db.execute("SELECT name FROM catalog_products WHERE ean = '5900000000011'").fetchall()
    assert by_ean == [("Mleko",)]
    assert h._db.execute("SELECT name FROM catalog_products WHERE lidl_art = '0193875'").fetchall() == [
        ("Bagietka",)
    ]
    assert h._db.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0] == 2  # `b:<nazwa>` pominięte
    rows = h._db.execute(
        "SELECT p.ean, o.source, o.store, o.price, o.regular, o.observed_at FROM catalog_obs o"
        " JOIN catalog_products p ON p.id = o.product_id WHERE p.ean IS NOT NULL"
    ).fetchall()
    assert rows == [("5900000000011", "receipt", "biedronka", 3.0, 3.5, "2026-11-01")]  # (7,0 - 1,0) / 2


def test_receipt_ingest_gtin14_with_leading_zero_becomes_ean13_and_others_are_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    h = History(tmp_path / "h.db")
    with caplog.at_level("INFO", logger="lidl.catalog"):
        _save(h, "g1", "2026-11-01", ReceiptItem("b:05900000000028", "Ser", 1, 4.0, 4.0), chain="biedronka")
        _save(
            h, "g2", "2026-11-02", ReceiptItem("b:15900000000025", "Jogurt", 1, 2.0, 2.0), chain="biedronka"
        )
        _save(h, "g3", "2026-11-03", ReceiptItem("b:mleko luz", "Mleko luz", 1, 3.0, 3.0), chain="biedronka")
    assert h._db.execute("SELECT ean FROM catalog_products").fetchall() == [("5900000000028",)]
    assert caplog.text.count("pominięto 1 ") == 1  # tylko 14-cyfrowy bez wiodącego 0; `b:<nazwa>` to nie błąd


def test_receipt_ingest_dedupes_equal_price_and_is_idempotent(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    item = ("b:5900000000011", "Mleko")
    _save(h, "t1", "2026-11-01", ReceiptItem(*item, 1, 3.5, 3.5), chain="biedronka")
    _save(h, "t2", "2026-11-08", ReceiptItem(*item, 2, 3.5, 7.0), chain="biedronka")  # ta sama cena
    _save(h, "t3", "2026-11-15", ReceiptItem(*item, 1, 3.9, 3.9), chain="biedronka")  # nowa cena
    assert [(r[2], r[4]) for r in _obs(h)] == [(3.5, "2026-11-01"), (3.9, "2026-11-15")]
    assert catalog.ingest_receipts(h) == 0  # backfill po fakcie nic nie dodaje
    assert len(_obs(h)) == 2


def test_backfill_ingests_old_receipts(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _save(h, "t1", "2026-10-01", ReceiptItem("b:5900000000028", "Twaróg", 1, 5.5, 5.5), chain="biedronka")
    _save(h, "t2", "2026-11-01", ReceiptItem("b:5900000000028", "Twaróg", 1, 5.9, 5.9), chain="biedronka")
    h._db.execute("DELETE FROM catalog_obs")
    h._db.execute("DELETE FROM catalog_products")
    h._db.commit()
    assert catalog.ingest_receipts(h) == 2
    assert [r[2] for r in _obs(h)] == [5.5, 5.9]


def test_startup_backfill_runs_only_on_empty_catalog(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _save(h, "t1", "2026-10-01", ReceiptItem("b:5900000000028", "Twaróg", 1, 5.5, 5.5), chain="biedronka")
    h._db.execute("DELETE FROM catalog_obs")
    h._db.commit()
    assert catalog.backfill_receipts(h) == 1
    _save(h, "t2", "2026-10-02", ReceiptItem("b:5900000000028", "Twaróg", 1, 6.0, 6.0), chain="biedronka")
    assert catalog.backfill_receipts(h) == 0  # katalog niepusty — start nie przelicza historii od nowa


def test_backfill_is_single_transaction(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    for i in range(3):
        _save(
            h,
            f"t{i}",
            f"2026-10-0{i + 1}",
            ReceiptItem("b:5900000000028", "Twaróg", 1, 5.0 + i, 5.0 + i),
            chain="biedronka",
        )
    h._db.execute("DELETE FROM catalog_obs")
    h._db.commit()
    commits: list[int] = []
    h._db.set_trace_callback(lambda q: commits.append(1) if q.strip().upper() == "COMMIT" else None)
    assert catalog.ingest_receipts(h) == 3
    assert len(commits) == 1


async def test_frisco_ingest_from_fixture(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    res = await frisco_feed.refresh(h, _fetch_fixture, tmp_path / "catalog", now=NOW)
    assert (res.products, res.observations, res.busy) == (19, 19, False)  # 20 w pliku, jeden bez EAN
    milk = h._db.execute(
        "SELECT id, name, brand, size, size_unit, frisco_id FROM catalog_products WHERE ean = '5900000000011'"
    ).fetchone()
    assert milk[1:] == ("Mleko testowe 3,2% 1 l", "Mlekoland", 1.0, "Litre", "1000")
    promo = h._db.execute(
        "SELECT source, store, price, regular, promo_to, observed_at FROM catalog_obs WHERE product_id = ?",
        (milk[0],),
    ).fetchone()
    assert promo == ("frisco", "frisco", 2.99, 3.49, "2026-12-13T23:59:00+01:00", "2026-11-23")
    assert not list((tmp_path / "catalog").glob("*.tmp"))  # plik feedu sprzątany
    assert h.events(datetime(2026, 1, 1), area="catalog")[0].level == "ok"


async def test_frisco_reingest_adds_no_observations_and_tracks_changes(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    await frisco_feed.refresh(h, _fetch_fixture, tmp_path / "catalog", now=NOW)
    again = await frisco_feed.refresh(h, _fetch_fixture, tmp_path / "catalog", now=NOW)
    assert (again.products, again.observations) == (19, 0)
    assert len(_obs(h, "frisco")) == 19

    async def cheaper(dest: Path) -> None:
        import json

        feed = json.loads(FIXTURE.read_text())
        feed["products"][1]["price"]["price"] = 4.99
        dest.write_text(json.dumps(feed))

    changed = await frisco_feed.refresh(h, cheaper, tmp_path / "catalog", now=datetime(2026, 11, 30, 3, 0))
    assert changed.observations == 1
    assert _obs(h, "frisco")[-1][2:] == (4.99, 4.99, "2026-11-30")
    assert len(_obs(h, "frisco")) == 20


async def test_frisco_fetch_failure_is_logged_not_raised(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")

    async def boom(dest: Path) -> None:
        raise OSError("sieć")

    res = await frisco_feed.refresh(h, boom, tmp_path / "catalog", now=NOW)
    assert res.error and res.observations == 0
    assert h.events(datetime(2026, 1, 1), area="catalog")[0].level == "error"
    assert not list((tmp_path / "catalog").glob("*.tmp"))


async def test_frisco_refresh_is_not_reentrant(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    async with frisco_feed.LOCK:
        res = await frisco_feed.refresh(h, _fetch_fixture, tmp_path / "catalog", now=NOW)
    assert res.busy and res.observations == 0


def test_receipt_and_frisco_share_one_product_by_ean(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _save(h, "b1", "2026-11-01", ReceiptItem("b:5900000000011", "Mleko", 1, 2.5, 2.5), chain="biedronka")
    import asyncio

    asyncio.run(frisco_feed.refresh(h, _fetch_fixture, tmp_path / "catalog", now=NOW))
    assert h._db.execute("SELECT COUNT(*) FROM catalog_products WHERE ean = '5900000000011'").fetchone() == (
        1,
    )
    prod = {p["ean"]: p for p in h.catalog_products()}["5900000000011"]
    assert {o["source"] for o in prod["observations"]} == {"receipt", "frisco"}


@pytest.fixture
def prod(tmp_path: Path) -> Iterator[TestClient]:
    s = Settings(
        data_dir=tmp_path, log_level="info", dev=False, share_dir=tmp_path / "share", api_token=TOKEN
    )
    with TestClient(create_app(s)) as c:
        h: History = c.app.state.history  # type: ignore[attr-defined]
        _save(h, "b1", "2026-11-01", ReceiptItem("b:5900000000011", "Mleko", 1, 2.5, 2.5), chain="biedronka")
        _save(h, "b2", "2026-11-10", ReceiptItem("b:5900000000028", "Twaróg", 1, 5.0, 5.0), chain="biedronka")
        h._db.execute("UPDATE catalog_obs SET observed_at = '2026-11-10' WHERE product_id = 2")
        h._db.commit()
        yield c


def test_catalog_requires_token(prod: TestClient) -> None:
    assert prod.get("/api/v1/catalog").status_code == 401
    assert prod.get("/api/v1/catalog", headers={"Authorization": "Bearer zly"}).status_code == 401
    assert prod.get("/api/v1/shelf").status_code == 401
    assert prod.post("/api/v1/catalog/frisco/refresh").status_code == 401


def test_catalog_lists_products_with_latest_observations(prod: TestClient) -> None:
    r = prod.get("/api/v1/catalog", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert "generated_at" in body
    by = {p["ean"]: p for p in body["products"]}
    assert set(by) == {"5900000000011", "5900000000028"}
    (o,) = by["5900000000011"]["observations"]
    assert (o["source"], o["price"], o["observed_at"], o["store"]) == (
        "receipt",
        2.5,
        "2026-11-01",
        "biedronka",
    )


def test_catalog_since_and_source_filters(prod: TestClient) -> None:
    auth = {"Authorization": f"Bearer {TOKEN}"}
    since = prod.get("/api/v1/catalog", params={"since": "2026-11-05"}, headers=auth).json()
    assert [p["ean"] for p in since["products"]] == ["5900000000028"]
    none = prod.get("/api/v1/catalog", params={"source": "frisco"}, headers=auth).json()
    assert none["products"] == []
    assert prod.get("/api/v1/catalog", params={"source": "zly"}, headers=auth).status_code == 422
    assert prod.get("/api/v1/catalog", params={"since": "nie-data"}, headers=auth).status_code == 422


def test_catalog_history_returns_all_observations(prod: TestClient) -> None:
    h: History = prod.app.state.history  # type: ignore[attr-defined]
    _save(h, "b3", "2026-11-20", ReceiptItem("b:5900000000011", "Mleko", 1, 2.9, 2.9), chain="biedronka")
    auth = {"Authorization": f"Bearer {TOKEN}"}
    plain = {p["ean"]: p for p in prod.get("/api/v1/catalog", headers=auth).json()["products"]}
    assert [o["price"] for o in plain["5900000000011"]["observations"]] == [2.9]
    full = {p["ean"]: p for p in prod.get("/api/v1/catalog?history=1", headers=auth).json()["products"]}
    assert [o["price"] for o in full["5900000000011"]["observations"]] == [2.5, 2.9]


def test_shelf_joins_cache_with_catalog(prod: TestClient) -> None:
    h: History = prod.app.state.history  # type: ignore[attr-defined]
    h.shelf_replace(
        "6308",
        [
            ShelfPrice("6308", "5900000000011", 2.19, 2.49, 2.1, "2026-11-20", "2026-11-27", False, True,
                       "2026-11-22T06:00:00", "high"),
            ShelfPrice("6308", "5900009999999", 1.0, 1.0, None, None, None, False, False,
                       "2026-11-22T06:00:00", None),
        ],
    )  # fmt: skip
    h.shelf_replace(
        "1111", [ShelfPrice("1111", "5900000000028", 9.0, 9.0, None, None, None, False, False, "x", None)]
    )
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert prod.get("/api/v1/shelf", headers=auth).json()["items"] == []  # brak sklepu głównego
    h.set_setting("biedronka_store", "6308")
    body = prod.get("/api/v1/shelf", headers=auth).json()
    assert body["store"] == "6308"
    milk, unknown = body["items"]
    assert (milk["ean"], milk["price"], milk["regular"], milk["promo_to"], milk["is_promotion"]) == (
        "5900000000011", 2.19, 2.49, "2026-11-27", True
    )  # fmt: skip
    assert (milk["fetched_at"], milk["stock"]) == ("2026-11-22T06:00:00", "high")
    assert milk["product"]["name"] == "Mleko" and milk["product"]["observations"][0]["source"] == "receipt"
    assert unknown["ean"] == "5900009999999" and unknown["product"] is None
    other = prod.get("/api/v1/shelf", params={"store": "1111"}, headers=auth).json()
    assert [i["ean"] for i in other["items"]] == ["5900000000028"]


def test_frisco_ingest_skips_bad_product_and_keeps_rest(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    good = {"ean": "5900000000002", "id": "1", "name": {"pl": "Mleko"}, "price": {"price": 3.0}}
    bad_promo = {"ean": "5900000000019", "id": "2", "price": {"price": 5.0, "priceAfterPromotion": 4.0},
                 "promotions": ["tekst"]}  # fmt: skip
    clash = {"ean": "5900000000026", "id": "1", "price": {"price": 2.0}}  # frisco_id UNIQUE
    res = frisco_feed.ingest(h, [good, bad_promo, clash], "2026-11-23")
    assert res.skipped == 1 and res.products == 2
    assert len(h.catalog_products()) == 2
