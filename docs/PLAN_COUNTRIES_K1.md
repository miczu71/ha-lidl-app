# PLAN K1 — model danych i pobieranie list (fundament paragonów zagranicznych)

Roadmapa: `docs/ROADMAP_countries.md`. Etap niesie wartość sam: po nim zagraniczne paragony (kwota w PLN po kursie NBP
+ oryginał) są w bazie i widoczne w istniejącej liście Paragonów; pozycje i Budżet dopiero w K3/K5.
Ryzyko: migracja bazy → wykonawca `sonnet-worker`.

## Decyzje (wywiad 2026-11-14)
- Pozycje zagraniczne do OSOBNEJ tabeli `foreign_items` (19 zapytań po `items` w `history.py` zostaje polskich bez ruszania).
- `tickets.id` zostaje kluczem głównym (identyfikatory Lidla to GUID-y; test sprawdza brak kolizji przy upsercie).
- `tickets.total`/`savings` = PLN po kursie NBP (sumy w całym add-onie działają bez zmian); oryginał w `total_orig`.
- Kurs: tabela A NBP, ostatni dzień roboczy PRZED dniem zakupu, cache w bazie. Brak kursu (awaria NBP) = paragon
  pomijany w tym przebiegu i ponawiany następnego (nie wstawiamy z kursem zgadniętym).
- Waluta z LISTY (`currency`; w szczegółach jej nie ma). Kształt pola nieznany (dict?) → parser tolerancyjny + mapa
  awaryjna kraj→waluta (CZ→CZK, IT→EUR, SK→EUR, DE→EUR, AT→EUR, HU→HUF, RO→RON, HR→EUR, FR→EUR, ES→EUR, GB→GBP).
- Zagranica tylko w przebiegu dziennym 07:00 i „Sprawdź teraz” (godzinny import zostaje polski).
- Kopia bazy `<db>.pre-countries` przed migracją v5→v6 (sqlite backup API).

## Wykonawca
Pliki i zmiany (wszystko w `/config/addons/ha-lidl-app/lidl/`, kod w `app/src/lidl/`):
1. `history.py`: `SCHEMA_VERSION = 6`; `_migrate_v5()` — najpierw kopia `<path>.pre-countries` (sqlite3 `backup`, tylko gdy
   istnieje `tickets`), potem `ALTER TABLE tickets ADD COLUMN country TEXT NOT NULL DEFAULT 'PL'`, `currency TEXT NOT NULL DEFAULT 'PLN'`,
   `total_orig REAL`, `fx_rate REAL NOT NULL DEFAULT 1` (+ wywołanie w `__init__` obok `_migrate_v4`). `_SCHEMA`: tabele
   `fx_rates (code TEXT, day TEXT, mid REAL NOT NULL, PRIMARY KEY (code, day))` i
   `foreign_items` (kolumny jak `items`, `ticket_id REFERENCES tickets(id) ON DELETE CASCADE`, `art_id` z prefiksem `CZ:`/`IT:`).
2. `history.py`: `upsert_tickets(account, tickets, country="PL", fx=None)` — dla `country != "PL"` wymaga `fx` (callable
   `(currency, day) -> float | None`); kurs `None` → paragon pomijany; zapis `total = round(orig * rate, 2)`, `total_orig`, `currency`, `fx_rate`, `country`;
   istniejące wiersze: nadal tylko odświeżenie `articles`. Zwraca liczbę nowych.
3. `fx.py` (nowy): `currency_code(raw, country) -> str` (str → upper; dict → klucze `code`/`currencyCode`/`isoCode`; inaczej
   mapa awaryjna; log.warning z kształtem — typ i nazwy kluczy, bez wartości); `NbpRates` — `rate(code, day, session) -> float | None`
   (EUR/CZK/…: `GET https://api.nbp.pl/api/exchangerates/rates/a/{code}/{day-10}/{day-1}/?format=json`, bierze ostatni wpis; cache w
   `fx_rates`; 404/timeout → `None`; PLN → 1.0). Wstrzykiwalny `fetch` (seam testów).
4. `service.py`: `_api(slug, country="PL")` — osobny `LidlPlusApi` per (konto, kraj) na tym samym tokenie (współdzielone
   `save_tokens`); `tickets(slug, offset, country="PL")`, `ticket(slug, id, country="PL")`. Odświeżenie tokenu przez jedno API
   musi trafić do pozostałych (po `save_tokens` czyść `_apis` konta).
5. `settings.py`: `extra_countries: tuple[str, ...] = ()` z opcji (wielkie litery, tylko `^[A-Z]{2}$`, bez `PL`); `config.yaml`
   `options.extra_countries: []`, `schema.extra_countries: ["match(^[A-Z]{2}$)"]`; `translations/pl.yaml` + `en.yaml` opis.
6. `sync.py`: `_import_lists(slug, full, country)`; `import_account(..., countries=("PL",))` — dla każdego dodatkowego kraju
   osobna pętla offsetów z `upsert_tickets(..., country, fx)`; błąd 400/403/404 kraju = log.info, kraj pomijany (nie przerywa konta).
   `run_daily` i „Sprawdź teraz” przekazują `settings.extra_countries`, `run_hourly` zawsze `("PL",)`.
   Szczegóły (`pending_details`) dla zagranicy NIE w K1 — `detail_fetched` zostaje 0, import szczegółów pomija `country != 'PL'`.
7. Testy (`tests/test_history.py`, nowy `tests/test_fx.py`, `tests/test_sync.py`): migracja z bazy v5 (kopia `.pre-countries`
   istnieje, dane PL bez zmian, domyślne PL/PLN/1); upsert zagraniczny z `fx` (kwota, brak kursu = pominięty, duplikat między
   offsetami 0 i 1 = jeden wiersz); `currency_code` dla str/dict/None; `NbpRates` z wstrzykniętym `fetch` (weekend → wcześniejszy dzień, 404 → None, cache);
   `import_account` z `extra_countries=("CZ",)` na fałszywym źródle.

Komenda testu: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q && uv run ruff check . && uv run mypy src`

DONE: wszystkie testy + ruff + mypy zielone; istniejące testy PL bez zmian (żadna asercja istniejącego testu nie osłabiona);
na kopii bazy z `~/lidl_dev` (dev, bez tokenów) migracja v5→v6 daje `PRAGMA user_version = 6` i plik `.pre-countries`.
NIE RÓB: zmian w `receipt*.py`, `web/`, `budget_feed.py`, `coupons.py`, `rewards.py`, `promotions.py`, `geo.py`; bumpu wersji add-onu;
commitów; uruchamiania czegokolwiek z tokenami ani odczytu `~/.secrets`; zmian zapytań po `items`.

## Weryfikacja na żywo (po wydaniu zbiorczym)
Ustaw `extra_countries: [CZ, IT]`, „Sprawdź teraz” → w logu „Import konta …: N nowych”, w Paragonach 4 zagraniczne (3 CZ, 1 IT),
kwoty w PLN ≈ oryginał × kurs; log zawiera ostrzeżenie o kształcie `currency` tylko jeśli nie był tekstem.

## Rollback
Przywrócić `<db>.pre-countries` (zatrzymać add-on, podmienić plik) i wersję add-onu; opcja `extra_countries: []` wyłącza pobieranie bez cofania kodu.
