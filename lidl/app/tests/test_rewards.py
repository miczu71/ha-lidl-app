from __future__ import annotations

from datetime import date
from typing import Any

from lidl.client.exceptions import LidlPlusError
from lidl.rewards import RewardsRunner, parse_coupon_plus, parse_lotteries


def _lottery(created: str, expires: str, kind: str = "Scratch") -> dict[str, Any]:
    return {"type": kind, "creationDate": created, "expirationDate": expires}


def _goal(value: float, status: str, title: str = "Produkt A", discount: str = "-50%") -> dict[str, Any]:
    return {
        "value": value,
        "status": status,
        "prize": {"type": "Coupon", "coupon": {"id": "c", "title": title, "discountTitle": discount}},
    }


def _coupon_plus(reached: float, goals: list[dict[str, Any]], status: str = "Active") -> dict[str, Any]:
    return {
        "endDate": "2026-10-31T00:00:00Z",
        "clusters": [{"status": status, "reachedAmount": reached, "goals": goals}],
    }


def test_lotteries_sorted_by_expiry_and_broken_items_skipped() -> None:
    cards = parse_lotteries(
        [
            _lottery("2026-10-06T10:00:00+02:00", "2026-10-09T23:59:59.999+02:00", "Roulette"),
            _lottery("2026-10-05T19:39:25+02:00", "2026-10-08T23:59:59.999+02:00"),
            {"type": "Scratch"},
        ]
    )
    assert [c.kind for c in cards] == ["Scratch", "Roulette"]
    assert cards[0].expires.date() == date(2026, 10, 8)
    assert cards[0].expires.utcoffset() is not None


def test_lotteries_empty_or_unexpected() -> None:
    assert parse_lotteries([]) == ()
    assert parse_lotteries(None) == ()
    assert parse_lotteries({"error": "x"}) == ()


def test_coupon_plus_next_goal_and_missing() -> None:
    cp = parse_coupon_plus(
        _coupon_plus(
            335.7,
            [
                _goal(500, "Uncompleted", "*Produkt C LUB Produkt D", "-50%"),
                _goal(50, "Won"),
                _goal(300, "Won"),
                _goal(1500, "Uncompleted"),
            ],
        )
    )
    assert cp is not None
    assert [g.value for g in cp.goals] == [50, 300, 500, 1500]
    assert cp.next_goal is not None and cp.next_goal.value == 500
    assert cp.next_goal.prize == "Produkt C LUB Produkt D"
    assert cp.next_goal.discount == "-50%"
    assert cp.missing == 164.3
    assert cp.ends == date(2026, 10, 31)


def test_coupon_plus_all_goals_won() -> None:
    cp = parse_coupon_plus(_coupon_plus(1600, [_goal(50, "Won"), _goal(1500, "Won")]))
    assert cp is not None and cp.next_goal is None and cp.missing is None


def test_coupon_plus_absent() -> None:
    assert parse_coupon_plus(None) is None
    assert parse_coupon_plus({"clusters": []}) is None
    assert parse_coupon_plus(_coupon_plus(10, [_goal(50, "Uncompleted")], status="Finished")) is None


class FakeSource:
    def __init__(self) -> None:
        self.fail: set[str] = set()

    async def lotteries(self, slug: str) -> Any:
        if slug in self.fail:
            raise LidlPlusError("http_500", status=500)
        return [_lottery("2026-10-05T19:00:00+02:00", "2026-10-08T23:59:59.999+02:00")]

    async def coupon_plus(self, slug: str) -> Any:
        return _coupon_plus(100, [_goal(300, "Uncompleted")])


async def test_runner_keeps_previous_state_of_failing_account() -> None:
    source = FakeSource()
    runner = RewardsRunner(source)
    first = await runner.run_all([("a", "Osoba 1"), ("b", "Osoba 2")])
    assert set(first) == {"Osoba 1", "Osoba 2"}
    source.fail.add("b")
    second = await runner.run_all([("a", "Osoba 1"), ("b", "Osoba 2")])
    assert second["Osoba 2"] == first["Osoba 2"]


async def test_runner_drops_disconnected_accounts() -> None:
    runner = RewardsRunner(FakeSource())
    await runner.run_all([("a", "Osoba 1"), ("b", "Osoba 2")])
    assert set(await runner.run_all([("a", "Osoba 1")])) == {"Osoba 1"}
