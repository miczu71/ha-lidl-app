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
