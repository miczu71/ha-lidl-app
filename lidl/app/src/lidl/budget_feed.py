"""Dane dla Budżetu Domowego (E6, plan docs/PLAN_E6_budzet.md).

Po każdym imporcie paragonów: nowe produkty bez kategorii idą jednym zapytaniem do modelu (kolejka modeli jak
w gazetkach; bez klucza, przy odmowie albo błędzie zostają „do sprawdzenia” i wracają przy następnym
imporcie),
potem plik `/share/lidl/receipts.json` z paragonami podzielonymi na kategorie produktów — zapis atomowy
(`.tmp` + rename), więc Budżet nigdy nie czyta połowy pliku.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from itertools import islice
from pathlib import Path
from time import monotonic
from typing import Any

import aiohttp

from .accounts import write_json_atomic
from .history import CATEGORIES, History
from .llm import ModelRefused, TryLater, ask_json, log_attempt
from .settings import Settings

log = logging.getLogger(__name__)

NEW_DAYS = 30  # „nowy” produkt = pierwszy zakup w tym oknie; starsze klasyfikuje jednorazowo Claude (E6.2)
MAX_ITEMS = 80  # produktów w jednym zapytaniu
PROMPT = (
    "Przypisz każdy produkt ze sklepu Lidl do jednej kategorii: food (żywność i napoje, też dla zwierząt), "
    "drugstore (kosmetyki, higiena, chemia domowa, papier toaletowy, ręczniki papierowe), kids (pieluszki, "
    "chusteczki i kosmetyki dla dzieci, zabawki, ubranka dziecięce), nonfood (reszta: dom, ogród, narzędzia, "
    'odzież, elektronika, torby). Nazwy są skrócone jak na paragonie. Zwróć JSON {"items": [{"code", '
    '"category"}]} dla wszystkich kodów.\n\n'
)
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                },
                "required": ["code", "category"],
            },
        }
    },
    "required": ["items"],
}


def write_export(history: History, path: Path) -> int:
    """Zapisuje paragony dla Budżetu; zwraca ich liczbę."""
    receipts = history.receipts_export()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, {"version": 1, "receipts": receipts}, 0o644)  # czyta inny add-on
    return len(receipts)


class BudgetFeed:
    def __init__(self, session: aiohttp.ClientSession, history: History, settings: Settings) -> None:
        self._session, self._history, self._settings = session, history, settings
        self.path = settings.share_dir / "lidl" / "receipts.json"
        self._lock = asyncio.Lock()  # import ręczny i poranny mogą skończyć się naraz

    async def refresh(self, today: date | None = None) -> None:
        """Po imporcie: kategorie nowych produktów (opcjonalnie), potem plik — błąd AI nie blokuje pliku."""
        async with self._lock:
            if self._settings.llm_enabled:
                try:
                    await self.classify_new(today or date.today())
                except Exception:
                    log.exception("Kategorie produktów: klasyfikacja nieudana")
            self.export()

    def export(self) -> None:
        """Sam plik (też po ręcznej zmianie kategorii i połączeń). W wątku pętli: History nie jest
        bezpieczne dla wątków (wspólne połączenie SQLite i cache)."""
        try:
            count = write_export(self._history, self.path)
            log.info("Budżet: %d paragonów w %s", count, self.path)
            self._history.log_event(
                "budget", "ok", f"Plik dla Budżetu: {count} paragonów", {"receipts": count}
            )
        except Exception as err:
            log.exception("Budżet: eksport nieudany")
            self._history.log_event("budget", "error", f"Plik dla Budżetu: eksport nieudany ({err})")

    async def classify_new(self, today: date) -> int:
        """Kategorie nowych produktów od modelu; zwraca liczbę zapisanych."""
        new = dict(islice(self._history.uncategorized(today - timedelta(days=NEW_DAYS)).items(), MAX_ITEMS))
        if not new:
            return 0
        content = [{"type": "text", "text": PROMPT + "\n".join(f"{c}: {n}" for c, n in new.items())}]
        s = self._settings
        for model in s.llm_vision_models:
            began = monotonic()
            try:
                payload = await ask_json(
                    self._session, s.llm_url, s.llm_key, model, content, "categories", SCHEMA
                )
                log_attempt(self._history, "kategorie", model, began)
                break
            except (ModelRefused, TryLater) as err:
                log.info("Kategorie produktów: model %s: %s, następny", model, err)
                log_attempt(self._history, "kategorie", model, began, err)
        else:
            log.info("Kategorie produktów: żaden model nie odpowiedział, %d produktów czeka", len(new))
            return 0
        rows = [
            (str(i.get("code")), str(i.get("category")))
            for i in payload.get("items") or []
            if isinstance(i, dict) and i.get("code") in new and i.get("category") in CATEGORIES
        ]
        saved = self._history.set_categories(rows, "ai")
        log.info("Kategorie produktów (%s): %d z %d nowych", model, saved, len(new))
        return saved
