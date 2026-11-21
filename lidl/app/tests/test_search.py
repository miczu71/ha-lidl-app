from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from lidl.chain_savings import Saving
from lidl.coupons import Coupon
from lidl.history import History
from lidl.promotions import Promotion
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.search import BiedronkaSearchCache, search_all

TODAY = date(2026, 11, 21)
EAN = "5900000000001"


def _ticket(tid: str, day: str) -> dict[str, Any]:
    return {
        "articlesCount": 2,
        "id": tid,
        "date": f"{day}T10:00:00+00:00",
        "totalAmount": 12.0,
        "savings": 0.0,
        "couponsUsedCount": 0,
        "storeCode": "PL0001",
    }


def _receipt(*items: tuple[str, str, float, float]) -> ParsedReceipt:
    return ParsedReceipt(items=[ReceiptItem(a, n, q, p, round(q * p, 2)) for a, n, q, p in items])


def _history(tmp_path: Path) -> History:
    """Dwa paragony: Biedronka „b:<EAN>” (2×) i Lidl „1” (1×), plus kupon i oferta Biedronki."""
    h = History(tmp_path / "h.db")
    h.upsert_tickets("osoba-1", [_ticket("t1", "2026-11-10"), _ticket("t2", "2026-11-12")])
    h.save_detail(
        "t1", "Sklep X", _receipt((f"b:{EAN}", "Masło extra 200 g", 1, 4.99), ("1", "Masło Lidl", 1, 7.0))
    )
    h.save_detail("t2", "Sklep X", _receipt((f"b:{EAN}", "Masło extra 200 g", 1, 4.99)))
    return h


def _offer(name: str, ean: str | None, price: float) -> Saving:
    extra: dict[str, Any] = {"ean": ean} if ean else {}
    return Saving("offer", f"o-{name}", name, price, 5.99, "2026-11-01", "2026-11-30", extra)


def _coupon(pid: str, title: str, end_year: int) -> Coupon:
    return Coupon(
        coupon_id=f"c{pid}",
        promotion_id=pid,
        section="",
        title=title,
        discount="-2 zł",
        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
        valid_to=datetime(end_year, 1, 1, tzinfo=UTC),
        article_ids=(),
        activated=False,
    )


def test_empty_query_returns_nothing(tmp_path: Path) -> None:
    assert search_all(_history(tmp_path), "  ", today=TODAY) == []


def test_bought_hits_carry_chain_ean_and_purchases(tmp_path: Path) -> None:
    got = search_all(_history(tmp_path), "masło", today=TODAY)
    bought = [h for h in got if h.kind == "bought"]
    by_chain = {h.chain: h for h in bought}
    assert by_chain["biedronka"].ean == EAN
    assert by_chain["biedronka"].purchases == 2
    assert by_chain["biedronka"].last_date == "2026-11-12"
    assert by_chain["biedronka"].price == 4.99
    assert by_chain["lidl"].ean is None
    assert by_chain["lidl"].purchases == 1
    assert [h.kind for h in got][:2] == ["bought", "bought"]
    assert got[0].purchases >= got[1].purchases


