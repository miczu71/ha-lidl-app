# Weryfikacja i poprawka planu K6 — zakładka „Kraje” (ha-lidl-app)

## Context
Wywiad K6 (2026-11-14) zamknięty, plan zapisany w `/config/addons/ha-lidl-app/docs/PLAN_COUNTRIES_K6.md` (niezacommitowany).
User poprosił o weryfikację w trybie planu. Dwa zwiady Explore znalazły w planie błędy, które zepsułyby wynik:
1. **Gramatura:** `pack_size()` rozpoznaje gramaturę tylko w 9 z 82 pozycji fixtures CZ/IT (~11%; brak „ks”, „gr”, „lt”).
   Ustalenie „bez gramatury = poza koszykiem” dałoby koszyk z ~10% pozycji. Do tego `base_name` skleja różne opakowania PL.
   **Nowa decyzja usera (2026-11-14, tryb planu):** para wskazuje konkretny produkt PL, a zatwierdzenie oznacza
   porównywalne opakowanie. Porównanie: ważone zł/kg↔zł/kg; obie gramatury znane → za kg/l; inaczej sztuka↔sztuka.
2. **Prefiltr difflib** nie zadziała dla włoskiego (tłumaczenie, nie podobieństwo pisowni). Zamiast niego LLM dostaje listę produktów PL.
3. **„Sprawdź teraz” przez `/history/resume`** robi pełny import historii (`full=True`), a to za ciężkie na przycisk.
4. **„Wybór innego produktu PL przez istniejącą wyszukiwarkę”** nie istnieje: wyszukiwarki filtrują własne listy stron, katalogu PL nie ma.
5. **Głęboki link z Budżetu:** obejście w `web/templates/base.html:15-21` Lidla obsługuje tylko `/app/<slug>/paragony/<id>`, więc `/kraje` z Budżetu otworzy korzeń panelu.
6. **Hook:** `after=feed.refresh` (`web/app.py:133`). Propozycji par nie wkładamy do `BudgetFeed`; hook będzie złożony.

## Poprawiony plan (zastępuje treść `docs/PLAN_COUNTRIES_K6.md` po zatwierdzeniu)

### Fakty i elementy do ponownego użycia
- `History._price_rows()` (`history.py:1883`) zwraca `(art_id po moście/merges, name, day, cena półkowa, zapłacono, qty, is_weight)` tylko dla PL; z tego liczymy średnią PL. Nie piszemy nowego zapytania z mostem.
- `foreign_items.unit_price` to cena półkowa w walucie kraju (ważone: za kg, `quantity` w kg; `receipt_html.py:23,183`). Kurs: `tickets.fx_rate`.
- `llm.ask_logged(...)` (`llm.py:45`), pętla po `settings.llm_vision_models` i wyjątki `KeyRejected/ModelRefused/TryLater`, jak w `budget_feed.classify_new` (`budget_feed.py:103-124`); `settings.llm_enabled` to property.
- Migracje: `history.py:786-801` (`if version < N: _migrate_vN`), wzorzec kopii w `_migrate_v5` (`:866`); tabela w `_SCHEMA` jako `CREATE TABLE IF NOT EXISTS`.
- Wzorzec POST HTMX + partial: `web/app.py:810-824` (kupony toggle, 303 bez htmx). Testy: `tests/conftest.py:14-21`, seed `test_web.py:86-96`.
- Filtr bez ogonków: `text.matches` (używa go `history.other_products`, `history.py:1434`).

### K6a — dane i propozycje AI (`sonnet-worker`, ryzyko: migracja)
1. Migracja v7 (`SCHEMA_VERSION = 7`, `_migrate_v6(path)` z kopią `<db>.pre-countries-pairs`). Tabela
   `country_pairs(country, foreign_name, status CHECK proposed|approved|rejected, pl_art_id NULL, candidates TEXT JSON [art_id×≤3], decided_at NULL, PK(country, foreign_name))`.
   `foreign_name = base_name(name)` pozycji zagranicznej.
