# ROADMAP: paragony z innych krajów (CZ, IT)

Status: **K1–K5 wydane i zweryfikowane na żywo 2026-11-14 (Lidl 1.1.0, Budżet 0.75.0). D1 ✅ (2026-11-14). Dalej: K6 (zakładka „Kraje”, wywiad `grill-me`), jedno wydanie zbiorcze na końcu.**

## Cel
Pobierać do add-onu e-paragony z zakupów w Lidlu za granicą (w 2026: Czechy, Włochy). Paragony są widoczne w aplikacji
Lidl Plus po przełączeniu kraju. Kwoty w statystykach i w Budżecie przeliczamy na PLN po średnim kursie NBP z dnia zakupu,
z zapisem oryginalnej kwoty i waluty (decyzja usera).

## Stan kodu (sprawdzone 2026-11-13)
- Kraj na sztywno: `lidl/app/src/lidl/settings.py:11` (`COUNTRY="PL"`, `LANGUAGE="pl-PL"`), użycie w `service.py:35,70`.
- Klient API już przyjmuje kraj: `client/api.py` (`/v3/{country}/tickets`, `/v3/{country}/tickets/{id}`).
- Założenie PLN wszędzie: `text.fmt_pln`, tabela `tickets` (`history.py:69`) bez kolumny waluty, `budget_feed.py`, widoki w `web/`.

## Niewiadoma (rozstrzyga etap 0)
Czy token z logowania „PL” dostaje paragony z `/v3/CZ|IT/tickets`, czy trzeba logować się osobno w każdym kraju.

## Etap 0 — spike (tylko odczyt, bez zmian w add-onie)
Skrypt: `docs/spike_countries.py`. Tokeny zostają w pamięci, wypisuje tylko liczby, daty, sumy, waluty i nazwy kluczy.

1. Uruchom (user, bo wymaga logowania w przeglądarce):
   `! cd /config/addons/ha-lidl-app/lidl/app && uv run python ../../docs/spike_countries.py PL`
2. Otwórz wypisany adres, zaloguj się, wklej nagłówek `Location` (`com.lidlplus.app://…code=…`).
3. Wynik:
   - **A**: CZ/IT zwracają paragony przy tokenie PL → jedno konto, lista krajów do pobrania.
   - **B**: 403 albo pusto → uruchom z `CZ`, potem `IT` jako argumentem; osobny token na kraj (model jak osobne konto w `accounts.py`).
4. Zapisz wynik (bez danych osobowych) w tym pliku, sekcja „Wynik etapu 0”.

Rollback: brak zmian do cofnięcia.

## Decyzje z wywiadu (2026-11-14)
- Produkty, Ceny, Oszczędności, kupony i nagrody zostają polskie; pozycje zagraniczne w osobnej tabeli `foreign_items`.
  Porównanie między krajami = osobna zakładka „Kraje” (K6), nie standardowe porównania.
- Sumy, Paragony, Miesiące i Budżet liczą zagranicę w PLN po kursie NBP (ostatni dzień roboczy przed zakupem), oryginał w nawiasie. Rytm (mapa, heatmapa) tylko PL.
- Kategorie dla Budżetu: AI na pozycjach CZ/IT. Parowanie z transakcją z karty: tolerancja kwoty 5%, kwota z banku po sparowaniu.
- Kraje z opcji `extra_countries` (start CZ, IT); import raz dziennie 07:00 + „Sprawdź teraz”; oba konta; pełna historia, dedup po `id`.
- Jedno wydanie zbiorcze po K1–K5 (Lidl, potem Budżet); K6 osobno po obejrzeniu prawdziwych danych.
- Wywiad zatwierdzony przez usera 2026-11-14 („Go”). **Plany K1–K4 czekają na jego zgodę przed implementacją**; po zgodzie etapy idą po kolei, stop przy kroku spoza planu.

