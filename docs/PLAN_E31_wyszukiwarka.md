# E31 — Wspólna wyszukiwarka (paragony, produkty, katalog Biedronki/Lidla, kupony, oferty)

## Context
Po E30 (1.8.0) stan półki Biedronki widać tylko dla produktów obserwowanych albo z zatwierdzoną parą. User chce
wpisać nazwę dowolnego produktu, także nigdy niekupionego, i w jednym miejscu zobaczyć, czy jest w Biedronce/Lidlu
i za ile. Każdy wynik ma mieć logo sieci.

Decyzje z wywiadu (2026-11-21):
- jedno pole „Szukaj” w nagłówku każdej zakładki;
- produkt już kupowany: znacznik „kupowane 7× · ostatnio 12.11 · 4,99 zł”; niekupiony bez znacznika;
- zakres: paragony, produkty, katalog Biedronki i Lidla, kupony i oferty, w jednej liście;
- Biedronka: stan półki i cena na żywo dopiero po kliknięciu wyniku (2 zapytania);
- Lidl: oferta z gazetki i cena, bez stanu półki;
- źródło EAN Biedronki dla nieznanych produktów: najpierw spike API;
- logo: oficjalne logotypy SVG (warunek: licencja/zasady znaków przed commitem do repo PUBLIC).

Fakty z kodu:
- Klient Biedronki (`client/biedronka.py`, `API_BASE …/api/v7`) zna tylko ścieżki po EAN albo id
  (`products/price|stock/{sklep}/{ean}/`). Kandydat na wyszukiwanie to `GET products/search/{query}/` w
  `~/dev/biedronka-spike/vendor/biedronka/api.py:296`, nigdy niesprawdzony.
- Lokalne źródła już istnieją: `history.ranking(query=)` (`history.py:1653`), `history.other_products`
  (`:1747`), `web/chains.py:71 search` (katalog Lidla z `chain_catalog`, bez EAN/oferty), `coupon_rows` +
  `matches` (`text.py:33`), promocje i gazetka w `promotions.py` (dziś poza filtrem).
- Obserwowanie: `POST /kupony/produkt/{art_id}/obserwuj` → `set_watched` (`history.py:1775`); `watched_eans`
  (`shelf_prices.py:40`) bierze `b:`/`n:` + EAN, więc gwiazdka na `b:<EAN>` od razu włącza poranny odczyt półki.
- Odczyt ceny i stanu: `parse_price`, `parse_stock` (`shelf_prices.py`) do ponownego użycia.
- UI: `base.html:25` blok `bar`; makro `search_input` ma na sztywno `id="q"`, a `test_web.py:522` wymaga
  jednego `id="q"`, więc pole w nagłówku dostaje własne id (`szukaj`).

## Etapy (każdy commit na `main`, jedno wydanie 1.9.0 na końcu)

**E31.0 Docs:** `docs/ROADMAP.md` punkt E31, `docs/PLAN_E31_wyszukiwarka.md` z krokami i rollbackiem, `CONTEXT.md`
(słownik: wynik wyszukiwania, źródło, sieć, stan półki, oferta). Rollback: `git revert`.

**Skąd produkty niekupione (stan dziś):** „katalog sieci” w add-onie (`history.chain_catalog`,
`history.py:2244`) to tylko produkty z paragonów z 12 miesięcy, więc nie zawiera niczego niekupionego. Dziś
niekupione znamy tylko z ofert:
- Lidl: promocje lidl.pl (~157 pozycji), gazetka (odczyt AI), oferty Lidl Plus i kupony;
- Biedronka: oferty z karuzeli (`product_main_ean_code`) i kupony.

Pełny asortyment wymaga nowego, zdalnego źródła na sieć. Sprawdzi to spike:
- Biedronka: `products/search/{query}/`;
- Lidl: `www.lidl.pl/q/api/search` z dowolną frazą (dziś używany tylko z filtrem kategorii, `promotions.py:28`).