2. `History`: `pair_pending()` (nazwy zagraniczne bez wiersza), `pl_catalog(since)` (z `_price_rows()`: art_id → ostatnia nazwa, ostatnia cena, wydatek; zakupy z 12 mies. przed najstarszą oczekującą pozycją; limit ~600 wg wydatku), `pair_propose/pair_decide/pair_list`.
3. Nowy `pairs.py`: `propose(history, session, settings)`. Porcje ≤40 nazw zagranicznych, a w każdym prompcie lista katalogu PL `id: nazwa`. Odpowiedź JSON `{foreign: [ids ≤3]}`. Zwrócone id spoza katalogu są odrzucane. Zapis `proposed`, pusta lista dozwolona. Błąd/limit LLM → log, nic się nie zapisuje (ponowienie przy następnym przebiegu).
4. Hook w `web/app.py`: `after` = funkcja wołająca `feed.refresh()`, potem `pairs.propose(...)`, gdy `llm_enabled`. Działa po imporcie dziennym, godzinnym (gdy coś przyszło) i ręcznym; idempotentny po `(country, foreign_name)`.
DONE: testy (migracja v6→v7 z kopią; idempotencja; mock LLM → proposed; id spoza katalogu odrzucone; błąd LLM nic nie zapisuje; brak klucza = zero wywołań), ruff/format/mypy, pełny pytest `--deselect tests/test_leaflet.py` bez nowych czerwonych.
NIE RÓB: zmian `items`/`foreign_items`/`packsize.py`, UI, wydań; do LLM idą tylko nazwy produktów.
Rollback: przywrócić `.pre-countries-pairs` albo `DROP TABLE country_pairs; PRAGMA user_version=6`.

### K6b — zakładka „Kraje”, zatwierdzanie, „Sprawdź teraz”
Pliki: `web/app.py`, nowy `web/countries.py`, `templates/countries.html` + `_countries_pair.html`, chip w `base.html` (po „Rytm”), regex głębokiego linku w `base.html:15-21` rozszerzony o `/kraje`, `static/app.css`, `tests/test_web.py`.
1. `GET /kraje`. Sekcja „Do zatwierdzenia”: karta z nazwą zagraniczną, krajem i ceną w PLN, do tego ≤3 kandydatów PL (nazwa z gramaturą, średnia cena) jako przyciski, „bez odpowiednika” i mała wyszukiwarka `GET /kraje/szukaj?q=` po `pl_catalog` (`text.matches`). Sekcje „Zatwierdzone” i „Bez odpowiednika” z możliwością cofnięcia.
2. `POST /kraje/para` (approve z `pl_art_id` / reject / undo; partial HTMX, 303 bez htmx).
3. `POST /kraje/sprawdz`: dla kont z historią `sync.start(slug, full=False, countries=(COUNTRY, *extra))`. Ten sam przebieg co dzienny, propozycje idą przez hook. Odpowiedź: partial „Import trwa…”.
4. Puste stany: brak `extra_countries` / brak klucza LLM (ręczne parowanie przez wyszukiwarkę nadal działa).
5. UI skillem `impeccable` zgodnie z `docs/DESIGN.md`. Weryfikacja Playwright (screenshot + `browser_console_messages`) na dev-serwerze z demo.
DONE: testy web (200, approve/reject/undo, szukaj, sprawdz woła `start` z `full=False`), screenshot bez błędów konsoli.
Rollback: revert commita (tabela zostaje).

