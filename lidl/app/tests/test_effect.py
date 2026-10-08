from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lidl.coupons import parse_coupons
from lidl.history import ADDON_START, History
from lidl.receipt_html import ParsedReceipt, ReceiptItem

TODAY = date(2026, 12, 1)  # okno 30 dni nie nachodzi na okres sprzed add-onu
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)  # dla testów statusów kuponów


def _ticket(h: History, tid: str, day: date, *items: ReceiptItem, account: str = "osoba-1") -> None:
    h.upsert_tickets(account, [{"id": tid, "date": f"{day.isoformat()}T10:00:00+00:00"}])
    h.save_detail(tid, "S", ParsedReceipt(items=list(items)))


def _item(art_id: str, coupon: float = 0.0, promo: float = 0.0) -> ReceiptItem:
    """Rabaty na paragonie są ujemne; `discount` obejmuje kupon i promocję."""
    return ReceiptItem(art_id, "Produkt", 1, 10, 10, discount=coupon + promo, coupon=coupon)


def test_effect_compares_last_30_days_with_the_pre_addon_average(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _ticket(h, "now1", TODAY - timedelta(days=3), _item("1", coupon=-30.0, promo=-5.0))
    _ticket(h, "now2", TODAY - timedelta(days=29), _item("1", coupon=-20.0))
    _ticket(h, "old", TODAY - timedelta(days=30), _item("1", coupon=-99.0))  # poza oknem 30 dni
    _ticket(h, "base", ADDON_START - timedelta(days=100), _item("1", coupon=-73.0, promo=-36.5))
    _ticket(h, "too_old", ADDON_START - timedelta(days=366), _item("1", coupon=-500.0))
    e = h.coupon_effect(TODAY)
    assert e.coupons == 50.0 and e.promotions == 5.0
    assert e.coupons_before == 6.0 and e.promotions_before == 3.0  # 73 / 365 * 30, 36,5 / 365 * 30
    assert e.delta == 44.0 and e.delta_pct == 733.3


def test_effect_without_a_baseline_has_no_percentage(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _ticket(h, "now", TODAY - timedelta(days=1), _item("1", coupon=-12.0))
    e = h.coupon_effect(TODAY)
    assert (e.coupons, e.coupons_before, e.delta, e.delta_pct) == (12.0, 0.0, 12.0, None)


def test_effect_on_an_empty_database_is_zero(tmp_path: Path) -> None:
    e = History(tmp_path / "h.db").coupon_effect(TODAY)
    assert (e.coupons, e.promotions, e.coupons_before, e.delta, e.delta_pct) == (0.0, 0.0, 0.0, 0.0, None)


def _promo(pid: str, codes: list[str], *, start: str, end: str, active: bool = True) -> dict[str, object]:
    return {
        "id": pid,
        "promotionId": pid,
        "title": f"Kupon {pid}",
        "discount": {"title": "-30%"},
        "validity": {"start": start, "end": end},
        "isActivated": active,
        "articleIds": codes,
    }


def _coupons(h: History, account: str, promos: list[dict[str, object]], seen: str = "t1") -> None:
    payload = {"sections": [{"name": "AllStores", "promotions": promos}]}
    h.save_coupons(account, parse_coupons(payload), seen)


START, END = "2026-10-12T10:00:00+00:00", "2026-10-18T10:00:00+00:00"  # ważny 12.10–18.10, przed NOW
LATER_END = "2026-10-25T10:00:00+00:00"


def _status(h: History, pid: str) -> str:
    return next(c.status for c in h.activated_coupons(NOW) if c.title == f"Kupon {pid}")


def test_activated_coupon_statuses(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _ticket(h, "t-used", date(2026, 10, 14), _item("111", coupon=-3.0))
    _coupons(
        h,
        "osoba-1",
        [
            _promo("used", ["111", "999"], start=START, end=END),
            _promo("lost", ["222"], start=START, end=END),
            _promo("pending", ["222"], start=START, end=LATER_END),
            _promo("nodata", [], start=START, end=END),
            _promo("inactive", ["111"], start=START, end=END, active=False),
        ],
    )
    assert _status(h, "used") == "used"
    assert _status(h, "lost") == "lost"
    assert _status(h, "pending") == "pending"
    assert _status(h, "nodata") == "unknown"
    assert [c.title for c in h.activated_coupons(NOW)].count("Kupon inactive") == 0


def test_coupon_is_used_only_by_a_matching_receipt_of_the_same_account_in_the_window(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _ticket(h, "other-account", date(2026, 10, 14), _item("111", coupon=-3.0), account="osoba-2")
    _ticket(h, "before-window", date(2026, 10, 10), _item("111", coupon=-3.0))
    _ticket(h, "after-window", date(2026, 10, 19), _item("111", coupon=-3.0))
    _ticket(h, "no-coupon", date(2026, 10, 14), _item("111"))  # kupiony bez rabatu kuponowego
    _coupons(h, "osoba-1", [_promo("p", ["111"], start=START, end=END)])
    assert _status(h, "p") == "lost"
    _ticket(h, "hit", date(2026, 10, 18), _item("111", coupon=-3.0))  # ostatni dzień ważności
    assert _status(h, "p") == "used"


def test_archived_activated_coupons_stay_on_the_list(tmp_path: Path) -> None:
    h = History(tmp_path / "h.db")
    _coupons(h, "osoba-1", [_promo("p", ["222"], start=START, end=END)], seen="t1")
    _coupons(h, "osoba-1", [], seen="t2")  # kupon znika z listy Lidla
    assert h.account_coupons("osoba-1") == []
    assert [(c.title, c.status) for c in h.activated_coupons(NOW)] == [("Kupon p", "lost")]
