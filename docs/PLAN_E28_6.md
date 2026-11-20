# PLAN E28.6 — domknięcie uwag E28.4/E28.5 + mapa sklepów Biedronki

Wywiad 2026-11-20 (zatwierdzony „go”). Wydanie: jedno **1.5.1** na końcu obu podetapów, bez zmiany schematu bazy
(chyba że B wykaże kolizję kodów w `store_geo` — wtedy migracja v11 z kopią `.pre-…`).

## Cel i sukces
Kto: Ty i Ada. Mniej cichych awarii, mapa sklepów obu sieci, możliwość cofnięcia pomyłki w parowaniu.
Sukces: testy zielone, ruff/mypy czyste; na żywo 1.5.1: sklepy Biedronki na mapie Rytmu, wymuszony błąd Shakeomatu
widoczny w Statusie bez pusha, odrzucona para EAN daje się przywrócić, kody Biedronki nie dostają NULL w `store_geo`.

## Decyzje z wywiadu
1. Bez bramki weryfikacji E28.5 — punkty zależne od kształtu migawki dochodzą później jako **E28.6b**.
2. Błędy Shakeomatu: poziom `warn` w Statusie (obszar Oszczędzanie), **bez** Problemu, kropki-alarmu i pusha.
   `KeyRejected` już tworzy Problem (`web/status.py::_ai`) — poza zakresem.
3. „Przywróć” w sekcji „Bez odpowiednika” dla pary EAN → wraca jako zatwierdzona para EAN.
4. Wiek migawki: zawsze podpis „Dane z <data, godz.>”, po 36 h wyróżnienie na żółto.
5. Mapa Biedronki: geokodowanie adresów z paragonów w **Nominatim (OSM)**, raz na sklep, wynik w `store_geo`;
   generyczny User-Agent (bez danych usera), ≤1 zapytanie/s; adres bez trafienia → zapis NULL (jak dziś u Lidla),
   „brak na mapie”, bez ponawiania. Wysyłane są tylko publiczne adresy sklepów.
6. Filtr `chain` w `stores_without_geo` robimy teraz (kody Biedronki nie mogą trafiać do listy Lidla).
7. Podział: **A** poprawki (haiku-worker, `wt new`), **B** mapa (robię sam — zewnętrzna usługa).

## Kroki
- E28.6.0 docs ✅ (ten plik)
- E28.6.1 podetap A (W1, commit)
- E28.6.2 podetap B (commit)
- E28.6.3 wydanie 1.5.1: `simplify` → `code-review` + `silent-failure-hunter` + `pr-test-analyzer` + security → `release` → weryfikacja na żywo

Rollback: `git revert` commitów A/B albo wydanie 1.5.2 z revertem; baza bez zmian (B: wiersze `store_geo` dla Biedronki
można usunąć `DELETE`, geokodowanie wróci przy kolejnym przebiegu).

## Wykonawca — podetap A (haiku-worker, ryzyko niskie)
Repo `/config/addons/ha-lidl-app`, kod `lidl/app/src/lidl/`, testy `lidl/app/tests/`. Komenda testu (z `lidl/app`):
`uv run pytest -q --ignore=tests/test_leaflet.py && uv run ruff check . && uv run mypy .` (test_leaflet: 13 znanych
błędów zależnych od daty). Konwencje: skill `addon-conventions`.

