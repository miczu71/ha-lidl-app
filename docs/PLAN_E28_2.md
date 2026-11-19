# PLAN E28.2 — wspólne widoki z filtrem sieci (`?siec=`) + `chain` w pliku dla Budżetu

Źródło prawdy: `docs/ROADMAP.md` (E28), `docs/PLAN_E28_biedronka.md`. Stan wejściowy: E28.1 (`d622cd8`), schemat v8
(`tickets.chain`), add-on 1.2.1. Wydanie 1.3.0 po tym etapie (łańcuch: simplify → code-review → release).

## Zakres
Wartość: user widzi Lidla, Biedronkę albo obie sieci razem w każdej zakładce; Budżet dostaje `chain` w `receipts.json`.
- `?siec=lidl|biedronka` (brak = obie) w: Paragony (+ znacznik sieci przy wierszu), Ceny, Miesiące, Rytm, Oszczędności.
  Nieznana wartość = brak filtra. Filtr jako pigułki „Wszystkie / Lidl / Biedronka” (bez JS), pokazywany tylko gdy w bazie są
  paragony obu sieci (jedna sieć = widok bez zmian).
- Push 1. dnia miesiąca: gdy w miesiącu były paragony obu sieci, dodatkowa linia „Lidl X zł · Biedronka Y zł”.
- Rytm/mapa: sklepy Biedronki bez współrzędnych — lista sklepów bez punktu na mapie (lokalizator Biedronki poza E28.2;
  mapa tylko dla sklepów ze współrzędnymi). Status: wpisy `sync` pokazują sieć konta (`.chain-tag`).
- `budget_feed.py`: `chain` w każdym paragonie `receipts.json`; prompt kategorii bez „Lidl” (neutralny: „ze sklepu
  spożywczo-dyskontowego”); `version` pliku zostaje 1 (pole dodatkowe nie psuje starego Budżetu).
- Poza E28.2: logo sieci w Budżecie i dopasowanie po `chain` (E28.3), porównanie cen (E28.4), lokalizator sklepów.

## Decyzje
- `ReceiptFilter.chain: str | None`; `_receipt_where` dodaje `t.chain = ?` → automatycznie działają `tickets`, `ticket_months`,
  `stores`, `rhythm`, `savings_breakdown`, `month_summary`. `TicketSummary.chain: str = "lidl"` (ostatnie pole, wartość domyślna).
- Ceny: `_price_rows(chain=None)` (klucz cache `("price_rows", chain)`, filtr `t.chain = ?` w SQL), `price_overview(today, chain=None)`,
  `shrinkflation(today, chain=None)` z `chain` w kluczu cache. `product_prices(art_id)` bez zmian (kod produktu wyznacza sieć).
- `month_summary(month, chain=None)`: filtr przekazany do `ReceiptFilter`; `by_month` i `rank` liczone w obrębie sieci.
  `History.month_chain_totals(month) -> dict[str, tuple[int, float]]` (sieć → (paragony, zapłacono)) do linii w pushu.
- Rollback: `git revert` commitów etapu; brak zmian schematu.

## Etapy wewnętrzne
- **W1 (backend + budget_feed + notify; „ryzyko”: cache i SQL → `sonnet-worker`)** — poniżej.
- **W2 (web: trasy, szablony, pigułki, Status — robię sam po W1, bo wymaga weryfikacji wizualnej Playwright 390/1280 px).**

## Wykonawca (W1)

**Repo:** `/config/addons/ha-lidl-app` (worktree `wt new /config/addons/ha-lidl-app e28-2-w1`, podany jako `WORKTREE:`).
Katalog aplikacji: `lidl/app` (`src/lidl`, `tests`). Test: `cd <WORKTREE>/lidl/app && uv run pytest -q` (13 testów w
`tests/test_leaflet.py` pada też na main — zależne od daty, ignorować) oraz `uv run ruff check . && uv run ruff format --check . && uv run mypy src`.
TDD: najpierw test (czerwony), potem kod.

Pliki i zmiany:
1. `src/lidl/history.py`:
   - `ReceiptFilter.chain: str | None = None`; `_receipt_where`: `("t.chain = ?", f.chain)`.
   - `TicketSummary.chain: str = "lidl"` jako ostatnie pole; `_TICKET_COLS`/`_summary` czytają `t.chain` (zachowaj
     kolejność kolumn i `_TICKET_N` spójne we wszystkich użyciach `_TICKET_COLS`).
   - `_price_rows(chain: str | None = None)` + `_collect_price_rows(chain)` (SQL: dodatkowy `AND t.chain = ?` gdy chain);
     `price_overview(today, chain=None)`, `_price_overview(today, chain)`, `shrinkflation(today, chain=None)`; klucze `_cached` z `chain`.
   - `month_summary(month, chain=None)`; `ReceiptFilter(start=…, end=…, chain=chain)` w obu miejscach (też `ticket_months`
     wewnątrz); nowa metoda `month_chain_totals(month)`.
   - `has_chains() -> set[str]`: `SELECT DISTINCT chain FROM tickets`.
   - `receipts_export`: dodać `chain` (kolumna `chain` z `tickets`) do każdego słownika paragonu.
2. `src/lidl/budget_feed.py`: PROMPT bez słowa „Lidl” (np. „ze sklepu spożywczo-dyskontowego (Lidl lub Biedronka)” jest OK,
   byle nazwy sieci nie sugerowały jednej); reszta bez zmian.
3. `src/lidl/notify.py` + `src/lidl/daily.py`: `compose_month(s, by_chain: dict[str, tuple[int, float]] | None = None)`;
   gdy `by_chain` ma ≥2 sieci, treść dostaje linię „Lidl 123,45 zł · Biedronka 67,89 zł” (kolejność lidl, biedronka; format
   kwot jak reszta pushu); `daily` przekazuje `history.month_chain_totals(month)`.
4. Testy: `tests/test_history.py` (filtr `chain` w `tickets`/`ticket_months`/`stores`; `_price_rows` per sieć i klucze cache nie
   mieszają sieci; `month_summary(chain=…)`; `month_chain_totals`; `has_chains`; `receipts_export` ma `chain`),
   `tests/test_budget_feed.py` (`chain` w pliku, prompt bez „Lidl” jako jedynej sieci), `tests/test_notify.py` (linia sieci
   tylko przy ≥2 sieciach), `tests/test_daily.py` jeśli zmiana wywołania wymaga.
   Dane testowe: istniejące helpery `upsert_tickets(..., chain="biedronka")` na neutralnych nazwach „Sklep X”.

DONE: pytest (poza 13 znanymi), ruff, mypy czyste; nowe testy czerwone przed kodem i zielone po; `git diff --stat` tylko pliki wyżej.
NIE RÓB: zmian w `web/`, szablonach, `client/`, `accounts.py`, `sync.py`, schemacie (`SCHEMA_VERSION` zostaje 8); commitów;
dotykania `tests/test_leaflet.py`; zmiany sygnatur publicznych poza wymienionymi.
