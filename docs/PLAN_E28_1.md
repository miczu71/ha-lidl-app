# PLAN E28.1 — konta i import Biedronki (fundament)

Źródło prawdy: `docs/ROADMAP.md` (E28) i `docs/PLAN_E28_biedronka.md`. Stan wejściowy: D2 zrobione (`3f0e3a3`), add-on 1.2.1,
schemat v7. Wynik E28.0a: lista starszych zakupów `GET transactions/archived/?page=N`, świeże `GET transactions/?page=N`,
pozycje i EAN w `GET transactions/{id}/` (e-paragon `e-receipt/` tylko dla świeżych — parser go nie używa).

## Zakres (bez UI-filtra sieci, bez Budżetu, bez wydania)
Biedronka: konto (logowanie PKCE przez wklejenie `app://…`), import listy + szczegółów do tych samych tabel co Lidl,
`chain` w `tickets` i w pliku konta. Paragony Biedronki widać na liście Paragony razem z Lidlem (filtr dopiero w E28.2).
Wydanie dopiero po E28.2 (jedno na grupę etapów; numer po 1.2.1, np. 1.3.0).

## Decyzje techniczne (E28.1)
- **Schemat v8:** `tickets.chain TEXT NOT NULL DEFAULT 'lidl'`; migracja v7→v8 = kopia `history.db.pre-biedronka`
  (`sqlite3.backup`, wzorzec `_migrate_v6`) + `ALTER TABLE` tylko gdy kolumny brak; świeża baza dostaje kolumnę z `_SCHEMA`.
- **Id paragonu:** `b:<id transakcji>`; kod produktu `b:<EAN>` (brak EAN → `b:<nazwa małymi>`). Kolizji z `n:`/Lidlem brak.
- **Konto:** pole `chain` w `accounts/<slug>.json` (`lidl` domyślnie, brak pola = lidl); `save_tokens` zachowuje `chain`.
- **Wyjątki:** klient Biedronki rzuca istniejące `LidlPlusAuthError` / `LidlPlusCannotConnect` / `LidlPlusError(status=…)`,
  dzięki czemu `sync.is_fatal` i alerty działają bez zmian.
- **Lista w sync:** `service.tickets(slug, year_offset)` dla konta Biedronki: offset 0 = świeże (`transactions/`, wszystkie
  strony, limit 20), offset 1 = archiwum (`archived/`, wszystkie strony, limit 50), offset ≥2 → `LidlPlusError(status=400)`
  (koniec historii). Istniejąca pętla `_import_lists` (full = offsety 0..9, przerwanie na 400 przy offset>0) działa bez zmian.
  Element listy mapowany na kształt Lidla: `{"id": "b:<id>", "date": date, "totalAmount": total_price, "savings": 0,
  "couponsUsedCount": 0, "storeCode": None, "articlesCount": -1}`.
- **Szczegół:** `service.ticket(slug, "b:<id>")` → `GET transactions/{id}/`. Parser `parse_biedronka(detail) -> ParsedReceipt`
  (nowy moduł `receipt_biedronka.py`):
  - pozycja: `art_id=b:<ean>`, `name`, `quantity`, `unit_price`, `total=total_price_without_discount`,
    `discount=total_discount` (dodatnie), `is_weight = measure_unit == "KG"`, `coupon=0`, `promo=""`;
  - pozycje z „kaucj” w nazwie (bez względu na wielkość liter) NIE są pozycjami: ich `total_price` (ujemne = zwrot) idzie do
    `deposit_charged` / `deposit_refunded`; `deposit = charged − refunded`. Kontrola: suma kaucji z pozycji = 
    `sold_returnable_packagings_value` (w danych z E28.0 zgadza się 2/2); gdy w szczegółach jest tylko pole zbiorcze
    (`sold_…`/`collected_…`) bez pozycji, użyć pól zbiorczych;
  - `purchased_at = date[:19]`, `payment = payments[0].name`, `store = {code: store_id, name: store_name,
    address: store.street, postal: store.zip_code, locality: store.city}`.
  - Zgodność z Lidlem: suma `total − discount` pozycji + kaucja = `total_price` paragonu (test na fixture).
- **sanitize_detail:** dopisać do `_DROP_KEYS`: `receipt_barcode`, `extended_transaction_number`, `cashier_id`, `basket_id`,
  `invoice_id`, `id_from_receipt` (kopia surowa bez identyfikatorów kasjera/kodów).
- **Sync:** `HistorySync(chain_of=Callable[[str], str])` (domyślnie zawsze `lidl`, żeby stare testy nie ruszały);
  `upsert_tickets(..., chain=...)`; `parse_biedronka` zamiast `parse_detail` dla `chain == "biedronka"`; `_store_name`
  czyta też `store_name` z góry szczegółu. Kraje dodatkowe i kursy: tylko Lidl (Biedronka zawsze PL, `countries=(PL,)`).
