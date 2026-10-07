from __future__ import annotations

from typing import Any

import pytest

from lidl.coupons import Activation
from lidl.notify import NOTIFY_URL, compose, send


def _a(title: str, status: str = "activated", new: bool = True, discount: str = "-30%") -> Activation:
    return Activation(title, discount, "2026-10-10", status, new)


def test_nothing_new_means_no_message() -> None:
    assert compose({"Osoba 1": [_a("Produkt A", new=False)]}, dry_run=False) is None
    assert compose({}, dry_run=False) is None


def test_activated_message_lists_accounts_with_validity() -> None:
    msg = compose(
        {
            "Osoba 1": [
                _a("Produkt A"),
                _a("Rabat od zakupów", discount="10 zł rabatu"),
                _a("Stary", new=False),
            ],
            "Osoba 2": [_a("Produkt B"), _a("Produkt C", status="failed")],
        },
        dry_run=False,
    )
    assert msg == (
        "Lidl: aktywowano 3 kupony",
        "Osoba 1: Produkt A, -30% (do 10 paź); Rabat od zakupów, 10 zł rabatu (do 10 paź)\n"
        "Osoba 2: Produkt B, -30% (do 10 paź)\n"
        "Nie udało się: Produkt C (Osoba 2)",
    )


def test_dry_run_title_and_plural() -> None:
    title, body = compose({"Osoba 1": [_a(f"P{i}", status="would") for i in range(5)]}, dry_run=True) or (
        "",
        "",
    )
    assert title == "Lidl (tryb próbny): aktywowałbym 5 kuponów"
    assert body.startswith("Osoba 1: P0, -30% (do 10 paź)")


class FakeResponse:
    status = 200

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        self.posts.append((url, json, headers))
        return FakeResponse()


async def test_send_posts_to_notify_family_with_supervisor_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    session = FakeSession()
    await send(session, ("Tytuł", "Treść"))  # type: ignore[arg-type]
    assert session.posts == [
        (NOTIFY_URL, {"title": "Tytuł", "message": "Treść"}, {"Authorization": "Bearer t"})
    ]


async def test_send_without_token_only_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    session = FakeSession()
    await send(session, ("Tytuł", "Treść"))  # type: ignore[arg-type]
    assert session.posts == []
