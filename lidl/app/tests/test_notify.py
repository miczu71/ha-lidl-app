from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from lidl.coupons import AccountReport, Activation, ActiveCoupon
from lidl.notify import NOTIFY_URL, PANEL, compose, compose_expiring, send
from lidl.rewards import Rewards, ScratchCard

TODAY = date(2026, 10, 7)
LATER = "2026-10-10"


def _c(title: str, discount: str, weight: int = 0, end: str = LATER, general: bool = False) -> ActiveCoupon:
    return ActiveCoupon(title, discount, end, weight, general)


def test_recommends_the_card_with_more_weighted_coupons() -> None:
    general = _c("*na zakupy za min. 100 zł", "10 zł rabatu*", general=True)
    kiwi = _c("Kiwi Gold | sztuka", "1 + 1 gratis", 5, end="2026-10-07")
    results = {
        "Osoba 1": AccountReport(
            [], [_c("Papryka czerwona | luzem", "-11%", 28, end="2026-10-07"), kiwi, general]
        ),
        "Osoba 2": AccountReport([], [_c("Banany | luzem", "2,99 zł / 1 kg", 40), kiwi, general]),
        "Osoba 3": AccountReport([], [_c("Wyciskarka", "-100 zł")]),
    }
    title, body = compose(results, dry_run=False, today=TODAY) or ("", "")
    assert title == "Lidl: dziś karta Osoba 2 (2 kupony na Wasze produkty)"
    assert body.splitlines() == [
        "Osoba 1: Papryka czerwona −11%",
        "Osoba 2: Banany 2,99 zł/kg",
        "Obie: Kiwi Gold 1+1 · 10 zł na zakupy od 100 zł",
        "Koniec dziś: Papryka czerwona, Kiwi Gold",
    ]


def test_two_cards_common_line_and_tie() -> None:
    a = AccountReport([], [_c("Mleko UHT 3,2% Mazurski Smak", "1,99 zł / 1 szt. przy zakupie 6 szt.", 7)])
    b = AccountReport([], [_c("Ser gouda plastry 150 g", "-30%", 7)])
    title, body = compose({"Osoba 1": a, "Osoba 2": b}, dry_run=False, today=TODAY) or ("", "")
    assert title == "Lidl: obie karty podobnie (1 kupon na Wasze produkty)"
    assert body.splitlines() == [
        "Osoba 1: Mleko UHT 3,2% Mazurski Smak 1,99 zł/szt. przy 6 szt.",
        "Osoba 2: Ser gouda plastry 150 g −30%",
    ]


def test_nothing_for_our_products_means_no_message() -> None:
    only_general = AccountReport([], [_c("*na zakupy za min. 100 zł", "10 zł rabatu*", general=True)])
    assert compose({"Osoba 1": only_general}, dry_run=False, today=TODAY) is None
    assert compose({}, dry_run=False, today=TODAY) is None


def test_dry_run_title_and_new_failures_line() -> None:
    report = AccountReport(
        [
            Activation("Jajka L", "-10%", LATER, "failed", True),
            Activation("Stary", "-5%", LATER, "failed", False),
        ],
        [_c("Banany", "-10%", 4)],
    )
    title, body = compose({"Osoba 1": report}, dry_run=True, today=TODAY) or ("", "")
    assert title == "Lidl (tryb próbny): dziś karta Osoba 1 (1 kupon na Wasze produkty)"
    assert body.splitlines()[-1] == "Nie udało się: Jajka L (Osoba 1)"


def _rewards(*days: int) -> Rewards:
    cards = tuple(
        ScratchCard("Scratch", datetime(2026, 10, 5, 19, 0), datetime(2026, 10, d, 23, 59, 59)) for d in days
    )
    return Rewards(cards, None)


def test_scratch_cards_line_after_coupons() -> None:
    report = AccountReport([], [_c("Banany", "-10%", 4)])
    rewards = {"Osoba 1": _rewards(7), "Osoba 2": _rewards(8, 12)}
    _, body = compose({"Osoba 1": report}, rewards, dry_run=False, today=TODAY) or ("", "")
    assert body.splitlines()[-1] == "Zdrapki: Osoba 1 do dziś · Osoba 2 do jutra · Osoba 2 do 12 paź"


def test_scratch_card_alone_still_sends_morning_message() -> None:
    assert compose({}, {"Osoba 1": _rewards(9)}, dry_run=False, today=TODAY) == (
        "Lidl: zdrapka do zdrapania",
        "Zdrapki: Osoba 1 do 9 paź",
    )
    assert compose({}, {"Osoba 1": _rewards()}, dry_run=False, today=TODAY) is None


def test_expiring_reminder_lists_only_cards_ending_today() -> None:
    rewards = {"Osoba 1": _rewards(7), "Osoba 2": _rewards(7, 9), "Osoba 3": _rewards(8)}
    assert compose_expiring(rewards, TODAY) == (
        "Lidl: zdrapki wygasają dziś o 23:59",
        "Osoba 1, Osoba 2 — zdrap w aplikacji Lidl Plus",
    )
    assert compose_expiring({"Osoba 3": _rewards(8)}, TODAY) is None


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


async def test_send_posts_to_notify_family_with_tap_action_and_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    session = FakeSession()
    await send(session, ("Tytuł", "Treść"))  # type: ignore[arg-type]
    url, body, headers = session.posts[0]
    assert url == NOTIFY_URL and headers == {"Authorization": "Bearer t"}
    assert body == {
        "title": "Tytuł",
        "message": "Treść",
        "data": {"clickAction": PANEL, "url": PANEL, "tag": "lidl-kupony"},
    }


async def test_send_with_own_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    session = FakeSession()
    await send(session, ("Tytuł", "Treść"), tag="lidl-zdrapki")  # type: ignore[arg-type]
    assert session.posts[0][1]["data"]["tag"] == "lidl-zdrapki"


async def test_send_without_token_only_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    session = FakeSession()
    await send(session, ("Tytuł", "Treść"))  # type: ignore[arg-type]
    assert session.posts == []
