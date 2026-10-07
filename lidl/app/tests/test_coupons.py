from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from lidl.client.exceptions import LidlPlusAuthError, LidlPlusError
from lidl.coupons import CouponRunner, parse_coupons
from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem

NOW = datetime(2026, 10, 7, 5, 0, tzinfo=UTC)
PAST, FUTURE, LATER = "2026-10-04T22:00:01Z", "2026-10-08T22:00:00Z", "2026-10-10T21:59:59Z"


def _promo(
    pid: str,
    title: str,
    codes: list[str],
    *,
    cid: str | None = None,
    start: str = PAST,
    end: str = LATER,
    active: bool = False,
) -> dict[str, Any]:
    return {
        "id": cid or pid,
        "promotionId": pid,
        "title": title,
        "discount": {"title": "-30%"},
        "validity": {"start": start, "end": end},
        "isActivated": active,
        "articleIds": codes,
    }


def _payload(**sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sections": [{"name": name, "promotions": promos} for name, promos in sections.items()]}


class FakeSource:
    """Lista kuponów + aktywacja; `instance` symuluje egzemplarz tworzony po pierwszej nieudanej próbie."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.activations: list[str] = []
        self.fail: dict[str, LidlPlusError] = {}
        self.instance: dict[str, str] = {}  # promotionId -> nowe id po pierwszej próbie
        self.list_calls = 0

    async def promotions(self, slug: str) -> dict[str, Any]:
        self.list_calls += 1
        return self.payload

    async def activate(self, slug: str, coupon_id: str) -> None:
        self.activations.append(coupon_id)
        if coupon_id in self.fail:
            raise self.fail[coupon_id]
        for section in self.payload["sections"]:
            for p in section["promotions"]:
                if p["id"] == coupon_id and p["promotionId"] in self.instance:
                    p["id"] = self.instance.pop(p["promotionId"])
                    raise LidlPlusError("http_412", status=412)


def _history(tmp_path: Path) -> History:
    """Produkt 111 kupowany regularnie (3 paragony w ostatnim roku), 222 też, ale odznaczony."""
    h = History(tmp_path / "h.db")
    days = [(date(2026, 10, 7) - timedelta(days=d)).isoformat() for d in (5, 40, 80)]
    h.upsert_tickets("osoba-1", [{"id": f"t{i}", "date": f"{d}T10:00:00+00:00"} for i, d in enumerate(days)])
    for i in range(3):
        h.save_detail(
            f"t{i}",
            "S",
            ParsedReceipt(
                items=[ReceiptItem("111", "Produkt A", 1, 2, 2), ReceiptItem("222", "Produkt B", 1, 3, 3)]
            ),
        )
    h.set_auto_activate("222", False)
    return h


def _runner(source: FakeSource, history: History, now: datetime = NOW) -> CouponRunner:
    async def no_sleep(_: float) -> None:
        return None

    return CouponRunner(source, history, sleep=no_sleep, now=lambda: now)


def test_parse_keeps_only_all_stores_and_ssc() -> None:
    payload = _payload(
        SSC=[_promo("g1", "Rabat od zakupów", [])],
        AllStores=[_promo("p1", "Produkt A", ["111"])],
        OtherStores=[_promo("p2", "Inny sklep", ["111"])],
        OnlineShop=[_promo("p3", "Online", ["111"])],
    )
    assert [(c.section, c.promotion_id) for c in parse_coupons(payload)] == [
        ("SSC", "g1"),
        ("AllStores", "p1"),
    ]


async def test_selects_generic_and_matching_skips_rest(tmp_path: Path) -> None:
    source = FakeSource(
        _payload(
            SSC=[_promo("g1", "Rabat od zakupów", [])],
            AllStores=[
                _promo("cat", "Cała kategoria", ["999", "111", "888"]),
                _promo("off", "Odznaczony produkt", ["222"]),
                _promo("other", "Obcy produkt", ["555"]),
                _promo("soon", "Nadchodzący", ["111"], start=FUTURE),
                _promo("gone", "Wygasły", ["111"], end="2026-10-06T21:59:59Z"),
                _promo("done", "Już aktywny", ["111"], active=True),
            ],
        )
    )
    result = await _runner(source, _history(tmp_path)).run("osoba-1", dry_run=False)
    assert source.activations == ["g1", "cat"]
    assert [(a.title, a.status, a.valid_to) for a in result] == [
        ("Rabat od zakupów", "activated", "2026-10-10"),
        ("Cała kategoria", "activated", "2026-10-10"),
    ]


async def test_dry_run_sends_nothing_and_marks_would(tmp_path: Path) -> None:
    history = _history(tmp_path)
    source = FakeSource(_payload(AllStores=[_promo("p1", "Produkt A", ["111"])]))
    result = await _runner(source, history).run("osoba-1", dry_run=True)
    assert source.activations == [] and [a.status for a in result] == ["would"]
    assert [(c["promotion_id"], c["status"]) for c in history.account_coupons("osoba-1")] == [("p1", "would")]


async def test_two_step_activation_retries_with_new_instance_id(tmp_path: Path) -> None:
    history = _history(tmp_path)
    source = FakeSource(_payload(AllStores=[_promo("p1", "Produkt A", ["111"])]))
    source.instance["p1"] = "01a1-nowe"
    result = await _runner(source, history).run("osoba-1", dry_run=False)
    assert source.activations == ["p1", "01a1-nowe"]
    assert [a.status for a in result] == ["activated"]
    saved = history.account_coupons("osoba-1")[0]
    assert (saved["coupon_id"], saved["status"], saved["activated"]) == ("01a1-nowe", "activated", 1)


async def test_failed_coupon_does_not_stop_the_rest(tmp_path: Path) -> None:
    source = FakeSource(_payload(SSC=[_promo("g1", "Rabat 1", []), _promo("g2", "Rabat 2", [])]))
    source.fail["g1"] = LidlPlusError("http_412", status=412)
    result = await _runner(source, _history(tmp_path)).run("osoba-1", dry_run=False)
    assert [(a.title, a.status) for a in result] == [("Rabat 1", "failed"), ("Rabat 2", "activated")]


async def test_rate_limit_stops_the_run(tmp_path: Path) -> None:
    source = FakeSource(_payload(SSC=[_promo("g1", "Rabat 1", []), _promo("g2", "Rabat 2", [])]))
    source.fail["g1"] = LidlPlusError("http_429", status=429)
    with pytest.raises(LidlPlusError):
        await _runner(source, _history(tmp_path)).run("osoba-1", dry_run=False)
    assert source.activations == ["g1"]


async def test_saved_list_follows_current_coupons(tmp_path: Path) -> None:
    history = _history(tmp_path)
    source = FakeSource(
        _payload(AllStores=[_promo("p1", "Produkt A", ["111"]), _promo("x", "Obcy", ["555"])])
    )
    await _runner(source, history).run("osoba-1", dry_run=False)
    source.payload = _payload(AllStores=[_promo("p1", "Produkt A", ["111"], active=True)])
    await _runner(source, history, NOW + timedelta(days=1)).run("osoba-1", dry_run=False)
    saved = history.account_coupons("osoba-1")
    assert [(c["promotion_id"], c["status"], c["activated"]) for c in saved] == [("p1", "activated", 1)]


async def test_failures_refetch_the_list_only_once(tmp_path: Path) -> None:
    source = FakeSource(_payload(SSC=[_promo(f"g{i}", f"Rabat {i}", []) for i in range(3)]))
    source.instance.update({"g0": "01a1-a", "g2": "01a1-c"})
    source.fail["g1"] = LidlPlusError("http_412", status=412)
    result = await _runner(source, _history(tmp_path)).run("osoba-1", dry_run=False)
    assert source.list_calls == 2
    assert source.activations == ["g0", "g1", "g2", "01a1-a", "01a1-c"]
    assert [a.status for a in result] == ["activated", "failed", "activated"]


async def test_new_flag_reports_each_decision_once(tmp_path: Path) -> None:
    history = _history(tmp_path)
    source = FakeSource(_payload(AllStores=[_promo("p1", "Produkt A", ["111"])]))
    first = await _runner(source, history).run("osoba-1", dry_run=True)
    second = await _runner(source, history, NOW + timedelta(days=1)).run("osoba-1", dry_run=True)
    third = await _runner(source, history, NOW + timedelta(days=2)).run("osoba-1", dry_run=False)
    assert [(a.status, a.new) for a in first + second + third] == [
        ("would", True),
        ("would", False),
        ("activated", True),
    ]


async def test_run_all_collects_per_account_and_skips_failing_one(tmp_path: Path) -> None:
    source = FakeSource(_payload(AllStores=[_promo("p1", "Produkt A", ["111"])]))
    runner = _runner(source, _history(tmp_path))
    original = source.promotions

    async def promotions(slug: str) -> dict[str, Any]:
        if slug == "osoba-2":
            raise LidlPlusAuthError("unauthorized")
        return await original(slug)

    source.promotions = promotions  # type: ignore[method-assign]
    result = await runner.run_all([("osoba-2", "Osoba 2"), ("osoba-1", "Osoba 1")], dry_run=True)
    assert list(result) == ["Osoba 1"] and [a.title for a in result["Osoba 1"]] == ["Produkt A"]