def test_offer_joins_bought_by_ean_without_duplicate(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.savings_replace("a", {"offer"}, [_offer("Masło extra 200 g", EAN, 3.99)])
    got = search_all(h, "masło", today=TODAY)
    same = [x for x in got if x.ean == EAN]
    assert len(same) == 1
    assert same[0].kind == "bought"
    assert same[0].until == "2026-11-30"
    assert same[0].price == 3.99


def test_offer_without_purchase_is_its_own_hit(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.savings_replace("a", {"offer"}, [_offer("Mleko UHT", None, 2.49)])
    got = search_all(h, "mleko", today=TODAY)
    assert [(x.kind, x.chain, x.name, x.price, x.until) for x in got] == [
        ("offer", "biedronka", "Mleko UHT", 2.49, "2026-11-30")
    ]


def test_promo_joins_bought_by_key_or_stands_alone(tmp_path: Path) -> None:
    h = _history(tmp_path)
    promos = [
        Promotion("1", "Masło Lidl", "-30%", date(2026, 11, 20), date(2026, 11, 25)),
        Promotion("9", "Masło z gazetki", "-20%", date(2026, 11, 20), date(2026, 11, 22)),
        Promotion("8", "Masło wygasłe", "-50%", date(2026, 10, 1), date(2026, 10, 31)),
    ]
    got = search_all(h, "masło", today=TODAY, promos=promos)
    lidl = [x for x in got if x.chain == "lidl"]
    assert [(x.kind, x.key, x.until) for x in lidl] == [
        ("bought", "1", "2026-11-25"),
        ("promo", "9", "2026-11-22"),
    ]


def test_coupon_active_only(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.save_coupons("a", [_coupon("1", "Masło kupon", 2099), _coupon("2", "Masło stary", 2020)], "t1")
    got = search_all(h, "masło", today=TODAY)
    coupons = [x for x in got if x.kind == "coupon"]
    assert [(x.name, x.until, x.chain) for x in coupons] == [("Masło kupon", "2099-01-01", "lidl")]


def test_catalog_skips_known_names_and_dedups(tmp_path: Path) -> None:
    h = _history(tmp_path)
    remote = [
        {"name": "Masło  extra 200 g", "sap_product_number": "111", "unit": "szt"},
        {"name": "Masło Gouda 300 g", "sap_product_number": "222", "unit": "szt"},
        {"name": "masło gouda 300 g", "sap_product_number": "333", "unit": "szt"},
        {"name": "Sałata masłowa", "sap_product_number": "444", "unit": "szt"},
    ]
    got = search_all(h, "masło", today=TODAY, remote=remote)
    catalog = [x for x in got if x.kind == "catalog"]
    assert [(x.name, x.key, x.chain, x.ean, x.price) for x in catalog] == [
        ("Masło Gouda 300 g", "222", "biedronka", None, None),
        ("Sałata masłowa", "444", "biedronka", None, None),
    ]


def test_order_is_bought_offer_promo_coupon_catalog_and_limit(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.savings_replace("a", {"offer"}, [_offer("Masło oferta", None, 3.0)])
    h.save_coupons("a", [_coupon("1", "Masło kupon", 2099)], "t1")
    promos = [Promotion("9", "Masło promo", "-20%", date(2026, 11, 20), date(2026, 11, 22))]
    remote = [{"name": "Masło katalog", "sap_product_number": "5", "unit": "szt"}]
    full = search_all(h, "masło", today=TODAY, promos=promos, remote=remote)
    assert [x.kind for x in full] == ["bought", "bought", "offer", "promo", "coupon", "catalog"]
    assert len(search_all(h, "masło", today=TODAY, promos=promos, remote=remote, limit=3)) == 3


class _FakeApi:
    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    async def product_search(self, query: str) -> list[dict[str, Any]]:
        self.calls.append(query)
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[no-any-return]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def test_cache_hits_within_ttl_and_refetches_after() -> None:
    clock = _Clock()
    cache = BiedronkaSearchCache(ttl=600, now=clock)
    api = _FakeApi([[{"name": "Masło"}], [{"name": "Masło 2"}]])
    assert await cache.names(api, "Masło") == [{"name": "Masło"}]
    assert await cache.names(api, "masło") == [{"name": "Masło"}]  # ta sama fraza po składaniu
    assert len(api.calls) == 1
    clock.t = 601
    assert await cache.names(api, "masło") == [{"name": "Masło 2"}]
    assert len(api.calls) == 2


async def test_cache_does_not_store_errors_and_skips_short_queries() -> None:
    cache = BiedronkaSearchCache(ttl=600, now=_Clock())
    api = _FakeApi([RuntimeError("boom"), [{"name": "Chleb"}]])
    try:
        await cache.names(api, "chleb")
    except RuntimeError:
        pass
    assert await cache.names(api, "chleb") == [{"name": "Chleb"}]
    assert len(api.calls) == 2
    assert await cache.names(api, "ab") == []
    assert len(api.calls) == 2
