from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import pytest

from lidl import geo
from lidl.geo import NOMINATIM_URL, STORES_URL, refresh_store_geo, refresh_store_geo_biedronka
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


async def test_biedronka_store_is_not_sent_to_the_lidl_list_and_gets_no_null_row(tmp_path: Path) -> None:
    h = _history(tmp_path)
    h.upsert_tickets(
        "a",
        [{"id": "b1", "date": "2026-01-02T10:00:00+00:00", "totalAmount": 3.0, "storeCode": "7777"}],
        chain="biedronka",
    )
    assert h.stores_without_geo() == {"PL0001", "PL0002"}  # kod Biedronki nie trafia do listy Lidla
    assert await refresh_store_geo(FakeSession(STORES), h) == 1  # type: ignore[arg-type]
    codes = {row[0] for row in h._db.execute("SELECT code FROM store_geo")}
    assert codes == {"PL0001", "PL0002"}  # brak wiersza NULL dla kodu Biedronki


class NominatimSession:
    """Podstawiony klient HTTP: odpowiedzi wg kolejki; zapisuje parametry zapytań."""

    def __init__(self, *answers: Any) -> None:
        self.answers, self.requests = list(answers), []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        assert url == NOMINATIM_URL
        self.requests.append(kwargs)
        return FakeResponse(self.answers.pop(0))


def _bdr_history(tmp_path: Path, *stores: tuple[str, str, str, str]) -> History:
    """Paragony Biedronki; adres sklepu zapisuje szczegół paragonu, więc kolumny ustawiamy wprost."""
    h = History(tmp_path / "b.db")
    h.upsert_tickets(
        "a",
        [
            {"id": f"b{i}", "date": "2026-01-02T10:00:00+00:00", "totalAmount": 3.0, "storeCode": s[0]}
            for i, s in enumerate(stores)
        ],
        chain="biedronka",
    )
    with h._db:
        h._db.executemany(
            "UPDATE tickets SET store_code = ?, store_address = ?, store_postal = ?, store_locality = ?"
            " WHERE id = ?",
            [(code, street, postal, city, f"b{i}") for i, (code, street, postal, city) in enumerate(stores)],
        )
    return h


def test_biedronka_address_comes_from_the_ticket_and_placeholder_is_blank(tmp_path: Path) -> None:
    h = _bdr_history(
        tmp_path, ("7001", "ul. Przykładowa 1", "50-001", "Miasto A"), ("7003", "---", "---", "---")
    )
    assert h.biedronka_stores_without_geo() == {
        "7001": ("ul. Przykładowa 1", "50-001", "Miasto A"),
        "7003": ("", "", ""),
    }


async def test_biedronka_geocoded_once_with_generic_agent_and_public_address_only(tmp_path: Path) -> None:
    h = _bdr_history(tmp_path, ("7001", "ul. Przykładowa 1", "50-001", "Miasto A"))
    session = NominatimSession([{"lat": "51.1", "lon": "17.0"}])
    assert await refresh_store_geo_biedronka(session, h, pause=0) == 1  # type: ignore[arg-type]
    assert {s.code: (s.chain, s.location) for s in h.stores()} == {"7001": ("biedronka", (51.1, 17.0))}
    request = session.requests[0]
    assert request["params"]["street"] == "Przykładowa 1" and request["params"]["format"] == "jsonv2"
    assert set(request["headers"]) == {"User-Agent"} and "@" not in request["headers"]["User-Agent"]
    assert await refresh_store_geo_biedronka(session, h, pause=0) == 0  # type: ignore[arg-type]
    assert len(session.requests) == 1  # znany sklep nie jest pytany ponownie


async def test_biedronka_no_hit_or_no_address_saves_null_but_network_error_saves_nothing(
    tmp_path: Path,
) -> None:
    h = _bdr_history(
        tmp_path,
        ("1111", "ul. A 1", "50-001", "Miasto A"),
        ("2222", "---", "---", "---"),
        ("3333", "ul. C 3", "50-003", "Miasto B"),
    )
    session = NominatimSession([], aiohttp.ClientError("brak sieci"))
    assert await refresh_store_geo_biedronka(session, h, pause=0) == 0  # type: ignore[arg-type]
    saved = dict(h._db.execute("SELECT code, lat FROM store_geo"))
    assert saved == {
        "1111": None,
        "2222": None,
    }  # brak trafienia i brak adresu = NULL; 3333 (błąd sieci) → jutro
    assert h.biedronka_stores_without_geo().keys() == {"3333"}


async def test_biedronka_malformed_answer_saves_nothing_and_retries_tomorrow(tmp_path: Path) -> None:
    h = _bdr_history(tmp_path, ("1111", "ul. A 1", "50-001", "Miasto A"))
    session = NominatimSession({"error": "x"})
    assert await refresh_store_geo_biedronka(session, h, pause=0) == 0  # type: ignore[arg-type]
    assert h.biedronka_stores_without_geo().keys() == {"1111"}  # bez zapisu NULL


async def test_refresh_all_store_geo_one_source_failing_does_not_block_the_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []

    async def boom(session: object, history: object) -> int:
        raise RuntimeError("x")

    async def ok(session: object, history: object) -> int:
        called.append("bdr")
        return 0

    monkeypatch.setattr(geo, "refresh_store_geo", boom)
    monkeypatch.setattr(geo, "refresh_store_geo_biedronka", ok)
    await geo.refresh_all_store_geo(None, _history(tmp_path))  # type: ignore[arg-type]
    assert called == ["bdr"]


def test_migration_v11_drops_empty_points_of_biedronka_codes_left_by_1_5_0(tmp_path: Path) -> None:
    h = _bdr_history(tmp_path, ("7001", "ul. Przykładowa 1", "50-001", "Miasto A"))
    h.save_store_geo([("7001", None, None), ("PL0001", None, None), ("PL0009", 52.2, 21.0)])
    h._db.execute("PRAGMA user_version = 10")
    h._db.commit()
    h2 = History(tmp_path / "b.db")
    assert dict(h2._db.execute("SELECT code, lat FROM store_geo")) == {"PL0001": None, "PL0009": 52.2}


async def test_biedronka_street_prefix_is_stripped_and_empty_postal_omitted(tmp_path: Path) -> None:
    h = _bdr_history(tmp_path, ("7001", "ul. Przykładowa 1", "", "Miasto A"))
    session = NominatimSession([])
    await refresh_store_geo_biedronka(session, h, pause=0)  # type: ignore[arg-type]
    params = session.requests[0]["params"]
    assert params["street"] == "Przykładowa 1" and "postalcode" not in params