**E31.1 Spike (bramka, bez kodu add-onu):**
1. `~/dev/biedronka-spike/spike.py probe <konto> products/search/<fraza>/`, 5–8 fraz (masło, mleko, banany,
   nazwa z paragonu, kod SAP), ≤1/s. Zapisuję kształt odpowiedzi: czy jest EAN, nazwa, cena, zdjęcie,
   stronicowanie, 404/429.
1b. Lidl: `GET www.lidl.pl/q/api/search?q=<fraza>` (bez filtra kategorii, parametry jak `WEB_PARAMS`), te same
   frazy. Zapisuję: czy zwraca stały asortyment (nie tylko promocje), cenę, kod/EAN, stronicowanie.
2. Logotypy: sprawdzam źródło SVG (iconify/Wikimedia) i zasady użycia znaków Lidl/Biedronka. Zapis w PLAN.
3. Bramka:
   - **A:** search zwraca EAN → katalog Biedronki na żywo.
   - **B:** brak/nieprzydatne → wyniki Biedronki tylko z EAN-ów znanych lokalnie (paragony `b:`, karuzela
     `product_main_ean_code`, pary). Stop i pytanie do usera o Open Food Facts.
   - Lidl: wyszukiwarka lidl.pl działa dla dowolnej frazy → zdalny asortyment Lidla; nie działa → Lidl tylko
     z ofert, gazetki i paragonów (user o tym wie).
   - Logo bez zgody licencji → stop i pytanie (zapas: własne znaczki).

**E31.2 Backend wyszukiwania** (nowy `src/lidl/search.py`, Wykonawca `haiku-worker`):
- `SearchHit(kind, chain, name, key, ean, price, offer)`; `search_all(history, q, *, biedronka=None, limit)`
  łączy: produkty z paragonów (`ranking`/`other_products`), oferty Biedronki z karuzeli, a przy zaliczonym spike
  zdalną wyszukiwarkę lidl.pl (nowa funkcja obok `promotions.py`), kupony
  (`coupon_rows`+`matches`), promocje i gazetkę (`promotions`), a przy A także `BiedronkaApi.product_search`
  (nowa metoda w `client/biedronka.py`, wzór jak `product_price`).
- Dedup po EAN/kluczu (most nazw i `ean_matches`, `history.py:2267`), `matches` jako wspólne dopasowanie.
- Wynik kupowany wcześniej niesie historię z `ranking`/`_products` (liczba zakupów, ostatnia data, ostatnia
  cena). Jeden wpis na produkt, nie osobno „z paragonu” i „z katalogu”.
- Cache wyników Biedronki w pamięci (TTL ~10 min), bez zmiany schematu.
- Testy w `tests/test_search.py` i `test_biedronka_client.py`.

**E31.3 UI** (Wykonawca `haiku-worker`):
- Pole w bloku `bar` (`base.html`), `GET /szukaj?q=` (pełna strona + fragment htmx `_search_results.html`).
- Logotypy w `static/chain-lidl.svg` i `static/chain-biedronka.svg` z `?v={{ version }}`.
- Klik w wynik Biedronki → `GET /szukaj/stan/{ean}`: `product_price`+`product_stock` → `parse_price`/
  `parse_stock`, za zamkiem `shelf_lock` (zajęty → komunikat).
- Gwiazdka reużywa `/kupony/produkt/{art_id}/obserwuj` z kluczem `b:<EAN>`.
- Testy w `test_web.py`, w tym brak drugiego `id="q"`.

**E31.4 Wydanie 1.9.0:** simplify → code-review + silent-failure-hunter + pr-test-analyzer + security →
`release` → na żywo.

Rollback każdego etapu: `git revert <commit>`; brak migracji schematu. Wydanie: poprzedni tag v1.8.0 przez
Supervisor.

