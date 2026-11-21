# E29 Ceny półkowe Biedronki (propozycja P2 z ROADMAP) — plan

Repo: `/config/addons/ha-lidl-app` (public `miczu71/ha-lidl-app`), gałąź `main`, add-on 1.6.2 → wydanie **1.7.0** na końcu.

## Context
Ceny Biedronki znamy dziś tylko z paragonów (E28.1–E28.4). Aplikacja Moja Biedronka ma endpoint
`products/price/{sklep}/{ean}/` (cena, regularna, Omnibus — „jak po zeskanowaniu kodu”), nigdy niesprawdzony (spike E28.0
go nie wołał; jest w `~/dev/biedronka-spike/vendor/biedronka/api.py:273`). Cel: dowiedzieć się o promocji na produkt,
który i tak kupujemy, i widzieć dzisiejszą cenę Biedronki obok Lidla.

**Wywiad 2026-11-21 (decyzje usera):**
- Zastosowania: **push o promocji** obserwowanych produktów + **Porównanie „teraz”** w `/sieci`. Bez historii cen.
- Zakres EAN: **gwiazdka E15 kupiona w Biedronce + produkty z zatwierdzonych par** Lidl↔Biedronka.
- Sklep: **jeden, wybierany z listy w panelu** (sklepy z paragonów, adres + kod), zapis w bazie, bez restartu.
- Częstotliwość: **raz dziennie w porannym przebiegu** (`run_time`, 07:00), przed powiadomieniem obserwowanych.
- Push: **cena < Omnibus** (bez Omnibusa: cena < regularna), raz na promocję, tag `lidl-obserwowane`.
- Porównanie: **obie kolumny** — Biedronka z paragonu + „dziś na półce” (znacznik promocji, data odczytu);
  zwycięzca liczony dalej z paragonów.

**Podsumowanie:** korzystają oboje domownicy (push) i ja w panelu (`/sieci`); automatycznie: poranny odczyt cen + push;
za zgodą/ręcznie: wybór sklepu (user), weryfikacja cen z aplikacją; sukces = 2–3 ceny z panelu zgadzają się z aplikacją
w wybranym sklepie, push przychodzi przy obserwowanym produkcie poniżej Omnibusa, `/sieci` pokazuje kolumnę „dziś”.

## Etapy

### E29.0 Docs
ROADMAP (`docs/ROADMAP.md`: P2 → etap E29 z podetapami), plan skopiowany do `docs/PLAN_E29_ceny_polkowe.md`. Commit docs.
Rollback: `git revert`.

### E29.1 Spike GET (bramka)
- Skrypt w `~/dev/biedronka-spike` (poza repo, dane w `data/` lokalnie), tylko GET `product_price` dla 5 EAN z paragonów
  (w tym 1 w promocji wg aplikacji, 1 ważony, 1 nieistniejący) w 1–2 sklepach z paragonów. Token: z bazy add-onu tylko
  do odczytu albo login usera (jak E28.0). Bez wypisywania tokenów.
- Zapis w planie: kształt odpowiedzi (pola ceny/regularnej/Omnibusa/dat promocji, jednostka ważonych), 404/pusta dla
  nieznanego EAN, format kodu sklepu (4 cyfry jak w `tickets`?), limit/429.
- **Bramka:** odpowiedź ma cenę + regularną (Omnibus mile widziany). Brak cen albo wymóg innego nagłówka/geo → stop,
  pytam usera z wynikiem.

**Wynik E29.1 (2026-11-21, bramka ZALICZONA):** 19 odczytów `products/price/{sklep}/{ean}/` (4 sklepy z paragonów, ~1 req/0,3 s, bez 429)
+ 3 odczyty negatywne. Token z konta spike (E28.0), bez geo/dodatkowych nagłówków.
- Kod sklepu: 4 cyfry jak w `tickets` (np. `0001`). Zły sklep (`0000`) i nieistniejący EAN → `BiedronkaError("http_404")`;
  zdegenerowany EAN (`123`) → `http_503` (traktować jak błąd chwilowy). 429 nie zaobserwowano (limit nieznany; trzymamy ≤1 req/s, ≤60/dzień).
