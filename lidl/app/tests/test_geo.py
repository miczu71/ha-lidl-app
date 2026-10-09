from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp

from lidl.geo import STORES_URL, refresh_store_geo
from lidl.history import History
from lidl.receipt_html import ParsedReceipt, ReceiptItem

URL = STORES_URL.format(country="PL")
STORES = [
    {"storeKey": "PL0001", "name": "Miasto A, Ulica A 1", "location": {"latitude": 51.1, "longitude": 17.0}},
    {"storeKey": "PL0009", "name": "Miasto B, Ulica B 2", "location": {"latitude": 52.2, "longitude": 21.0}},
]


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
    def __init__(self, payload: Any) -> None:
        self.payload, self.calls = payload, 0

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        assert url == URL
        self.calls += 1
        return FakeResponse(self.payload)


def _history(tmp_path: Path) -> History:
    """Dwa sklepy z paragonów: PL0001 jest na liście Lidla, PL0002 (zamknięty) nie."""
    h = History(tmp_path / "h.db")
    tickets = [("t1", "PL0001"), ("t2", "PL0002")]
    h.upsert_tickets(
        "a",
        [
            {"id": t, "date": "2026-01-01T10:00:00+00:00", "totalAmount": 5.0, "storeCode": s}
            for t, s in tickets
        ],
    )
    h.save_detail("t1", None, ParsedReceipt(items=[ReceiptItem("1", "Mleko", 1, 5.0, 5.0)]))
    return h


async def test_saves_coordinates_of_our_stores_once_and_remembers_stores_off_the_list(tmp_path: Path) -> None:
    h = _history(tmp_path)
    session = FakeSession(STORES)
    assert await refresh_store_geo(session, h) == 1  # type: ignore[arg-type]
    assert {s.code: s.location for s in h.stores()} == {"PL0001": (51.1, 17.0), "PL0002": None}
    await refresh_store_geo(session, h)  # type: ignore[arg-type]
    assert session.calls == 1  # PL0002 spoza listy już sprawdzony → bez kolejnego pobrania

    h.upsert_tickets("a", [{"id": "t3", "date": "2026-02-01T10:00:00+00:00", "storeCode": "PL0009"}])
    assert await refresh_store_geo(session, h) == 1  # type: ignore[arg-type]
    assert session.calls == 2  # nowy sklep → lista jeszcze raz


async def test_network_error_keeps_stores_without_coordinates(tmp_path: Path) -> None:
    h = _history(tmp_path)
    assert await refresh_store_geo(FakeSession(aiohttp.ClientError("brak sieci")), h) == 0  # type: ignore[arg-type]
    assert [s.location for s in h.stores()] == [None, None]
