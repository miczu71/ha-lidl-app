from __future__ import annotations

from fastapi.testclient import TestClient

from lidl import __version__
from lidl.client.exceptions import LidlPlusAuthError
from lidl.receipt_html import ParsedReceipt, ReceiptItem
from lidl.service import LidlService
from lidl.settings import Settings
from lidl.web.app import create_app


def test_index_empty_and_no_store(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Brak kont" in r.text and f"?v={__version__}" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_static_is_immutable(client: TestClient) -> None:
    r = client.get("/static/app.css")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_add_account_then_login_page_has_pkce_url(client: TestClient) -> None:
    r = client.post(
        "/accounts", data={"label": "Osoba 1"}, headers={"x-ingress-path": "/api/hassio_ingress/abc"}
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/api/hassio_ingress/abc/accounts/osoba-1/login"
    page = client.get("/accounts/osoba-1/login")
    assert "accounts.lidl.com/connect/authorize" in page.text
    assert "code_challenge_method=S256" in page.text
    assert "Osoba 1" in client.get("/").text


def test_failed_login_shows_error_and_fresh_url(client: TestClient, monkeypatch) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})

    async def reject(self: LidlService, slug: str, pasted: str) -> None:
        raise LidlPlusAuthError("token_rejected")

    monkeypatch.setattr(LidlService, "finish_login", reject)
    r = client.post("/accounts/osoba-1/login", data={"pasted": "com.lidlplus.app://callback?code=SECRETCODE"})
    assert r.status_code == 200
    assert "Zaloguj się od nowa" in r.text
    assert "SECRETCODE" not in r.text


def test_successful_login_redirects(client: TestClient, monkeypatch) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})

    async def ok(self: LidlService, slug: str, pasted: str) -> None:
        return None

    monkeypatch.setattr(LidlService, "finish_login", ok)
    r = client.post("/accounts/osoba-1/login", data={"pasted": "x"})
    assert (r.status_code, r.headers["location"]) == (303, "/?m=connected")


def test_delete_removes_account(client: TestClient) -> None:
    client.post("/accounts", data={"label": "Osoba 1"})
    client.post("/accounts/osoba-1/delete")
    assert "Brak kont" in client.get("/").text


def test_non_ingress_peer_is_rejected(settings: Settings) -> None:
    prod = Settings(data_dir=settings.data_dir, log_level="info", dev=False)
    with TestClient(create_app(prod)) as c:
        assert c.get("/").status_code == 403


# --- Produkty (E2.2) ---------------------------------------------------------


def _seed(client: TestClient, days: tuple[str, ...] = ("2026-09-02", "2026-10-02")) -> None:
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets(
        "osoba-1",
        [
            {"id": f"t{i}", "date": f"{d}T10:00:00+00:00", "totalAmount": 20.0, "savings": 2.5}
            for i, d in enumerate(days)
        ],
    )
    for i, _ in enumerate(days):
        history.save_detail(
            f"t{i}",
            "Sklep X",
            ParsedReceipt(
                items=[
                    ReceiptItem("111", "Produkt A", 2, 5.0, 10.0, discount=-2.0, coupon=-1.0),
                    ReceiptItem("222", "Produkt B", 1, 8.0, 8.0),
                ]
            ),
        )


def _connect(client: TestClient, label: str = "Osoba 1") -> str:
    store = client.app.state.service.store  # type: ignore[attr-defined]
    slug = store.create(label).slug
    store.save_tokens(slug, {"access_token": "a", "refresh_token": "r"})
    return slug


def test_products_empty_history_offers_import_per_account(client: TestClient) -> None:
    _connect(client)
    client.app.state.service.store.create("Osoba 2")  # type: ignore[attr-defined]
    r = client.get("/produkty")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "Brak historii zakupów" in r.text
    assert 'action="/accounts/osoba-1/history"' in r.text
    assert "/accounts/osoba-2/login" in r.text
    assert "Dotychczasowe oszczędności" not in r.text


