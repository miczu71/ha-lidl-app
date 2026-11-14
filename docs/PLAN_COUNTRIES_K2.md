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
1. **Fixtures są gotowe** (zanonimizowane, w repo, `8554b56`): `lidl/app/tests/fixtures/foreign/{cz_0,cz_1,it_0}.json` (pola `htmlPrintedReceipt`,
   `languageCode`, `totalAmount`, `id`, `date`). Worker NIE sięga po prawdziwe dane ani sieć. Format (sprawdzony 2026-11-14):
   - pozycja = `span.article` z `data-art-id/-quantity/-unit-price/-tax-type/-art-description`; przecinek dziesiętny (`"19,90"`, `"2,374"`);
     pozycja z ilością ma dwie linie article (nazwa+kwota, potem „3 ks   x 19,90  Kč/ks” / IT „Cad 0,99 Pz. 3” / IT waga „  2,374 kg x 0,89  EUR/kg”) —
     druga linia nie tworzy pozycji (nie pasuje do `_DETAIL_LINE` PL: inne jednostki/układ; potrzebny wzorzec per `locale`);
   - CZ pozycje ważone NIE mają `class="article"`: zwykły `span` w `purchase_list` „Banány   16,20 B” + następny „N   0,406 kg   x 39,90  Kč/kg ”
     (kwota = ostatnia liczba pierwszej linii przed literą stawki, ilość/cena z drugiej); `art_id` brak → pusty (`CZ:` + nazwa znormalizowana NIE; zostaw `CZ:` + pusty = pozycja bez art_id, nie wchodzi do statystyk);
   - rabaty `span.discount` („2+1 zdarma …  -19,90”, „Lidl Plus sleva na nákup”, IT „Offerta Lidl Plus   10%   -0,59”): kwota = OSTATNIA liczba w linii
     (uwaga IT: procent „10%” stoi przed kwotą — ostatnia liczba nadal dobra); `coupon` gdy opis zawiera „Lidl Plus”; linie „Cena po slevě N” (plain span) ignorujemy;
   - waluta: `span.currency[data-currency]` („Kč”, „€”), suma w sekcji `purchase_summary` („K PLATBĚ 175,40”, IT „VALORE/TOTALE”); płatność: `data-tender-description` na `purchase_summary_*`
     (CZ „Karta”) — wyciągnij do `payment`, jeśli proste; inaczej `None`.
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