- Pola odpowiedzi (dict): `price` (str `"7.49"`, kropka; **`""` przy „DRUGI ZA x zł”** → brak ceny półkowej), `regular_price` (str),
  `omnibus_price` (str; **`"0.00"` = brak Omnibusa**), `is_promotion` (bool), `promotion_valid_period` (`"od 16.11 do 22.11"` lub None),
  `discount` (str `"93"` lub None), `omnibus_type`, `price_tag_info` („ZAWSZE NISKIE CENY”/„TERAZ TANIEJ”/„3+1 GRATIS …”),
  `unit` (`szt`/`opa`/`""`), `unit_price` (lista tekstów typu `"59,92 zł/kg"` — nie parsować), `name`, `only_with_biedronka_card`.
- **Pułapki dla E29.2/E29.3:** (1) `is_promotion=False` mimo `price < regular_price` przy promocjach warunkowych („3+1 GRATIS”,
  „DRUGI TANIEJ 40%”) — `price` to cena nominalna z promocją, nie cena za 1 szt. → push tylko gdy `is_promotion=True`
  i `price < omnibus` (bez Omnibusa: `< regular`); promocje wielosztukowe pomijamy; (2) `price==""` = brak ceny → nie błąd, pomijamy;
  (3) ceny w groszach-jak-tekst z kropką, `omnibus "0.00"` ≠ cena zero; (4) ważone: cena półkowa jest za `unit` (szt/opa),
  za kg tylko w `unit_price` (tekst) — porównanie z paragonem tylko dla `unit=szt` i tego samego EAN, ważone (`n:`/`b:` z wagą) pomijamy w E29.4;
  (5) `only_with_biedronka_card=True` → cena tylko z kartą (zapisz flagę, push z dopiskiem).
- Fixtures do testów: neutralne, ręcznie zbudowane z powyższych kształtów (nie kopiować danych z `~/dev/biedronka-spike/data`).

### E29.2 Backend (paczka W1, `haiku-worker`, verifier)
- `lidl/app/src/lidl/client/biedronka.py`: `product_price(store, ean)` (wzór `vendor/.../api.py:273`, ścieżka `_get`).
- `history.py`: schemat **v13** — tabela `shelf_prices(store, ean, price, regular, omnibus, promo_from, promo_to,
  fetched_at, PRIMARY KEY(store, ean))` (ostatni odczyt, nadpisywany) + ustawienie `biedronka_store` (tabela ustawień,
  jeśli jest; inaczej mała tabela `settings`) + kopia bazy `.pre-shelf` przed migracją (wzorzec v8/v9/v12).
- Nowy `shelf_prices.py` (wzorzec `chain_savings.refresh`): `targets(history)` = EAN z `watched` (kody `b:<EAN>`/`n:<EAN>`
  kupione w Biedronce) ∪ strona Biedronki z `chain_pairs` `approved`; `refresh(history, api, store)` — błąd jednego EAN
  nie przerywa reszty, limit ~60 EAN, ≤1 zapytanie/s, nieznany kształt = błąd części (stare wiersze zostają),
  zdarzenie `shelf/ok` (wiek odczytu jak `savings/ok`), `auth` → Problem jak w imporcie.
- Testy: fałszywe API (cena/promocja/brak Omnibusa/404/zły kształt), migracja v13, `targets`.
- Rollback: revert commitów; migracja tylko dodaje tabelę, kopia `.pre-shelf`.

**Wykonawca E29.2 (paczka W1, `haiku-worker`; repo `/config/addons/ha-lidl-app`, katalog `lidl/app`):**
- Skille: `addon-conventions`, `tdd` (test przed kodem). Wzory: `chain_savings.refresh`/`fetch` (błąd części nie ukrywa reszty),
  migracje `History._migrate_v8/_v9` (kopia `.pre-…` przez `self._db.backup`), testy `tests/test_chain_savings.py` (FakeApi), `tests/test_history.py`.
