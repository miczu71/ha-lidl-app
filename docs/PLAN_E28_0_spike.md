# E28.0: spike Biedronki na żywo (tylko odczyt, bez zmian w add-onie)

## Context
E28 to ostatni otwarty etap roadmapy Lidla: Biedronka w tym samym add-onie. Plan zatwierdzony 2026-11-04 jest w
`/config/addons/ha-lidl-app/docs/PLAN_E28_biedronka.md`. E28.0 ma rozstrzygnąć, czy API Moja Biedronka daje dość danych,
zanim ruszymy D2 i E28.1. Bramki planu:
- historia ≥ ~12 mies.,
- pozycje mają EAN,
- sesja Keycloak żyje co najmniej kilka tygodni (jeśli wygasa co kilka dni, pytam, czy ręczne logowanie jest do przyjęcia).

Od listopada zmieniło się jedno: wersje schematu v6 (kraje) i v7 (pary) są już zajęte, więc E28.1 użyje v8, a wydania
dostaną numery po 1.2.1 zamiast 0.24–0.26. Poprawiam to w ROADMAP przy zapisie wyniku.

## Kroki
1. **Docs (repo `ha-lidl-app`):** kopia tego planu do `docs/PLAN_E28_0_spike.md` i znacznik „E28.0 w toku” w `docs/ROADMAP.md`.
   Commit + push.
2. **Katalog `~/dev/biedronka-spike/`** (poza repo, bez gita, wzorzec `~/dev/lidl-spike`):
   - `vendor/biedronka/`: `auth.py`, `api.py`, `const.py`, `exceptions.py`, `html_form.py` + `LICENSE` (MIT) z
     Przemko92/home-assistant-mojabiedronka @ `b3c2b7302449`. Zależą tylko od aiohttp, nie od HA.
   - `spike.py`, w którym żadna komenda nie czyta stdin, więc wszystkie działają z `!`:
     - `login <slug>`: wypisuje link PKCE (`auth.authorization_url`), verifier do `~/.cache/biedronka_spike_<slug>` (0600).
     - `code <slug> '<app://cma20.biedronka.pl?code=…>'`: `KeycloakLogin.exchange_code` zapisuje tokeny do
       `~/.secrets/biedronka_<slug>.json` (0600, zapis atomowy). Na ekran trafia tylko `exp`/`refresh_expires_in` z JWT
       (`auth.jwt_payload`) i czas zalogowania.
     - `dump <slug>`: wszystkie strony `transactions/?page=`, dla każdej `transaction_details` + `e_receipt(json)` do
       `data/<slug>/` (0600). Zapisuje obrócony refresh token. Wypisuje tylko liczby.
     - `refresh <slug>`: test rotacji (`auth.refresh_tokens`). Wypisuje, czy się udało, i nowe `exp`; dopisuje wiersz do
       `data/<slug>/rotation.log`.
     - `report`: analiza offline danych z `data/`. Liczy:
       - głębokość historii (najstarsza i najnowsza data, liczba transakcji na miesiąc),
       - odsetek e-paragonów,
       - zgodność sumy sellLine/discountLine/storno z `fiscalTotal` i z `total_price…` w szczegółach,
       - pola sklepu,
       - obecność EAN w pozycjach,
       - nazwy kluczy (bez wartości),
       - nakładanie się EAN z kodami `n:<EAN>` Lidla, jako pierwszą miarę pokrycia porównania.
   - Kody Lidla: jednorazowo przez SSH na hosta HA (tylko odczyt, `docker exec` add-onu, python `SELECT DISTINCT code
     … LIKE 'n:%'`) do `data/lidl_codes.txt`.
   - Test na sucho: składnia i `report` na pustym `data/`. Logowania bez usera nie testuję.
3. **User (Ty):** `! cd ~/dev/biedronka-spike && uv run --with aiohttp python spike.py login osoba1`. Otwierasz link,
   przechodzisz captcha i SMS, kopiujesz adres `app://…` z przekierowania (DevTools → Network albo pasek błędu), potem
   uruchamiasz `… spike.py code osoba1 '<adres>'` w ciągu ~1 min, a na koniec `… dump osoba1`. Drugie konto (osoba2)
   opcjonalnie tak samo.
