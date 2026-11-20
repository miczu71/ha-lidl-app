from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lidl import chain_savings
from lidl.chain_savings import Saving
from lidl.client.exceptions import LidlPlusError
from lidl.history import History

CAROUSEL_ID = "11111111-aaaa-bbbb-cccc-222222222222"

DASHBOARD = {
    "sections": [
        {"slug": "x", "type": "Store", "param": None},
        {"slug": "biedronew", "type": "Carousels", "param": "other-id"},
        {"slug": "Just4You", "type": "Carousels", "param": CAROUSEL_ID},
    ]
}
CAROUSEL = {
    "type": "j4u",
    "items": [
        {"type": "STATIC_CONTENT", "id": "s1", "name": "banner"},
        {"type": "AD", "zone_id": 5},
        {
            "type": "SHAKEOMAT",
            "offer_type": "SHAKEOMAT",
            "offer_id": "sh-1",
            "available_from": None,
            "available_to": "2026-11-19T22:59:59Z",
        },
        {
            "type": "SINGLE_PRODUCT_PROMOTION",
            "offer_type": "WELCOME",
            "id": "of-1",
            "name": "Mleko 1l",
            "price": 3.49,
            "regular_price": 4.99,
            "start": "2026-11-19T00:00:00Z",
            "end": "2026-11-25T22:59:59Z",
            "from_shakeomat": False,
        },
    ],
}


class FakeApi:
    def __init__(self, *, coupons: Any = None, fail: set[str] | None = None) -> None:
        self._coupons = {"coupons": [], "meta": {}} if coupons is None else coupons
        self.fail = fail or set()
        self.calls: list[str] = []

    async def _do(self, name: str, value: Any) -> Any:
        self.calls.append(name)
        if name in self.fail:
            raise LidlPlusError("http_500", status=500)
        return value

    async def coupons(self) -> Any:
        return await self._do("coupons", self._coupons)

    async def dashboard(self) -> Any:
        return await self._do("dashboard", DASHBOARD)

    async def carousel(self, carousel_id: str) -> Any:
        assert carousel_id == CAROUSEL_ID
        return await self._do("carousel", CAROUSEL)


def test_parse_coupons_empty_and_garbage() -> None:
    assert chain_savings.parse_coupons({"coupons": [], "meta": {}}) == []
    assert chain_savings.parse_coupons(None) == []
    assert chain_savings.parse_coupons({"coupons": ["x", 3, {}]}) == []


def test_parse_coupons_tolerant_fields() -> None:
    data = {"coupons": [{"id": "c-1", "title": "Rabat 5 zł", "end": "2026-11-21T22:59:59Z"}]}
    [s] = chain_savings.parse_coupons(data)
    assert (s.kind, s.ext_id, s.name, s.valid_to) == ("voucher", "c-1", "Rabat 5 zł", "2026-11-21T22:59:59Z")


def test_parse_offers_skips_banners_and_keeps_shakeomat() -> None:
    rows = chain_savings.parse_offers(CAROUSEL)
    assert [(r.kind, r.ext_id) for r in rows] == [("shakeomat", "sh-1"), ("offer", "of-1")]
    offer = rows[1]
    assert (offer.name, offer.price, offer.regular_price, offer.valid_to) == (
        "Mleko 1l",
        3.49,
        4.99,
        "2026-11-25T22:59:59Z",
    )
    assert rows[0].valid_to == "2026-11-19T22:59:59Z"


def test_parse_offers_garbage() -> None:
    assert chain_savings.parse_offers(None) == []
    assert chain_savings.parse_offers({"items": "x"}) == []


@pytest.mark.asyncio
async def test_fetch_finds_just4you_carousel() -> None:
    api = FakeApi()
    result = await chain_savings.fetch(api)  # type: ignore[arg-type]
    assert result.errors == []
    assert {r.kind for r in result.rows} == {"shakeomat", "offer"}
    assert api.calls == ["coupons", "dashboard", "carousel"]


@pytest.mark.asyncio
async def test_fetch_reports_failed_part_but_keeps_other() -> None:
    api = FakeApi(coupons={"coupons": [{"id": "c-1", "title": "Rabat"}]}, fail={"dashboard"})
    result = await chain_savings.fetch(api)  # type: ignore[arg-type]
    assert [r.kind for r in result.rows] == ["voucher"]
    assert result.failed_kinds == {"offer", "shakeomat"}
    assert result.errors and "dashboard" in result.errors[0]