def test_products_shows_kpi_chart_and_ranking(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all").text
    assert "Dotychczasowe oszczędności" in text and "4,00 zł" in text
    assert "Kupony Lidl Plus" in text and "Promocje" in text and "2,00 zł" in text
    assert "wrzesień 2026: 16 zł" in text
    assert "Produkt A" in text and "2 zakupy" in text
    assert 'aria-pressed="true"' in text and "Historia jest aktualna: 2 paragony" in text


def test_products_filters_chart_by_product_and_metric(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all&produkt=222&miara=sztuki").text
    assert "wrzesień 2026: 1 szt." in text
    assert 'value="222" selected' in text


def test_products_reversed_range_shows_error_without_chart(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?od=2026-10-01&do=2026-01-01").text
    assert "Data „Od” jest późniejsza niż „Do”" in text
    assert 'role="img"' not in text


def test_products_range_without_purchases_says_so(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?od=2018-01-01&do=2018-03-31").text
    assert "Brak zakupów w tym zakresie" in text and 'role="img"' not in text


def test_products_ranking_limit_and_more_link(client: TestClient) -> None:
    _seed(client)
    text = client.get("/produkty?zakres=all&limit=1").text
    assert "Produkt A" in text and 'aria-label="Pokaż Produkt B na wykresie"' not in text
    assert "limit=26" in text and "Pokaż więcej" in text
    assert "Pokaż więcej" not in client.get("/produkty?zakres=all").text


def test_products_running_import_shows_progress_and_refreshes(client: TestClient) -> None:
    slug = _connect(client)
    _seed(client)
    progress = client.app.state.sync.progress(slug)  # type: ignore[attr-defined]
    progress.running, progress.done, progress.total = True, 120, 334
    text = client.get("/produkty").text
    assert 'aria-valuenow="120"' in text and "120 z 334" in text
    assert 'http-equiv="refresh"' in text


def test_products_failed_import_offers_resume(client: TestClient) -> None:
    slug = _connect(client)
    _seed(client)
    client.app.state.sync.progress(slug).error = "http_429"  # type: ignore[attr-defined]
    text = client.get("/produkty").text
    assert "Import przerwany" in text and 'action="/history/resume"' in text
    assert 'http-equiv="refresh"' not in text


def test_start_history_import_redirects_and_starts_full_sync(client: TestClient, monkeypatch) -> None:
    slug = _connect(client)
    started: list[tuple[str, bool]] = []
    sync = client.app.state.sync  # type: ignore[attr-defined]
    monkeypatch.setattr(sync, "start", lambda s, *, full: started.append((s, full)) or True)
    r = client.post(f"/accounts/{slug}/history", headers={"x-ingress-path": "/i"})
    assert r.status_code == 303 and r.headers["location"] == "/i/produkty"
    assert started == [(slug, True)]


def test_start_history_import_for_unconnected_account_goes_to_accounts(client: TestClient) -> None:
    slug = client.app.state.service.store.create("Osoba 2").slug  # type: ignore[attr-defined]
    r = client.post(f"/accounts/{slug}/history")
    assert r.status_code == 303 and r.headers["location"] == "/?m=expired"


def test_resume_restarts_only_accounts_with_history(client: TestClient, monkeypatch) -> None:
    slug = _connect(client)
    _connect(client, "Osoba 2")
    _seed(client)
    started: list[str] = []
    sync = client.app.state.sync  # type: ignore[attr-defined]
    monkeypatch.setattr(sync, "start", lambda s, *, full: started.append(s) or True)
    r = client.post("/history/resume")
    assert r.status_code == 303 and r.headers["location"] == "/produkty"
    assert started == [slug]


def test_navigation_links_products_and_accounts(client: TestClient) -> None:
    text = client.get("/").text
    assert 'href="/produkty"' in text and 'aria-current="page"' in text


def test_products_warns_about_unparsed_receipts_and_partial_kpi(client: TestClient) -> None:
    _seed(client)
    history = client.app.state.history  # type: ignore[attr-defined]
    history.upsert_tickets(
        "osoba-1", [{"id": "tx", "date": "2026-10-03T10:00:00+00:00", "articlesCount": 4, "totalAmount": 9.0}]
    )
    history.save_detail("tx", "Sklep X", ParsedReceipt())
    history.upsert_tickets(
        "osoba-1", [{"id": "ty", "date": "2026-10-04T10:00:00+00:00", "articlesCount": 2, "totalAmount": 5.0}]
    )
    text = client.get("/produkty?zakres=all").text
    assert "Nie udało się odczytać paragonów: 1" in text
    assert "Liczone z 3 z 4 paragonów" in text


def test_products_offers_import_for_connected_account_without_history(client: TestClient) -> None:
    _connect(client)
    _connect(client, "Osoba 2")
    _seed(client)
    text = client.get("/produkty").text
    assert 'action="/accounts/osoba-2/history"' in text
    assert 'action="/accounts/osoba-1/history"' not in text