4. **Ja:** `report`, a potem pierwsze `refresh` po >1 h. Kolejne `refresh` po 1 i kilku dniach (przypomnę). W tym
   czasie mogę równolegle ruszyć D2 (zrzuty z aplikacji), bo nie zależy od rotacji.
5. **Wynik:** sekcja „Wynik E28.0” w `PLAN_E28_biedronka.md` i w ROADMAP (bez danych osobowych, same liczby), korekta
   numerów schematu i wersji, commit + push. Potem `stage-end`, a następny etap to D2.

## Bezpieczeństwo
- Nie czytam `~/.secrets/biedronka_*.json`. Skrypt nie wypisuje tokenów, nagłówków, URL-i z kodem ani tracebacków
  z treścią żądania; wyjątki skraca do typu i statusu HTTP.
- `data/` zawiera dane osobowe (adresy sklepów, zakupy). Zostaje lokalnie, nie trafia do repo ani do pamięci. Fixtures do
  E28.1 powstaną później jako neutralne („Sklep X”).
- Ryzyko konta (nieoficjalne API): tylko odczyt. Dzwonię wyłącznie do `transactions`, `details` i `e-receipt`, bez
  `reveal-and-activate`, z przerwą ~0,3 s między żądaniami.

## Bramka (stop i pytanie)
Historia < ~12 mies., pozycje bez EAN albo refresh token wygasa w < kilka dni.

## Rollback
`rm -r ~/dev/biedronka-spike` (robi user albo ja po zgodzie) i usunięcie `~/.secrets/biedronka_*.json`. Wylogowanie
w aplikacji Biedronki unieważnia sesję. W repo cofam tylko commity docs.

## Weryfikacja
`report` wypisuje wszystkie miary bez błędów. Liczba transakcji i suma ostatniego miesiąca zgadzają się z aplikacją Moja
Biedronka (sprawdzasz na telefonie). W `rotation.log` widać udane odświeżenie po >1 h.

---

## Stan E28.0 (2026-11-19, wstrzymany)

**Zrobione i działa** (`~/dev/biedronka-spike`, `spike.py login|code|dump|refresh|report`):
- Logowanie PKCE: kod wymieniany od razu po skopiowaniu (kod żyje ~1 min; po minucie `invalid_grant`). Tokeny w `~/.secrets/biedronka_osoba1.json`.
- Sesja: access ~24 h, **refresh 120 dni** (okno `exp - iat`) → bramka sesji spełniona.
- Kody EAN Lidla (3 417, `n:<EAN>`) wyeksportowane do `data/lidl_codes.txt` (SELECT z `/data/history.db` add-onu, tylko odczyt).

**Blokada bramki historii:**
- `consents.ereceipt_consents` było `False` (włączone przez usera 2026-11-19, serwer już widzi `True`), a `transactions/?page=1` nadal zwraca 0 (`page_count: 0`). Stare zakupy nie pojawiły się wstecznie.
- User widzi starsze zakupy w aplikacji po „zobacz starsze zakupy” i w panelu web (`moja.biedronka.pl/panel/ajax/paragons`, POST, sesja PHP w ciasteczku — **inny system niż API aplikacji, nie nadaje się do add-onu**).
- Nie znamy endpointu/parametrów, których aplikacja używa dla starszych zakupów. Próby bez skutku: 9 wariantów parametrów dat na `transactions/` (serwer je ignoruje), 13 zgadywanych ścieżek (`purchases/`, `receipts/`, `users/me/transactions/` …), `dashboards/dashboard/` bez wskazówek.

## E28.0a Analiza aplikacji Biedronki (zrobić w osobnej rozmowie)
Cel: znaleźć w kodzie aplikacji endpoint i parametry „zobacz starsze zakupy” (i czy to ta sama baza co `transactions/`), potem sprawdzić je tokenem z `spike.py`.

