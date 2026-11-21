from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from lidl import shelf_prices
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusError
from lidl.history import History
from lidl.shelf_prices import MAX_EANS, parse_price, refresh, targets

NOW = datetime(2026, 11, 21, 7, 0, 0)
EAN_A = "5900000000001"
EAN_B = "5900000000002"
EAN_C = "5900000000003"

PROMO = {
    "price": "7.49",
    "regular_price": "12.99",
    "omnibus_price": "9.99",
    "omnibus_type": "x",
    "is_promotion": True,
    "promotion_valid_period": "od 16.11 do 22.11",
    "discount": "42",
    "price_tag_info": "TERAZ TANIEJ",
    "unit": "szt",
    "unit_price": ["59,92 zł/kg"],
    "name": "Produkt X",
    "only_with_biedronka_card": False,
}
PLAIN = {
    "price": "3.20",
    "regular_price": "3.20",
    "omnibus_price": "0.00",
    "is_promotion": False,
    "promotion_valid_period": None,
    "discount": None,
    "unit": "szt",
    "unit_price": [],
    "name": "Produkt Y",
    "only_with_biedronka_card": True,
}


async def _no_sleep(_: float) -> None:
    return None


class FakeApi:
    def __init__(
        self, prices: dict[str, Any] | None = None, errors: dict[str, Exception] | None = None
    ) -> None:
        self.prices = prices or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, str]] = []

    async def product_price(self, store: str, ean: str) -> Any:
        self.calls.append((store, ean))
        if ean in self.errors:
            raise self.errors[ean]
        return self.prices[ean]


def _history(tmp_path: Path) -> History:
    return History(tmp_path / "h.db")


def test_parse_price_promotion_with_omnibus() -> None:
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None
    assert (row.store, row.ean, row.price, row.regular, row.omnibus) == ("0001", EAN_A, 7.49, 12.99, 9.99)
    assert row.promo_from == "od 16.11 do 22.11" and row.promo_to is None
    assert row.is_promotion is True and row.card_only is False
    assert row.fetched_at == NOW.isoformat(timespec="seconds")


def test_parse_price_zero_omnibus_means_none_and_card_flag() -> None:
    row = parse_price("0001", EAN_B, PLAIN, NOW)
    assert row is not None
    assert row.omnibus is None and row.is_promotion is False and row.card_only is True
    assert row.promo_from is None


def test_parse_price_empty_price_is_no_price() -> None:
    assert parse_price("0001", EAN_B, {**PROMO, "price": ""}, NOW) is None


@pytest.mark.parametrize("data", [["x"], {"name": "bez cen"}, None])
def test_parse_price_unknown_shape_raises(data: Any) -> None:
    with pytest.raises(ValueError):
        parse_price("0001", EAN_B, data, NOW)


def test_targets_watched_and_approved_pairs_without_weighted(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"n:{EAN_B}", True)
    h.set_watched("b:12,345kg", True)  # ważone — pomijamy
    h.set_watched("n:abc", True)  # nie EAN — pomijamy
    h.set_watched(f"c:{EAN_C}", True)  # kupon, nie produkt
    insert = (
        "INSERT INTO chain_pairs (b_art_id, status, lidl_art_id, source, candidates)"
        " VALUES (?, ?, ?, 'ean', '[]')"
    )
    h._db.execute(insert, (EAN_C, "approved", "1"))
    h._db.execute(insert, ("5900000000009", "proposed", "2"))
    h._db.commit()
    assert targets(h) == [EAN_A, EAN_B, EAN_C]


def test_targets_are_capped_at_limit(tmp_path: Path) -> None:
    h = _history(tmp_path)
    for i in range(MAX_EANS + 10):
        h.set_watched(f"b:{5900000000000 + i}", True)
    result = targets(h)
    assert MAX_EANS == 60
    assert len(result) == MAX_EANS
    assert result == sorted(result)


async def test_refresh_saves_reads_and_logs_ok(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"b:{EAN_B}", True)
    api = FakeApi({EAN_A: PROMO, EAN_B: {**PROMO, "price": ""}})
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = await refresh(h, api, "0001", sleep=sleep)  # type: ignore[arg-type]
    assert api.calls == [("0001", EAN_A), ("0001", EAN_B)]
    assert sleeps == [1.0]  # między zapytaniami, nie przed pierwszym
    assert result.ok == 2 and result.failed == 0 and result.skipped == 0
    assert [r.ean for r in h.shelf_list("0001")] == [EAN_A]
    events = h._db.execute("SELECT area, level FROM events WHERE area = 'shelf'").fetchall()
    assert events == [("shelf", "ok")]


async def test_refresh_404_is_skipped_and_503_failed_others_continue(tmp_path: Path) -> None:
    h = _history(tmp_path)
    for ean in (EAN_A, EAN_B, EAN_C):
        h.set_watched(f"b:{ean}", True)
    api = FakeApi(
        {EAN_C: PLAIN},
        {EAN_A: LidlPlusError("http_404", status=404), EAN_B: LidlPlusError("http_503", status=503)},
    )
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert api.calls == [("0001", EAN_A), ("0001", EAN_B), ("0001", EAN_C)]
    assert result.skipped == 1 and result.failed == 1 and result.ok == 1
    assert len(result.errors) == 1 and EAN_B in result.errors[0]
    assert [r.ean for r in h.shelf_list("0001")] == [EAN_C]
    assert h._db.execute("SELECT level FROM events WHERE area = 'shelf'").fetchall() == [("error",)]


async def test_refresh_bad_shape_is_failure_and_keeps_old_row(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None
    h.shelf_replace("0001", [row])
    result = await refresh(h, FakeApi({EAN_A: {"zupelnie": "inny"}}), "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.failed == 1 and result.ok == 0
    assert [r.price for r in h.shelf_list("0001")] == [7.49]


async def test_refresh_auth_error_stops_and_propagates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"b:{EAN_B}", True)
    api = FakeApi({EAN_A: PROMO}, {EAN_B: LidlPlusAuthError("unauthorized", status=401)})
    with pytest.raises(LidlPlusAuthError):
        await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert api.calls == [("0001", EAN_A), ("0001", EAN_B)]
    assert [r.ean for r in h.shelf_list("0001")] == [EAN_A]  # odczyt przed błędem zostaje


def test_module_exports_refresh_result() -> None:
    assert shelf_prices.RefreshResult().ok == 0


async def test_refresh_empty_price_clears_old_row(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None
    h.shelf_replace("0001", [row])
    result = await refresh(h, FakeApi({EAN_A: {**PROMO, "price": ""}}), "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.failed == 0
    assert h.shelf_list("0001") == []
