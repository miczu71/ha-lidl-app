# PLAN E28 — Biedronka w add-onie (wywiad 2026-11-04, zatwierdzony)

## Context
User chce mieć w add-onie `ha-lidl-app` (0.23.1, klon `/config/addons/ha-lidl-app`, slug `f0987e0f_lidl`) również Biedronkę.
Wywiad 2026-11-04:
- **Cel:** pełny obraz wydatków domu z obu sieci (Paragony, Ceny, Miesiące, Budżet).
- **Architektura:** ten sam add-on, wspólne widoki z filtrem sieci (Lidl / Biedronka / obie); Kupony, Oszczędności i gazetki Lidla bez zmian.
- **Konta:** oboje (Osoba 1/2), e-paragony włączone (do 3 lat historii).
- **Porównanie cen między sieciami:** tak, łącznie z produktami podobnymi (nie tylko ten sam EAN).
- **Nazwa:** nowa nazwa wyświetlana („Zakupy (Lidl + Biedronka)”); repo, slug, panel i pakiet `lidl` bez zmian.
- **Oszczędzanie Biedronki:** na końcu roadmapy, z auto-Shakeomatem.
- **Budżet:** logo sieci i link do paragonu przy transakcji, dla obu sieci.
- **Design:** sekcje tylko dla Biedronki w osobnym stylu Biedronki (D2, przed E28.1), we wspólnych widokach tylko akcent sieci.

Podsumowanie wywiadu:
1. **Kto korzysta:** oboje domownicy (panel i powiadomienia) oraz Budżet (plik `/share/lidl/receipts.json`).
2. **Automatycznie:** import paragonów Biedronki według tego samego harmonogramu co Lidl, kategorie produktów dla Budżetu,
   grupy porównawcze dla produktów z tym samym EAN, poranne odsłanianie Shakeomatu (gdy włączone w opcji).
3. **Dopiero za zgodą:** logowanie na konta (robi user: captcha i SMS), pary „podobnych” produktów zaproponowane przez AI
   (zatwierdzane w UI), włączenie auto-Shakeomatu (opcja domyślnie wyłączona, włącza ją user).
4. **Po czym poznamy sukces:** paragony Biedronki obu kont z pełną historią, które co do grosza zgadzają się z aplikacją;
   Miesiące i Budżet pokazują sumy z obu sieci; zakładka „Porównanie” pokazuje, w której sieci produkt jest tańszy
   (cena za kg/l); rano przychodzi powiadomienie z odsłoniętym Shakeomatem.

## Źródła
- **Przemko92/home-assistant-mojabiedronka** (MIT, aktywne, push 2026-11-02) — wzorzec klienta (ten sam autor co klient Lidla
  w add-onie). API `https://api.prod.biedronka.cloud/api/v7/`, `User-Agent: Android/2.56.0`, przy 426 nagłówek
  `min-supported-version-android` → automatyczny bump. Keycloak `konto.biedronka.pl/realms/loyalty`, klient `cma20`, PKCE,
  redirect `app://cma20.biedronka.pl?code=…` (kod żyje ~1 min, limit ~10 SMS / 30 min). Endpointy: `transactions/?page=`,
  `transactions/{id}/`, `transactions/{id}/e-receipt/` (`output-format: json`), `promos/coupons/`, `dashboards/dashboard/`,
  `promos/carousels/{id}/`, `offers/{id}/reveal-and-activate/`, `loyalty-actions/`, `users/me/wallets/`,
  `products/price/{sklep}/{ean}/`.
- **Homobonus/securo PR #1** — parser e-paragonu (sellLine/discountLine/storno w groszach, `sumInCurrency.fiscalTotal`)
  i fallback `transactions/{id}/` (`total_price_without_discount`, `total_discount`, `ean`).

