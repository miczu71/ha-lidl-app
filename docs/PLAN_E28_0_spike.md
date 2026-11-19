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
