# E9 + E10 Rytm zakupów i sklepy — plan (add-on ha-lidl-app)

## Context
E19 (0.16.0) jest zamknięte i kolejny etap trzeba było wybrać. User wybrał połączenie E9 (heatmapa) i E10 (sklepy z mapą).
Dane już są w bazie (`tickets.purchased_at` w czasie lokalnym, `store_code/name/address/locality`, `total`, `savings`, `account`).
Zakładka Miesiące pokazuje tylko „ulubiony dzień/godzinę/sklep” dla jednego miesiąca. Ta zakładka da cały obraz.

## Ustalenia z wywiadu (2026-10-09)
1. Cel: **ciekawostka** (jak E19). Bez powiadomień.
1a. **Mapa sklepów: tak** (decyzja usera 2026-10-09). Współrzędne najpierw z API Lidl Plus (rozpoznanie tylko do odczytu),
   a gdy API ich nie daje, jednorazowe geokodowanie publicznych adresów sklepów w Nominatim (OSM). Wynik trzymamy w bazie,
   pobieramy tylko dla nowych sklepów. Później posłuży jako strefy pod E17.
2. Miejsce: nowa zakładka **„Rytm”** (`/rytm`, chip w `base.html` obok „Miesiące”).
3. Heatmapa dzień tygodnia × godzina: domyślnie **liczba wizyt**, przełącznik **„Wydatki”**. Pod nią najczęstszy
   dzień i godzina.
4. Tabela sklepów: nazwa + adres, wizyty, wydatki, średni paragon, oszczędności, ostatnia wizyta, podział na konta.
   Klik w sklep otwiera Paragony z filtrem tego sklepu (`ReceiptFilter.store` już istnieje).
5. Założenia (do korekty): filtry **konto** (oba / każde) i **zakres** (12 mies. / cała historia), na żywo przez htmx
   jak w Paragonach; godziny tylko z paragonów, które mają `purchased_at`, z widoczną informacją
   „N z M paragonów z godziną”; zakres godzin heatmapy przycięty do tych, w których były zakupy.
6. Sukces: suma wizyt i wydatków w tabeli sklepów zgadza się z listą Paragonów dla tych samych filtrów, a heatmapa
   wygląda wiarygodnie na żywych danych (zakupy w godzinach otwarcia).

## Projekt
- **Dane** (`lidl/app/src/lidl/history.py`, bez zmiany schematu):
  - `rhythm(f: ReceiptFilter) -> Rhythm`: macierz 7×24 (wizyty, wydatki), `with_time`/`total`. Zapytanie przez
    `_receipt_where(f)` i godzinę z `purchased_at[11:13]` (jak `_summary`); dzień tygodnia z `t.day`.
  - `store_stats(f) -> list[StoreStats]`: rozszerzenie obecnego `stores()` (te same `_STORE_KEY` i nazwa z najnowszego)
    o adres/miejscowość, sumę `total`, `savings`, MAX(`day`), podział na konta. Jeśli `stores()` da się zbudować
    na `store_stats`, uprościć zamiast dublować.
- **Web** (`web/rhythm.py` wzorem `web/months.py`/`web/receipts.py`; `templates/rhythm.html` + częściowy
  `_rhythm_results.html` dla htmx): heatmapa jako siatka CSS (bez biblioteki wykresów), intensywność koloru
  z tokenów `docs/DESIGN.md`, liczba i kwota w `title`/`aria-label`; kwoty i odmiany z `text.py`
  (`fmt_pln`, `plural`). Link sklepu → `/paragony?sklep=<kod>` (sprawdzić nazwę parametru w `web/receipts.py`).
- **Współrzędne** (`lidl/app/src/lidl/geo.py`): nowa tabela `store_geo(code PK, lat, lon, source, fetched_at)`, dodana
  przez `CREATE TABLE IF NOT EXISTS` bez bumpu schematu (wzorzec z `watched`). Źródło `lidl`
  (endpoint z rozpoznania) albo `osm` (Nominatim: zapytania z adresu, kodu pocztowego i miejscowości, własny User-Agent,
  max 1 zapytanie/s zgodnie z polityką OSM). Uruchamiane po imporcie paragonów (`DailyJob`) tylko dla sklepów bez
  wpisu. Nieudane geokodowanie zostaje bez punktu, a sklep zostaje w tabeli z dopiskiem „bez lokalizacji”.