## Etapy (kontrakt Wykonawca w `docs/PLAN_COUNTRIES_K<n>.md`)
- **K1 ✅ 2026-11-14 (`f53da88`, wypchnięte)** model danych + pobieranie list + kurs NBP (migracja v6, `.pre-countries`, `extra_countries`) — `sonnet-worker` (migracja = ryzyko).
  Wynik: pełny pytest 474 zielone + 13 czerwonych w `tests/test_leaflet.py` (zahardkodowane daty z października, **te same 13 padają na `4973f64`** — dług niezwiązany z K1);
  ruff/format/mypy czyste; verifier REJECT → blokujące (ręczny import historii z panelu pomijał kraje) poprawione przeze mnie: `HistorySync.start()` bez `countries` bierze PL + `extra_countries` (+ test).
  Odstępstwa od planu: `web/app.py` podpięty przeze mnie (plan K1 błędnie zakazywał `web/`); kolumny też w `CREATE TABLE tickets`; `NbpRates.cached/prefetch`, `History.fx_get/fx_put`;
  `pending_details` ma `AND country='PL'`; zagraniczny duplikat bez kursu tylko odświeża `articles`. Nieblokujące: błąd 5xx/auth kraju przerywa konto po PL (zgodne z planem), nieznany kraj bez `currency` dostaje EUR.
  Na żywo dopiero po wydaniu K5 (`extra_countries` domyślnie puste = zero zmian zachowania).
- **K2 ✅ 2026-11-14 (`fedd296`)** szczegóły i pozycje zagraniczne (parser cs/it → `foreign_items`) — `sonnet-worker`.
  Wynik: pytest 478 zielone (bez `test_leaflet.py`; po poprawce 118 zielonych w test_history/sync/receipt_html), ruff/format/mypy czyste; fixtures cz_0 5 poz./175,40, cz_1 59 poz./2433,80, it_0 18 poz./43,91 — sumy (kwota+rabat) zgodne z `totalAmount`.
  Verifier REJECT → blokujące (przy `articles=0` i niezgodnej sumie pozycje trafiały do `foreign_items`) poprawione przeze mnie + test.
  Odstępstwa: `pending_foreign_details()` zwraca `[(id, country)]` (`pending_details` PL bez zmian); `FOREIGN_PARSER_VERSION=1`; `reparse()` filtruje `country='PL'`;
  zmieniona asercja `detail_calls` w `test_sync.py` (K2 pobiera też szczegóły CZ). Płatność z `data-tender-description` (CZ „Karta”, IT „Pagamento elettronico”).
  Nieblokujące: niedopasowana druga linia artykułu staje się osobną pozycją (łapie ją reguła sumy; brak testu); błąd szczegółu zagranicznego w przebiegu ręcznym zapisuje `detail_version=1` bez powrotu do kolejki (jak PL).
  Do K5: `coupon_effect` nadal tylko PL (pozycje zagraniczne poza `items`) — świadomie, bez zmian.
- Kolejność wykonania: K1 → K3 → K2 (fixtures dostarczone) → K4 → K5.
- **K3 ✅ 2026-11-14 (`bf64073`)** widoki: flaga/oryginał w Paragonach, filtr kraju, linia „za granicą” w Miesiącach, Rytm tylko PL — `sonnet-worker`.
  Wynik: pytest 469 zielone (bez `test_leaflet.py`, 13 starych czerwonych), ruff/format/mypy czyste; verifier ACCEPT; demo (seed PL + 3 CZ + 1 IT): lista z flagą i oryginałem, `?kraj=CZ` filtruje, Miesiące „w tym za granicą”, Rytm liczy tylko PL.
  Nieblokujące do K5: brak linii „za granicą” w `notify.py` (powiadomienie miesięczne); słaba asercja `i-flag-cz` w `test_web.py` (sprite zawsze na stronie); test `fmt_money` w `test_chart.py`; `stores/rhythm/_savings_breakdown` przy `ReceiptFilter(country='CZ')` dają pusty wynik; `coupon_effect` tylko PL de facto (zagranica bez `items`, do K2).