def test_history_replace_keeps_kinds_not_refreshed(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.savings_replace(
        "a",
        {"voucher", "offer"},
        [
            Saving("voucher", "c-1", "Rabat", None, None, None, "2026-11-21", {}),
            Saving("offer", "o-1", "Mleko", 3.0, 4.0, None, "2026-11-25", {}),
        ],
    )
    h.savings_replace("a", {"offer"}, [Saving("offer", "o-2", "Ser", 5.0, 6.0, None, "2026-11-26", {})])
    rows = h.savings_list()
    assert sorted((r.kind, r.ext_id) for r in rows) == [("offer", "o-2"), ("voucher", "c-1")]
    assert rows[0].slug == "a"


def test_history_replace_isolated_per_account(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.savings_replace("a", {"offer"}, [Saving("offer", "o-1", "A", None, None, None, None, {})])
    h.savings_replace("b", {"offer"}, [Saving("offer", "o-1", "B", None, None, None, None, {})])
    h.savings_replace("a", {"offer"}, [])
    assert [(r.slug, r.name) for r in h.savings_list()] == [("b", "B")]


def test_schema_v10_makes_backup(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "h.db"
    h = History(path)
    h.upsert_tickets("a", [{"id": "t", "date": "2026-10-01T10:00:00+00:00", "totalAmount": 1.0}])
    del h
    db = sqlite3.connect(path)
    db.execute("DROP TABLE chain_savings")
    db.execute("PRAGMA user_version = 9")
    db.commit()
    db.close()
    History(path)
    assert (tmp_path / "h.db.pre-chain-savings").exists()


class ShakeApi(FakeApi):
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        super().__init__()
        self.revealed: list[str] = []
        self.fail_ids = fail_ids or set()

    async def reveal_and_activate(self, offer_id: str) -> Any:
        if offer_id in self.fail_ids:
            raise LidlPlusError("http_409", status=409)
        self.revealed.append(offer_id)
        return {"ok": True}


def _shake_rows(h: History) -> None:
    h.savings_replace(
        "a",
        {"shakeomat"},
        [
            Saving("shakeomat", "sh-1", "Shakeomat", None, None, None, "2099-01-01T00:00:00Z", {}),
            Saving("shakeomat", "sh-old", "Shakeomat", None, None, None, "2020-01-01T00:00:00Z", {}),
            Saving("shakeomat", "sh-2", "Shakeomat", None, None, None, None, {}),
        ],
    )


async def test_shake_reveals_only_current_and_refreshes(tmp_path: Path) -> None:
    from datetime import date

    h = History(tmp_path / "h.db")
    _shake_rows(h)
    api = ShakeApi()
    result = await chain_savings.shake(h, "a", api, date(2026, 11, 19))  # type: ignore[arg-type]
    assert sorted(api.revealed) == ["sh-1", "sh-2"]
    assert (result.done, result.failed) == (2, [])
    assert "dashboard" in api.calls  # migawka odświeżona po odsłonięciu


async def test_shake_reports_failures_and_logs_event(tmp_path: Path) -> None:
    from datetime import date

    h = History(tmp_path / "h.db")
    _shake_rows(h)
    api = ShakeApi(fail_ids={"sh-1"})
    result = await chain_savings.shake(h, "a", api, date(2026, 11, 19))  # type: ignore[arg-type]
    assert result.done == 1 and len(result.failed) == 1 and "http_409" in result.failed[0]
    from datetime import datetime

    [event] = h.events(datetime(2000, 1, 1), area="daily")
    assert (event.level, event.detail["run"]) == ("error", "shakeomat")


async def test_shake_without_offer_does_nothing(tmp_path: Path) -> None:
    from datetime import date

    h = History(tmp_path / "h.db")
    api = ShakeApi()
    result = await chain_savings.shake(h, "a", api, date(2026, 11, 19))  # type: ignore[arg-type]
    assert (result.done, result.failed, api.revealed, api.calls) == (0, [], [], [])


async def test_unrecognised_shape_is_failure_and_keeps_old_rows(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    h.savings_replace("a", {"voucher"}, [Saving("voucher", "v1", "Stary", None, None, None, None, {})])

    api = FakeApi(coupons={"coupons": [{"coupon_uuid": "x", "label": "Y"}]})
    result = await chain_savings.refresh(h, "a", api)  # type: ignore[arg-type]
    assert "voucher" in result.failed_kinds
    assert [r.name for r in h.savings_list() if r.kind == "voucher"] == ["Stary"]


async def test_refresh_keeps_old_rows_of_failed_part_and_logs(tmp_path: Path) -> None:
    from datetime import datetime

    h = History(tmp_path / "h.db")
    h.savings_replace("a", {"voucher"}, [Saving("voucher", "v1", "Stary", None, None, None, None, {})])
    result = await chain_savings.refresh(h, "a", FakeApi(fail={"coupons"}))  # type: ignore[arg-type]
    assert result.failed_kinds == {"voucher"}
    assert [r.name for r in h.savings_list() if r.kind == "voucher"] == ["Stary"]
    assert [e.level for e in h.events(datetime(2000, 1, 1), area="sync")] == ["error"]
    assert h.events(datetime(2000, 1, 1), area="savings") == []  # częściowy błąd = bez znacznika świeżości


async def test_refresh_logs_snapshot_time_on_success(tmp_path: Path) -> None:
    from datetime import datetime

    h = History(tmp_path / "h.db")
    await chain_savings.refresh(h, "a", FakeApi())
    assert [e.level for e in h.events(datetime(2000, 1, 1), area="savings")] == ["ok"]


class _Acc:
    def __init__(self, slug: str, chain: str, connected: bool = True) -> None:
        self.slug, self.chain, self.connected = slug, chain, connected


class _Store:
    def __init__(self, accounts: list[_Acc]) -> None:
        self._a = accounts

    def list(self) -> list[_Acc]:
        return self._a


class _Service:
    def __init__(self, accounts: list[_Acc], bad: str) -> None:
        self.store, self._bad, self.apis = _Store(accounts), bad, {}

    async def chain_api(self, slug: str) -> Any:
        if slug == self._bad:
            raise LidlPlusError("not_supported")
        return self.apis.setdefault(slug, ShakeApi())


async def test_shake_accounts_filters_and_isolates_errors(tmp_path: Path) -> None:
    from datetime import date

    h = History(tmp_path / "h.db")
    h.savings_replace(
        "ok", {"shakeomat"}, [Saving("shakeomat", "s1", "Shakeomat", None, None, None, None, {})]
    )
    service = _Service(
        [
            _Acc("bad", "biedronka"),
            _Acc("ok", "biedronka"),
            _Acc("lidl", "lidl"),
            _Acc("off", "biedronka", False),
        ],
        bad="bad",
    )
    results = await chain_savings.shake_accounts(h, service, date(2026, 11, 19))
    assert [(r.slug, r.done, bool(r.failed)) for r in results] == [("bad", 0, True), ("ok", 1, False)]
    assert set(service.apis) == {"ok"}
