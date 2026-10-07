from __future__ import annotations

from fastapi.testclient import TestClient

from lidl import __version__
from lidl.client.exceptions import LidlPlusAuthError
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