- **K4 ✅ 2026-11-14 (Lidl `3954d65`, Budżet `cca665f`, wypchnięte)** kategorie AI + eksport do Budżetu + parowanie 5% w Budżecie (dwa repo, dwa `sonnet-worker`y równolegle).
  Wynik: Lidl pytest 483 zielone (bez `test_leaflet.py`), ruff/format/mypy czyste; Budżet pytest 1457 zielone, ruff/format czyste; verifier ACCEPT w obu (zero blokujących).
  Odstępstwa: do wszystkich paragonów w eksporcie dopisane `country/currency/paid_orig/fx_rate` (PL: PL/PLN/null/1.0), więc zmieniona asercja w `test_history.py`; `country` w Budżecie zamieniane na wielkie litery; etykieta kraju/oryginału tylko na chipach wyboru, nie na połączonym paragonie.
  Nieblokujące do K5: `islice(MAX_ITEMS)` w `classify_new` bierze najpierw PL — przy dużym backlogu PL zagraniczne mogą czekać między przebiegami (rozważyć kolejność/limit osobno); brak testu „PL bez zmian” dla treści promptu; w Budżecie brak testów: dokładnie 5%, PL+zagraniczny na tę samą transakcję (`claims==2` → ręcznie), `sum(parts)=0` w `_scaled`, render chipa zagranicznego (Jinja niewyrenderowana).
- **K5 ✅ 2026-11-14 (Lidl `a2e4897` + tag v1.1.0, Budżet `ab2ee68` + tag v0.75.0, wydania opublikowane, zainstalowane przez Supervisora)** wydanie zbiorcze K1–K5.
  Wynik: Lidl pytest 483 zielone (bez `test_leaflet.py`), Budżet 1458 zielone, ruff/format/mypy czyste; pubguard 0 oflagowanych w obu; na żywo znaczek wersji i `?v=` zgodne, konsola bez błędów; dev-serwer na kopii księgi: chip „CZ · 2 225,61 CZK” renderuje się.
  `simplify` (4 agentów): jedno wywołanie `tickets(country=)`, wspólny formater liczb, `_flag`, indeks `by_amount` dla PL w `match()`. `code-review` + security + silent-failure + test-analyzer: zero blokujących po poprawkach.
  **Regresja złapana w review:** simplify usunął `Receipt.currency/paid_orig` używane przez `_txn_category.html` — przywrócone + test renderu chipa (`test_foreign_lidl_receipt_chip_shows_country_and_original`).
  Poprawki z review: logi NBP (status/wyjątek), ostrzeżenie przy braku kursu i nieznanym kraju parsera, `currency_code` tylko `[A-Z]{3}` (kod trafia do URL NBP), kaucje w `purchase_totals` tylko PL.
  Dług (do raportu, nie blokuje): kurs NBP szeregowo per dzień (zbiorczo per waluta + `executemany`); `foreign_items` jako osobna tabela vs `items` z `country` (migracja v7); trzy mapy kraj→waluta/język/locale (rejestr `COUNTRIES`); `_drop_apis` czyści klientów wszystkich krajów przy rotacji tokenu; `pending_foreign_details` ignoruje usunięty z `extra_countries` kraj; błąd szczegółu zagranicznego zapisuje `detail_version` bez powrotu do kolejki; `islice(MAX_ITEMS)` w `classify_new` najpierw PL; brak linii „za granicą” w `notify.py`; brak testów `service.py` (`_api`, `_drop_apis`), `settings._countries`, `_http_fetch`, migracji wielostopniowej; 13 starych czerwonych w `test_leaflet.py`.
  **Weryfikacja na żywo 2026-11-14 (po wpisaniu `extra_countries` = CZ, IT przez usera):** import ręczny `POST /history/resume` (w panelu brak przycisku „Sprawdź teraz” — uwaga do K6). Lidl: 3 CZ + 1 IT, wszystkie `parsed=1`, `foreign_items` 11/59/5/18, kursy NBP z dnia zakupu, `total = total_orig × fx_rate` co do grosza, feed `/share/lidl/receipts.json` 543 paragony (539 PL).
  Budżet po „Synchro”: 3 z 4 sparowane automatycznie (CZ 2026-11-11 → −444,57, 2 części = suma co do grosza; CZ 2025-11-15 i IT 2026-09-10 → jedna kategoria „Spożywcze” bez podziału, tak ma być: jedna część = kategoria, nie split). CZ 2026-11-14 czeka na transakcję w banku (sprawdzić po kolejnej synchronizacji). Chip wyboru z krajem na żywo niewidziany (nic nie wymagało ręcznego wyboru).
