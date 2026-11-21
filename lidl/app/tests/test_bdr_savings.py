"""Zakładka „Oszczędzanie” Biedronki (E28.5.2): widok vouchery/oferty z migawki `chain_savings`."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from lidl.chain_savings import Saving
from lidl.history import History
from lidl.web.bdr_savings import build

TODAY = date(2026, 11, 19)


def _s(kind: str, ext: str, name: str, valid_to: str | None, **kw: object) -> Saving:
    extra = kw.pop("extra", {})
    return Saving(kind, ext, name, kw.get("price"), kw.get("regular"), None, valid_to, extra)  # type: ignore[arg-type]


def _saved(rows: list[Saving], tmp_path) -> list:  # type: ignore[no-untyped-def]
    h = History(tmp_path / "h.db")
    h.savings_replace("a", {r.kind for r in rows} | {"voucher"}, rows)
    return h.savings_list()


def test_build_sorts_marks_urgent_and_drops_expired(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = _saved(
        [
            _s("voucher", "v1", "Rabat późny", "2026-11-30T22:59:59Z"),
            _s("voucher", "v2", "Rabat pilny", "2026-11-21T22:59:59Z"),
            _s("voucher", "v3", "Rabat stary", "2026-11-10T22:59:59Z"),
            _s("voucher", "v4", "Rabat bez daty", None),
        ],
        tmp_path,
    )
    v = build(rows, TODAY)
    assert [x["name"] for x in v.vouchers] == ["Rabat pilny", "Rabat późny", "Rabat bez daty"]
    assert [x["urgent"] for x in v.vouchers] == [True, False, False]
    assert v.vouchers[0]["until"] == "do 21.11" and v.vouchers[0]["days_left"] == 2
    assert v.urgent_count == 1


def test_build_offer_prices_and_percent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = _saved(
        [
            _s(
                "offer",
                "o1",
                "Mleko 1l",
                "2026-11-25T22:59:59Z",
                price=3.49,
                regular=4.99,
                extra={"card_only": True, "limit": "Limit 6 szt."},
            ),
            _s("offer", "o2", "Bez ceny", "2026-11-25T22:59:59Z"),
        ],
        tmp_path,
    )
    v = build(rows, TODAY)
    [b, m] = v.offers
    assert (m["price"], m["regular"], m["pct"]) == ("3,49 zł", "4,99 zł", 30)
    assert m["card_only"] is True and m["limit"] == "Limit 6 szt."
    assert (b["price"], b["regular"], b["pct"]) == ("", "", None)


def test_build_shakeomat_available_today(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = _saved([_s("shakeomat", "sh1", "Shakeomat", "2026-11-19T22:59:59Z")], tmp_path)
    assert build(rows, TODAY).shakeomat is True
    expired = _saved([_s("shakeomat", "sh1", "Shakeomat", "2026-11-18T22:59:59Z")], tmp_path / "x")
    assert build(expired, TODAY).shakeomat is False


def test_route_hidden_without_biedronka(client: TestClient) -> None:
    assert client.get("/biedronka").status_code == 404
    assert 'href="/biedronka"' not in client.get("/kupony").text


def _with_biedronka(client: TestClient) -> History:
    h: History = client.app.state.history  # type: ignore[attr-defined]
    h.upsert_tickets(
        "b", [{"id": "b-1", "date": "2026-10-02T10:00:00+00:00", "totalAmount": 9.0}], chain="biedronka"
    )
    return h


def test_route_shows_tab_and_empty_state(client: TestClient) -> None:
    _with_biedronka(client)
    assert 'href="/biedronka"' in client.get("/oszczednosci").text
    r = client.get("/biedronka")
    assert r.status_code == 200 and "Oszczędzanie" in r.text and "Brak voucherów" in r.text


def test_route_lists_vouchers_and_offers(client: TestClient) -> None:
    h = _with_biedronka(client)
    h.savings_replace(
        "b",
        {"voucher", "offer"},
        [
            _s("voucher", "v1", "Rabat 5 zł", "2099-01-01T00:00:00Z"),
            _s("offer", "o1", "Mleko 1l", "2099-01-01T00:00:00Z", price=3.49, regular=4.99),
        ],
    )
    text = client.get("/biedronka").text
    assert "Rabat 5 zł" in text and "Mleko 1l" in text and "3,49" in text


def test_shakeomat_button_runs_reveal_and_redirects(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    h = _with_biedronka(client)
    h.savings_replace("b", {"shakeomat"}, [_s("shakeomat", "sh1", "Shakeomat", "2099-01-01T00:00:00Z")])
    from lidl import chain_savings

    calls: list[str] = []

    async def fake(history, service, today):  # type: ignore[no-untyped-def]
        calls.append("x")
        return [chain_savings.ShakeResult("b", 1)]

    monkeypatch.setattr(chain_savings, "shake_accounts", fake)
    page = client.get("/biedronka").text
    assert "Odsłoń teraz" in page and 'action="/biedronka/shakeomat"' in page
    r = client.post("/biedronka/shakeomat")
    assert r.status_code == 303 and r.headers["location"].endswith("/biedronka?m=shake_ok")
    assert calls == ["x"]
    assert "Shakeomat odsłonięty." in client.get("/biedronka?m=shake_ok").text


def test_shakeomat_post_404_without_biedronka(client: TestClient) -> None:
    assert client.post("/biedronka/shakeomat").status_code == 404


def test_shakeomat_route_result_codes(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _with_biedronka(client)
    from lidl import chain_savings
    from lidl.chain_savings import ShakeResult

    for results, code in (
        ([ShakeResult("b")], "shake_none"),
        ([ShakeResult("b", 1), ShakeResult("c", 0, ["x"])], "shake_err"),
    ):

        async def fake(history, service, today, results=results):  # type: ignore[no-untyped-def]
            return results

        monkeypatch.setattr(chain_savings, "shake_accounts", fake)
        assert client.post("/biedronka/shakeomat").headers["location"].endswith(f"?m={code}")


def test_build_labels_snapshot_age() -> None:
    now = datetime(2026, 11, 20, 12, 0)
    fresh = build([], TODAY, datetime(2026, 11, 20, 7, 2), now)
    assert fresh.fetched_label == "Dane z 20.11, 07:02" and not fresh.stale
    old = build([], TODAY, datetime(2026, 11, 18, 7, 0), now)
    assert old.stale
    assert build([], TODAY).fetched_label == "Jeszcze bez danych"


def test_build_shake_state_and_next_label(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    later = Saving(
        "shakeomat", "sh2", "Shakeomat", None, None, "2026-11-19T12:47:00Z", "2026-11-19T22:59:59Z", {}
    )
    rows = _saved([later], tmp_path)
    v = build(rows, TODAY, now=now)
    assert (v.shakeomat, v.shake_state, v.shake_next_label, v.shake_ready_at) == (
        True, "wait", "13:47", "2026-11-19T12:47:00+00:00",
    )  # fmt: skip
    ready = _saved([_s("shakeomat", "sh1", "Shakeomat", None)], tmp_path / "r")
    assert build(ready, TODAY, now=now).shake_state == "ready"


def test_shake_card_htmx_shows_result_without_redirect(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    h = _with_biedronka(client)
    h.savings_replace("b", {"shakeomat"}, [_s("shakeomat", "sh1", "Shakeomat", "2099-01-01T00:00:00Z")])
    from lidl import chain_savings

    async def fake(history, service, today):  # type: ignore[no-untyped-def]
        history.savings_mark_revealed("b", "sh1", today)
        return [chain_savings.ShakeResult("b", 1, new_offers=["Mleko 1l"])]

    monkeypatch.setattr(chain_savings, "shake_accounts", fake)
    r = client.post("/biedronka/shakeomat", headers={"hx-request": "true"})
    assert r.status_code == 200 and 'id="bdr-shake"' in r.text
    assert "Shakeomat odsłonięty." in r.text and "Nowa oferta: Mleko 1l." in r.text
    assert "Dzisiejszy Shakeomat odsłonięty" in r.text and "<button" not in r.text  # nic więcej do kliknięcia


def test_shake_card_disabled_button_with_next_time(client: TestClient) -> None:
    h = _with_biedronka(client)
    h.savings_replace(
        "b",
        {"shakeomat"},
        [
            Saving(
                "shakeomat",
                "sh2",
                "Shakeomat",
                None,
                None,
                "2099-01-01T12:47:00Z",
                "2099-01-01T22:59:59Z",
                {},
            )
        ],
    )
    page = client.get("/biedronka").text
    assert "Następny Shakeomat od 13:47" in page and "disabled" in page and "data-ready-at" in page
    card = client.get("/biedronka/shakeomat/karta")
    assert card.status_code == 200 and "Następny Shakeomat od 13:47" in card.text


def test_shake_card_route_404_without_biedronka(client: TestClient) -> None:
    assert client.get("/biedronka/shakeomat/karta").status_code == 404


def test_shake_htmx_wait_and_plain_post_redirect(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    h = _with_biedronka(client)
    h.savings_replace("b", {"shakeomat"}, [_s("shakeomat", "sh1", "Shakeomat", "2099-01-01T00:00:00Z")])
    from lidl import chain_savings

    async def fake(history, service, today):  # type: ignore[no-untyped-def]
        return [chain_savings.ShakeResult("b", skipped=1)]

    monkeypatch.setattr(chain_savings, "shake_accounts", fake)
    htmx = client.post("/biedronka/shakeomat", headers={"hx-request": "true"})
    assert "jeszcze dostępny" in htmx.text and 'id="bdr-shake"' in htmx.text
    plain = client.post("/biedronka/shakeomat")
    assert plain.status_code == 303 and plain.headers["location"].endswith("?m=shake_wait")


def test_route_snapshot_age_comes_from_the_last_savings_event(client: TestClient) -> None:
    h = _with_biedronka(client)
    assert "Jeszcze bez danych" in client.get("/biedronka").text
    h.log_event("savings", "ok", "Migawka odświeżona", {})
    assert "Jeszcze bez danych" not in client.get("/biedronka").text
    assert f"Dane z {datetime.now():%d.%m}" in client.get("/biedronka").text


def test_route_snapshot_age_prefers_the_persistent_setting(client: TestClient) -> None:
    h = _with_biedronka(client)
    h.set_setting("savings_fetched_at", "2026-10-01T07:02:00")  # starsze niż 30 dni dziennika
    assert "Dane z 01.10, 07:02" in client.get("/biedronka").text
