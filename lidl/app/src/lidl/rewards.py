"""Nagrody Lidl Plus: niezdrapane zdrapki i postęp akcji Kupon Plus (E20; plan: docs/PLAN_E20_nagrody.md).

- Tylko odczyt: add-on nie zdrapuje i nie startuje akcji. Zdrapana znika z listy (lista = do zdrapania).
- Stan trzymamy w pamięci (`RewardsRunner.last`), bez bazy; błąd konta zostawia jego poprzedni stan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from .client.exceptions import LidlPlusError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScratchCard:
    kind: str  # Scratch / Roulette / Special
    created: datetime
    expires: datetime  # czas lokalny z przesunięciem, np. 23:59:59.999+02:00


@dataclass(frozen=True)
class Goal:
    value: float
    won: bool
    prize: str
    discount: str


@dataclass(frozen=True)
class CouponPlus:
    reached: float
    goals: tuple[Goal, ...]
    ends: date  # ostatni dzień akcji

    @property
    def next_goal(self) -> Goal | None:
        return next((g for g in self.goals if not g.won), None)

    @property
    def missing(self) -> float | None:
        """Ile brakuje do następnego progu; None, gdy wszystkie zdobyte."""
        goal = self.next_goal
        return None if goal is None else round(max(goal.value - self.reached, 0.0), 2)


@dataclass(frozen=True)
class Rewards:
    scratch_cards: tuple[ScratchCard, ...]
    coupon_plus: CouponPlus | None


def parse_lotteries(payload: Any) -> tuple[ScratchCard, ...]:
    cards = []
    for item in payload if isinstance(payload, list) else []:
        try:
            created = datetime.fromisoformat(item["creationDate"])
            expires = datetime.fromisoformat(item["expirationDate"])
        except (KeyError, TypeError, ValueError):
            continue
        cards.append(ScratchCard(item.get("type", ""), created, expires))
    return tuple(sorted(cards, key=lambda c: c.expires))


def _goal(g: dict[str, Any]) -> Goal:
    coupon = (g.get("prize") or {}).get("coupon") or {}
    return Goal(
        float(g.get("value") or 0),
        g.get("status") == "Won",
        (coupon.get("title") or "").strip(" *"),
        (coupon.get("discountTitle") or "").strip(),
    )


def parse_coupon_plus(payload: Any) -> CouponPlus | None:
    """Aktywny klaster akcji (w praktyce jeden, `Store`); None, gdy akcji nie ma."""
    if not isinstance(payload, dict):
        return None
    cluster = next((c for c in payload.get("clusters") or [] if c.get("status") == "Active"), None)
    try:
        ends = datetime.fromisoformat(payload["endDate"]).date()
    except (KeyError, TypeError, ValueError):
        return None
    if cluster is None:
        return None
    goals = sorted((_goal(g) for g in cluster.get("goals") or []), key=lambda g: g.value)
    return CouponPlus(float(cluster.get("reachedAmount") or 0), tuple(goals), ends)


class RewardsSource(Protocol):
    async def lotteries(self, slug: str) -> Any: ...

    async def coupon_plus(self, slug: str) -> Any: ...


class RewardsRunner:
    def __init__(self, source: RewardsSource) -> None:
        self._source = source
        self.last: dict[str, Rewards] = {}  # nazwa konta -> stan z ostatniego udanego odczytu

    async def run_all(self, accounts: list[tuple[str, str]]) -> dict[str, Rewards]:
        """Wszystkie konta (slug, nazwa); błąd jednego konta nie blokuje innych."""
        new: dict[str, Rewards] = {}
        for slug, label in accounts:
            try:
                new[label] = Rewards(
                    parse_lotteries(await self._source.lotteries(slug)),
                    parse_coupon_plus(await self._source.coupon_plus(slug)),
                )
            except LidlPlusError as err:
                log.warning("Nagrody konta %s: odczyt nieudany (%s)", slug, err)
                if label in self.last:
                    new[label] = self.last[label]
        self.last = new
        return new