- Pliki i zmiana:
  1. `src/lidl/client/biedronka.py`: `async def product_price(self, store: str, ean: str) -> dict[str, Any]` —
     `await self.request(f"products/price/{quote(store, safe='')}/{quote(ean, safe='')}/")`; wynik nie-dict → `LidlPlusError("bad_shape")`.
  2. `src/lidl/history.py`: `SCHEMA_VERSION = 13`; w `_SCHEMA` tabele `shelf_prices(store TEXT, ean TEXT, price REAL, regular REAL,
     omnibus REAL, promo_from TEXT, promo_to TEXT, card_only INTEGER NOT NULL DEFAULT 0, is_promotion INTEGER NOT NULL DEFAULT 0,
     fetched_at TEXT NOT NULL, PRIMARY KEY (store, ean))` i `settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)`;
     `_migrate_v12(path)` (kopia `.pre-shelf`, tylko gdy istnieje `tickets`) wołana jak `_migrate_v11` (`if has_tables and version < 13`);
     metody `get_setting(key) -> str | None`, `set_setting(key, value)`, `shelf_replace(store, rows)` (upsert wierszy), `shelf_list(store=None)`
     zwracająca `list[ShelfPrice]` (dataclass w `shelf_prices.py` lub history — wzorzec `SavedSaving`).
     Nowy `History.chain_store_codes()` NIE jest potrzebny (sklepy z paragonów w E29.4).
  3. Nowy `src/lidl/shelf_prices.py`: `targets(history) -> list[str]` (EAN-y: z `history.watched_codes()` kody `b:<EAN>` (i `n:<EAN>`
     tylko gdy `<EAN>` to 8–13 cyfr) ∪ `b_art_id` z `chain_pair_list()` ze `status == "approved"`; bez prefiksu, unikalne, posortowane,
     ważone pomijamy: kody `n:`/`b:` z sufiksem wagi nie-cyfrowym; obcięte do `MAX_EANS = 60`);
     `parse_price(ean, data, now) -> ShelfPrice | None` (`price==""` → `None`; `omnibus "0.00"` → `omnibus=None`; ceny `float(str)`;
     `promo_from/to` z `promotion_valid_period` jako tekst bez parsowania; `is_promotion`, `only_with_biedronka_card` → `card_only`);
     `async def refresh(history, api, store, *, sleep=asyncio.sleep) -> RefreshResult(ok, skipped, failed, errors)`: pętla po `targets`,
     `await sleep(1.0)` między zapytaniami, `LidlPlusError` z `http_404` → pomiń EAN (skipped), inne błędy (w tym `http_503`) → `failed`
     + `errors`, reszta idzie dalej; `LidlPlusAuthError` przerywa pętlę i jest rzucany dalej; zapis `shelf_replace` tylko udanych
     (stare wiersze zostają); po przebiegu bez błędów `history.log_event("shelf", "ok", "Ceny półkowe Biedronki: odczytane", {"store": store, "count": n})`,
     przy błędach `log_event("shelf", "error", …)` (bez treści odpowiedzi).
  4. Testy: `tests/test_shelf_prices.py` (FakeApi: cena+promocja, brak Omnibusa, `price==""`, 404, 503, zły kształt, auth przerywa; `targets`:
     obserwowane + zatwierdzone pary, bez ważonych, limit 60; `sleep` podmieniony na no-op), `tests/test_history.py` (migracja v12→v13 tworzy
     `shelf_prices`+`settings` i kopię `.pre-shelf`, round-trip `get/set_setting`, `shelf_replace/list`), `tests/test_biedronka_client.py` (`product_price`: ścieżka, zły kształt).
     Fixtures neutralne („Sklep X”, EAN `5900000000001`…), bez prawdziwych danych.