- **Poza E28.1:** filtr `?siec=`, Budżet, Rytm/mapa, `translations`/nazwa wyświetlana (UI robię w kroku W2 poniżej).

## Etapy wewnętrzne
- **W1 (backend, „ryzyko”: migracja + tokeny → `sonnet-worker`).** Pliki i testy poniżej.
- **W2 (UI i konfiguracja — robię sam po W1, bo wymaga weryfikacji wizualnej):** formularz „Dodaj konto” z wyborem sieci,
  `login.html` w wersji Biedronki w zakresie `.chain-biedronka` (instrukcja: captcha + SMS w przeglądarce, wklej `app://…`),
  etykieta sieci w `index.html` (`.chain-tag`), `LidlService.begin_login/finish_login` rozgałęzione po `chain`
  (`client/biedronka.py`), `daily._accounts()` → tylko konta Lidla dla kuponów i nagród (`_import_accounts()` = wszystkie
  połączone dla `run_daily`/`run_hourly`), `HistorySync(chain_of=…)` w `web/app.py`, `config.yaml` nazwa
  „Zakupy (Lidl + Biedronka)” (bez zmiany slug/wersji), `THIRD_PARTY_NOTICES.md` (Przemko92/home-assistant-mojabiedronka, MIT,
  commit `b3c2b7302449`), zrzut Playwright + konsola.

## Wykonawca (W1)

**Repo:** `/config/addons/ha-lidl-app` (worktree z `wt new /config/addons/ha-lidl-app e28-1-w1`; podany jako `WORKTREE:`).
Katalog aplikacji: `lidl/app` (`src/lidl`, `tests`). Komenda testu: `cd <WORKTREE>/lidl/app && uv run pytest -q`
oraz `uv run ruff check . && uv run ruff format --check . && uv run mypy src` (jak w CI repo; ten sam zestaw musi przejść).
Wzorzec kodu klienta: `~/dev/biedronka-spike/vendor/biedronka/{auth,api,const}.py` (MIT, tylko do przepisania, nie importować;
wolno czytać; plików spoza worktree nie zmieniać).

Pliki i zmiany:
1. `src/lidl/client/biedronka.py` (nowy). Własny, przycięty klient aiohttp:
   - stałe: `API_BASE=https://api.prod.biedronka.cloud/api/v7`, `AUTH_BASE=https://konto.biedronka.pl`, realm `loyalty`,
     `CLIENT_ID=cma20`, `REDIRECT_URI=app://cma20.biedronka.pl`, `API_APP_VERSION="2.56.0"`;
   - `generate_pkce()`, `authorization_url(challenge)`, `auth_code_from_redirect(value)` (z `app://…?code=…` lub samego kodu),
     `class BiedronkaLogin` z `prepare() -> str` (ustawia `verifier`, `auth_url`) i `async exchange_code(code, verifier) ->
     {"access_token","refresh_token"}`, `async refresh_tokens(session, refresh_token)`; `jwt_payload` zaimportować z `.auth`;
   - `class BiedronkaApi(session, access_token, refresh_token, save_tokens)`: `ensure_fresh_token` (odświeża 60 s przed `exp`),
     retry po 401 (jedno odświeżenie), obsługa 426 (`min-supported-version-android` → podbicie wersji w pamięci i powtórzenie),
     metody `transactions(page)`, `archived(page)`, `transaction_details(id)`; nagłówki `Authorization`, `User-Agent:
     Android/<wersja>`, `Accept-Language: pl-PL`, `Accept: application/json`;
   - błędy: 401 po odświeżeniu / `invalid_grant` → `LidlPlusAuthError`; błąd sieci → `LidlPlusCannotConnect`; inny status →
     `LidlPlusError(f"http_{status}", status=status)` (import z `.exceptions`). Nigdzie nie logować tokenów, nagłówków,
     URL-i z `code=` ani treści odpowiedzi.
2. `src/lidl/receipt_biedronka.py` (nowy): `parse_biedronka(detail: dict) -> ParsedReceipt` według sekcji „Szczegół” wyżej.
3. `src/lidl/receipt.py`: dopisać klucze do `_DROP_KEYS` (patrz wyżej). `PARSER_VERSION` bez zmian.
4. `src/lidl/history.py`: `SCHEMA_VERSION = 8`; kolumna `chain` w `_SCHEMA` (`tickets`) i `_migrate_v7(path)` (kopia
   `.pre-biedronka` + `ALTER TABLE tickets ADD COLUMN chain TEXT NOT NULL DEFAULT 'lidl'`, tylko gdy tabela istnieje i kolumny
   brak); wywołanie `if version < 8` obok pozostałych; `upsert_tickets(..., chain: str = "lidl")` zapisuje `chain` przy
   INSERT (konflikt nadal aktualizuje tylko `articles`).