| # | Plik | Zmiana |
|---|------|--------|
| 1 | `web/status.py` (`_daily` ~l.256–285) + test w `tests/test_status.py` | Zdarzenia `daily` z `detail.run == "shakeomat"` i `level == "error"` z ostatnich 12 h → w obszarze „Przebiegi zaplanowane” wiersz `facts`/poziom `warn` „Shakeomat: błąd” (bez `Problem`, bez zmiany `level` całego obszaru na error). Test: wpis shakeomat error → brak `Problem`, jest wiersz warn; wpis `morning` ok bez zmian. |
| 2 | `history.py::chain_pair_decide` (~l.2174) + `tests/test_chain_pairs.py` | Nowa akcja `restore` (tylko dla wiersza `status='rejected'` i `source='ean'`): odtwarza parę EAN — użyj tej samej logiki dopasowania co auto-EAN w `chain_pairs.py` (~l.56–58) dla danego `b_art_id`; gdy dopasowania EAN brak → `proposed`. False dla innych wierszy. Testy: restore EAN-rejected → approved/ean; restore na manualnie odrzuconej → False. |
| 3 | `web/app.py` (`/sieci/para`, ~l.1075) | Akcja `restore` przekazana do `chain_pair_decide`; złe/nieznane akcje zwracają 400 z krótkim komunikatem zamiast cichego 200. |
| 4 | `web/templates/_chains_body.html` (~l.78–83) | Dla `r.is_ean` przycisk „Przywróć” (`pair_form(..., "restore", "Przywróć", ...)`); usunąć komentarz o „odrzuconej na stałe”. |
| 5 | `web/chains.py` + szablony Sieci | `?kat=` zachowany po akcjach htmx (hx-vals/hx-include albo `hx-push-url`; sprawdź, jak `chains_ctx` czyta `kat`). Test trasy: akcja pary z `?kat=X` zwraca fragment z tym samym `kat`. |
| 6 | `web/templates/bdr_savings.html` (+ widok `web/bdr_savings.py`) + `tests/test_bdr_savings.py` | Podpis „Dane z <data, godz. lokalnie>” z czasu ostatniej udanej migawki (`chain_savings`); > 36 h → klasa ostrzegawcza (żółty, istniejąca klasa `warn` z `app.css`, bez nowych kolorów). Brak migawki → „Jeszcze bez danych”. |
| 7 | `web/templates/_countries_body.html:59` | `hx-trigger` `from:find input` → selektor ograniczony do tego formularza (`from:find input[type=search]`, jak w `_chains_search`/Sieci). |
| 8 | `history.py::stores_without_geo` (~l.2500) + `geo.py` + `tests/test_geo.py` | Filtr `t.chain = 'lidl'` (zgodnie z istniejącą kolumną `tickets.chain`). Test: sklep Biedronki nie trafia do `missing`, nie dostaje NULL. |

Seamy testów: bazy w pamięci jak w istniejących testach (`conftest.py`); bez sieci i bez prawdziwego API.
DONE: wszystkie 8 punktów z testami, `ruff`/`mypy` czyste, pełny zestaw (bez `test_leaflet.py`) zielony, `git status` bez
plików spoza listy.
NIE RÓB: migracji schematu, `release/`, `config.yaml` i `CHANGELOG`, plików `geo.py` poza filtrem chain, zmian
`Problem`/`alerts.py`, commitów, nowych zależności; nie ruszaj `receipt_*`.

## Podetap B — mapa sklepów Biedronki (ja)
1. Sprawdzić na żywej bazie format `store_id` Biedronki (kolumny `tickets.store_*` dla `chain='biedronka'`) i ryzyko
   kolizji kodów z Lidlem w `store_geo` (PK `code`); jeśli kolizja możliwa → klucz z prefiksem sieci (migracja v11).
2. `geo.py`: `refresh_store_geo_biedronka` — adres (ulica, kod pocztowy, miasto z `tickets.store_*`) → Nominatim
   (`/search?format=jsonv2&limit=1`), 1 zapytanie/s, generyczny User-Agent, timeout, błąd sieci = pominięcie bez zapisu
   NULL (ponowienie następnego dnia), brak trafienia = zapis NULL.
3. Hook: kroki „sklepy” w `daily.py` (~l.165) i w starcie `web/app.py` (~l.216) wywołują oba odświeżenia.
4. `web/rhythm.py`: punkty Biedronki na mapie z akcentem sieci (`.chain-biedronka`), „brak na mapie” dla reszty.
5. Testy z podstawionym klientem HTTP; wizualnie Playwright 390 i 1280 px na demo `~/lidl_dev`.
Weryfikacja na żywo: liczba sklepów Biedronki z punktem vs wszystkie; ręcznie 2–3 punkty vs adres.
Zgoda: wybór Nominatim jest decyzją usera z wywiadu; wysyłka dotyczy wyłącznie publicznych adresów sklepów.

## Poza zakresem
`KeyRejected` (już działa), E28.6b (punkty zależne od weryfikacji E28.5), P2, P3, ponawianie geokodowania adresów bez trafienia.
