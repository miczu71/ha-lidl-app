"""Promocje z cotygodniowej gazetki przez model wizyjny (E4.3; próby i wyniki w docs/PLAN_E4_gazetki.md).

- Gazetka: z publicznego `v4/overview` pozycje „Gazetka” (jedna na tydzień); JSON gazetki daje obrazy stron.
- Strony idą do modelu paczkami po `BATCH` obrazów razem z listą „Kupowane regularnie” (włączone); model
  wypisuje oferty na te produkty. Darmowe limity liczą zapytania, nie obrazy (Gemini Flash: 20 na dzień
  i model), więc cała gazetka to ok. 20 zapytań.
- Kolejka modeli (`llm_vision_models`): limit albo odmowa (4xx) wyłącza model do wyczerpania wszystkich;
  przeciążenie (5xx), sieć albo zły klucz → następny model, a gdy żaden nie odpowie — ta sama paczka
  za `RETRY`. Postęp jest w bazie (restart nie marnuje limitów).
- Kupony Lidl Plus z gazetki pomijamy — aktywuje je E3.
- Strony bez spożywczych ofert (informacje, porównania cen z konkurencją, odzież, narzędzia, dom, rośliny,
  znicze) odpadają po opisie strony `altText` przed wysłaniem — mniej zapytań do limitu (E22.4). Drogeria
  zostaje (na liście są ręczniki, papier toaletowy). Wzorzec tylko z pewnych słów: wątpliwa strona zostaje.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp

from .history import History
from .promotions import Promotion
from .settings import Settings

log = logging.getLogger(__name__)

OVERVIEW_URL = "https://endpoints.leaflets.schwarz/v4/overview"
OVERVIEW_PARAMS = {"client_locale": "lidl/pl-PL"}
LEAFLET_NAME = "Gazetka"
NON_FOOD = re.compile(
    r"^(informacja|reklama|kampania|ekologiczna inicjatywa)\b|^strona \d+ - "
    r"|porówna|analiz\w* (porównawcz|cenow)|zestawienie cenowe"
    r"|odzież|\bbut(y|ów)\b|doniczk|znicz|zabawk|bielizn|piżam|swet(er|r)|jeans|kurtk|skarpet|mebl|dekorac"
    r"|parkside|silvercrest|livarno|crivit|esmara|ernesto|auriol|melinera|florabest|playtive|odkurzacz|narzędz",
    re.IGNORECASE,
)
BATCH = 5
PAUSE = 120  # s między zapytaniami do modelu
IDLE = 3600  # s między sprawdzeniami nowej gazetki, gdy nic nie czeka
RETRY = timedelta(minutes=10)
EXHAUSTED = timedelta(hours=6)
MAX_ATTEMPTS = 30
LLM_TIMEOUT = aiohttp.ClientTimeout(total=180)

SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "page": {"type": "integer"},
                    "leaflet_name": {"type": "string"},
                    "discount": {"type": "string"},
                    "valid_from": {"type": "string"},
                    "valid_to": {"type": "string"},
                    "lidl_plus_coupon": {"type": "boolean"},
                },
                "required": ["code", "page", "leaflet_name", "discount", "lidl_plus_coupon"],
            },
        }
    },
    "required": ["matches"],
}

PROMPT = """Jesteś asystentem zakupowym. Dostajesz strony polskiej gazetki Lidl i listę produktów, które
kupujemy (kod: nazwa skrócona z paragonu). Wypisz TYLKO te oferty z gazetki, które dotyczą produktu z listy —
ten sam produkt (np. „Banany, luzem” = „Banany luz”), nie podobny ani z tej samej kategorii. Oferta obejmująca
grupę („Wszystkie czekolady X”) pasuje tylko, gdy nasz produkt należy do tej grupy (ta sama marka). Dla każdej
podaj kod z listy, numer strony, nazwę z gazetki, rabat/mechanikę (np. „-38%”, „1+1 gratis”, „-20% przy
zakupie 2”), daty (DD.MM) i czy wymaga kuponu Lidl Plus („Aktywuj kupon”, „Zeskanuj aplikację”, logo
Lidl Plus). Odpowiedz wyłącznie JSON-em zgodnym ze schematem. Gdy nic nie pasuje: {"matches": []}.