5. `src/lidl/accounts.py`: `Account.chain: str = "lidl"`; `AccountStore.create(label, chain="lidl")` (dozwolone `lidl`,
   `biedronka`, inne → `ValueError("bad_chain")`); `get()` czyta `chain` (brak/nieznane → `lidl`); `save_tokens` zachowuje
   `chain`; `_write` ma zawsze `chain`.
6. `src/lidl/service.py`: `_api(slug, country)` dla konta Biedronki zwraca `BiedronkaApi` (zapis tokenów jak dziś, ta sama
   blokada per konto); `tickets()` i `ticket()` rozgałęzione po `account.chain` zgodnie z „Lista w sync” i „Szczegół”
   (id bez prefiksu `b:` do API); `begin_login/finish_login/check` rozgałęzione po `chain` (`BiedronkaLogin`; `check` dla
   Biedronki = `transactions(1)` bez wyjątku). Metody tylko-Lidlowe (`promotions`, `lotteries`, `coupon_plus`, `activate`)
   dla konta Biedronki rzucają `LidlPlusError("not_supported")`.
7. `src/lidl/sync.py`: `chain_of` w konstruktorze, `upsert_tickets(chain=…)`, wybór parsera i `_store_name` jak wyżej,
   dla Biedronki `countries` ignorowane (tylko PL).
8. Testy (tdd: najpierw czerwone, neutralne fixtures „Sklep X”, bez prawdziwych imion, miast, adresów, EAN-ów z danych usera —
   wymyślone EAN-y 5900000000001…):
   - `tests/test_receipt_biedronka.py`: pozycja z rabatem, na wagę (`KG`), kaucja z pozycji (pobrana + zwrot), płatność, sklep,
     spójność sumy `total − discount + kaucja = total_price`, brak EAN → klucz po nazwie, `sanitize_detail` usuwa nowe klucze;
   - `tests/test_biedronka_client.py`: `aiohttp` z lokalnym serwerem testowym albo atrapą sesji (wzorzec z `tests` klienta
     Lidla, jeśli jest): 401 → odświeżenie → powtórzenie, rotacja tokenu zapisana, 426 → podbicie wersji i powtórzenie,
     `invalid_grant` → `LidlPlusAuthError`, paginacja `archived` do `page_count`;
   - `tests/test_accounts.py`: `chain` zapisany/odczytany, brak pola = lidl, `save_tokens` zachowuje `chain`, zły `chain` → błąd;
   - `tests/test_history.py`: migracja v7→v8 na bazie v7 (kopia `.pre-biedronka`, wiersze dostają `lidl`), świeża baza, `upsert_tickets`
     z `chain="biedronka"`;
   - `tests/test_sync.py`: import Biedronki (`chain_of`) z atrapą źródła: lista offset 0 i 1, szczegóły zapisane z `b:` EAN-ami,
     paragon Biedronki daje te same pola co paragon Lidla (`TicketDetail` ma `items`, `deposit`, `store`), zakończenie
     historii na offset 2, błąd 401 → `stopped` + `auth`;
   - `tests/test_service.py`: routing `tickets`/`ticket` po `chain` (atrapa `BiedronkaApi`), `not_supported` dla kuponów.
9. Wersje: nic nie zmieniać (wydanie po E28.2).

DONE: wszystkie powyższe testy zielone; pełny `uv run pytest -q` bez regresji (zestaw przed zmianą: patrz BASELINE od rodzica),
`ruff check`, `ruff format --check`, `mypy src` czyste; `git status --short` pokazuje tylko pliki z listy wyżej.

NIE RÓB: nie ruszaj `web/`, `daily.py`, `config.yaml`, `translations/`, `docs/`, `THIRD_PARTY_NOTICES.md`, `README`, `CHANGELOG`;
nie commituj; nie czytaj `~/.secrets`, `~/dev/biedronka-spike/data` (dane osobowe) ani żadnych tokenów; nie wykonuj żądań do
sieci prawdziwej Biedronki (wszystko na atrapach); nie zmieniaj istniejących asercji testów (poza koniecznym podbiciem wersji
schematu 7→8); żadnych prawdziwych imion/miast/adresów/EAN-ów w fixtures i komentarzach.

## Rollback
`git revert` commita E28.1 (kolumna `chain` jest nieszkodliwa dla starego kodu; pliki kont Biedronki stary kod czyta jako konta
Lidla bez tokenów Lidla → „rozłączone”; po cofnięciu usunąć je w Konta albo przywrócić `history.db.pre-biedronka`).

## Weryfikacja etapu
1. `uv run pytest -q`, `ruff`, `mypy` w `lidl/app` (po W1 i po W2).
2. Playwright (dev server, `Settings(dev=True)`): Konta → „Dodaj konto” z wyborem Biedronki → ekran logowania w stylu D2
   (zrzut + konsola bez błędów, kontrast przycisku `--blue`/`--on-blue`).
3. Import na żywo dopiero po wydaniu (E28.2) — wtedy logowanie osoba1 robi user, a liczbę (22) i sumy porównuje z aplikacją.