## Weryfikacja
- Etapy: pytest plików dotkniętych (`test_search`, `test_web -k szukaj`, `test_biedronka_client`) + ruff + mypy;
  verifier po workerze.
- Na żywo (E31.4): Playwright 390 i 1280 px:
  - fraza „masło” daje wyniki z obu sieci z logo;
  - klik w wynik Biedronki pokazuje cenę i stan w sklepie 6715;
  - gwiazdka dodaje produkt do porannego odczytu;
  - brak przewijania poziomego, konsola bez błędów.

## Ryzyka
- `products/search` może nie istnieć albo wymagać innej wersji API (bramka B).
- Zbyt wiele zapytań przy szybkim pisaniu: debounce htmx 400 ms, cache, Biedronka tylko z przycisku.
- Znaki towarowe w repo PUBLIC (sprawdzane w E31.1).
- Kontekst tej sesji jest duży: po akceptacji zaczynam od E31.0, potem `stage-end` i auto-handoff.

## Wynik spike'u E31.1 (2026-11-21)
**Biedronka `products/search/<fraza>/`** (5 fraz: masło, mleko, banany, chleb, ser gouda, mozzarella; ≤1/s; 200, bez 429):
- działa na żywo, zwraca listę 10 pozycji `{name, sap_product_number, unit}`; **brak EAN, ceny, zdjęcia i stronicowania**; fraza bez trafień (kod EAN) → `[]`.
- ranking szumny (np. „masło” → popcorn maślany, sałata masłowa); nazwa zawiera gramaturę.
- `products/price/<sklep>/<SAP>/` odrzuca SAP (`BiedronkaError`) — cena i stan wymagają EAN. SAP↔EAN znamy tylko tam, gdzie
  odpowiedź ma oba pola: karuzela ofert (`product_main_ean_code` + `sap_product_number`); `most-purchased` ma tylko SAP.
- **Bramka: B** — nazwy z katalogu na żywo są, EAN-u (więc ceny/stanu po kliknięciu) nie ma.
**Lidl `www.lidl.pl/q/api/search`** (bez filtra kategorii, parametry jak `WEB_PARAMS`, `fetchsize` 10–50):
- 200, `numFound` 47–74, `items[].gridbox.data` z `fullTitle`, `erpNumber`, `ians`, `price.price`, `category`; stronicowanie `offset`/`fetchsize`.
- to sklep online: ~80% wyników to non-food (AGD, moda); żywność rzadka („masło” → 1 produkt, „mleko” → 1, „banany” → 4 z 10) i zwykle `price: None`
  (cena tylko przy ofercie). Z filtrem `category.id=10068374`: „masło” → 2 wyniki. Kod: `erpNumber`/`ians`, nie EAN.
- **Wniosek:** Lidl nie daje stałego asortymentu spożywczego; wystarczy jako uzupełnienie ofert/gazetki, nie jako katalog.
**Logotypy:** zasady użycia znaków Lidl/Biedronka w repo PUBLIC niesprawdzone przeze mnie (brak źródła do automatycznej weryfikacji) — decyzja usera.
**Decyzje usera po spike'u (2026-11-21):** Biedronka = nazwy z `products/search` na żywo + cena/stan po kliknięciu tylko gdy EAN znany lokalnie
(paragony `b:`, karuzela `product_main_ean_code`+SAP, pary), reszta sama nazwa; Lidl = tylko oferty, gazetka, paragony (bez zdalnego lidl.pl);
logo = własne neutralne znaczki (`.chain-tag`), bez oficjalnych SVG. Open Food Facts odrzucone. Następny: E31.2 backend `search.py`.

## E31.2 — Wykonawca (kontrakt dla `haiku-worker`; bramka B, decyzje usera po spike'u)
Repo: `/config/addons/ha-lidl-app`, kod `lidl/app/src/lidl`, testy `lidl/app/tests`; python: `lidl/app/.venv/bin/python -m pytest`.
Wzory: `product_price` w `client/biedronka.py`, `_history` w `tests/test_chain_pairs.py`, `FakeSession`/`Resp` w `tests/test_biedronka_client.py`.

