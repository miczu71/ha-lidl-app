# PLAN K3 — widoki: Paragony, sumy, podsumowanie miesiąca (Rytm zostaje polski)

Zależy od K1 (K2 opcjonalnie dla pozycji na paragonie). Wartość: zagraniczne zakupy widać obok polskich, z flagą,
kwotą w PLN i oryginałem. Wykonawca: `sonnet-worker` (audyt 34 zapytań po `tickets` wymaga osądu).

## Decyzje
- Rytm (heatmapa godzin, mapa, lista sklepów), skuteczność kuponów (`coupon_effect`) i geokodowanie: tylko `country = 'PL'`.
- Sumy (Paragony, Miesiące, KPI, baner miesiąca, Status — liczniki paragonów) liczą zagranicę w PLN; w Miesiącach osobna linia
  „w tym za granicą: X zł (CZ, IT)”.
- Oznaczenie kraju: SVG flaga (symbol w sprite, bez emoji/PNG — zasada projektu), kwota PLN główna, w nawiasie oryginał
  („175,40 CZK”), filtr `?kraj=` w liście Paragonów obok konta/sklepu.
- Format kwot: `fmt_pln` zostaje; nowy `fmt_money(amount, currency)` w `text.py` (NBSP, przecinek, kod waluty po spacji).

## Wykonawca
1. Audyt: wypisz każde z 34 zapytań `FROM tickets|JOIN tickets` w `history.py` do tabeli w tym pliku (sekcja „Audyt”) z werdyktem
   „+zagranica” / „tylko PL” / „bez znaczenia”. Reguła: tylko PL — Rytm, geo, efekt kuponów, wszystko łączące `tickets` z `items`.
   Dla „tylko PL” dodaj `AND country = 'PL'` (parametr `country` w publicznych metodach tylko tam, gdzie widok ma filtr).
2. `history.py`: `ticket_list(...)` i `receipt(ticket_id)` zwracają `country`, `currency`, `total_orig`; `month_summary()` dodaje
   `abroad_total`, `abroad_countries`; filtr `country` w `ticket_list`.
3. `text.py`: `fmt_money`; `web/receipts.py` + szablony `receipts*.html`: flaga (symbole `i-flag-cz`, `i-flag-it` w sprite),
   oryginał w nawiasie, filtr kraju (htmx jak filtr sklepu); `web/months.py`/`notify.py`: linia „za granicą”.
4. Flagi: proste SVG (własne, prostokąt 3 pasy/2 kolory, bez cudzych znaków), dodać `docs/DESIGN.md` wpis; użyć `impeccable` do
   weryfikacji układu (Playwright, zrzut do `/config/playwright/`).
5. Testy: `test_history.py`/`test_web.py` — Rytm i `coupon_effect` ignorują zagranicę (dane mieszane), Paragony pokazują oba,
   filtr `?kraj=CZ`, `month_summary` z `abroad_total`, `fmt_money`.

Komenda testu: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q && uv run ruff check . && uv run mypy src`

DONE: testy zielone; tabela audytu uzupełniona; na danych demo (seed z zagranicznymi paragonami, `~/dev/lidl-spike/seed_*` wzorem
`seed_receipts_demo.py`) Paragony pokazują flagę i oryginał, a Rytm liczy tylko PL (zrzut Playwright).
NIE RÓB: zmian w `budget_feed.py`, `receipt*.py`, `coupons.py`; zmiany sum PL przy danych tylko polskich (wynik ma być identyczny).

## Rollback
Revert commitów etapu; dane nietknięte.

## Audyt
Zapytania `FROM/JOIN tickets` w `history.py` (łącznie z zapisem/migracją). „Tylko PL” = `country = 'PL'` w SQL.

| Zapytanie (metoda) | Werdykt |
|---|---|
| `_ensure`/`has_tables` (sqlite_master), sprawdzenia schematu | bez znaczenia |
| `known` w imporcie listy (`SELECT 1 FROM tickets WHERE id`) | bez znaczenia |
| `ticket_count` (COUNT, z kontem i bez) | +zagranica |
| `last_day`/`MAX(day)` | +zagranica |
| ids do pobrania szczegółów (`account = ? AND country = 'PL'`, K1) | tylko PL (już) |
| `articles` po id | bez znaczenia |
| `SELECT * FROM tickets WHERE id` | bez znaczenia |
| `detail_version < ?` JOIN `ticket_raw` (reparse) | bez znaczenia |
| `budget_tickets` (≈l.1143) | bez zmian (K4) |
| zapytania `items i JOIN tickets t` (ranking, nazwy, price_rows, shrink, product_purchases, _products, month earlier, coupon_effect, _coupon_used, spend_series pozycje, savings items) | tylko PL de facto (zagranica bez `items`, K2) — bez zmian |
| `main_store` | tylko PL (dodano) |
| `savings_kpi` (liczniki i sumy z `tickets`) | tylko PL (dodano) |
| `savings_kpi` (items JOIN tickets) | tylko PL de facto (bez items) |
| `purchase_totals` (SUM/COUNT total, kaucje) | +zagranica |
| `spend_series` (kaucje z `tickets`) | +zagranica (kaucje zagranicy 0) |
| `tickets` (lista + COUNT) | +zagranica (+ filtr `country`) |
| `ticket_months` | +zagranica |
| `month_summary` (lista paragonów miesiąca) | +zagranica (+ `abroad_total`, `abroad_countries`) |
| `stores` | tylko PL (dodano) |
| `stores_without_geo` | tylko PL (dodano) |
| `rhythm` | tylko PL (dodano) |
| `_savings_breakdown` ticket_rows | tylko PL (dodano) |
| `_savings_breakdown` items, `ticket_coupons` JOIN tickets | tylko PL de facto (bez items/kuponów) |
| `ticket` (szczegół) | +zagranica (z country/currency/total_orig) |
| `countries` (nowa, do filtra) | +zagranica |
