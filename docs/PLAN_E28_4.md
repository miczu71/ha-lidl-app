# PLAN E28.4 — porównanie cen Lidl ↔ Biedronka (zakładka „Sieci”)

Źródło prawdy: `docs/ROADMAP.md` (E28), `docs/PLAN_E28_biedronka.md`. Stan wejściowy: add-on 1.3.0 (E28.2) i Budżet 0.77.0
(E28.3). Commit `c659164`, schemat v8. **Wydanie 1.4.0** po tym etapie (w planach stoi 0.25.0, numer jest nieaktualny).

## Context
Gdy obie sieci są już w bazie, user chce wiedzieć, gdzie kupuje taniej i ile by oszczędził, kupując dany produkt w tańszej
sieci. Spike E28.0: 18 z 81 produktów Biedronki ma EAN wspólny z Lidlem (22%). Resztę par musi zaproponować AI, a user je zatwierdza.

## Decyzje (wywiad 2026-11-19)
- Ten sam EAN → para **zatwierdzona automatycznie** (`source='ean'`), w UI można ją cofnąć.
- **Nowa zakładka „Sieci”** (`/sieci`). Wzorzec kodu skopiowany z K6 (Kraje), bez łączenia tabel i bez refaktoru K6. Chip i trasa
  są widoczne tylko przy ≥2 sieciach w bazie (`has_chains()`).
- Cena w parze: dla każdej sieci **ostatni zakup + mediana z 3 mies.**. Gdy w 3 mies. nie ma zakupu, mediana z 12 mies. z dopiskiem
  „12 mies.”. Jednostka: kg/l/szt jak w K6 (oba produkty ważone → kg, obie gramatury z `pack_size` → kg/l, inaczej szt).
- **Oszczędność z faktycznych zakupów** za 12 mies., w obie strony: Σ po zakupach zatwierdzonych par
  `ilość × (cena zapłacona za jednostkę − mediana tańszej sieci)`, ale tylko gdy druga sieć jest tańsza. Do tego pokrycie
  „X z Y produktów Biedronki w parach” i „objęte N zł z M zł wydatków”.
- Kierunek parowania: **produkt Biedronki → produkt Lidla**. Biedronka ma mało produktów, a katalog Lidla jest duży.
- Bez nowych pushy.

## Fakty z rozpoznania (do ponownego użycia)
- Wzorzec K6: `pairs.py` (`propose`, `CHUNK=40`, `MAX_CANDIDATES=3`, `_ask` z pętlą po `settings.llm_vision_models`,
  `KeyRejected` przerywa pętlę), `History.pair_pending/pair_propose/pair_decide/pair_list` (`history.py:1983-2051`),
  `pl_catalog` (`:2011`), trasy `/kraje*` (`web/app.py:892-960`), `web/countries.py:141` `compare`, testy `test_pairs.py` i `test_countries.py`.
- Kody: Biedronka `b:<EAN>` (`receipt_biedronka.py:42`). Lidl NATIVE `n:<EAN|PLU>` (`receipt_native.py:27`), kody HTML Lidla nie są
  EAN-ami. `_resolver` (`history.py:1186`) mapuje `n:` przez `merges` albo unikalną nazwę na kod HTML. **EAN łączy się więc tylko tak:**
  `b:<EAN>` → `n:<EAN>` istnieje w `items` → `lidl_art_id = resolver(n:<EAN>)`.
- `_price_rows(chain)` (`history.py:~1968`) zwraca `(art_id po moście, name, day, cena półkowa, zapłacono, qty, is_weight)` per sieć.
- Kategorie: `product_category(art_id, category)` (`history.py:205`), `category_of` (`:1221`).
- Migracje: `SCHEMA_VERSION = 8` (`:57`), łańcuch w `__init__` (`:836-858`), kopia `.pre-<nazwa>` jak w `_migrate_v7` (`:954`).
- Sieci w widoku: `text.CHAIN_LABELS`, `web/receipts.chain_pills`. Chipy: `base.html:27-36`. Regex głębokiego linku: `base.html:16`.
- Uwaga (K6, poza zakresem, do raportu): `pl_catalog` bez filtra sieci zawiera także kody `b:`, więc kandydatami w Krajach mogą być produkty Biedronki.

## Podetapy
### E28.4.0 docs (robię sam)
Kopia tego planu do `docs/PLAN_E28_4.md`. W `ROADMAP.md` i `PLAN_E28_biedronka.md` zmieniam numery wydań: E28.4 → 1.4.0,
E28.5 → 1.5.0. Commit docs.

### E28.4.1 dane i propozycje (`sonnet-worker`, ryzyko: migracja) — Wykonawca niżej
Rollback: przywrócić `history.db.pre-chain-pairs` albo `DROP TABLE chain_pairs; PRAGMA user_version=8` i revert commita.