**Pliki i zmiany**
1. `client/biedronka.py`: `async def product_search(self, query: str) -> list[dict[str, Any]]` — `GET products/search/{quote(query, safe='')}/`;
   wynik nie-lista → `LidlPlusError("bad_shape")`; zwraca tylko elementy-słowniki z niepustym `name`.
2. `tests/test_biedronka_client.py`: ścieżka zakodowana (`products/search/mas%C5%82o%20extra/`), lista pozycji, `[]`, nie-lista → `bad_shape`.
3. `history.py`: `def coupons_active(self, today: date) -> list[tuple[str, str, str]]` — `(title, discount, valid_to)` z `coupons`
   gdzie `gone_at IS NULL AND valid_to >= today`, DISTINCT, `ORDER BY title`; test w `tests/test_history.py`.
4. nowy `search.py`:
   - `@dataclass(frozen=True) SearchHit(kind: str, chain: str, name: str, key: str|None, ean: str|None, price: float|None, purchases: int, last_date: str|None, until: str|None)`;
     `kind` ∈ `bought|offer|promo|coupon|catalog` (catalog = nazwa z `products/search`, bez ceny).
   - `search_all(history, query, *, today, promos: Iterable[Promotion]=(), remote: Iterable[dict]=(), limit=30) -> list[SearchHit]`:
     a) `bought`: `history.ranking(query=query)`; `chain` = `biedronka` gdy `art_id` zaczyna się od `b:`, inaczej `lidl`; `ean` = część po `b:`/`n:` gdy 8–14 cyfr;
        `price` = `last_price`; `purchases`/`last_date` z `RankedProduct`.
     b) `offer`: `history.savings_list()` (`kind == "offer"`, `matches(name, query)`, ważne dziś wg `valid_from/valid_to` ISO, puste = ważne); `chain="biedronka"`,
        `ean = extra["ean"] or None`, `price`, `until = valid_to`. Jeśli jest `bought` o tym samym `ean` → nie dubluj, tylko uzupełnij `until` i `price` oferty (nowy `SearchHit` przez `dataclasses.replace`).
     c) `promo`: z `promos` + `history.leaflet_matches_active(today)` (krotki jak `Promotion`), `matches(title, query)`, `chain="lidl"`, `key=art_id`, `until=end`;
        jeśli `bought` ma ten `art_id` → dopisz `until`, bez drugiego wpisu.
     d) `coupon`: `history.coupons_active(today)`, `matches(title, query)`, `chain="lidl"`, `name=title`, `until=valid_to`.
     e) `catalog`: elementy `remote` (`{"name","sap_product_number","unit"}`) z `matches(name, query)`; pomiń, gdy znana jest już pozycja o tej samej
        nazwie po `_fold` (zwinięte spacje); `chain="biedronka"`, `ean=None`, `price=None`.
     Kolejność: `bought` (malejąco `purchases`), `offer`, `promo`, `coupon`, `catalog`; obcięcie do `limit`.
   - `class BiedronkaSearchCache`: `__init__(self, ttl: float = 600, now: Callable[[], float] = time.monotonic)`;
     `async def names(self, api, query) -> list[dict]` — klucz = `_fold(query).strip()`; trafienie w cache bez zapytania; wyjątek z `api.product_search`
     nie jest cache'owany i leci dalej; fraza krótsza niż 3 znaki → `[]` bez zapytania.