### K6c — koszyk porównawczy w PLN
Pliki: `web/countries.py` (czysta funkcja `compare(...)`), `history.py` (odczyt pozycji zagranicznych zatwierdzonych par), szablon sekcji, testy.
1. Cena zagraniczna w PLN = `unit_price × tickets.fx_rate`.
2. Cena PL = średnia ceny półkowej z `_price_rows()` dla `pl_art_id` z 12 mies. przed dniem zakupu zagranicznego (ważona ilością).
3. Tryb porównania: oba ważone → za kg; obie gramatury z `pack_size` → przeliczenie na kg/l; inaczej za sztukę (zatwierdzenie = porównywalne opakowanie). Brak ceny PL w oknie → wiersz „brak ceny PL”, pozycja poza koszykiem.
4. Widok: tabela par (cena PL vs kraj, różnica %, tryb), koszyk per kraj: Σ `qty × cena zagr. PLN` vs Σ `qty × cena PL` w PLN i %, plus pokrycie „X z Y pozycji”.
DONE: testy liczb co do grosza (CZK, EUR, ważone, gramatura, sztuka, brak ceny PL), demo.
Rollback: revert commita.

**Wykonawca (K6c, `sonnet-worker`, ryzyko: pieniądze)** — repo `/config/addons/ha-lidl-app`, kod w `lidl/app/`.
- Skill `addon-conventions`. Test: `cd lidl/app && uv run --extra dev pytest --deselect tests/test_leaflet.py tests/test_countries.py tests/test_history.py tests/test_web.py -q` + `uv run --extra dev ruff check`, `ruff format --check`, `mypy src`. Pełny pytest robi rodzic.
- `history.py` (tylko dopisać, nic nie zmieniać w istniejących metodach):
  - `@dataclass(frozen=True) PairLine`: `country, foreign_name, pl_art_id, name, day: date, quantity, unit_price, fx_rate, is_weight`.
  - `History.pair_lines() -> list[PairLine]`: pozycje `foreign_items` z biletów z `fx_rate IS NOT NULL`, których `(t.country, base_name(i.name))` ma wiersz `country_pairs` ze `status='approved'` i niepustym `pl_art_id`; `quantity > 0 AND unit_price > 0`; sort po dniu.
  - `History.pl_price_history(art_ids: set[str]) -> list[PlPrice]` (`PlPrice`: `art_id, name, day, price, qty, is_weight`) z `self._price_rows()` filtrowane po `art_id`.
  - `History.foreign_line_counts() -> dict[str, int]`: kraj → liczba pozycji `foreign_items` z `fx_rate IS NOT NULL` (mianownik pokrycia „X z Y”).
- `web/countries.py`: czysta funkcja `compare(lines, pl_prices, line_counts) -> Comparison` (bez I/O, `today` niepotrzebne). Dla każdej linii: okno PL = wiersze `pl_prices` tego `pl_art_id` z `day` w `[linia.day − 365 dni, linia.day)`; cena PL = średnia ważona `qty` z `price`; brak wierszy → linia „brak ceny PL”, poza koszykiem. Cena zagr. w PLN = `unit_price × fx_rate`.
  Tryb linii (kolejność): (1) `line.is_weight` i ostatni wiersz okna `is_weight` → `kg`: ceny już za kg, ilość = `quantity`; (2) `pack_size(line.name)` i `pack_size(nazwa PL z ostatniego wiersza okna)` oba znane i ta sama jednostka bazowa `kg`/`l` → `kg`/`l`: cena za jednostkę = cena ÷ ilość opakowania, ilość = `quantity × pack zagr.`; (3) inaczej `szt`: cena i ilość wprost (`quantity`).
  Koszt zagr. = ilość × cena zagr. PLN za jednostkę trybu; koszt PL = ta sama ilość × cena PL za jednostkę trybu. Wynik: wiersze par (grupa `country, foreign_name, tryb`: cena zagr./PL za jednostkę = Σkoszt ÷ Σilość, różnica % = zagr/PL − 1 ×100, zaokr. 1 miejsce) + koszyk per kraj (Σ kosztów zagr. vs PL w PLN po 2 miejscach, różnica %, `covered` = liczba linii w koszyku, `total` = `line_counts[kraj]`) + lista „brak ceny PL” (kraj, nazwa, liczba linii). Kwoty zaokrąglać dopiero na wyjściu. Formatowanie przez `fmt_pln`; dodatni % = za granicą drożej.
