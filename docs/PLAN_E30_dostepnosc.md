# E30 Dostępność produktu w sklepie Biedronki — plan

Repo: `/config/addons/ha-lidl-app` (public `miczu71/ha-lidl-app`), gałąź `main`, add-on 1.7.0 → wydanie **1.8.0**
(ścieżka B bez dostępności: **1.7.1**). Kod: `lidl/app/src/lidl`, testy `lidl/app/tests`.

## Context
E29 czyta tylko cenę półkową (`products/price/{sklep}/{ean}/`); 404 = „pominięty”, bez rozróżnienia „sklep nie ma
produktu” / „chwilowy brak”. W kliencie spike'u jest nieużyty endpoint stanu: GET `products/stock/{sklep}/{ean}/`
(code, city, street, coverage) i POST `products/stock/` (sklepy wokół punktu) — `~/dev/biedronka-spike/vendor/biedronka/api.py:277-294`.
Cel: wiedzieć, czy obserwowany produkt jest na półce w wybranym sklepie, i dostać push, gdy wróci.

**Wywiad 2026-11-21 (decyzje usera):**
- Spike: GET stock w wybranym sklepie + POST okolica (współrzędne z `zone.home`, czytane na żywo, nie wypisywane/zapisywane).
- Zakres w add-onie: **znacznik w `/sieci`** (kolumna „dziś na półce”: brak/mało/jest) + **push „wrócił na półkę”**.
  „Inne sklepy w okolicy” poza zakresem (POST tylko w spike'u jako wiedza).
- Push promocji E29 przy braku na półce: **wysyłany z dopiskiem** „brak na półce w <sklep>”.
- „Wrócił na półkę”: tylko obserwowane (gwiazdka E15), raz na przejście brak→jest między porannymi odczytami, tag `lidl-obserwowane`.
- Porządki z review E29: **osobny podetap** w E30.
- Bramka niezaliczona → opis 404 w panelu + porządki, wydanie 1.7.1.

**Podsumowanie:** korzystają domownicy (push) i ja w `/sieci`; automatycznie: poranny odczyt ceny + stanu, push
„wrócił” i dopisek przy promocji; ręcznie: `/polka/sprawdz`, weryfikacja stanu z aplikacją Moja Biedronka; sukces =
stan 2–3 produktów w panelu zgadza się z aplikacją, push „wrócił” w teście na fałszywym API i bez duplikatu, `/sieci`
pokazuje znacznik na 390/1280.

## Etapy

### E30.0 Docs
ROADMAP (`docs/ROADMAP.md`: punkt E30 → podetapy E30.0–E30.5), ten plan → `docs/PLAN_E30_dostepnosc.md`. Commit docs.
Rollback: `git revert`.

### E30.1 Spike (bramka) — poza repo, tylko odczyt
- `~/dev/biedronka-spike`: GET `spike.py probe osoba1 products/stock/<sklep>/<ean>/` (istniejący `cmd_probe`, zapis
  do `data/` lokalnie, bez tokenów na ekranie) dla 6–8 EAN w sklepie z ustawienia `biedronka_store`: 2–3 obserwowane
  z ceną, 1–2 z 404 w `products/price`, 1 ważony, 1 nieistniejący, 1 zły sklep. ~1 req/s.
- POST okolica: nowa komenda `probe-nearby <slug> <ean>` w `spike.py` (wzór `cmd_probe`, `api.product_stock_nearby`),
  lat/lon z env `SPIKE_LAT/SPIKE_LON` (wartości z `zone.home` przez ha-mcp, nie wypisywane); 1–2 wywołania;
  wynik zapisywany bez współrzędnych (tylko klucze, liczba sklepów, pola stanu).
- Zapis w planie: kształt odpowiedzi (pole stanu: bool/liczba/poziom „coverage”), 404 vs brak, relacja do 404 z ceny,
  429/limit, czy stan zgadza się z aplikacją (user sprawdza 2–3 produkty).
- **Bramka:** jest pole, które odróżnia „jest/brak” (albo poziom) dla EAN znanego sklepowi → ścieżka A (E30.2–E30.5).
  Brak takiego pola / wymaga geo/innych nagłówków → ścieżka B. Wynik podważający założenia → stop i pytanie.

**Wynik E30.1 (2026-11-21, bramka ZALICZONA → ścieżka A):** 10 GET `products/stock/{sklep}/{ean}/` (sklep `6715`, 1 req/s, bez 429)
+ 2 POST `products/stock/` (okolica z `zone.home`; plik ze współrzędnymi usunięty, wyniki w `data/` bez współrzędnych).
- GET: dict `{distance: null, code, coverage: int, city, street}`; `coverage` ∈ {2, 3} dla znanych EAN-ów (8× 3, 1× 2).
  Nieistniejący EAN i zły sklep (`0000`) → `BiedronkaError` (404, jak w `price`). 429 nie zaobserwowano; trzymamy ≤1 req/s.
- POST: lista 5 sklepów `{city, code, coverage, distance, latitude, longitude, store, street}`; widziane `coverage` 0 (3×) i 3 (2×) —
  czyli skala co najmniej 0–3, **0 = brak w sklepie**.
- **Założenie do potwierdzenia przez usera (E30.5, z aplikacją Moja Biedronka):** `coverage` = poziom zapasu; mapowanie
  `0 → 'no'`, `1–2 → 'low'`, `3 → 'yes'`. Do sprawdzenia w aplikacji: EAN `5907439112128` w sklepie `6715` (coverage 2) vs
  EAN o coverage 3. Mapowanie trzymamy w jednej funkcji `parse_stock`, więc korekta = 1 zmiana.
- Zapytań: 1 stan / EAN / dzień obok ceny (≤60 EAN ⇒ ≤120 req/dzień łącznie); stan tylko dla `targets` (jak cena).

### E30.2 Backend stanu (ścieżka A; paczka W1, `haiku-worker`, `verifier`)
Kontrakt **Wykonawca** dopisuję do `docs/PLAN_E30_dostepnosc.md` po spike'u (znane pola). Zakres:
- `client/biedronka.py`: `product_stock(store, ean)` (wzór `product_price`, `biedronka.py:272`; nie-dict → `bad_shape`).
- `history.py`: **v14** — `ALTER TABLE shelf_prices ADD COLUMN stock TEXT` (`'yes'|'low'|'no'|NULL`) i `stock_at TEXT`;
  `_migrate_v13(path)` z kopią `.pre-stock` (wzorzec `_migrate_v12`, `history.py:1085`); `ShelfPrice` + `shelf_replace`/`shelf_list` z nowymi polami.
  Wiersz stanu bez ceny (404 w price, stan znany) też zapisywany (cena NULL).
- `shelf_prices.py`: `parse_stock(data) -> str | None`; `refresh` czyta stan po cenie dla każdego EAN (pauza 1 s,
  łącznie ≤120 req/dzień; przy 429 w spike'u — stan tylko dla `watched_eans`); błąd stanu nie psuje ceny (licznik
  `stock_failed`); `RefreshResult.back_in_stock: list[str]` = obserwowane EAN-y z poprzednim `stock='no'` i nowym `yes|low`.
- Testy (TDD): fałszywe API (jest/mało/brak/404/zły kształt), migracja v14 z kopią, przejście brak→jest, brak przejścia przy pierwszym odczycie.
- Rollback: revert; migracja tylko dodaje kolumny, kopia `.pre-stock`.

**Wykonawca E30.2 (paczka W1, `haiku-worker`; repo `/config/addons/ha-lidl-app`, katalog `lidl/app`; testy: `cd lidl/app && .venv/bin/python -m pytest -q`):**
Skille: `addon-conventions`, `tdd` (test przed kodem). Upraszczamy plan: **jedna** nowa kolumna `stock` (bez `stock_at` — wiek = `fetched_at`).
1. `src/lidl/client/biedronka.py`: `async def product_stock(self, store: str, ean: str) -> dict[str, Any]` — kopia wzoru `product_price`
   (`products/stock/{quote(store)}/{quote(ean)}/`; nie-dict → `LidlPlusError("bad_shape")`). Test w `tests/test_biedronka_client.py` jak dla `product_price` (linia ~207).
2. `src/lidl/history.py`: `SCHEMA_VERSION = 14`; w `_SCHEMA` do `shelf_prices` dodaj `stock TEXT` (po `is_promotion`; `'yes'|'low'|'no'|NULL`);
   `_migrate_v13(path)`: gdy istnieje tabela `tickets` → kopia `.pre-stock` (jak `_migrate_v12`), potem `ALTER TABLE shelf_prices ADD COLUMN stock TEXT`
   jeśli kolumny nie ma (`PRAGMA table_info`); wołana w bloku migracji jak `_migrate_v12` (`if has_tables and version < 14`).
   `ShelfPrice` dostaje pole `stock: str | None = None` NA KOŃCU (domyślne, by nie rozbić istniejących wywołań); `shelf_replace` zapisuje `stock`,
   `shelf_list` czyta `stock`. Test migracji v13→v14 (kopia `.pre-stock` istnieje, kolumna jest, dane zostają) wg `tests/test_history.py`.
3. `src/lidl/shelf_prices.py`:
   - `def parse_stock(data: Any) -> str | None`: dict z `coverage` typu `int` (nie `bool`) → `0 → 'no'`, `1`/`2 → 'low'`, `>=3 → 'yes'`; `coverage` ujemne, brak klucza albo zły
     typ → `ValueError("nieznany kształt odpowiedzi")`. (Jedyne miejsce mapowania; może się zmienić po weryfikacji z aplikacją.)
   - `RefreshResult`: dodaj `stock_failed: int = 0` i `back_in_stock: list[str] = field(default_factory=list)`.
   - `refresh(...)`: przed pętlą `previous = {r.ean: r.stock for r in history.shelf_list(store)}`. Dla każdego EAN-u po odczycie ceny (pauza `REQUEST_PAUSE_S`
     także przed zapytaniem o stan) wołaj `api.product_stock(store, ean)`:
       * `LidlPlusAuthError`/`LidlPlusCannotConnect` → `raise` (jak przy cenie);
       * `LidlPlusError` ze `status == 404` → `stock = None` (nieznany, bez błędu);
       * inny `LidlPlusError`, `TypeError`, `ValueError` → `stock_failed += 1`, `errors.append(f"{ean} (stan): ...")`, `stock = previous.get(ean)` (zachowaj poprzedni);
       * sukces → `stock = parse_stock(data)`.
     Wiersz: gdy cena jest → `dataclasses.replace(row, stock=stock)`; gdy ceny brak (`parse_price` → `None` albo 404 ceny) i `stock is not None` → wiersz pusty
     `ShelfPrice(store, ean, None, None, None, None, None, False, False, fetched_at, stock)` (zapisany, nie `cleared`); gdy ceny brak i `stock is None` → jak dziś (`cleared`
     tylko dla „brak ceny”, 404 ceny = `skipped`). 404 ceny przy znanym stanie liczymy jako `ok`, nie `skipped`.
     `back_in_stock`: EAN z `watched_eans(history)`, gdzie `previous.get(ean) == 'no'` i nowy `stock in ('yes','low')`.
     Zdarzenie końcowe: błędy stanu liczone razem z `failed` w istniejącym `shelf/error`; reszta bez zmian.
   - `shelf_offers`/`ShelfOffer`: BEZ zmian w tym etapie (E30.3).
4. Testy `tests/test_shelf_prices.py` (FakeApi z `product_stock`): `parse_stock` (0/1/2/3/`True`/brak/ujemne), refresh z `yes`/`low`/`no`, 404 stanu → `None`, błąd stanu zachowuje poprzedni
   `stock` i liczy `stock_failed`, wiersz bez ceny ze stanem trafia do `shelf_list`, `back_in_stock` tylko dla obserwowanych i tylko przy przejściu `no`→`yes|low` (brak przy pierwszym
   odczycie i przy `yes`→`yes`). Istniejące testy dostają FakeApi bez `product_stock` → dodaj domyślną metodę w FakeApi zwracającą `{"coverage": 3}`.
`DONE:` pytest całego `lidl/app` zielony (≥735 + nowe), `.venv/bin/ruff check src tests` i `.venv/bin/mypy src` bez błędów, `git status --short` tylko w plikach z listy.
`NIE RÓB:` zmian w `notify.py`, `daily.py`, `web/*`, `config.yaml`/wersji, `docs/`; commitów; zmiany podpisu `parse_price`.

### E30.3 Push i panel (ścieżka A; paczka W1 po E30.2, `haiku-worker`, `verifier`)
- `notify.py`: `_shelf_line` z dopiskiem „brak na półce w <sklep>” gdy `stock='no'` (`ShelfOffer` + pole `stock`);
  nowa linia/wiadomość „wrócił na półkę: <nazwa> (<sklep>)” w tym samym pushu obserwowanych (tag `TAG_WATCHED`).
- `daily.py`: `_morning_shelf` przekazuje `back_in_stock` do kroku obserwowanych; klucz deduplikacji
  `bb:<ean>:<data odczytu>` w `mark_watched_sent` (wzór `_shelf_fresh`, `daily.py:302`).
- `web/chains.py` `_shelf_cell` (`:265`) + szablon `/sieci`: znacznik „brak na półce”/„mało”/„jest”, wiek odczytu; bez ceny a stan znany → sam znacznik.
- Testy: compose z dopiskiem, push „wrócił” raz, `/sieci` render (test_web).
- Rollback: revert.

**Wykonawca E30.3 (paczka W1, `haiku-worker`; repo `/config/addons/ha-lidl-app`, katalog `lidl/app`):**
Skille: `addon-conventions`, `tdd`. Zmiana względem szkicu: „wróciło na półkę” **nie** jest przekazywane w pamięci, tylko trwale w `settings`
(klucz `shelf_back_pending`, JSON-lista EAN-ów) — przeżywa ręczne „Sprawdź teraz” i nieudaną wysyłkę; czyszczone dopiero po udanym pushu (dedup = to samo).
1. `src/lidl/shelf_prices.py`:
   - `ShelfOffer` dostaje `stock: str | None = None` NA KOŃCU; `shelf_offers` wypełnia je z `row.stock`.
   - `refresh`: w bloku `finally` (obok `history.shelf_replace`) gdy `result.back_in_stock` niepuste → dopisz do `shelf_back_pending` (suma z istniejącą, bez duplikatów, `json.dumps(sorted(...))`).
   - Nowe: `pending_back(history) -> list[str]` (parsuje ustawienie; zły JSON/brak → `[]`) i `clear_back(history, eans)` (usuwa podane EAN-y z ustawienia).
2. `src/lidl/notify.py`: `_shelf_line` dopisuje ` · brak na półce` gdy `offer.stock == 'no'`. `compose_watched(..., back: Sequence[str] = ())` — `back` = nazwy produktów, które wróciły na półkę
   w Biedronce. `None` tylko gdy brak wierszy, `shelf` i `back`. Linia ciała: `"<nazwa> wróciło na półkę · Biedronka"`. Tytuł: sam jeden `back` i nic więcej →
   `"<nazwa> — wróciło na półkę w Biedronce"`; w pozostałych przypadkach zachowaj dotychczasowe reguły, liczba produktów w tytule liczy też `back`, a gdy `back` niepuste sufiks `" z rabatem"` zastąp `" — zmiany"`.
3. `src/lidl/daily.py`: w `_watched` po `shelf = self._shelf_fresh(...)`: `back_eans = shelf_prices.pending_back(self._history)` ograniczone do obserwowanych (`watched_eans`-owy EAN z `watched`: kod `b:<ean>` lub `n:<ean>` ∈ `watched`);
   nazwy jak w `_shelf_fresh` (`self._history.product_name(code) or ean`); przekaż `back=` do `compose_watched`. Po UDANEJ wysyłce (i nie w `dry_run`): `shelf_prices.clear_back(self._history, back_eans)`.
   EAN-y pending, które już nie są obserwowane, też czyść razem (`clear_back` na wszystkich z `pending_back`). Warunek wczesnego `return` przy braku `watched` zostaje.
4. `src/lidl/web/chains.py`: `_shelf_by_ean` bierze wiersze z `price is not None` LUB `stock is not None`; `_shelf_cell` zwraca `{"price": fmt_pln(...) albo None, "promo": bool, "read": ..., "stock": "yes"|"low"|"no"|None}`
   (dla wiersza bez ceny i bez stanu nadal `None`). `_chains_body.html` (komórka „Dziś na półce”): cena + `promocja` jak dziś (gdy jest cena), a gdy `stock`: znacznik `<span class="tag">` z tekstem `brak na półce` (no) / `mało` (low) / bez znacznika dla `yes`;
   gdy brak ceny, a jest stan — sam znacznik + odczyt (zamiast „—”). Bez nowego CSS: użyj istniejącej klasy `tag` (jak `promocja`).
5. Testy: `tests/test_notify.py` (dopisek `brak na półce`, `back` jedyny/z innymi, `None` bez niczego), `tests/test_shelf_prices.py` (`ShelfOffer.stock`, `refresh` dopisuje `shelf_back_pending` także przy `AuthError` w połowie, `pending_back`/`clear_back`, zły JSON),
   `tests/test_daily.py` (push „wróciło” raz: po udanym wysłaniu pending czyści się; przy nieudanym zostaje; `dry_run` nie czyści; nieobserwowany nie trafia do pusha), `tests/test_web.py`/`test_chains.py` (komórka: promocja + `brak na półce`; sam stan bez ceny; `yes` bez znacznika) wg istniejących wzorców.
`DONE:` pełny pytest `lidl/app` — poza 13 znanymi czerwonymi w `tests/test_leaflet.py` (stan sprzed E30) wszystko zielone; ruff i mypy czyste; `git status --short` tylko pliki z listy.
`NIE RÓB:` zmian w `history.py` (schemat v14 jest gotowy), `client/`, `config.yaml`/wersji, `docs/`, `test_leaflet.py`; commitów; nowego CSS.

### E30.2B Opis 404 (tylko ścieżka B, zamiast E30.2–E30.3)
- `refresh` zapisuje EAN z 404 jako wiersz bez ceny ze znacznikiem `not_listed` (v14: kolumna `not_listed INTEGER`,
  kopia `.pre-stock`); `/sieci` pokazuje „sklep nie zna produktu (404)” zamiast pustej komórki. Testy jak wyżej. Wydanie 1.7.1.

### E30.4 Porządki z review E29 (paczka W1, `haiku-worker`, `verifier`)
- `/polka/sprawdz` (`web/app.py:387`): `asyncio.Lock` w `app.state`; trwa odczyt (ręczny albo poranny) → `?m=shelf_busy`
  zamiast drugiego przebiegu; komunikat w szablonie `/polka`.
- `_shelf_fresh` (`daily.py:302`): nazwy jednym zapytaniem (nowe `History.product_names(codes)` albo istniejąca metoda zbiorcza, jeśli jest) zamiast `product_name` na ofertę.
- `promo_to`: wypełniany ISO-datą z `parse_promo_end` w `parse_price`; `shelf_offers` czyta `promo_to` (fallback na parsowanie `promo_from` dla starych wierszy).
- `refresh_morning` → `None` (brak sklepu/konta) loguje zdarzenie `shelf/info` z powodem zamiast cicho.
- Testy do każdego punktu. Rollback: revert.

### E30.5 Wydanie (ostatni etap: bez pytania)
`simplify` → `code-review` (+ równolegle `silent-failure-hunter`, `pr-test-analyzer`, security `general-purpose` na
`git -C /config/addons/ha-lidl-app diff <baza E30.0>..HEAD`) → `release` 1.8.0 (B: 1.7.1) → na żywo: `/polka/sprawdz`,
`/sieci` w Playwright 390/1280, stan 2–3 produktów vs aplikacja (user), zdarzenie `shelf/ok`.
Rollback: wersja 1.7.0 z poprzedniego wydania + backup add-onu (migracja v14 tylko dodaje kolumny; kopia `.pre-stock`).

## Przebieg
Etapy po kolei bez czekania; po każdym zweryfikowanym `stage-end`. Stop: bramka E30.1 (wynik → ścieżka A/B wg planu;
stop tylko, gdy wynik podważa założenia), krok produkcyjny spoza planu.

## Weryfikacja
- Testy: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q` (+ ruff/mypy wg `addon-conventions`).
- Migracja: test v13→v14 na kopii bazy z fixture; na żywo log startu add-onu + istnienie `.pre-stock`.
- Na żywo po wydaniu: `/polka/sprawdz` → `shelf/ok`, `/sieci` znacznik (Playwright 390/1280), porównanie z aplikacją.