1. **Pobrać APK Moja Biedronka** (wersja z telefonu usera): APKMirror/APKPure albo na PC z `adb`: `adb shell pm path <pakiet>` + `adb pull`. Zapisać w `~/dev/biedronka-apk/`. Plik z sieci jest niezaufany: tylko analiza statyczna, nic nie uruchamiać, hash SHA-256 do notatki.
2. **Zainstalować zależności w `~/.local`** (nie w obrazie; kontener ma Debian 12, bez Javy i bez `adb`):
   - JDK 17+ (pełny, z `jdk.compiler`), np. Temurin w `~/.local/jdk`, `JAVA_HOME` ustawić w `~/.bashrc`.
   - Wariant **A (REA)**: `jadx-headless-mcp` 0.7.1 (JAR, REA go nie pobiera; źródło do ustalenia), `REA_JADX_MCP_JAR=<abs>`; sprawdzić `npx -y rea-agents@6.8.0 doctor --provider jadx --json` (doctor zgłasza też Node 22.23.2 < wymaganego 22.23.4 — sprawdzić, czy blokuje).
   - Wariant **B (zapasowy)**: zwykły `jadx` (wydania skylot/jadx na GitHubie, `~/.local/jadx`), dekompilacja do katalogu i grep po `transactions`, `older`, daty. Do wyboru, gdy JAR dla REA jest nieosiągalny.
   - `adb` nie jest potrzebny, jeśli APK dostarcza user.
3. **Analiza:** `inspect_android_package` → `search_android_classes` (`Transaction`, `Receipt`, `Purchase`, `History`) → `inspect_android_method` / `trace_android_references`. Jeśli aplikacja okaże się Flutter/React Native, logika jest w pakiecie Dart/JS — wtedy `analyze_javascript_application` albo `inspect_dart_aot`.
4. **Weryfikacja:** nowy endpoint wywołać tokenem osoba1 (tylko GET), wynik: liczba transakcji i najstarsza data, bez wartości. Bramka: ≥ ~12 mies. historii i EAN w pozycjach.
5. **Plan awaryjny**, jeśli historii wstecz nie da się pobrać: zbieranie paragonów od dnia włączenia e-paragonów; E28 zachowuje wartość (od teraz), ale bez historii wstecz — zmiana zakresu do uzgodnienia z userem.

**Higiena:** user wkleił w czacie nagłówki żądania z ciasteczkiem `PHPSESSID` panelu web — wylogowanie z `moja.biedronka.pl` zalecone (potwierdzić). Nie wklejać nagłówków ani ciasteczek, tylko sam Request URL.

## Wynik E28.0a (2026-11-19) — bramka historii SPEŁNIONA
- APK Moja Biedronka 2.25.0 (pakiet `pl.jmpolska.clos0.mojabiedronka`, natywna Kotlin/Java, 2 pliki dex, bez Fluttera/RN);
  SHA-256 XAPK `3498f552…327757d`. Analiza statyczna samych stringów dex wystarczyła, jadx niepotrzebny.
- W aplikacji jest `GetTransactionsUseCase` ze stanami `OldTransactions*`/`noOlderTransactions` i endpoint Retrofit
  **`GET api/v7/transactions/archived/?page=N`** (obok `transactions/` = świeże zakupy). `transactions/` zwraca 0, dopóki
  e-paragony nie nazbierają świeżych zakupów, a starsze są wyłącznie w `archived/`.
- Odpowiedź `archived/`: `{transactions[], page_number, page_count, previous_page, next_page}`; element listy:
  `date, id, is_e_receipt_available, receipt_num, store_name, total_price`.
- Konto osoba1: 22 transakcje z archiwum, zakres 2024-12 … 2026-10 (~22 mies., rzadkie: ~1–3/mies.), 1 strona.
- `transactions/{id}/` (szczegóły) działa dla wszystkich 22 i ma pozycje z `ean`: 125/125 pozycji z EAN (81 unikalnych),
  suma pozycji = `total_price` w 22/22 paragonach, kaucje i VAT w polach. `e-receipt/` dla archiwalnych → błąd
  (`is_e_receipt_available` brak) — parser E28.1 musi opierać się na szczegółach `transactions/{id}/`, e-paragon tylko
  dla świeżych zakupów.
- Pokrycie porównania z Lidlem: 18 wspólnych EAN z 81 (22%); pierwsza miara dla E28.4.
- Sesja: access ~24 h, refresh 120 dni (bramka sesji OK).
- Korekta numeracji: schemat E28.1 = v8, wydania numerowane po 1.2.1 (zamiast 0.24–0.26).
- Otwarte: drugie konto (osoba2) jeszcze niezalogowane; archiwum ma tylko 22 zakupy, więc „pełna historia” = to, co zwraca
  `archived/` (do porównania z aplikacją przez usera).