- **Mapa:** Leaflet dołączony lokalnie do `static/` (jak htmx, licencja BSD-2) i `circleMarker` (wektor, bez ikon PNG),
  promień zależny od liczby wizyt. Kafelki OSM z atrybucją ładuje przeglądarka. Klik w punkt pokazuje dymek ze sklepem,
  wizytami i linkiem do Paragonów. Filtry konta i zakresu działają też na mapie.
- **Styl:** skill `impeccable` dla układu heatmapy i tabeli, makieta do akceptacji przed kodem strony;
  cache-busting `?v={{ version }}` już jest w `base.html`.

## Podetapy (wydanie 0.17.0)
- **E9.0 docs:** `docs/PLAN_E9_rytm.md` (ten plan) i wpis w `ROADMAP.md` (E9 i E10 jako jeden etap).
- **E9.1 dane:** `Rhythm`, `rhythm()`, `StoreStats`, `store_stats()` z testami w `tests/test_history.py`
  (neutralne fixtures: „Sklep X”, konto `a`/`b`). Przypadki: paragony bez godziny, filtr konta/dat, sklep bez kodu pominięty.
- **E9.2 rozpoznanie współrzędnych:** szukam w znanych endpointach i APK 17.11.6 (z E20.0) usługi sklepów
  z `latitude`/`longitude` dla kodu sklepu, potem robię próbny GET skryptem w `~/dev/lidl-spike` (tylko odczyt; jeśli wymaga
  tokenu, uruchamia go user albo ja za wyraźną zgodą). Wynik w `docs/PLAN_E9_rytm.md` i wybór źródła: `lidl` albo `osm`.
- **E9.3 współrzędne w add-onie:** `geo.py`, tabela `store_geo`, wywołanie w `DailyJob`, testy z mockiem HTTP.
- **E9.4 strona:** makieta, potem akceptacja, potem `/rytm` (heatmapa, mapa, tabela) + testy web; weryfikacja w Playwright na
  danych demo (`~/lidl_dev/receipts_demo` z `seed_receipts_demo.py`, serwer `LIDL_DEV=1`), screenshot + konsola.
- **E9.5 wydanie 0.17.0:** `simplify`, potem skill `release` (bump `config.yaml` + `pyproject.toml`). Na żywo:
  porównanie sum sklepów z Paragonami, sprawdzenie pokrycia godzin i tego, czy punkty na mapie leżą przy właściwych adresach.

## Ryzyka
- Pokrycie `purchased_at` dla starych paragonów NATIVE jest nieznane (pełna baza jest tylko na hoście), sprawdzić
  na żywo w E9.3. Przy niskim pokryciu heatmapa domyślnie pokazuje 12 mies. i informację o pokryciu.
- Wiele `store_code` dla tego samego sklepu (zmiana kodu albo stare paragony z samą nazwą `store`) da zdublowane
  wiersze. Zgłosić, nie łączyć w tym etapie.
- Nominatim może nie trafić skróconych adresów z paragonu. Wtedy sklep zostaje bez punktu, a ręczna korekta jest poza zakresem
  (wróci przy E17).
- Kafelki OSM w WebView HA Companion: sprawdzić na telefonie. Gdyby nie działały, mapa nie blokuje reszty strony.

## Weryfikacja
`pytest` w venv add-onu (wszystkie testy zielone), mypy/ruff jak w CI. Playwright: `/rytm` na danych demo
(przełącznik, filtry, link sklepu otwiera Paragony z filtrem), na żywo po wydaniu przez `playwright-ha`.

Cofnięcie: osobne commity na podetap. Wydanie cofa poprzednia wersja add-onu (schemat bez zmian).