## Zasada: część transakcyjna tożsama z Lidlem (decyzja usera 2026-11-04)
Paragony Biedronki przechodzą tę samą ścieżkę co paragony Lidla, bez osobnych tabel i widoków: `tickets`/`items`,
widok paragonu `/paragony/{id}` (ten sam układ i rozliczenie do zapłaty), te same kategorie produktów
(`food`, `drugstore`, `kids`, `nonfood`) i ta sama klasyfikacja AI w `budget_feed.py`, ten sam format `receipts.json`,
ceny, gramatura (`packsize.py`), Miesiące, Rytm, Status i godzinny import. Różnice tylko tam, gdzie wymaga ich źródło:
parser (e-paragon fiskalny zamiast HTML/NATIVE), logowanie i funkcje oszczędzania (kupony Lidla ≠ vouchery/Shakeomat).
Każdy etap sprawdza to testem: paragon Biedronki z fixture daje te same pola co paragon Lidla.

## Kluczowe decyzje techniczne
- Schemat v6: `tickets.chain TEXT NOT NULL DEFAULT 'lidl'` (migracja `ALTER TABLE`, istniejące wiersze = lidl). Kody produktów
  Biedronki to `b:<EAN>`, więc nie kolidują z kodami Lidla ani z `n:<EAN>`. Id paragonu: `b:<transaction id>`.
- Konta: `accounts/<slug>.json` dostaje pole `chain` (brak pola = lidl). Logowanie w Konta: link PKCE i pole na adres
  `app://…` (ten sam wzorzec UX co Lidl, bez Browser Companion).
- Klient: nowy moduł `lidl/client/biedronka.py` (aiohttp jak `client/api.py`), wpis w `THIRD_PARTY_NOTICES.md` (MIT).
- Sync: `sync.py` rozgałęzia się po `chain`; godzinny import i dni handlowe (`shopdays.py`) obowiązują obie sieci.
- Widoki: wspólny parametr `?siec=` w `web/app.py` → filtr w zapytaniach `History` (Paragony, Ceny, Miesiące, Rytm, Status).
  Kupony, Oszczędności i Produkty-kupony zostają tylko dla Lidla.
- Budżet (osobne repo `ha-budget-app`): `receipts.json` dostaje pole `chain`, a `lidl_link.py` dopasowuje paragon Biedronki
  do wydatku z opisem „biedronka|jeronimo”. Osobne wydanie Budżetu.

## Etapy (szczegółowe kroki, rollback i sekcje **Wykonawca** w `docs/PLAN_E28_<n>.md` przed każdym etapem)
Najpierw kopia tego planu do `docs/ROADMAP.md` (sekcja E28) i `docs/PLAN_E28_biedronka.md`.

- **E28.0 Rozpoznanie na żywo (spike, bez add-onu).** Skrypt `~/dev/biedronka-spike/spike.py` (`login` → link PKCE,
  wklejenie `app://`, tokeny do `~/.secrets/biedronka_osoba1.json`; `dump` → transakcje, e-paragony, szczegóły do
  `~/dev/biedronka-spike/data/`). Logowanie i uruchomienie robi user (`! …`). Pomiar: głębokość historii, odsetek
  e-paragonów, zgodność sumy z `fiscalTotal`, identyfikator sklepu, rotacja refresh tokenu po >1 h, nakładanie się EAN
  z `n:<EAN>` Lidla (pierwsza miara pokrycia porównania).
  **Bramka:** jeśli historia ma mniej niż ~12 mies. albo pozycje nie mają EAN, staję i pokazuję wnioski.