- Test: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q --ignore=tests/test_leaflet.py && uv run ruff check && uv run mypy src`.
- `DONE:` wszystkie trzy komendy zielone; nowe testy czerwone przed kodem i zielone po; `git status --short` w worktree = tylko pliki z listy wyżej.
- `NIE RÓB:` `daily.py`, `notify.py`, `web/*`, szablony, `config.yaml` (wersja), `ROADMAP`; nie commitować; nie wołać prawdziwego API ani czytać `~/dev/biedronka-spike/data`;
  nie zmieniać istniejących migracji ani testów poza dopisaniem nowych; bez nowych zależności.

### E29.3 Poranny przebieg + push (paczka W2 po W1, `haiku-worker`, verifier)
- `daily.py`: krok odczytu cen przed `_watched` (brak sklepu/konta Biedronki = pomijam z info w logu; błąd = warn, nie
  zatrzymuje porannego przebiegu — jak Shakeomat).
- `_watched`: promocja = `price < omnibus` (bez Omnibusa `price < regular`); klucz `bs:<ean>:<promo_to|price>` w
  `watched_sent`; `notify.compose_watched` dostaje linie Biedronki (nazwa, cena, „było X”, do kiedy), ten sam tag.
- Testy: `compose_watched` z liniami Biedronki, brak duplikatu po drugim przebiegu, tryb próbny bez zapisu.

**Wykonawca E29.3 (paczka W2, `haiku-worker`; repo `/config/addons/ha-lidl-app`, katalog `lidl/app`):**
- Skille: `addon-conventions`, `tdd`. Wzory: `DailyJob._morning_shakeomat` (krok z własnym try/except), `notify.compose_watched`, `tests/test_daily.py::test_watched_products_get_a_separate_push_once` (FakeHistory, `_job`).
- Pliki i zmiana:
  1. `src/lidl/shelf_prices.py`: (a) `parse_promo_end(text: str | None, today: date) -> date | None` — z tekstu `od 16.11 do 22.11` bierze datę po „do” (`DD.MM`),
     rok = rok `today`; gdy data wypada >180 dni przed `today` → rok+1; brak/zły tekst → `None`; (b) `async def refresh_morning(history, service) -> RefreshResult | None` —
     `store = history.get_setting("biedronka_store")`; brak → `None`; slugi Biedronki przez `chain_savings._bdr_slugs(service)` (pierwszy; brak → `None`);
     `api = await service.chain_api(slug)`; `return await refresh(history, api, store)`; (c) `@dataclass(frozen=True) ShelfOffer(ean, price, was, end: date | None, card_only)` i
     `shelf_offers(history, store, today) -> list[ShelfOffer]` — wiersze `history.shelf_list(store)` z `is_promotion` i `price is not None`, gdzie `price < (omnibus if omnibus else regular)`
     (brak obu → pomiń), tylko EAN-y z obserwowanych (`history.watched_codes()`: kody `b:<EAN>`/`n:<EAN>`), `was` = omnibus albo regular, `end = parse_promo_end(promo_from, today)`.
  2. `src/lidl/notify.py`: `compose_watched(coupons, promos, today, shelf: list[tuple[str, ShelfOffer]] = [])` (para nazwa produktu, oferta) — linia
     `f"{name} {fmt_pln(price, 2)} (było {fmt_pln(was, 2)}{', do ' + fmt_until(end, today) if end else ''}) · Biedronka{' · tylko z kartą' if card_only else ''}"`;
     wlicza się do liczby produktów w tytule (`n` unikalnych nazw); przy jednej linii Biedronki tytuł `Lidl: {name} — Biedronka {fmt_pln(price, 2)}`; brak kuponów/promocji/shelf → `None` jak dotąd. Domyślny argument nie zmienia dotychczasowych wyników.
  3. `src/lidl/daily.py`: parametr `shelf: Callable[[], Awaitable[RefreshResult | None]] | None = None` (po `shakeomat`); w `__call__` po kroku „promocje”, przed „kupony”: `step = "ceny"`;
     `try: await self._shelf()` (gdy nie `None`); `LidlPlusAuthError` → `log_event("shelf", "error", "Ceny półkowe Biedronki: wymagane ponowne logowanie", {"run": "shelf"})`;
     inny `Exception` → `log.exception` + `log_event("daily", "error", f"Ceny półkowe Biedronki: {type(err).__name__}: {err}", {"run": "shelf"})`; żaden nie przerywa przebiegu.
     W `_watched` (po `found`): `offers = shelf_offers(history, store, today)` z `store = history.get_setting("biedronka_store")` (brak → `[]`); klucz `bs:<ean>:<end.isoformat() | price>` (price jako `f"{price:.2f}"`);
     pomiń klucze w `sent`; nazwa = `history.product_name(code) or ean` (kod `b:<EAN>` albo `n:<EAN>`, który jest w `watched_codes`); do `compose_watched(..., shelf=...)`;
     `mark_watched_sent([*coupons, *found, *shelf_keys])` jak dotąd (próbny bez zapisu, nieudany push bez zapisu). Zwrot wczesny `if not watched: return` zostaje.
  4. `src/lidl/web/app.py` (~linia 192): `shelf=lambda: shelf_prices.refresh_morning(history, service)` w `DailyJob(...)` (import modułu `shelf_prices`).
  5. Testy: `tests/test_shelf_prices.py` (`parse_promo_end`: zwykły, rok przełomu grudzień→styczeń, brak/zły tekst; `shelf_offers`: promocja < Omnibus, bez Omnibusa < regular, `is_promotion=False`, nieobserwowany EAN, `price is None`;
     `refresh_morning`: brak sklepu → `None`, brak konta Biedronki → `None`, wołanie `refresh` ze sklepem), `tests/test_notify.py` (`compose_watched` z linią Biedronki: jedna, razem z kuponem, `card_only`, brak `end`),
     `tests/test_daily.py` (krok „ceny” wołany raz przed kuponami; `LidlPlusAuthError` → event `shelf/error` i przebieg idzie dalej; push z linią Biedronki raz po dwóch przebiegach; tryb próbny bez zapisu `bs:`).
     Fixtures neutralne („Produkt X”, EAN `5900000000001`, sklep `0001`).
- Test: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q --ignore=tests/test_leaflet.py && uv run ruff check && uv run mypy src` (na pierwszym planie; ~10 min — `timeout` 600000, a przy limicie uruchom tylko `tests/test_shelf_prices.py tests/test_notify.py tests/test_daily.py` i podaj, że pełny zostawiasz rodzicowi).
- `DONE:` nowe testy czerwone przed kodem, zielone po; ruff i mypy zielone; `git status --short` w worktree = tylko pliki z listy (shelf_prices.py, notify.py, daily.py, web/app.py, 3 pliki testów).
- `NIE RÓB:` `history.py`, `client/*`, `web/*` poza jedną linią w `app.py`, szablony, `config.yaml`, `ROADMAP`; nie commitować; nie wołać prawdziwego API; jeśli istniejący test wymaga zmiany asercji z powodu nowego parametru — wolno, wypisz to w raporcie; bez nowych zależności.

### E29.4 Panel (ja — wymaga weryfikacji wizualnej)
- Konta (sekcja Biedronki): lista sklepów z paragonów Biedronki (adres + kod), POST zapisuje `biedronka_store`
  (walidacja: kod musi być ze znanych sklepów). Status: wybrany sklep + wiek ostatniego odczytu.
- `/sieci` Porównanie (`web/chains.py::comparison_view`, szablon `_chains_body.html`): kolumna „dziś na półce” dla
  Biedronki (cena, znacznik promocji gdy < Omnibus, data odczytu); ważone — zgodnie z wynikiem spike'u (jak nie da się
  porównać jednostek → „—”). Zwycięzca bez zmian.
- Testy tras + Playwright 390/1280 na demo `~/lidl_dev/sieci_demo`, konsola czysta.

### E29.5 Wydanie 1.7.0
`simplify` → `code-review` + `silent-failure-hunter` + `pr-test-analyzer` + security (general-purpose, `<baza>..HEAD`)
→ poprawki → backup add-onu → `release` (bump `lidl/config.yaml`, tag non-draft) → na żywo: wersja, start bez ERROR,
wybór sklepu w Konta, „Sprawdź teraz”, `/sieci` z kolumną, konsola czysta. **Kryterium usera:** 2–3 ceny z panelu vs
aplikacja Moja Biedronka w tym sklepie. Rollback: `ha_manage_app` na 1.6.2 + przywrócenie backupu (migracja v13).

## Weryfikacja (każdy etap)
`cd lidl/app && uv run pytest -q --ignore=tests/test_leaflet.py`, `uv run ruff check`, `uv run mypy src` (baza = main);
claimcheck + verifier dla paczek W; pubguard przed wydaniem (repo PUBLIC — bez adresów sklepów i prawdziwych danych w fixtures,
„Sklep X”).

## Ryzyka
Endpoint może wymagać sklepu „ulubionego” konta albo geolokalizacji (bramka E29.1); regulamin/blokada konta — mało zapytań
(≤60/dzień, 1/s); ceny ważonych w innej jednostce niż paragon; rotacja tokenu (jak w E28).
