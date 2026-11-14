# PLAN D1 — spłata długu K1–K5 (bez wydania)

Wartość: kraje zagraniczne nie głodzą się przy klasyfikacji, usunięty kraj nie jest odpytywany, miesięczne powiadomienie
mówi o zagranicy, a luki testowe K1–K5 są zamknięte. Wydanie dopiero po K6.

## Kroki
1. **Kod (zrobione przeze mnie, `main` w repo Lidl):**
   - `budget_feed._capped`: zagraniczne pozycje (`CZ:…`) dostają ≥ połowę z `MAX_ITEMS`, gdy czekają (zamiast `islice` po PL).
   - `History.pending_foreign_details(account, countries)`: filtr `country IN (...)`; `sync.py` przekazuje `countries` przebiegu
     (kraj usunięty z `extra_countries` przestaje być odpytywany, jego paragony zostają w bazie).
   - `notify.compose_month`: linia „W tym za granicą: X zł (CZ, IT)” gdy `abroad_total > 0` (format jak w Miesiącach).
2. **Testy Lidl (Wykonawca W1)**, 3. **testy Budżet (ja)**.
4. Pełne testy + ruff + mypy, `simplify` NIE (przed wydaniem), commit(y), push, ROADMAP, `stage-end`.

Rollback: `git revert` commitów D1 (nic nie zmienia schematu ani danych, wydania nie ma).

## Wykonawca W1 — repo Lidl (`haiku-worker`, worktree `wt new ha-lidl-app d1-tests`)
Tylko dopisywanie testów w `lidl/app/tests/`; kod `src/` NIE jest do zmiany (jeśli test wykaże błąd w `src/`, zgłoś, nie naprawiaj).
Komenda: `cd <WORKTREE>/lidl/app && PATH=$HOME/.local/bin:$PATH uv run --extra dev pytest -q --deselect tests/test_leaflet.py` (+ `ruff check .`, `ruff format --check .`, `mypy src`).
Testy (po jednym lub kilku przypadkach; wzoruj się na sąsiednich testach w pliku):
1. `tests/test_service.py`: `_api(slug, country)` buduje klienta z `language` z `COUNTRY_LANGUAGE` (CZ→cs-CZ, IT→it-IT, nieznany→en-GB) i cache'uje per `(slug, country)`;
   `_drop_apis(slug)` kasuje klientów wszystkich krajów tylko tego konta (drugie konto zostaje); callback `save_tokens` zapisuje tokeny w `AccountStore` i czyści cache.
   Klienta nie łącz z siecią (`LidlPlusApi` nie wołamy; sprawdź atrybuty/podmień klasę przez monkeypatch).
2. `tests/test_fx.py`: `_http_fetch` — brak sesji → `None`; status ≠ 200 → `None` + ostrzeżenie w logu; wyjątek `aiohttp.ClientError`/`TimeoutError` → `None`; poprawny JSON-dict → dict; JSON nie-dict → `None`. Sesję podstaw atrapą z `get()` jako async context manager.
3. `tests/test_addon_config.py` albo nowy `tests/test_settings.py`: `settings._countries`: `["cz"," it ","PL","CZ","xyz","1a"]` → `("CZ","IT")`; nie-lista → `()`; `load_settings` czyta `extra_countries` z pliku opcji (`LIDL_OPTIONS_PATH` w `tmp_path`).
4. `tests/test_history.py`: migracja wielostopniowa — baza v2 (jak w teście `test_v2_database_is_migrated…`) otwarta nowym kodem kończy na `SCHEMA_VERSION`, ma kopię `.pre-countries`, kolumny `country/currency/total_orig/fx_rate` i tabele `fx_rates`, `foreign_items`; dane z v2 zachowane.
5. `tests/test_history.py`: `pending_foreign_details("a", countries)` — kraj spoza listy (np. IT przy `("CZ",)`) pomijany, pusta lista/`("PL",)` → `[]`, paragon PL nigdy.
6. `tests/test_budget_feed.py`: `_capped` / `classify_new` — 100 polskich + 10 zagranicznych oczekujących: wynik ma ≤ `MAX_ITEMS`, zawiera wszystkie 10 zagranicznych; 5 zagranicznych + 100 PL → 5 zagranicznych i `MAX_ITEMS-5` PL; same PL bez zmiany (pierwsze `MAX_ITEMS`).
7. `tests/test_notify.py`: `compose_month` z `abroad_total=… , abroad_countries=("CZ","IT")` zawiera linię „W tym za granicą”; bez zagranicy (0) jej nie ma.
8. `tests/test_sync.py`: przebieg z `countries=("CZ",)` nie pobiera szczegółów paragonu IT już zapisanego w bazie (kraj poza listą).
DONE: wszystkie nowe testy zielone, pełny pytest zielony (poza 13 starymi z `test_leaflet.py`), ruff/format/mypy czyste; w raporcie lista dodanych testów.
NIE RÓB: zmian w `src/`, w `tests/test_leaflet.py`, w `docs/`, commitów; nie rozszerzaj zakresu poza listę.