- **D2 Design Biedronki (przed E28.1, decyzja usera 2026-11-04; wzorzec D1).** Części tylko dla Biedronki: konto
  i logowanie (link, captcha i SMS, wklejenie `app://`, stan karty), oszczędzanie z E28.5 (vouchery, oferty „Tylko dla
  Ciebie”, Shakeomat/Shakeomarka, naklejki/punkty). Kroki: (1) user wkleja do czatu zrzuty aplikacji Moja Biedronka
  (lokalnie `~/dev/biedronka-design-refs`, poza repo, z danymi osobowymi); (2) Design System Biedronki jako Artifact
  w Claude Design (prywatny, bez zrzutów, bez logo i fontów Biedronki — wolne zamienniki); (3) makiety sekcji Biedronki
  (telefon + PC) i akcentu we wspólnych widokach: znacznik sieci przy paragonie i na liście, kolor sieci w filtrze
  `?siec=` i na wykresach (Lidl / Biedronka), nagłówek paragonu Biedronki — ocena usera; (4) wdrożenie: tokeny pod
  zakresem `.chain-biedronka` w `app.css` (styl Lidla bez zmian), sekcja „Biedronka” w `docs/DESIGN.md`; skill
  `impeccable`, weryfikacja w Playwright (zrzut + konsola). Rollback: usunięcie zakresu `.chain-biedronka`.
  Kod D2 trafia do wydania 0.24.0 razem z E28.1–E28.2.
- **E28.1 Fundament: konta i import Biedronki** (logowanie od razu w stylu D2). Schemat v6, `chain` w kontach, klient + parser (tdd na neutralnych fixtures
  „Sklep X”), logowanie w Konta, import w sync (pełna historia przy pierwszym logowaniu, potem przyrostowo), wpisy
  `sync` w Statusie z `chain`, nowa nazwa w `config.yaml`, tytułach i `translations`. Paragony Biedronki widoczne na liście
  Paragony (dla wszystkich sieci, jeszcze bez filtra). Rollback: `git revert`, kolumna `chain` jest nieszkodliwa dla starego
  kodu, a pliki kont Biedronki stary kod pomija (brak tokenów Lidla → konto „rozłączone”).
- **E28.2 Wspólne widoki z filtrem sieci.** `?siec=` w Paragonach, Cenach, Miesiącach (+ push 1. dnia z rozbiciem
  na sieci), Rytmie (mapa: współrzędne sklepów Biedronki z publicznego lokalizatora, jeśli działa; inaczej z adresu
  bez mapy) i Statusie. Kategorie produktów Biedronki dla Budżetu (prompt `budget_feed.py` bez „Lidl”) + `chain`
  w `receipts.json`. **Wydanie 0.24.0** (pierwsza grupa: import + widoki; potrzebne na żywo do pomiaru w E28.4).
- **E28.3 Budżet: paragony obu sieci z logo przy transakcji** (repo `ha-budget-app`, decyzja usera 2026-11-04).
  Dziś: `lidl_link.py` (dopasowanie po „lidl”, kwota co do grosza, ±3 dni), tabele `txn_lidl` i `txn_lidl_reject`
  (migracja 019), link „paragon Lidl” w `_txn_category.html`, wybór paragonu przy niejednoznacznym. Zmiana:
  - dopasowanie według `chain` z `receipts.json`: Lidl → „lidl”, Biedronka → „biedronka|jeronimo”, a paragon jednej sieci
    nigdy nie łączy się z wydatkiem drugiej; tabele zostają (`ticket_id` Biedronki ma prefiks `b:`), bez migracji danych;
  - przy transakcji z dołączonym paragonem: **logo sieci (SVG) + link „paragon”** do `/app/f0987e0f_lidl/paragony/<id>`,
    w karcie transakcji i na liście Transakcji, również przy wyborze paragonu przy niejednoznacznym dopasowaniu;
  - loga: moduł `store_logos.py` + `web/static/stores/{lidl,biedronka}.svg` według wzorca `bank_logos.py`
    (favicony z oficjalnych stron, źródło i licencja w `SOURCES.md` przed commitem — repo publiczne);
  - mapowanie kategorii (`lidl_category_map`) wspólne dla obu sieci, bo kategorie są te same.
  Testy dopasowania obu sieci i krzyżowego braku dopasowania. Wydanie Budżetu (wersja według jego pliku wersji),
  na żywo: transakcja z Biedronki z logo i działającym linkiem do paragonu.