### E28.4.2 zakładka „Sieci”: zatwierdzanie (robię sam: UI, `impeccable`, Playwright 390/1280 px)
Pliki: `web/app.py`, nowy `web/chains.py` (kontekst widoku), `templates/chains.html` + `_chains_body.html` + `_chains_search.html`,
chip „Sieci” po „Kraje” w `base.html` (tylko przy ≥2 sieciach), regex `base.html:16` rozszerzony o `/sieci`, `static/app.css`
(akcenty `.chain-tag` z D2), testy `tests/test_chains.py`.
1. `GET /sieci`: sekcja „Do zatwierdzenia” (karta produktu Biedronki z ceną, ≤3 kandydatów z Lidla jako przyciski, „bez odpowiednika”,
   wyszukiwarka `GET /sieci/szukaj?q=` po katalogu Lidla przez `text.matches`). Sekcje „Zatwierdzone” (znacznik „EAN” / „AI” / „ręcznie”)
   i „Bez odpowiednika”, obie z cofnięciem. Przy jednej sieci → 404.
2. `POST /sieci/para` (approve z `lidl_art_id` / reject / undo; partial HTMX, 303 bez htmx). Cofnięcie pary EAN → `rejected`,
   żeby auto-parowanie nie przywróciło jej przy następnym imporcie.
3. Puste stany: brak klucza LLM (wtedy działa ręczne parowanie i EAN).
DONE: testy web (200/404, approve/reject/undo, undo EAN → nie wraca po `propose`, szukaj), zrzut bez błędów konsoli.
Rollback: revert commita.

### E28.4.3 porównanie i oszczędność (`sonnet-worker`, ryzyko: pieniądze) — Wykonawca niżej
Rollback: revert commita.

### E28.4.4 wydanie 1.4.0
`simplify` → `code-review` + `silent-failure-hunter` + `pr-test-analyzer` + security `general-purpose` (repo + `c659164..HEAD`)
→ `claimcheck` → `release` (minor 1.4.0, backup add-onu przed aktualizacją) → weryfikacja na żywo: `/sieci` przez Ingress,
pary EAN obecne bez klucza, propozycje AI po imporcie, zatwierdzenie 2–3 par → kwoty, konsola czysta, 390 px.
**Pomiar do ROADMAP:** pokrycie EAN/AI/ręczne i odsetek objętych wydatków.

## Wykonawca (E28.4.1)
**Repo:** `/config/addons/ha-lidl-app`, worktree `wt new /config/addons/ha-lidl-app e28-4-1` (podany jako `WORKTREE:`). Kod w `lidl/app`.
Skill `addon-conventions`. TDD. Test: `cd <WORKTREE>/lidl/app && uv run --extra dev pytest -q --deselect tests/test_leaflet.py`
oraz `uv run --extra dev ruff check . && uv run --extra dev ruff format --check . && uv run --extra dev mypy src`.

1. `src/lidl/history.py`:
   - `SCHEMA_VERSION = 9`, `_migrate_v8(path)` z kopią `<db>.pre-chain-pairs` (wzorzec `_migrate_v7`). Tabela w `_SCHEMA`:
     `chain_pairs(b_art_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK(status IN ('proposed','approved','rejected')),
     lidl_art_id TEXT, source TEXT CHECK(source IN ('ean','ai','manual')), candidates TEXT NOT NULL DEFAULT '[]', decided_at TEXT)`.
   - `chain_catalog(chain: str, limit=600) -> list[CatalogItem]`: jak `_pl_catalog`, ale z `_price_rows(chain=chain)`. `pl_catalog` zostaje bez zmian.
   - `chain_pending() -> list[tuple[str, str]]`: `(b_art_id, nazwa)` produktów Biedronki z 365 dni bez wiersza `chain_pairs`.
   - `ean_matches(b_ids) -> dict[str, str]`: dla `b:<EAN>` (EAN = 8–14 cyfr), gdy w `items` jest `n:<EAN>` → `resolver(n:<EAN>)`.
   - `chain_pair_propose(b_id, candidates)` (INSERT OR IGNORE, `proposed`, `source='ai'`), `chain_pair_approve(b_id, lidl_id, source)`
     (UPSERT, `decided_at`), `chain_pair_decide(b_id, action, lidl_id=None)` (approve→`manual` / reject / undo→`proposed`; undo pary `ean` → `rejected`),
     `chain_pair_list() -> list[ChainPair]` (dataclass: b_art_id, b_name, status, lidl_art_id, lidl_name, source, candidates).
2. Nowy `src/lidl/chain_pairs.py`: `async def propose(history, session, settings) -> int`.
   (a) EAN: `ean_matches(pending)` → `chain_pair_approve(..., source='ean')`. Działa bez klucza LLM.
   (b) gdy `settings.llm_enabled`: reszta w porcjach `CHUNK=40`, w prompcie katalog Lidla `id: nazwa` („produkty z Biedronki;
   wybierz ≤3 odpowiedniki z Lidla o porównywalnym opakowaniu, pusta lista gdy brak”), schemat JSON jak `pairs.SCHEMA`,
   `ask_logged(history, "pary-sieci", …, "chain_pairs", SCHEMA)`. Id spoza katalogu odrzucane. Błąd LLM → log, nic się nie zapisuje.
   Do LLM idą tylko nazwy produktów.
