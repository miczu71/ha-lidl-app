from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from lidl import shelf_prices
from lidl.accounts import Account
from lidl.client.exceptions import LidlPlusAuthError, LidlPlusCannotConnect, LidlPlusError
from lidl.history import History, ShelfPrice
from lidl.shelf_prices import (
    MAX_EANS,
    ShelfOffer,
    parse_price,
    parse_promo_end,
    parse_stock,
    refresh,
    refresh_morning,
    shelf_offers,
    targets,
)

NOW = datetime(2026, 11, 21, 7, 0, 0)
TODAY = date(2026, 11, 21)
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
        self,
        prices: dict[str, Any] | None = None,
        errors: dict[str, Exception] | None = None,
        stock: dict[str, Any] | None = None,
        stock_errors: dict[str, Exception] | None = None,
    ) -> None:
        self.prices = prices or {}
        self.errors = errors or {}
        self.stock = stock or {}
        self.stock_errors = stock_errors or {}
        self.calls: list[tuple[str, str]] = []
        self.stock_calls: list[tuple[str, str]] = []

    async def product_price(self, store: str, ean: str) -> Any:
        self.calls.append((store, ean))
        if ean in self.errors:
            raise self.errors[ean]
        return self.prices[ean]

    async def product_stock(self, store: str, ean: str) -> Any:
        self.stock_calls.append((store, ean))
        if ean in self.stock_errors:
            raise self.stock_errors[ean]
        return self.stock.get(ean, {"coverage": 3})


def _history(tmp_path: Path) -> History:
    return History(tmp_path / "h.db")


def test_parse_price_promotion_with_omnibus() -> None:
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None
    assert (row.store, row.ean, row.price, row.regular, row.omnibus) == ("0001", EAN_A, 7.49, 12.99, 9.99)
    assert row.promo_from == "od 16.11 do 22.11" and row.promo_to == "2026-11-22"  # E30.4: koniec jako ISO
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
    api = FakeApi(
        {EAN_A: PROMO, EAN_B: {**PROMO, "price": ""}},
        stock_errors={EAN_B: LidlPlusError("http_404", status=404)},
    )
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = await refresh(h, api, "0001", sleep=sleep)  # type: ignore[arg-type]
    assert api.calls == [("0001", EAN_A), ("0001", EAN_B)]
    assert sleeps == [1.0, 1.0, 1.0]  # przed każdym zapytaniem poza pierwszym (cena, stan, cena)
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
        stock_errors={EAN_A: LidlPlusError("http_404", status=404)},
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
    stock_404 = {EAN_A: LidlPlusError("http_404", status=404)}
    api = FakeApi({EAN_A: {**PROMO, "price": ""}}, stock_errors=stock_404)
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.failed == 0
    assert h.shelf_list("0001") == []


@pytest.mark.parametrize(
    ("text", "today", "expected"),
    [
        ("od 16.11 do 22.11", TODAY, date(2026, 11, 22)),
        ("od 28.12 do 03.01", date(2026, 12, 30), date(2027, 1, 3)),  # rok przełomu grudzień → styczeń
        ("od 01.01 do 05.01", date(2026, 1, 2), date(2026, 1, 5)),
        (None, TODAY, None),
        ("", TODAY, None),
        ("bez daty", TODAY, None),
        ("od 16.11 do 31.02", TODAY, None),  # nieistniejąca data
    ],
)
def test_parse_promo_end(text: str | None, today: date, expected: date | None) -> None:
    assert parse_promo_end(text, today) == expected


def _shelf_row(
    ean: str,
    price: float | None,
    regular: float | None,
    omnibus: float | None = None,
    *,
    promo: bool = True,
    card: bool = False,
    period: str | None = None,
) -> ShelfPrice:
    return ShelfPrice(
        "0001", ean, price, regular, omnibus, period, None, card, promo, NOW.isoformat(timespec="seconds")
    )