- **E28.4 Porównanie cen między sieciami.** Grupy porównawcze: (a) ten sam EAN automatycznie (`b:<EAN>` ↔ `n:<EAN>`
  i znane pary z `merges`); (b) produkty podobne: AI (`llm.ask_logged`, `model: auto:text`, json_schema) proponuje pary
  według nazwy i gramatury (`packsize.py`), user zatwierdza lub odrzuca w UI (tabele `xchain_pairs`, `xchain_rejects`).
  Zakładka „Porównanie”: cena za kg/l/szt. w obu sieciach (mediana z 3 mies., ostatni zakup), oszczędność, gdyby
  kupować w tańszej sieci, filtr kategorii. **Wydanie 0.25.0.**
- **E28.5 Oszczędzanie w Biedronce.** Panel: vouchery (`promos/coupons/`), oferty „Tylko dla Ciebie”, naklejki/punkty
  z saldem i najbliższą nagrodą. Opcja `biedronka_auto_shakeomat` (domyślnie wyłączona): poranne odsłanianie
  Shakeomatu i Shakeomarki (`reveal-and-activate`) + push `notify.family` (tag `biedronka-shakeomat`) z wynikiem;
  linia „Biedronka” w porannym powiadomieniu (vouchery wygasające, nowe oferty). **Wydanie 0.26.0** po pełnym
  łańcuchu simplify → code-review (+ silent-failure-hunter, pr-test-analyzer, security) → release → weryfikacja na żywo.

## Propozycje na później (poza E28, do decyzji usera)
- **P1 Gdzie kupić taniej z listy zakupów:** produkty z `todo.*` z podpowiedzią sieci na podstawie „Porównania”.
- **P2 Cena na półce teraz:** `products/price/{sklep}/{ean}` (cena, regularna, Omnibus) dla obserwowanych produktów
  Biedronki — alert, gdy promocja.
- **P3 Gazetka Biedronki:** API jej nie daje; ewentualnie publiczna gazetka + AI jak w E4 (koszt limitów freellmapi).

## Pierwszy krok wykonania (po zatwierdzeniu)
Tylko zapis: ta roadmapa → `docs/ROADMAP.md` (sekcja E28 + D2) i `docs/PLAN_E28_biedronka.md` w `ha-lidl-app`,
commit + push (poza oknem 02:45–03:15), bez kodu. Implementację user startuje później (od E28.0).

## Ryzyka
- Nieoficjalne API, regulamin tego nie przewiduje (ryzyko dla konta). Captcha i limit SMS — logowanie wyłącznie przez usera.
- 426 / zmiany API → automatyczny bump wersji; awaria ma być widoczna w Statusie (alert `alert_notify`).
- Migracja v6 na żywej bazie (524+ paragonów): przed wydaniem 0.24.0 kopia `history.db` w katalogu danych add-onu
  (`*.pre-e28`) i backup tylko tego add-onu przez `ha_manage_updates(backup=true)`.
- Hook pre-commit: w fixtures i docs żadnych prawdziwych imion, miast ani adresów sklepów.
- Porównanie „podobnych” może mieć niskie pokrycie (marki własne) — mierzę w E28.0 i E28.4, a wynik wpisuję do ROADMAP.

## Weryfikacja
- Każdy etap: `uv run pytest`, `ruff`, `mypy` w `lidl/app` (oraz Budżetu w E28.3), verifier po workerach.
- Na żywo (playwright-ha przez Ingress): oba konta Biedronki „połączone”; liczba paragonów i suma miesiąca zgodne
  z aplikacją; Paragony/Ceny/Miesiące z filtrem `siec` dają sumę Lidl + Biedronka = „obie”; w Statusie wpisy sync
  Biedronki bez błędów; Budżet łączy paragon Biedronki z wydatkiem i pokazuje przy nim logo Biedronki z działającym
  linkiem (a Lidl dalej z logo Lidla); poranny push Shakeomatu dociera (potwierdza user).