- **D1 ✅ 2026-11-14 (Lidl `0872dd6` + testy `987a36f`, Budżet `c28ac4a`; bez wydania)** spłata długu K1–K5; plan `docs/PLAN_COUNTRIES_D1.md`.
  Kod: `budget_feed._capped` (zagranica ≥ połowa z `MAX_ITEMS`, nie czeka za PL), `pending_foreign_details(account, countries)` (usunięty kraj nie jest odpytywany), linia „W tym za granicą” w `notify.compose_month`.
  Testy (`haiku-worker` W1 + ja w Budżecie): `_api/_drop_apis/save_tokens`, `_http_fetch`, `settings._countries`, migracja v2→v6, filtr krajów, `_capped`, powiadomienie, sync z filtrem; Budżet: dokładnie 5%, PL+zagraniczny na jedną transakcję (ręcznie), `_scaled` przy sumie 0.
  Wynik: Lidl pytest 500 zielone (26 zdeselektowanych = cały `test_leaflet.py`, 13 z nich starych czerwonych), ruff/format/mypy czyste; Budżet test_lidl_link 17 zielone, ruff czyste; verifier ACCEPT bez blokujących.
  Nieblokujące: brak testu `classify_new` end-to-end (tylko `_capped`, bez mocka LLM); test sync zależy od ścieżki z bazy. W długu zostaje: osobna tabela `foreign_items`, rejestr `COUNTRIES`, szeregowe kursy NBP, `_drop_apis` przy rotacji tokenu, błąd szczegółu zagranicznego zapisuje `detail_version`.