def test_shelf_offers_promotion_below_omnibus(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.shelf_replace("0001", [_shelf_row(EAN_A, 7.49, 12.99, 9.99, period="od 16.11 do 22.11")])
    assert shelf_offers(h, "0001", TODAY) == [ShelfOffer(EAN_A, 7.49, 9.99, date(2026, 11, 22), False)]


def test_shelf_offers_without_omnibus_compares_with_regular(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"n:{EAN_A}", True)
    h.shelf_replace("0001", [_shelf_row(EAN_A, 3.20, 3.50, card=True)])
    assert shelf_offers(h, "0001", TODAY) == [ShelfOffer(EAN_A, 3.20, 3.50, None, True)]


def test_shelf_offers_skips_non_promotion_price_not_below_and_missing_prices(tmp_path: Path) -> None:
    h = _history(tmp_path)
    for ean in (EAN_A, EAN_B, EAN_C):
        h.set_watched(f"b:{ean}", True)
    h.shelf_replace(
        "0001",
        [
            _shelf_row(EAN_A, 3.20, 3.50, promo=False),  # nie promocja
            _shelf_row(EAN_B, 9.99, 12.99, 9.99),  # cena = Omnibus, nie „poniżej”
            _shelf_row(EAN_C, None, 12.99, 9.99),  # „DRUGI ZA x zł” — brak ceny
        ],
    )
    assert shelf_offers(h, "0001", TODAY) == []


def test_shelf_offers_skips_unwatched_ean_and_missing_reference(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.shelf_replace(
        "0001",
        [
            _shelf_row(EAN_B, 3.20, 3.50),  # nieobserwowany
            _shelf_row(EAN_A, 3.20, None, None),  # brak Omnibusa i regular
        ],
    )
    assert shelf_offers(h, "0001", TODAY) == []


class FakeChainStore:
    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    def list(self) -> list[Account]:
        return self._accounts


class FakeService:
    def __init__(self, accounts: list[Account], api: Any = None) -> None:
        self.store = FakeChainStore(accounts)
        self.api = api
        self.asked: list[str] = []

    async def chain_api(self, slug: str) -> Any:
        self.asked.append(slug)
        return self.api


BDR = Account("bdr-1", "Biedronka 1", refresh_token="r", chain="biedronka")


async def test_refresh_morning_without_store_setting_does_nothing(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    service = FakeService([BDR])
    assert await refresh_morning(h, service) is None  # type: ignore[arg-type]
    assert service.asked == []


async def test_refresh_morning_without_biedronka_account_does_nothing(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_setting("biedronka_store", "0001")
    h.set_watched(f"b:{EAN_A}", True)
    service = FakeService([Account("osoba-1", "Osoba 1", refresh_token="r")])
    assert await refresh_morning(h, service) is None  # type: ignore[arg-type]
    assert service.asked == []


async def test_refresh_morning_reads_store_with_first_connected_biedronka_account(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_setting("biedronka_store", "0001")
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({EAN_A: PROMO})
    service = FakeService([BDR], api)
    result = await refresh_morning(h, service)  # type: ignore[arg-type]
    assert result is not None and result.ok == 1
    assert service.asked == ["bdr-1"]
    assert api.calls == [("0001", EAN_A)]
    assert [r.ean for r in h.shelf_list("0001")] == [EAN_A]


async def test_refresh_network_failure_stops_and_keeps_earlier_reads(tmp_path: Path) -> None:
    h = _history(tmp_path)
    for ean in (EAN_A, EAN_B, EAN_C):
        h.set_watched(f"b:{ean}", True)
    api = FakeApi({EAN_A: PROMO}, {EAN_B: LidlPlusCannotConnect("timeout")})
    with pytest.raises(LidlPlusCannotConnect):
        await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert api.calls == [("0001", EAN_A), ("0001", EAN_B)]  # EAN_C już nie, bez czekania na martwym łączu
    assert [r.ean for r in h.shelf_list("0001")] == [EAN_A]


async def test_refresh_all_404_logs_warn_not_ok(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi(
        {},
        {EAN_A: LidlPlusError("http_404", status=404)},
        stock_errors={EAN_A: LidlPlusError("http_404", status=404)},
    )
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 0 and result.skipped == 1
    assert h._db.execute("SELECT level FROM events WHERE area = 'shelf'").fetchall() == [("warn",)]


def test_shelf_offers_skips_ended_promotion(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    row = parse_price("0001", EAN_A, {**PROMO, "promotion_valid_period": "od 02.11 do 08.11"}, NOW)
    assert row is not None
    h.shelf_replace("0001", [row])
    assert shelf_offers(h, "0001", TODAY) == []  # koniec 8.11 < 21.11


@pytest.mark.parametrize(
    ("coverage", "expected"), [(0, "no"), (1, "low"), (2, "low"), (3, "yes"), (7, "yes")]
)
def test_parse_stock_maps_coverage_levels(coverage: int, expected: str) -> None:
    assert parse_stock({"coverage": coverage, "code": "6715"}) == expected


@pytest.mark.parametrize(
    "data", [{"coverage": True}, {"coverage": "3"}, {"coverage": -1}, {"code": "6715"}, None, ["x"]]
)
def test_parse_stock_unknown_shape_raises(data: Any) -> None:
    with pytest.raises(ValueError, match="nieznany kształt"):
        parse_stock(data)


def _stock_only(store: str, ean: str, stock: str | None) -> ShelfPrice:
    return ShelfPrice(store, ean, None, None, None, None, None, False, False, "t0", stock)


async def test_refresh_saves_stock_next_to_price(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({EAN_A: PROMO}, stock={EAN_A: {"coverage": 0}})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.stock_failed == 0 and result.back_in_stock == []
    assert api.stock_calls == [("0001", EAN_A)]
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(7.49, "no")]


async def test_refresh_stock_404_is_unknown_not_error(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({EAN_A: PROMO}, stock_errors={EAN_A: LidlPlusError("http_404", status=404)})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.stock_failed == 0 and result.errors == [] and result.failed == 0
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(7.49, None)]


async def test_refresh_stock_error_keeps_previous_stock_and_counts(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.shelf_replace("0001", [_stock_only("0001", EAN_A, "low")])
    api = FakeApi({EAN_A: PROMO}, stock_errors={EAN_A: LidlPlusError("http_503", status=503)})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.failed == 0 and result.stock_failed == 1
    assert len(result.errors) == 1 and "(stan)" in result.errors[0] and EAN_A in result.errors[0]
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(7.49, "low")]
    assert h._db.execute("SELECT level FROM events WHERE area = 'shelf'").fetchall() == [("error",)]


async def test_refresh_stock_bad_shape_counts_as_stock_failure(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({EAN_A: PROMO}, stock={EAN_A: {"zupelnie": "inny"}})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.stock_failed == 1 and result.failed == 0
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(7.49, None)]


async def test_refresh_stock_auth_error_propagates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({EAN_A: PROMO}, stock_errors={EAN_A: LidlPlusAuthError("unauthorized", status=401)})
    with pytest.raises(LidlPlusAuthError):
        await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]


async def test_refresh_empty_price_with_known_stock_saves_stock_only_row(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.shelf_replace("0001", [parse_price("0001", EAN_A, PROMO, NOW)])  # type: ignore[list-item]
    api = FakeApi({EAN_A: {**PROMO, "price": ""}}, stock={EAN_A: {"coverage": 0}})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.skipped == 0
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(None, "no")]


async def test_refresh_price_404_with_known_stock_is_ok_not_skipped(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({}, {EAN_A: LidlPlusError("http_404", status=404)}, stock={EAN_A: {"coverage": 3}})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.ok == 1 and result.skipped == 0 and result.failed == 0
    assert [(r.price, r.stock) for r in h.shelf_list("0001")] == [(None, "yes")]


async def test_refresh_price_failure_skips_stock_query(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    api = FakeApi({}, {EAN_A: LidlPlusError("http_503", status=503)})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.failed == 1 and api.stock_calls == []


async def test_back_in_stock_on_no_to_yes_or_low_for_watched(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"b:{EAN_B}", True)
    h.shelf_replace("0001", [_stock_only("0001", EAN_A, "no"), _stock_only("0001", EAN_B, "no")])
    api = FakeApi({EAN_A: PROMO, EAN_B: PROMO}, stock={EAN_A: {"coverage": 3}, EAN_B: {"coverage": 1}})
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.back_in_stock == [EAN_A, EAN_B]


async def test_back_in_stock_not_for_first_read_yes_to_yes_or_unwatched(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)  # pierwszy odczyt, brak poprzedniego wiersza
    h.set_watched(f"b:{EAN_B}", True)  # poprzednio „yes”
    h._db.execute(
        "INSERT INTO chain_pairs (b_art_id, status, lidl_art_id, source, candidates)"
        " VALUES (?, 'approved', '1', 'ean', '[]')",
        (EAN_C,),
    )
    h._db.commit()
    h.shelf_replace("0001", [_stock_only("0001", EAN_B, "yes"), _stock_only("0001", EAN_C, "no")])
    api = FakeApi(
        {EAN_A: PROMO, EAN_B: PROMO, EAN_C: PROMO},
        stock={EAN_A: {"coverage": 3}, EAN_B: {"coverage": 3}, EAN_C: {"coverage": 3}},
    )
    result = await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert result.back_in_stock == []  # EAN_C nieobserwowany, więc bez powiadomienia
    assert [r.stock for r in h.shelf_list("0001") if r.ean == EAN_C] == ["yes"]


def test_shelf_offer_carries_stock_from_row(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None
    h.shelf_replace("0001", [replace(row, stock="no")])
    offers = shelf_offers(h, "0001", TODAY)
    assert [(o.ean, o.stock) for o in offers] == [(EAN_A, "no")]


async def test_refresh_persists_pending_back_in_finally_even_on_auth_error(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"b:{EAN_B}", True)
    h.shelf_replace("0001", [_stock_only("0001", EAN_A, "no"), _stock_only("0001", EAN_B, "no")])
    api = FakeApi(
        {EAN_A: PROMO},
        stock={EAN_A: {"coverage": 3}},
        errors={EAN_B: LidlPlusAuthError("unauthorized", status=401)},
    )
    with pytest.raises(LidlPlusAuthError):
        await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert shelf_prices.pending_back(h) == [EAN_A]


async def test_refresh_pending_back_merges_without_duplicates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_setting(shelf_prices.BACK_KEY, json.dumps([EAN_B]))
    h.shelf_replace("0001", [_stock_only("0001", EAN_A, "no")])
    api = FakeApi({EAN_A: PROMO}, stock={EAN_A: {"coverage": 2}})
    await refresh(h, api, "0001", sleep=_no_sleep)  # type: ignore[arg-type]
    assert shelf_prices.pending_back(h) == sorted([EAN_A, EAN_B])
    assert h.get_setting(shelf_prices.BACK_KEY) == json.dumps(sorted([EAN_A, EAN_B]))


def test_pending_back_empty_or_bad_json_is_empty_list(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert shelf_prices.pending_back(h) == []
    h.set_setting(shelf_prices.BACK_KEY, "{nie json")
    assert shelf_prices.pending_back(h) == []
    h.set_setting(shelf_prices.BACK_KEY, json.dumps({"a": 1}))
    assert shelf_prices.pending_back(h) == []


def test_clear_back_removes_only_given_eans(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_setting(shelf_prices.BACK_KEY, json.dumps([EAN_A, EAN_B]))
    shelf_prices.clear_back(h, [EAN_A])
    assert shelf_prices.pending_back(h) == [EAN_B]
    shelf_prices.clear_back(h, [EAN_B])
    assert shelf_prices.pending_back(h) == []


def test_parse_price_stores_promo_end_as_iso_date() -> None:
    row = parse_price("0001", EAN_A, PROMO, NOW)
    assert row is not None and row.promo_to == "2026-11-22"
    plain = parse_price("0001", EAN_A, PLAIN, NOW)
    assert plain is not None and plain.promo_to is None


def test_shelf_offers_reads_promo_to_and_falls_back_to_period(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.set_watched(f"b:{EAN_A}", True)
    h.set_watched(f"b:{EAN_B}", True)
    row_a = replace(_shelf_row(EAN_A, 7.49, 12.99, 9.99), promo_to="2026-11-25")
    row_b = replace(_shelf_row(EAN_B, 7.49, 12.99, 9.99, period="od 16.11 do 22.11"), promo_to="zle")
    h.shelf_replace("0001", [row_a, row_b])
    assert {o.ean: o.end for o in shelf_offers(h, "0001", TODAY)} == {
        EAN_A: date(2026, 11, 25),
        EAN_B: date(2026, 11, 22),
    }


async def test_refresh_morning_without_store_logs_warn_event(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert await refresh_morning(h, FakeService([BDR])) is None  # type: ignore[arg-type]  # brak sklepu
    h.set_setting("biedronka_store", "0001")
    assert await refresh_morning(h, FakeService([])) is None  # type: ignore[arg-type]  # brak konta
    events = [(e.area, e.level, e.summary) for e in h.events(datetime(2000, 1, 1), area="shelf")]
    assert sorted(events) == sorted(
        [
            ("shelf", "warn", "Ceny półkowe Biedronki: pominięto — brak sklepu"),
            ("shelf", "warn", "Ceny półkowe Biedronki: pominięto — brak połączonego konta"),
        ]
    )