Nasze produkty:
"""


@dataclass(frozen=True)
class Flyer:
    id: str
    json_url: str
    start: date
    end: date


class ModelRefused(Exception):
    """Model odmówił (limit, brak obsługi obrazów, za duże zapytanie) — spróbuj następnego."""


class TryLater(Exception):
    """Przeciążenie albo sieć — ta sama paczka później."""


def find_flyers(overview: dict[str, Any]) -> list[Flyer]:
    out = []
    for category in overview.get("categories") or []:
        for sub in category.get("subcategories") or [category]:
            for f in sub.get("flyers") or []:
                if f.get("name") == LEAFLET_NAME and f.get("flyerJson"):
                    start = date.fromisoformat(str(f.get("offerStartDate") or f["startDate"])[:10])
                    end = date.fromisoformat(str(f.get("offerEndDate") or f["endDate"])[:10])
                    out.append(Flyer(str(f["id"]), str(f["flyerJson"]), start, end))
    return out


def page_batches(flyer: dict[str, Any]) -> list[list[Any]]:
    pages = [
        [p["number"], p["image"]]
        for p in (flyer.get("flyer") or {}).get("pages") or []
        if p.get("image") and not NON_FOOD.search(p.get("altText") or "")
    ]
    return [pages[i : i + BATCH] for i in range(0, len(pages), BATCH)]


def _day(text: Any, default: date) -> date:
    """„8.10” / „08.10” → data w roku gazetki (koniec roku: styczeń w gazetce grudniowej to kolejny rok)."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})", str(text or ""))
    if not m:
        return default
    try:
        d = date(default.year, int(m.group(2)), int(m.group(1)))
    except ValueError:
        return default
    return d.replace(year=d.year + 1) if d < default - timedelta(days=180) else d


def parse_matches(
    payload: dict[str, Any], codes: set[str], pages: set[int], start: date, end: date
) -> list[Promotion]:
    """Oferty z odpowiedzi modelu; kody spoza listy, strony spoza paczki i kupony Lidl Plus odpadają."""
    return [
        Promotion(
            m["code"],
            str(m.get("leaflet_name") or ""),
            str(m.get("discount") or ""),
            _day(m.get("valid_from"), start),
            _day(m.get("valid_to"), end),
        )
        for m in payload.get("matches") or []
        if m.get("code") in codes and m.get("page") in pages and not m.get("lidl_plus_coupon")
    ]


