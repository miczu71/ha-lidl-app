"""Ingest publicznego feedu produktów Frisco do katalogu cen (E6b.1).

Feed (~50 MB) pobieramy raz na tydzień strumieniowo do pliku w katalogu danych, parsujemy, a plik kasujemy.
Obserwacja powstaje tylko przy zmianie ceny albo okna promocji. Źródło: zobacz `THIRD_PARTY_NOTICES.md`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import aiohttp

from .history import History

log = logging.getLogger(__name__)

FEED_URL = "https://commerce.frisco.pl/api/v1/integration/feeds/public?language=pl"
USER_AGENT = "Mozilla/5.0 (compatible; ha-shopping-addon)"
SOURCE = "frisco"
WEEKLY_DAY = 6  # niedziela (datetime.weekday)
WEEKLY_AT = time(3, 0)
MAX_FEED_BYTES = 150 * 1024 * 1024  # feed ma ~50 MB; twardy limit chroni dysk i pamięć
LOCK = asyncio.Lock()  # jeden przebieg naraz: pętla tygodniowa i ręczne odświeżenie

Fetch = Callable[[Path], Awaitable[None]]


@dataclass
class Result:
    products: int = 0
    observations: int = 0
    skipped: int = 0
    busy: bool = False
    error: str = ""


def downloader(session: aiohttp.ClientSession) -> Fetch:
    """Pobranie feedu strumieniowo do `dest` (bez trzymania całości w pamięci)."""

    async def fetch(dest: Path) -> None:
        timeout = aiohttp.ClientTimeout(total=600)
        async with session.get(FEED_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout) as resp:
            resp.raise_for_status()
            if resp.content_length is not None and resp.content_length > MAX_FEED_BYTES:
                raise ValueError("feed za duży")
            total = 0
            with dest.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(1 << 16):
                    total += len(chunk)
                    if total > MAX_FEED_BYTES:
                        raise ValueError("feed za duży")
                    fh.write(chunk)

    return fetch


def _load(path: Path) -> list[dict[str, Any]]:
    with path.open("rb") as fh:
        feed = json.load(fh)
    products = feed.get("products") if isinstance(feed, dict) else None
    if not isinstance(products, list):
        raise ValueError("feed bez listy products")
    return [p for p in products if isinstance(p, dict)]


def _observation(product: dict[str, Any]) -> tuple[float, float | None, str | None] | None:
    """(cena, cena regularna, koniec promocji); promocja = `priceAfterPromotion` poniżej ceny zwykłej."""
    price = product.get("price")
    if not isinstance(price, dict) or not isinstance(price.get("price"), int | float):
        return None
    regular = float(price["price"])
    promo = price.get("priceAfterPromotion")
    if isinstance(promo, int | float) and 0 < promo < regular:
        valid_to = next(
            (
                p.get("validTo")
                for p in product.get("promotions") or []
                if isinstance(p, dict) and p.get("validTo")
            ),
            None,
        )
        return float(promo), regular, valid_to
    return regular, regular, None


def ingest(history: History, products: list[dict[str, Any]], day: str) -> Result:
    """Jedna transakcja (bez wielu commitów na wspólnym połączeniu); zły produkt jest pomijany i liczony."""
    res = Result()
    with history.catalog_bulk():
        for p in products:
            ean = str(p.get("ean") or "").strip()
            try:
                obs = _observation(p)
                if not ean or obs is None:
                    continue
                _ingest_one(history, p, ean, obs, day, res)
            except (sqlite3.Error, AttributeError, TypeError, ValueError):
                res.skipped += 1
                log.warning("Feed Frisco: pominięto produkt EAN %s", ean)
    return res


def _ingest_one(
    history: History,
    p: dict[str, Any],
    ean: str,
    obs: tuple[float, float | None, str | None],
    day: str,
    res: Result,
) -> None:
    name = p.get("name")
    title = name.get("pl") if isinstance(name, dict) else None
    unit = p.get("unitOfMeasure")
    grammage = p.get("grammage")
    pid = history.catalog_upsert_product(
        ean=ean,
        frisco_id=str(p["id"]) if p.get("id") else None,
        name=title or None,
        brand=p.get("brand") or None,
        size=float(grammage) if isinstance(grammage, int | float) else None,
        size_unit=str(unit) if unit else None,
        authoritative=True,
    )
    res.products += 1
    price, regular, promo_to = obs
    if history.catalog_add_obs(pid, SOURCE, SOURCE, price, regular, day, None, promo_to):
        res.observations += 1


async def refresh(history: History, fetch: Fetch, directory: Path, *, now: datetime | None = None) -> Result:
    """Pobiera feed i dopisuje zmiany cen; błąd trafia do dziennika (`catalog`), nie do wywołującego."""
    if LOCK.locked():
        return Result(busy=True)
    async with LOCK:
        began = datetime.now()
        day = (now or began).date().isoformat()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = directory / "frisco_feed.json.tmp"
        try:
            await fetch(tmp)
            products = await asyncio.to_thread(_load, tmp)
            if not products:
                raise ValueError("feed bez produktów")
            res = ingest(history, products, day)  # w wątku pętli: wspólne połączenie sqlite, jedna transakcja
        except Exception as err:
            log.exception("Katalog cen: feed Frisco nieudany")
            history.log_event(
                "catalog", "error", "Feed Frisco: błąd", {"error": type(err).__name__, "detail": str(err)}
            )
            return Result(error=f"{type(err).__name__}: {err}")
        finally:
            tmp.unlink(missing_ok=True)
        history.log_event(
            "catalog",
            "ok",
            f"Feed Frisco: {res.products} produktów, {res.observations} nowych cen, {res.skipped} pominięte",
            {"products": res.products, "observations": res.observations, "skipped": res.skipped},
            duration_ms=round((datetime.now() - began).total_seconds() * 1000),
        )
        return res


def seconds_until_weekly(now: datetime) -> float:
    """Czas do najbliższej niedzieli 03:00 (po przebiegu o 03:00 — do kolejnej)."""
    days = (WEEKLY_DAY - now.weekday()) % 7
    target = datetime.combine(now.date(), WEEKLY_AT).replace(tzinfo=now.tzinfo) + timedelta(days=days)
    if target <= now:
        target += timedelta(days=7)
    return (target - now).total_seconds()


async def weekly_loop(
    history: History,
    fetch: Fetch,
    directory: Path,
    *,
    now: Callable[[], datetime] = datetime.now,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Co niedzielę o 03:00 odświeża katalog; błąd jednego przebiegu nie zatrzymuje kolejnych."""
    while True:
        await sleep(seconds_until_weekly(now()))
        try:
            await refresh(history, fetch, directory, now=now())
        except Exception:
            log.exception("Katalog cen: przebieg tygodniowy nieudany")