- `web/app.py`: `countries_ctx` dopina `comparison` (wołanie `compare(history.pair_lines(), history.pl_price_history({l.pl_art_id …}), history.foreign_line_counts())`).
- Szablon `_countries_body.html`: nowa pierwsza sekcja „Porównanie cen” (karta na kraj: koszyk, różnica %, „X z Y pozycji”; pod nią tabela par: para, cena PL, cena kraj, różnica %, jednostka `/kg` `/l` `/szt`; pod spodem „Bez ceny PL”). Bez zatwierdzonych par: jedno zdanie zachęty. Klasy z `docs/DESIGN.md` i istniejące (`card`, `row2`, `meta`, `s`); `static/app.css` tylko jeśli konieczne, bez inline JS.
- Testy (`tests/test_countries.py`, `tests/test_history.py`, `tests/test_web.py`): `compare` na ręcznych liczbach co do grosza — CZK (kurs np. 0,1755), EUR (4,2), ważone za kg, gramatura g→kg (np. 500 g zagr. vs 1 kg PL), sztuka, brak ceny PL (okno puste, w tym zakup PL z tego samego dnia lub po dniu zakupu = poza oknem), średnia ważona z dwóch zakupów PL, pokrycie „X z Y”; `pair_lines` pomija pary `proposed`/`rejected` i bilety bez kursu; web: `/kraje` z zatwierdzoną parą pokazuje sekcję i % (200).
- DONE: komendy testowe zielone, wyrenderowana sekcja na `/kraje`, liczby w testach policzone ręcznie w komentarzu testu.
- NIE RÓB: zmian migracji/schematu, `items`, `foreign_items`, `country_pairs`, `packsize.py`, `pairs.py`, `budget_feed.py`, istniejących metod `History` (tylko dopisywanie), `settings`, wydań, commitów, plików poza listą (`history.py`, `web/countries.py`, `web/app.py`, `_countries_body.html`, `app.css`, testy).

### K6d — link z Budżetu (`/config/addons/ha-budget-app`, `wt new`)
Przy paragonie zagranicznym w `budget/app/src/budget/web/templates/_txn_category.html:40` (obok „paragon Lidl”) dochodzi link `data-ha-nav` do `{{ lidl_panel }}/kraje` (`lidl_link.LIDL_PANEL`) i test renderu. Działa dopiero razem z regexem z K6b.
Rollback: revert.

### Wydanie zbiorcze (po K6d)
`simplify` → `code-review` + `silent-failure-hunter` + `pr-test-analyzer` + security `general-purpose` (repo + `<baza>..HEAD`) → `claimcheck`/`verifier` → `release` Lidl (minor), potem Budżet → weryfikacja na żywo: zakładka Kraje, „Sprawdź teraz”, link z Budżetu otwiera `/kraje`, konsola czysta, znaczek wersji.

## Kroki implementacji po zatwierdzeniu
1. Nadpisuję `docs/PLAN_COUNTRIES_K6.md` tym planem (kopia z `~/.claude/plans/`) i poprawiam wiersz K6 w `ROADMAP_countries.md`: decyzja „para = konkretny produkt PL, porównywalne opakowanie” zastępuje „base_name” i „brak gramatury = poza koszykiem”. Commit docs.
2. K6a → K6b → K6c → K6d po kolei, każdy: `wt new /config/addons/<repo> <slug>`, worker z sekcją Wykonawca, `verifier`, commit, `stage-end`.

## Weryfikacja
- Każdy etap: `cd lidl/app && uv run pytest --deselect tests/test_leaflet.py`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src` (Budżet: komenda z jego CI).
- K6b/K6c: dev-serwer na demo z seedem PL + CZ/IT, Playwright screenshot + konsola.
- Na żywo po wydaniu: `/kraje` przez ingress, propozycje po „Sprawdź teraz” (4 paragony / 93 pozycje), zatwierdzenie kilku par → koszyk z pokryciem; link z Budżetu.