- **K6** zakładka „Kraje”: pary produktów PL↔CZ/IT (AI proponuje, user zatwierdza), koszyk porównawczy w PLN. Wywiad `grill-me` zamknięty 2026-11-14 (user: „Tak, zapisz i przygotuj plan”); plan: `docs/PLAN_COUNTRIES_K6.md`. **Czeka na zgodę usera na plan przed implementacją.**
  Korekta: „jak E21” to uproszczenie — E21 nie miała w add-onie propozycji AI ani UI zatwierdzania (pary układał Claude poza add-onem); K6 buduje to od zera na `llm.py`.
  Decyzje: cel = ciekawostka „ile taniej/drożej za granicą” (tylko dla usera, nic do Budżetu poza linkiem); budujemy teraz na 4 paragonach / 93 pozycjach;
  AI automatycznie po imporcie (hook `after`) → top-3 konkretnych produktów PL z katalogu `pl_catalog` (bez EAN — schemat go nie ma), propozycje czekają na zatwierdzenie; „bez odpowiednika” = odrzucenie z pamięcią, do cofnięcia;
  tabela `country_pairs` (migracja v7, kopia `.pre-countries-pairs`, rollback = DROP); przycisk „Sprawdź teraz” na zakładce Kraje (`full=False`, nie `/history/resume`); cena PL = średnia z 12 mies. przed zakupem zagranicznym;
  **Korekta po weryfikacji w trybie planu (2026-11-14):** `pack_size()` łapie gramaturę tylko w ~11% pozycji cs/it, więc zamiast „base_name + brak gramatury = poza koszykiem” para wskazuje konkretny produkt PL, a zatwierdzenie = porównywalne opakowanie (ważone zł/kg; obie gramatury → za kg/l; inaczej za sztukę);
  koszyk = Σ po zatwierdzonych parach (ilość z paragonu zagranicznego × cena jednostkowa) vs ta sama ilość po cenie PL, w PLN po kursie z dnia zakupu, z pokryciem „X z Y pozycji”; link z Budżetu wymaga też rozszerzenia obejścia głębokich linków w `base.html` Lidla o `/kraje`;
  wydanie: Lidl (minor) + Budżet z samym linkiem do zakładki (wybór usera, wbrew rekomendacji „tylko Lidl”).
  Etapy (szczegóły i rollback w `docs/PLAN_COUNTRIES_K6.md`, plan zatwierdzony przez usera 2026-11-14 w trybie planu, commit `6958a0c`): K6a → K6b → K6c → K6d → wydanie zbiorcze.
  - **K6a ✅ 2026-11-14 (`b51cbba`, lokalnie, bez pusha)** migracja v7 + `country_pairs` + `pairs.propose` po imporcie (hook `after_import` w `web/app.py`) — `sonnet-worker` (migracja = ryzyko).
    Wynik: pytest 506 zielone (`--deselect tests/test_leaflet.py`), ruff/format/mypy czyste; verifier ACCEPT (zero blokujących); pełny pytest uruchomiłem sam po zmianie `web/app.py` (exit 0).
    Odstępstwa: dwa stare testy migracji miały na sztywno wersję 6 → 7; kraj w `pair_pending` z `tickets.country`; `pair_propose/pair_decide` zwracają bool; okno `pl_catalog` = ostatnie 365 dni od dziś (plan: 12 mies. przed najstarszą oczekującą pozycją); `use="pary"` w dzienniku LLM.
    Nieblokujące: brak testu hooka `after_import` (wyjątek z `propose` nie przerywa `refresh`); ta sama nazwa w dwóch krajach idzie do promptu dwa razy; wyjątek spoza `KeyRejected/ModelRefused/TryLater` przerywa pętlę porcji (hook go łapie); `uv run` wymaga `--extra dev`.
    Na żywo: dopiero po wydaniu (propozycje wymagają klucza LLM w opcjach add-onu).

Otwarte rozpoznania (rozstrzyga K1/K2, nie wywiad): kształt pola `currency` na liście, format pozycji HTML cs/it, obecność EAN, historia sprzed 2 lat (offset ≥2).

## Wynik etapu 0
**2026-11-14: wariant A.** Jedno logowanie „PL” wystarcza; `/v3/CZ|IT/tickets` działają na tym samym tokenie
(spike odczytowy, `docs/spike_countries.py`, tokeny tylko w pamięci).
- Pobrane: PL 83 + 39 paragonów (offset 0/1), CZ 3 (+1 w offset 1), IT 1 (0 w offset 1). Zagranica to dziś garstka paragonów.
- Lista: te same klucze co PL, w tym `currency` (nie jest wartością prostą — prawdopodobnie obiekt; **sprawdzić kształt w etapie 1**,
  skrypt pomijał dicty), `totalAmount` w walucie kraju (CZ np. 175,4 / 2433,8 / 760,0 — korony; IT 43,91 — euro).
- Detal: te same klucze co PL, **bez `currency`** (waluta tylko z listy), jest `languageCode`, `htmlPrintedReceipt`, `isDeleted`.
- **Duplikat między oknami:** paragon CZ z 2025-11-15 jest zarówno w `yearOffset=0`, jak i `1` (okno kroczące ~12 mies.)
  → deduplikacja po `id` obowiązkowa przy imporcie wielu krajów/offsetów.
- Wniosek dla modelu: `country` + `currency` bierzemy z listy, pobieranie = pętla po `extra_countries` na jednym tokenie
  (nie trzeba modelu „osobne konto na kraj”).
- Otwarte do etapu 1: kształt `currency`; czy `totalAmount` w CZ to korony (nie hellery); format pozycji w HTML czeskim/włoskim
  (fixtures neutralne); czy `/v3/{country}/tickets` zwraca historię sprzed 2 lat (offset ≥2).
