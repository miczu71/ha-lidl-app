# PLAN K2 — szczegóły i pozycje zagranicznych paragonów

Zależy od K1. Wartość: pozycje CZ/IT zapisane (do kategorii AI w K4 i późniejszego porównania cen), paragon ma sklep i płatność.
Wykonawca: `sonnet-worker` (parser na nieznanym formacie, niejasne ryzyko).

## Decyzje
- Parser HTML (`receipt_html.py`) uruchamiamy na czeskim/włoskim `htmlPrintedReceipt`; pozycje do `foreign_items`.
  Zgodność: suma pozycji musi zgadzać się z `total_orig` (tolerancja 0,01 waluty), inaczej `parsed=0` i paragon zostaje
  tylko z kwotą (jak „nierozpoznany” PL) — nigdy zgadywane pozycje.
- `fiscalDataCZ`/`fiscalDataAt`/`ustIdNr` zostają w `_DROP_KEYS` (dane fiskalne nie do bazy).
- `art_id` zagraniczny z prefiksem kraju (`CZ:1234567`), żeby nie kolidował z polskimi w `product_category`.
- `PARSER_VERSION` bez zmian dla PL; zagraniczne mają własny `detail_version`.

## Wykonawca
1. **Rozpoznanie formatu (bez tokenów usera):** na pierwszym imporcie add-on zapisuje oczyszczoną kopię (`ticket_raw`, już
   istnieje). Worker NIE sięga po prawdziwe dane: fixtures piszemy po tym, jak USER wklei 1 zanonimizowany fragment HTML
   z każdego kraju (CZ, IT) do `tests/fixtures/receipt_cz.html`/`receipt_it.html` z neutralnymi nazwami („Sklep X”, „Produkt A”).
   Jeśli fixtures brak → worker zatrzymuje się i zgłasza „czeka na fixtures” (nie wymyśla formatu).
2. `receipt_html.py`: parametr `locale` (`pl`/`cs`/`it`) wybierający wzorce liczb/etykiet (separatory dziesiętne, słowa „SUMA/CELKEM/TOTALE”);
   PL bez zmian zachowania (istniejące testy `test_receipt_html.py` muszą przejść bez edycji).
3. `receipt.py`: `parse_detail(detail, country="PL")` przekazuje `locale`; `language` z pola `languageCode` jako podpowiedź.
4. `history.py`: `pending_details(account)` obejmuje zagraniczne (`country` w wyniku); `save_detail(..., country)` zapisuje do
   `foreign_items` z prefiksem `art_id` i weryfikuje sumę względem `total_orig`; kasowanie starych pozycji przy reparsie jak dla PL.
5. `sync.py`: pętla szczegółów woła `self._source.ticket(slug, id, country)` (kraj z wiersza); w przebiegu godzinnym nadal
   tylko PL.
6. Testy: `test_receipt_html.py` (cs/it z fixtures), `test_history.py` (zapis do `foreign_items`, niezgodna suma = `parsed=0`,
   brak wpływu na `items` i zapytania PL — asercja, że `ranking()`/`price_overview()` nie widzą pozycji zagranicznych).

Komenda testu: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q && uv run ruff check . && uv run mypy src`

DONE: testy zielone; fixtures neutralne (przechodzą hook pre-commit); `items` i wszystkie widoki PL bez zmian wyniku.
NIE RÓB: prawdziwych nazw sklepów/produktów w fixtures; zmian w `web/`, `budget_feed.py`; osłabiania testów PL; bumpu wersji.

## Rollback
Kod: revert commitów etapu. Dane: `DELETE FROM foreign_items; UPDATE tickets SET detail_fetched=0 WHERE country!='PL'` (przetworzenie od nowa).
