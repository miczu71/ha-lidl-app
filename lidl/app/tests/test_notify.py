from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

from lidl.coupons import AccountReport, Activation, ActiveCoupon
from lidl.history import WatchedCoupon
from lidl.notify import NOTIFY_URL, PANEL, compose, compose_expiring, compose_watched, send
from lidl.promotions import Promotion
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


def _promo(title: str, discount: str, end: int) -> Promotion:
    return Promotion("0000111", title, discount, TODAY, date(2026, 10, end))


def test_promotions_line_before_scratch_cards() -> None:
    report = AccountReport([], [_c("Banany", "-10%", 4)])
    promos = [_promo("Produkt A", "-40%", 10), _promo("Produkt B", "-20% przy zakupie 2 szt.", 8)]
    _, body = compose(
        {"Osoba 1": report}, {"Osoba 1": _rewards(9)}, dry_run=False, today=TODAY, promos=promos
    ) or (
        "",
        "",
    )
    assert body.splitlines()[-2:] == [
        "Nowe promocje: Produkt A −40% (do 10 paź) · Produkt B −20% przy 2 szt. (do jutra)",
        "Zdrapki: Osoba 1 do 9 paź",
    ]


def test_promotions_alone_still_send_morning_message() -> None:
    assert compose({}, dry_run=False, today=TODAY, promos=[_promo("Produkt A", "-40%", 10)]) == (
        "Lidl: 1 promocja na Wasze produkty",
        "Nowe promocje: Produkt A −40% (do 10 paź)",
    )


def test_expiring_reminder_lists_only_cards_ending_today() -> None:
    rewards = {"Osoba 1": _rewards(7), "Osoba 2": _rewards(7, 9), "Osoba 3": _rewards(8)}
    assert compose_expiring(rewards, TODAY) == (
        "Lidl: zdrapki wygasają dziś o 23:59",
        "Osoba 1, Osoba 2 — zdrap w aplikacji Lidl Plus",
    )
    assert compose_expiring({"Osoba 3": _rewards(8)}, TODAY) is None


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    def __init__(self, status: int = 200) -> None:
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.status = status

    def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> FakeResponse:
        self.posts.append((url, json, headers))
        return FakeResponse(self.status)


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


@pytest.mark.parametrize(("status", "ok"), [(200, True), (500, False)])
async def test_send_reports_whether_ha_accepted(
    monkeypatch: pytest.MonkeyPatch, status: int, ok: bool
) -> None:
    monkeypatch.setenv("SUPERVISOR_TOKEN", "t")
    assert await send(FakeSession(status), ("Tytuł", "Treść")) is ok  # type: ignore[arg-type]


def _w(account: str, title: str = "Kawa X | 500 g", discount: str = "-30%") -> WatchedCoupon:
    return WatchedCoupon(account, "p1", title, discount, date(2026, 10, 8))


def test_watched_nothing_new_is_silent() -> None:
    assert compose_watched([], [], TODAY) is None


def test_watched_single_coupon_on_both_cards_is_one_line_named_in_title() -> None:
    message = compose_watched([("Osoba 1", _w("osoba-1")), ("Osoba 2", _w("osoba-2"))], [], TODAY)
    assert message == ("Lidl: Kawa X — kupon −30%", "Kawa X −30% (do jutra) · kupon obie karty")


def test_watched_several_products_are_counted_in_title() -> None:
    promo = Promotion("333", "Masło", "-25%", TODAY, date(2026, 10, 12))
    message = compose_watched([("Osoba 1", _w("osoba-1"))], [promo], TODAY)
    assert message == (
        "Lidl: 2 obserwowane produkty z rabatem",
        "Kawa X −30% (do jutra) · kupon Osoba 1\nMasło −25% (do 12 paź) · promocja od dziś",
    )


def test_month_summary_message_first_place_and_no_previous_month(tmp_path: Any) -> None:
    from lidl.history import History
    from lidl.notify import compose_month
    from lidl.receipt_html import ParsedReceipt, ReceiptItem

    h = History(tmp_path / "h.db")
    h.upsert_tickets("osoba-1", [{"id": "s", "date": "2026-09-10T10:00:00+00:00", "totalAmount": 9.5}])
    h.save_detail("s", "Sklep X", ParsedReceipt(items=[ReceiptItem("1", "Produkt A", 1, 10.0, 10.0, -0.5)]))
    s = h.month_summary("2026-09")
    assert s is not None
    assert compose_month(s)[1].splitlines() == [
        "We wrześniu wydaliśmy 9,50 zł w 1 wizycie",
        "Najwięcej na: Produkt A (9,50 zł)",
        "Zaoszczędziliśmy 0,50 zł · najdroższy miesiąc w historii",
        "Więcej w panelu, zakładka Miesiące",
    ]
