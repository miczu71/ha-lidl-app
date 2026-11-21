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

### E29.3 Poranny przebieg + push (paczka W2 po W1, `haiku-worker`, verifier)
- `daily.py`: krok odczytu cen przed `_watched` (brak sklepu/konta Biedronki = pomijam z info w logu; błąd = warn, nie
  zatrzymuje porannego przebiegu — jak Shakeomat).
- `_watched`: promocja = `price < omnibus` (bez Omnibusa `price < regular`); klucz `bs:<ean>:<promo_to|price>` w
  `watched_sent`; `notify.compose_watched` dostaje linie Biedronki (nazwa, cena, „było X”, do kiedy), ten sam tag.
- Testy: `compose_watched` z liniami Biedronki, brak duplikatu po drugim przebiegu, tryb próbny bez zapisu.

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