3. `src/lidl/web/app.py` `after_import`: po `pairs.propose` osobny try/except z `chain_pairs.propose`, tylko gdy `history.has_chains()` ≥2.
4. Testy: `tests/test_chain_pairs.py` (EAN auto bez klucza; `n:` przez merges/most → kod HTML; mock LLM → proposed; id spoza katalogu;
   błąd LLM nic nie zapisuje; idempotencja; undo EAN → rejected i nie wraca), `tests/test_history.py` (migracja v8→v9 z kopią;
   `chain_catalog` nie zawiera `b:`), `tests/test_countries.py`/`test_web.py`: hook woła oba propose. Nazwy testowe neutralne („Mleko 1l”).

DONE: komendy testowe zielone, nowe testy czerwone przed kodem, `git diff --stat` tylko pliki z listy.
NIE RÓB: zmian `pairs.py`, `pl_catalog`, `country_pairs`, `items`, `packsize.py`, `budget_feed.py`, UI/szablonów, `client/`, `sync.py`;
commitów; wydań; dotykania `tests/test_leaflet.py`.

## Wykonawca (E28.4.3)
Repo i komendy jak w E28.4.1 (worktree `e28-4-3`).
1. `history.py` (tylko dopisać): `chain_price_rows(art_ids: set[str]) -> list[PlPrice]` łączy `_price_rows(chain='lidl')`
   i `_price_rows(chain='biedronka')` filtrowane po `art_id` (`PlPrice` z K6 + pole `chain`). Kategoria z `category_of(lidl_art_id)`,
   a gdy jej brak, z `category_of(b_art_id)`.
2. `web/chains.py`: czysta `compare(pairs, rows, categories, today) -> ChainComparison` (bez I/O).
   - Jednostka pary: obie ostatnie pozycje `is_weight` → kg; obie `pack_size` znane w tej samej jednostce kg/l → kg/l (cena ÷ ilość opakowania);
     inaczej szt. Logikę trybu brać z `web/countries.py`, jeśli jest tam osobna funkcja; jeśli nie, napisać lokalną i nie ruszać `countries.py`.
   - Per sieć: `last` = cena półkowa za jednostkę z ostatniego zakupu; `median` = mediana cen za jednostkę z `[today−90 d, today]`,
     a gdy pusto, z `[today−365 d, today]` z flagą `wide=True`; brak zakupów w 365 d → para w „Bez ceny”.
   - Tańsza sieć = mniejsza `median`; różnica % = droższa/tańsza − 1.
   - Oszczędność (12 mies.): dla każdego zakupu pary w sieci X: gdy `median(Y) < cena zapłacona za jednostkę`, dodaj
     `ilość × (zapłacona − median(Y))`. Zapłacona za jednostkę = `paid ÷ qty`, a dla kg/l z gramaturą także ÷ opakowanie. Suma per sieć i łącznie.
   - Pokrycie: produkty Biedronki z 365 d w zatwierdzonych parach / wszystkie; wydatki objęte parami / wydatki obu sieci w 12 mies.
   - Filtr `category` (None = wszystkie). Zaokrąglać dopiero na wyjściu.
3. `web/app.py` `/sieci`: kontekst dopina `comparison` i `?kat=` (food/drugstore/kids/nonfood, nieznana wartość = brak filtra).
   Szablon `_chains_body.html`: pierwsza sekcja „Porównanie” (KPI: oszczędność łącznie i per sieć, pokrycie; tabela: produkt,
   Lidl ostatnia/mediana, Biedronka ostatnia/mediana, jednostka, różnica %, tańsza sieć z `.chain-tag`; „Bez ceny”). Klasy z `docs/DESIGN.md`, bez inline JS.
4. Testy `tests/test_chains.py`: liczby co do grosza policzone ręcznie w komentarzu (kg ważone, gramatura 500 g vs 1 kg, sztuka,
   mediana parzysta i nieparzysta, fallback 12 mies., brak ceny, oszczędność w obie strony, zakup tańszy niż mediana drugiej sieci = 0,
   filtr kategorii, pokrycie); web: `/sieci` z zatwierdzoną parą pokazuje kwoty (200).

DONE: komendy zielone, sekcja wyrenderowana. NIE RÓB: zmian schematu, `chain_pairs.py`, istniejących metod `History`,
`countries.py`, `packsize.py`; commitów; wydań; plików spoza listy (`history.py`, `web/chains.py`, `web/app.py`, `_chains_body.html`, `app.css`, testy).

## Kroki po zatwierdzeniu
E28.4.0 → 4.1 (worker → `claimcheck` → `verifier` → commit → `stage-end`) → 4.2 (ja) → 4.3 (worker → verifier) → 4.4 wydanie bez przerw.
Pasek: `title: "Lidl E28.4.<n>"`.

## Weryfikacja
- Każdy podetap: pytest `--deselect tests/test_leaflet.py`, ruff, format, mypy.
- 4.2/4.3: dev-serwer na demo z seedem obu sieci (`~/lidl_dev/…`), Playwright screenshot 390/1280 px + `browser_console_messages`.
- Na żywo po 1.4.0: jak w E28.4.4, wyniki pomiaru pokrycia trafiają do `ROADMAP.md`.