5. `tests/test_search.py`: `bought` Lidl i Biedronka (chain, ean, purchases), oferta łączy się z `bought` po EAN, oferta bez `bought`, promo bez/z `bought`,
   kupon, `catalog` pomija nazwę już znaną, kolejność i `limit`, pusta fraza → `[]`, cache (drugi raz bez zapytania, po TTL znów pyta, wyjątek nie jest cache'owany, krótka fraza).
**Test:** `lidl/app/.venv/bin/python -m pytest lidl/app/tests/test_search.py lidl/app/tests/test_biedronka_client.py lidl/app/tests/test_history.py -q` + `ruff check` + `mypy` (jak w CI repo).
**DONE:** wszystkie trzy pliki testów zielone, ruff i mypy czyste, `search_all` czysta funkcja (bez sieci i bez zapisów).
**NIE RÓB:** zmian w `web/`, szablonach, `static/`, schemacie bazy, `chain_savings.py`, `promotions.py`; nie commituj; nie dodawaj zdalnego Lidla ani Open Food Facts.
Seamy testów: `History` na `tmp_path`, `savings_replace`/`upsert_tickets`+`save_detail` do danych; zdalne wyniki podawane jako lista słowników; zegar cache wstrzykiwany.

## E31.3 — Wykonawca (kontrakt dla `haiku-worker`; UI, wygląd weryfikuję sam w Playwright)
Repo/worktree: podany WORKTREE; kod `lidl/app/src/lidl`, testy `lidl/app/tests`; python z głównego repo: `PYTHONPATH=<WT>/lidl/app/src /config/addons/ha-lidl-app/lidl/app/.venv/bin/python -m pytest`.
Wzory: `chains_search`/`_chains_search.html` (htmx), gwiazdka `star` w `_coupons_row.html:3`, `check_shelf` (`shelf_lock`), `search.py` (E31.2: `search_all`, `BiedronkaSearchCache`, `SearchHit`).

**Pliki i zmiany**
1. nowy `web/search_view.py` (czyste funkcje, bez I/O poza `History`):
   - `known_eans(history) -> set[str]`: EAN-y z `history.ranking()` (`art_id` `b:`/`n:` + 8–14 cyfr) i z ofert `history.savings_list()` (`kind == "offer"`, `extra["ean"]`).
   - `rows(hits, watched: set[str]) -> list[dict]`: `chain`, `chain_label` (`CHAIN_LABELS`), `kind_label` (bought „Kupowane”, offer „Oferta”, promo „Promocja”, coupon „Kupon”, catalog „Katalog”), `name`, `price` (`fmt_pln(.,2)` albo `""`), `history` = „kupowane N× · ostatnio dd.mm” (`fmt_day_month`, tylko gdy `purchases`), `until` = „do dd.mm”, `ean`, `can_stock` (chain biedronka i `ean`), `watch_key` (`b:<ean>` dla Biedronki z EAN; dla Lidla `key`; inaczej `None`), `watched`.
2. `web/app.py`: `app.state.promotions = promotions`, `app.state.bdr_search = BiedronkaSearchCache()` w lifespan; trasy:
   - `GET /szukaj?q=&zdalne=0|1` — `search_all(history, q, today=date.today(), promos=app.state.promotions.latest, remote=...)`; `zdalne=1` i fraza ≥3 znaki: `slug = _bdr_slugs(service)[0]`, `remote = await bdr_search.names(await service.chain_api(slug), q)`; błąd (`LidlPlusError`, `LidlPlusAuthError`, `LidlPlusCannotConnect`) → komunikat „Katalog Biedronki niedostępny”, wyniki lokalne mimo to; brak konta → bez przycisku zdalnego. `hx-request` → fragment `_search_results.html`, inaczej pełna strona `search.html` (`section="szukaj"`). Pusta fraza → pusta lista bez błędu.
   - `GET /szukaj/stan/{ean}` — EAN musi pasować do `\d{8,14}` i być w `known_eans` (inaczej 404 `Response`); sklep z `history.get_setting("biedronka_store")` (brak → komunikat „Wybierz sklep w Ceny półkowe”); `shelf_lock.locked()` → komunikat „Trwa odczyt cen, spróbuj za chwilę”; pod zamkiem `api.product_price`+`product_stock` → `parse_price`/`parse_stock` (`datetime.now()`); `ValueError`/`BiedronkaError` → „Nie udało się odczytać”, `LidlPlusAuthError` → „Sesja wygasła — zaloguj ponownie w Konta”. Zwraca `_search_stan.html` (cena, cena regularna, stan: yes „jest”, low „mało”, no „brak”).
   - `POST /szukaj/obserwuj` (form `key`, `on`) — `set_watched(key, on == "1")`, zwraca `_search_star.html`; `key` musi zaczynać się od `b:` + EAN z `known_eans` albo być kodem Lidla (`\d{7}`), inaczej 400.
   Nie zmieniaj istniejących tras ani `toggled`.
3. szablony: `search.html` (extends `base.html`, `<h1>`, `<div id="szukaj-wyniki">` z include `_search_results.html`), `_search_results.html` (lista wierszy: `<span class="chain-tag chain-tag--{{chain}}">` + nazwa + `kind_label` + historia/cena/do-kiedy; przycisk „Stan w sklepie” dla `can_stock` z `hx-get="{{base}}/szukaj/stan/{{ean}}"` do `<div id="stan-{{ean}}">`; gwiazdka przez `_search_star.html`; przycisk „Szukaj też w katalogu Biedronki” (`hx-get` z `zdalne=1`, `hx-include` pola `#szukaj`) gdy jest konto i fraza ≥3 znaki i jeszcze nie `zdalne`; pusty stan „Nic nie pasuje do „q””), `_search_stan.html`, `_search_star.html` (wzór `star` z `_coupons_row.html:3`, `hx-post`, `hx-swap="outerHTML"`).
4. `web/templates/base.html`: w domyślnym bloku `bar` po `brand` dodaj `<form class="searchbar" action="{{ base }}/szukaj" method="get" role="search"><input id="szukaj" type="search" name="q" value="{{ q or '' }}" placeholder="Szukaj produktu" aria-label="Szukaj produktu" autocomplete="off" {% if section == 'szukaj' %}hx-get="{{ base }}/szukaj" hx-trigger="input changed delay:400ms, search" hx-target="#szukaj-wyniki"{% endif %}></form>`. Nie dodawaj innego `id="q"`.
5. `web/static/app.css`: `.searchbar` (flex:1, margin-left), `input#szukaj` (min-height 44px, pasuje do tokenów `--surface-inset`, `--radius-pill`, `--line`), `.hit` (wiersz wyniku, łamanie na 390 px), `.hit__meta`. Bez nowych kolorów poza istniejącymi tokenami; bez poziomego przewijania.
6. testy `tests/test_web.py` (wzór: istniejące testy `/sieci` i klient testowy): `/szukaj?q=` zwraca wynik kupowany z historii (nazwa, „kupowane”, znacznik sieci); pusta fraza → 200; fragment htmx bez `<html`; `/szukaj/stan/<EAN nieznany>` → 404; `/szukaj/stan/<EAN znany>` z atrapą API (price+stock) pokazuje cenę i „jest”; zajęty `shelf_lock` → komunikat; `POST /szukaj/obserwuj` zapisuje `b:<EAN>` w `watched_codes()`; zły klucz → 400; na `/paragony` dokładnie jedno `id="szukaj"` i brak drugiego `id="q"` poza już istniejącym.
**Test:** `… -m pytest lidl/app/tests/test_web.py lidl/app/tests/test_search.py -q -k "szukaj or search"` potem cały `test_web.py` + `ruff check` + `ruff format --check` + `mypy` (jak CI repo).
**DONE:** testy zielone, ruff/mypy czyste, wszystkie trasy jak wyżej, `base.html` ma dokładnie jedno pole `id="szukaj"`.
**NIE RÓB:** zmian w `search.py`, `history.py`, schemacie, `client/`, `shelf_prices.py`, istniejących trasach; nie commituj; bez zdalnego Lidla; bez oficjalnych logo.
