"""Kupony Lidl Plus: odczyt listy, wybór do aktywacji i aktywacja (E3; rozpoznanie w docs/PLAN_E3_kupony.md).

- Bierzemy tylko sekcje AllStores i SSC. Kupon ogólny (bez kodów artykułów) aktywujemy zawsze, produktowy —
  gdy któryś kod jest na liście „Kupowane regularnie” (`History.coupon_candidates()`, włączone). Kupony
  nadchodzące, wygasłe i już aktywne pomijamy; z sekcji SSC tylko jeden (najniższy rabat).
- Ocena karty: aktywne kupony ważone tym, jak często kupujemy trafione produkty (`AccountReport.score`).
- Aktywacja jest dwuetapowa: pierwszy POST po `id` z listy może się nie udać, ale tworzy egzemplarz kuponu
  konta z nowym `id` (ten sam `promotionId`); wtedy ponawiamy raz z nowym `id`.
- Przebieg próbny (`dry_run`) nic nie wysyła do Lidla, tylko zapisuje, co byłoby aktywowane.
"""

from __future__ import annotations

import asyncio
import logging
import re
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
    status: str  # activated | would | failed (w bazie także manual — aktywacja z panelu)
    new: bool  # decyzja inna niż w poprzednim przebiegu (powiadamiamy tylko o nowych)


@dataclass(frozen=True)
class ActiveCoupon:
    title: str
    discount: str
    valid_to: str
    weight: int  # zakupy produktu z listy „Kupowane regularnie” (12 mies.); 0 = kupon ogólny albo nie nasz
    general: bool  # kupon ogólny (bez kodów artykułów), np. rabat od kwoty zakupów


@dataclass(frozen=True)
class AccountReport:
    """Wynik przebiegu konta: nowe decyzje (do powiadomienia) i kupony aktywne po przebiegu (ocena karty)."""

    activations: list[Activation]
    active: list[ActiveCoupon]

    @property
    def score(self) -> int:
        return sum(c.weight for c in self.active)

    @property
    def weighted_count(self) -> int:
        """Aktywne kupony na nasze produkty."""
        return sum(1 for c in self.active if c.weight)


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


def _day(c: Coupon) -> str:
    return c.valid_to.date().isoformat()


def _amount(discount: str) -> float:
    match = re.search(r"\d+(?:[.,]\d+)?", discount)
    return float(match.group().replace(",", ".")) if match else float("inf")


def _ssc_group(c: Coupon) -> tuple[str, datetime] | None:
    """Kupony SSC o tym samym tytule i końcu ważności różnią się tylko kwotą; Lidl pozwala aktywować jeden."""
    return (c.title, c.valid_to) if c.section == "SSC" else None


def select(coupons: list[Coupon], codes: set[str], now: datetime) -> list[Coupon]:
    """Kupony do aktywacji; z grupy SSC tylko ten z najniższą kwotą, a gdy któryś jest już aktywny — żaden."""
    chosen = [c for c in coupons if should_activate(c, codes, now)]
    keep: set[str] = set()
    for group in {_ssc_group(c) for c in chosen} - {None}:
        if not any(c.activated for c in coupons if _ssc_group(c) == group):
            members = [c for c in chosen if _ssc_group(c) == group]
            keep.add(min(members, key=lambda c: _amount(c.discount)).promotion_id)
    return [c for c in chosen if _ssc_group(c) is None or c.promotion_id in keep]


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

    async def run_all(self, accounts: list[tuple[str, str]], *, dry_run: bool) -> dict[str, AccountReport]:
        """Wszystkie konta (slug, nazwa); błąd jednego konta (np. wygasła sesja) nie blokuje innych."""
        out: dict[str, AccountReport] = {}
        for slug, label in accounts:
            try:
                out[label] = await self.run(slug, dry_run=dry_run)
            except LidlPlusError as err:
                log.warning("Kupony konta %s: przebieg przerwany (%s)", slug, err)
        return out

    async def run(self, slug: str, *, dry_run: bool) -> AccountReport:
        """Pobiera kupony konta, zapisuje je i aktywuje wybrane; błąd jednego kuponu nie przerywa reszty,
        błąd autoryzacji, sieci, limitu lub serwera — tak (jak przy paragonach)."""
        now = self._now()
        coupons = parse_coupons(await self._source.promotions(slug))
        previous = {c["promotion_id"]: c["status"] for c in self._history.account_coupons(slug)}
        self._history.save_coupons(slug, coupons, now.isoformat())
        candidates = self._history.coupon_candidates(now.date())
        codes = {c.art_id for c in candidates if c.enabled}
        weights = {c.art_id: c.purchases for c in candidates if c.matchable}
        chosen = select(coupons, codes, now)
        done = {} if dry_run else await self._activate(slug, [(c.promotion_id, c.coupon_id) for c in chosen])
        statuses = [
            (c.promotion_id, "would" if dry_run else "activated" if c.promotion_id in done else "failed")
            for c in chosen
        ]
        self._history.set_coupon_statuses(slug, [(pid, status, done.get(pid)) for pid, status in statuses])
        activations = [
            Activation(c.title, c.discount, _day(c), status, previous.get(pid) != status)
            for c, (pid, status) in zip(chosen, statuses, strict=True)
        ]
        active = [
            ActiveCoupon(
                c.title,
                c.discount,
                _day(c),
                max((weights.get(a, 0) for a in c.article_ids), default=0),
                not c.article_ids,
            )
            for c in coupons
            if c.activated or c.promotion_id in done or (dry_run and c in chosen)
        ]
        return AccountReport(activations, active)

    async def activate_one(self, slug: str, promotion_id: str) -> None:
        """Ręczna aktywacja z panelu (także w trybie próbnym), po `id` zapisanym przy ostatnim przebiegu;
        status `manual` albo `failed`."""
        row = next(
            (r for r in self._history.account_coupons(slug) if r["promotion_id"] == promotion_id), None
        )
        done = await self._activate(slug, [(promotion_id, row["coupon_id"])]) if row else {}
        self._history.set_coupon_statuses(
            slug, [(promotion_id, "manual" if done else "failed", done.get(promotion_id))]
        )

    async def _activate(self, slug: str, coupons: list[tuple[str, str]]) -> dict[str, str]:
        """Aktywuje kupony (`promotionId`, `id`); zwraca `promotionId` -> `id`, po którym się udało. Po
        nieudanych pierwszych próbach pobiera listę raz i ponawia te, które dostały nowe `id` (egzemplarz
        konta). Przerwa tylko między kolejnymi żądaniami."""
        done: dict[str, str] = {}
        failed = []
        for n, (pid, cid) in enumerate(coupons):
            if n:
                await self._sleep(self._pause)
            if await self._try(slug, cid):
                done[pid] = cid
            else:
                failed.append((pid, cid))
        if failed:
            fresh = {c.promotion_id: c.coupon_id for c in parse_coupons(await self._source.promotions(slug))}
            for pid, cid in failed:
                new_id = fresh.get(pid)
                if new_id and new_id != cid:
                    await self._sleep(self._pause)
                    if await self._try(slug, new_id):
                        done[pid] = new_id
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