class LeafletRunner:
    def __init__(self, session: aiohttp.ClientSession, history: History, settings: Settings) -> None:
        self._session, self._history = session, history
        self._url, self._key, self._models = settings.llm_url, settings.llm_key, settings.llm_vision_models
        self._refused: set[str] = set()  # modele z wyczerpanym limitem (limity są per model, nie per paczka)
        self._checked: datetime | None = None

    async def run_forever(self) -> None:
        while True:
            try:
                busy = await self.step()
            except Exception:
                log.exception("Gazetka: przebieg nieudany")
                busy = False
            idle = RETRY.total_seconds() if self._history.has_pending_leaflet() else IDLE
            await asyncio.sleep(PAUSE if busy else idle)

    async def step(self, now: datetime | None = None) -> bool:
        """Sprawdza nowe gazetki (co `IDLE`) i przetwarza jedną paczkę; True, gdy paczka była do zrobienia."""
        now = now or datetime.now()
        if self._checked is None or now - self._checked >= timedelta(seconds=IDLE):
            self._checked = now
            await self._discover()
        batch = self._history.next_leaflet_batch(now.isoformat())
        if batch is None:
            return False
        await self._process(batch, now)
        return True

    async def _discover(self) -> None:
        async with self._session.get(OVERVIEW_URL, params=OVERVIEW_PARAMS) as r:
            r.raise_for_status()
            flyers = find_flyers(await r.json(content_type=None))
        for f in flyers:
            if self._history.has_leaflet(f.id):
                continue
            async with self._session.get(f.json_url) as r:
                r.raise_for_status()
                batches = page_batches(await r.json(content_type=None))
            self._history.add_leaflet(f.id, batches, f.start, f.end)
            pages = sum(map(len, batches))
            log.info("Gazetka %s (%s–%s): %d stron w %d paczkach", f.id, f.start, f.end, pages, len(batches))

    async def _process(self, batch: dict[str, Any], now: datetime) -> None:
        fid, n, pages = batch["flyer_id"], batch["batch"], batch["pages"]
        candidates = self._history.enabled_candidates(now.date())
        try:
            content = await self._content(candidates, pages)
        except TryLater as err:
            self._retry(batch, now, err)
            return
        overloaded: TryLater | None = None
        for model in [m for m in self._models if m not in self._refused]:
            try:
                payload = await self._ask(model, content)
                break
            except ModelRefused as err:
                log.info("Gazetka %s/%d: model %s odmówił (%s), następny", fid, n, model, err)
                self._refused.add(model)
            except TryLater as err:  # przeciążenie jednego modelu — inny może być wolny
                log.info("Gazetka %s/%d: model %s: %s, następny", fid, n, model, err)
                overloaded = err
        else:
            if overloaded:
                self._retry(batch, now, overloaded)
                return
            self._refused.clear()  # limity wszystkich modeli wyczerpane — za kilka godzin znów od pierwszego
            later = now + EXHAUSTED
            self._history.set_leaflet_batch(fid, n, "pending", batch["attempts"], later.isoformat())
            log.info(
                "Gazetka %s/%d: wszystkie modele odmówiły, ponowię o %s", fid, n, later.strftime("%H:%M")
            )
            return
        start, end = date.fromisoformat(batch["start"]), date.fromisoformat(batch["end"])
        promos = parse_matches(payload, {c.art_id for c in candidates}, {p[0] for p in pages}, start, end)
        self._history.save_leaflet_matches(fid, promos)
        self._history.set_leaflet_batch(fid, n, "done", batch["attempts"], "")
        log.info("Gazetka %s/%d (%s): %d trafień", fid, n, model, len(promos))

    def _retry(self, batch: dict[str, Any], now: datetime, err: TryLater) -> None:
        """Ta sama paczka za `RETRY`; po `MAX_ATTEMPTS` próbach odpuszczamy."""
        attempts = batch["attempts"] + 1
        later = now + RETRY
        status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
        self._history.set_leaflet_batch(
            batch["flyer_id"], batch["batch"], status, attempts, later.isoformat()
        )
        log.info(
            "Gazetka %s/%d: %s, ponowię o %s (próba %d)",
            batch["flyer_id"], batch["batch"], err, later.strftime("%H:%M"), attempts,
        )  # fmt: skip

    async def _content(self, candidates: list[Any], pages: list[list[Any]]) -> list[dict[str, Any]]:
        listing = PROMPT + "\n".join(f"{c.art_id}: {c.name}" for c in candidates)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": listing + f"\n\nPoniżej {len(pages)} stron gazetki; przed każdym obrazem jego numer.",
            }
        ]
        for number, url in pages:
            try:
                async with self._session.get(url) as r:
                    r.raise_for_status()
                    image = base64.b64encode(await r.read()).decode()
            except (aiohttp.ClientError, TimeoutError) as err:
                raise TryLater(f"obraz strony {number}: {type(err).__name__}") from err
            content.append({"type": "text", "text": f"STRONA {number}:"})
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}})
        return content

    async def _ask(self, model: str, content: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "matches", "schema": SCHEMA}},
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            async with self._session.post(
                f"{self._url}/chat/completions", json=body, headers=headers, timeout=LLM_TIMEOUT
            ) as r:
                if r.status >= 500:
                    raise TryLater(f"HTTP {r.status}")
                if r.status in (401, 403):  # zły klucz — to błąd konfiguracji, nie limit modelu
                    raise TryLater(f"klucz odrzucony (HTTP {r.status}), sprawdź opcję llm_key")
                if r.status >= 400:
                    raise ModelRefused(f"HTTP {r.status}")
                out = await r.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TryLater(type(err).__name__) from err
        text = ((out.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        try:
            payload = json.loads(text)
        except ValueError as err:
            raise TryLater("odpowiedź nie jest JSON-em") from err
        return payload if isinstance(payload, dict) else {}
