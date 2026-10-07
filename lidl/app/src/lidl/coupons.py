"""Kupony Lidl Plus: odczyt listy, wybór do aktywacji i aktywacja (E3; rozpoznanie w docs/PLAN_E3_kupony.md).

- Bierzemy tylko sekcje AllStores i SSC. Kupon ogólny (bez kodów artykułów) aktywujemy zawsze, produktowy —
  gdy któryś kod jest w `History.auto_activate_codes()`. Kupony nadchodzące, wygasłe i już aktywne pomijamy.
- Aktywacja jest dwuetapowa: pierwszy POST po `id` z listy może się nie udać, ale tworzy egzemplarz kuponu
  konta z nowym `id` (ten sam `promotionId`); wtedy ponawiamy raz z nowym `id`.
- Przebieg próbny (`dry_run`) nic nie wysyła do Lidla, tylko zapisuje, co byłoby aktywowane.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .client.exceptions import LidlPlusError
from .history import History
from .sync import is_fatal

log = logging.getLogger(__name__)

SECTIONS = ("AllStores", "SSC")


@dataclass(frozen=True)
class Coupon:
    coupon_id: str
    promotion_id: str
    section: str
    title: str
    discount: str
    valid_from: datetime
    valid_to: datetime
    article_ids: tuple[str, ...]
    activated: bool


@dataclass(frozen=True)
class Activation:
    title: str
    discount: str
    valid_to: str  # dzień końca ważności (czas UTC z API, przycięty do daty)
    status: str  # activated | would | failed
    new: bool  # decyzja inna niż w poprzednim przebiegu (powiadamiamy tylko o nowych)


class CouponSource(Protocol):
    async def promotions(self, slug: str) -> dict[str, Any]: ...

    async def activate(self, slug: str, coupon_id: str) -> None: ...


def _when(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def parse_coupons(payload: dict[str, Any]) -> list[Coupon]:
    out = []
    for section in payload.get("sections") or []:
        if section.get("name") not in SECTIONS:
            continue
        for p in section.get("promotions") or []:
            validity = p.get("validity") or {}
            out.append(
                Coupon(
                    coupon_id=str(p["id"]),
                    promotion_id=str(p.get("promotionId") or p["id"]),
                    section=section["name"],
                    title=str(p.get("title") or ""),
                    discount=str((p.get("discount") or {}).get("title") or ""),
                    valid_from=_when(validity["start"]),
                    valid_to=_when(validity["end"]),
                    article_ids=tuple(str(a) for a in p.get("articleIds") or []),
                    activated=bool(p.get("isActivated")),
                )
            )
    return out


def should_activate(coupon: Coupon, codes: set[str], now: datetime) -> bool:
    if coupon.activated or not coupon.valid_from <= now < coupon.valid_to:
        return False
    return not coupon.article_ids or not codes.isdisjoint(coupon.article_ids)


class CouponRunner:
    def __init__(
        self,
        source: CouponSource,
        history: History,
        *,
        pause: float = 2.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._source = source
        self._history = history
        self._pause = pause
        self._sleep = sleep
        self._now = now

    async def run_all(self, accounts: list[tuple[str, str]], *, dry_run: bool) -> dict[str, list[Activation]]:
        """Wszystkie konta (slug, nazwa); błąd jednego konta (np. wygasła sesja) nie blokuje innych."""
        out: dict[str, list[Activation]] = {}
        for slug, label in accounts:
            try:
                out[label] = await self.run(slug, dry_run=dry_run)
            except LidlPlusError as err:
                log.warning("Kupony konta %s: przebieg przerwany (%s)", slug, err)
        return out

    async def run(self, slug: str, *, dry_run: bool) -> list[Activation]:
        """Pobiera kupony konta, zapisuje je i aktywuje wybrane; błąd jednego kuponu nie przerywa reszty,
        błąd autoryzacji, sieci, limitu lub serwera — tak (jak przy paragonach)."""
        now = self._now()
        coupons = parse_coupons(await self._source.promotions(slug))
        previous = {c["promotion_id"]: c["status"] for c in self._history.account_coupons(slug)}
        self._history.save_coupons(slug, coupons, now.isoformat())
        codes = self._history.auto_activate_codes(now.date())
        chosen = [c for c in coupons if should_activate(c, codes, now)]
        done = {} if dry_run else await self._activate(slug, chosen)
        statuses = [
            (c.promotion_id, "would" if dry_run else "activated" if c.promotion_id in done else "failed")
            for c in chosen
        ]
        self._history.set_coupon_statuses(slug, [(pid, status, done.get(pid)) for pid, status in statuses])
        return [
            Activation(
                c.title, c.discount, c.valid_to.date().isoformat(), status, previous.get(pid) != status
            )
            for c, (pid, status) in zip(chosen, statuses, strict=True)
        ]

    async def _activate(self, slug: str, coupons: list[Coupon]) -> dict[str, str]:
        """Aktywuje kupony; zwraca `promotionId` -> `id`, po którym się udało. Po nieudanych pierwszych
        próbach pobiera listę raz i ponawia te kupony, które dostały nowe `id` (egzemplarz konta)."""
        done: dict[str, str] = {}
        failed = []
        for c in coupons:
            await self._sleep(self._pause)
            if await self._try(slug, c.coupon_id):
                done[c.promotion_id] = c.coupon_id
            else:
                failed.append(c)
        if failed:
            fresh = {c.promotion_id: c.coupon_id for c in parse_coupons(await self._source.promotions(slug))}
            for c in failed:
                new_id = fresh.get(c.promotion_id)
                if new_id and new_id != c.coupon_id:
                    await self._sleep(self._pause)
                    if await self._try(slug, new_id):
                        done[c.promotion_id] = new_id
        return done

    async def _try(self, slug: str, coupon_id: str) -> bool:
        try:
            await self._source.activate(slug, coupon_id)
        except LidlPlusError as err:
            if is_fatal(err):
                raise
            log.info("Kupon %s: aktywacja nieudana (%s)", coupon_id, err)
            return False
        return True
