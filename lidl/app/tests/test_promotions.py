from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiohttp

from lidl.history import History
from lidl.promotions import OFFERS_URL, WEB_URL, Promotion, PromotionRunner, parse_offers, parse_web
from lidl.receipt_html import ParsedReceipt, ReceiptItem

TODAY = date(2026, 10, 8)


def _epoch(d: date, hour: int = 0) -> int:
    return int(datetime(d.year, d.month, d.day, hour).timestamp())


def _web_item(title: str, ians: list[str], percent: int | None, lidl_plus: bool = False) -> dict[str, Any]:
    window = {"validFrom": _epoch(TODAY), "validUntil": _epoch(date(2026, 10, 10), 23)}
    return {
        "gridbox": {
            "data": {
                "fullTitle": title,
                "ians": ians,
                "price": {"price": 2.99, "discount": {"percentageDiscount": percent}},
                "stockAvailability": {"badgeInfoV2": [window]},
                "lidlPlus": [{"highlightText": "-50%"}] if lidl_plus else [],
            }
        }
    }


WEB = {
    "items": [
        _web_item("Produkt A", ["111", "0000112"], 40),
        _web_item("Produkt B (kupon)", ["0000222"], None, lidl_plus=True),
        _web_item("Produkt C (bez rabatu)", ["0000333"], None),
        {"resultClass": "banner"},
    ]
}

OFFERS = {
    "offers": [
        {
            "title": "Produkt D",
            "productIds": ["0000444", "0000445"],
            "priceBox": {"largePartString": "-20%", "discountMessage": "przy zakupie 2 szt."},
            "startValidityDate": "2026-10-08T00:00:01+00:00",
            "endValidityDate": "2026-10-10T23:59:59+00:00",
        }
    ],
    "totalOffers": 1,
}


def test_parse_web_keeps_discounted_non_coupon_items_with_padded_codes() -> None:
    end = date(2026, 10, 10)
    assert parse_web(WEB) == [
        Promotion("0000111", "Produkt A", "-40%", TODAY, end),
        Promotion("0000112", "Produkt A", "-40%", TODAY, end),
    ]


def test_parse_offers_uses_local_day_and_joins_discount_text() -> None:
    p = parse_offers(OFFERS)
    assert [x.art_id for x in p] == ["0000444", "0000445"]
    assert (p[0].discount, p[0].start, p[0].end) == ("-20% przy zakupie 2 szt.", TODAY, date(2026, 10, 10))


def _history(tmp_path: Path) -> History:
    """Produkt A (0000111) i Produkt D (0000444) kupowane 3 razy w sklepie PL0001, jeden zakup w PL0002."""
    h = History(tmp_path / "h.db")
    days = ["2026-09-01", "2026-09-15", "2026-10-01", "2026-10-02"]
    h.upsert_tickets(
        "a",
        [
            {"id": f"t{n}", "date": f"{d}T10:00:00+00:00", "totalAmount": 9.0, "savings": 0,
             "couponsUsedCount": 0, "articlesCount": 2}
            for n, d in enumerate(days)
        ],
    )  # fmt: skip
    items = [
        ReceiptItem("0000111", "Produkt A", 1, 4.0, 4.0),
        ReceiptItem("0000444", "Produkt D", 1, 5.0, 5.0),
    ]
    for n in range(4):
        store = {"code": "PL0002" if n == 3 else "PL0001"}
        h.save_detail(f"t{n}", "S", ParsedReceipt(items=items if n < 3 else [], store=store))
    return h


def test_history_main_store_and_enabled_codes(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert h.main_store(TODAY) == "PL0001"
    h.set_auto_activate("0000444", False)
    assert h.enabled_codes(TODAY) == {"0000111"}


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    async def __aenter__(self) -> FakeResponse:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self, content_type: str | None = None) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses, self.urls, self.headers = responses, [], {}  # type: ignore[var-annotated]

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.urls.append(url)
        self.headers[url] = kwargs.get("headers") or {}
        return FakeResponse(self.responses[url])


async def test_runner_reads_both_sources_and_lists_our_products_active_today(tmp_path: Path) -> None:
    h = _history(tmp_path)
    store_url = OFFERS_URL.format(country="PL", store="PL0001")
    runner = PromotionRunner(FakeSession({WEB_URL: WEB, store_url: OFFERS}), h)  # type: ignore[arg-type]
    await runner.refresh()
    runner.latest.append(Promotion("0000111", "Produkt A", "-10%", date(2026, 10, 9), date(2026, 10, 10)))
    # Produkt A i Produkt D to nasze; 0000112 i 0000445 nie, a oferta D nie powtarza się dla drugiego kodu
    assert [(p.title, p.art_id) for p in runner.active(TODAY)] == [
        ("Produkt A", "0000111"),
        ("Produkt D", "0000444"),
    ]
    assert [p.art_id for p in runner.active(date(2026, 10, 10))] == ["0000111", "0000444"]  # trwa
    assert runner.active(date(2026, 10, 11)) == []  # po końcu


async def test_lidl_pl_is_asked_without_json_accept_header(tmp_path: Path) -> None:
    """`Accept: application/json` → 401 z lidl.pl (sprawdzone 2026-10-08); oferty sklepu go przyjmują."""
    h = _history(tmp_path)
    store_url = OFFERS_URL.format(country="PL", store="PL0001")
    session = FakeSession({WEB_URL: WEB, store_url: OFFERS})
    await PromotionRunner(session, h).refresh()  # type: ignore[arg-type]
    assert "Accept" not in session.headers[WEB_URL]
    assert session.headers[store_url]["Accept"] == "application/json"


async def test_runner_survives_a_failing_source(tmp_path: Path) -> None:
    h = _history(tmp_path)
    store_url = OFFERS_URL.format(country="PL", store="PL0001")
    session = FakeSession({WEB_URL: aiohttp.ClientError("brak sieci"), store_url: OFFERS})
    runner = PromotionRunner(session, h)  # type: ignore[arg-type]
    await runner.refresh()
    assert session.urls == [WEB_URL, store_url]
    assert [p.art_id for p in runner.latest] == ["0000444", "0000445"]
