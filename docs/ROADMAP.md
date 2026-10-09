# Roadmapa — Lidl Plus

**Cel: oszczędność.** Nie przegapić kuponów i promocji na produkty, które i tak kupujemy. Sukces = zł
zaoszczędzone miesięcznie (kupony + promocje na produktach z historii), widoczne w add-onie.

## Ustalenia

1. Kilka kont Lidl Plus (po jednym na osobę); każde ma własne kupony, lista zakupów jest wspólna.
2. Automatycznie: pobieranie paragonów, kuponów i gazetek, **aktywacja kuponów pasujących do historii**,
   powiadomienie o nowych dopasowaniach. Ręcznie: aktywacja pozostałych kuponów.
3. Lista zakupów trafia na wspólną listę `todo.*` w HA (z adnotacją o promocji/kuponie).
4. Dopasowanie nazw: kod artykułu → reguły/fuzzy → AI dla niepewnych → potwierdzenia użytkownika zapamiętywane.
5. Logowanie ręczne w przeglądarce PC; hasła nigdy nie trafiają do add-onu.

## Wyniki rozpoznania (E0)

- Logowanie OAuth PKCE (`LidlPlusNativeClient`) działa bez dodatkowego add-onu z przeglądarką.
- **Paragony:** API zwraca historię od kilku lat w paczkach rocznych (`yearOffset` 0–5, dalej HTTP 400);
  pozycje są tylko w HTML paragonu (nazwa, kod artykułu, ilość, cena). Parser z upstream wymaga deduplikacji
  pozycji i pomijania linii daty/rabatów.
- **Kupony:** kilkadziesiąt aktywnych, większość z `articleIds` — **te same kody co na paragonach**, więc
  dopasowanie kuponów do historii działa po kodzie, bez AI. Część kuponów jest ogólna (rabat od kwoty zakupów).
- **Gazetki:** publiczne API `endpoints.leaflets.schwarz/v4/overview?client_locale=lidl/pl-PL` (bez logowania).
  Brak ustrukturyzowanych produktów; PDF ma warstwę tekstową (nazwy, ceny, „Aktywuj kupon”). Plan: tekst ze
  współrzędnymi (`pdftotext -bbox-layout`) → grupowanie w kafelki → model językowy.
- Aplikacja Lidl Plus na telefonie po zalogowaniu z add-onu pozostaje zalogowana.

## Decyzje techniczne

- **Stirling-PDF nie wnosi nic ponad `pdftotext`** (sprawdzone na gazetce: ten sam rozsypany układ kafelków,
  OCR niepotrzebny, a instancja ma tylko język angielski). Do gazetek: `pdftotext -bbox-layout` → kafelki → model.
- Kupony dopasowujemy po kodzie artykułu (bez AI); AI służy głównie gazetkom i skróconym nazwom z paragonów.
- `yearOffset=5` wystarcza: pierwsze konto ma paragony od 2019-05-10, 327 unikalnych (lista z paczek rocznych ma
  7 duplikatów na styku lat, dedup po id). Wyczerpanie historii poznajemy po HTTP 400 przy offsecie > 0.

## Stan i otwarte sprawy (2026-10-07)

- [x] E0 rozpoznanie, E1 add-on 0.1.0 (release `v0.1.0`), CI (testy, ruff, mypy, budowa arm64/amd64), D1 nowy styl (0.2.0).
- [x] E2 zakończone (2026-10-07, wydania 0.3.0 i 0.3.1, import na żywo zweryfikowany): 327 paragonów, 327 szczegółów, 0 pominiętych, 0 nierozpoznanych; wydatki w czasie od 2019 (suma 58 942 zł po rabatach, bez kaucji — zgodna z sumą paragonów ~58 958 zł z kaucjami); oszczędności z rabatów na pozycjach: 6 183,79 zł (kupony Lidl Plus 4 056,06 zł, promocje 2 127,73 zł).
- [x] Konto pierwszej osoby połączone w panelu (add-on 0.2.0 na żywo).
- [x] Konto drugiej osoby połączone i zaimportowane (2026-10-07: 197 paragonów, 0 nierozpoznanych).
- [x] **0.3.1 (wydane):** luka — przycisk „Pobierz historię” jest tylko w stanie pustym, a dzienny import i „Wznów teraz” pomijają konta bez paragonów, więc drugiego konta nie da się zaimportować z panelu. Poprawka: w stanie „ok” wiersz każdego połączonego konta bez historii z przyciskiem + test.
- [x] „Show in sidebar” włączone (potwierdzone 2026-10-07).
- [x] Test rotacji tokenu (2026-10-08): oba konta działają ponad dobę po logowaniu i po kilkunastu restartach
  (każdy wczytuje refresh token z pliku); przebieg 07:00 i „Sprawdź połączenie” 16:57 bez błędu — nowy refresh token jest zapisywany.
- [ ] Do sprawdzenia 2026-10-09: poranne 07:00 (jednorazowo wszystkie trwające promocje, w tym trafienia gazetki 8–10.10)
  i przypomnienie o zdrapkach 18:00 (czeka na pierwszą zdrapkę).
- [ ] Opcjonalnie `impeccable init` (`PRODUCT.md`) — UI na razie wzorowany na Budżecie.

## Etapy

Każdy etap niesie wartość sam z siebie; po każdym checkpoint.

- **E1 Szkielet add-onu i logowanie kont** — ✅ 0.1.0 (wydane, zainstalowane, UI sprawdzone w HA; CI zielony).
- **D1 Nowy styl wizualny w Claude Design — tor niezależny od E2–E6, kolejność do ustalenia** (UI rośnie od E3,
  więc najlepiej przed kuponami). Dziś panel ma styl Budżetu; nowy styl ma **naśladować wygląd strony i aplikacji
  Lidl**. Powstaje w Claude Design (Artifact typu *Design*: kanwa z makietami; systemu designu na koncie jeszcze
  nie ma, więc zakładamy własny), a do repo trafia tylko wynik. Kroki (każdy z checkpointem):
  1. *Referencje:* zrzuty publicznej strony lidl.pl (Playwright, desktop i mobile) oraz ekranów aplikacji
     (dostarcza użytkownik z telefonu). Zostają lokalnie, **poza repo** (prawa autorskie). Wgranie ich do
     artefaktu Claude Design to wysłanie do zewnętrznej usługi (artefakt jest domyślnie prywatny, bez
     udostępniania) — zgoda użytkownika przed wgraniem.
  2. *System designu* (Artifact typu *Design System*, „Lidl Plus styl”; **v1 gotowy 2026-10-07**, prywatny:
     https://claude.ai/artifact/7Dc5dqGHZaj5dCmRHyxu1u; 7 komponentów, okładka; bez zrzutów, tylko tokeny i opis): paleta, typografia, kształty,
     komponenty (przyciski, chipy, kafelki kuponów, listy), ruch; kontrast ≥ 4,5:1 (żółć na bieli zwykle nie
     przechodzi — osobne warianty tekstowe); wolne od licencji fonty i ikony SVG o podobnym charakterze.
  3. *Makiety* (Artifact typu *Design*; **v1 2026-10-07: konta i logowanie, telefon i komputer**, prywatny:
     https://claude.ai/artifact/QZrsn5Vf3MXYcoDxQnGCvS; kolejne ekrany dochodzą z etapami E2–E5): ekrany konta, logowania, a później kupony, ranking produktów, gazetki,
     lista zakupów — desktop i telefon; iteracje z użytkownikiem w przeglądarce.
  4. *Akceptacja:* zestawienie obok siebie (referencja ↔ makieta), decyzja użytkownika.
  5. *Wdrożenie w add-onie* (✅ 0.2.0, 2026-10-07; `docs/DESIGN.md`, Figtree lokalnie): tokeny i zasady z zaakceptowanego systemu do repo (`docs/DESIGN.md` + `app.css`),
     podmiana szablonów, weryfikacja w przeglądarce (desktop i telefon), cache-busting, wydanie skillem
     `release`. Do implementacji skill `impeccable` (`init` → `PRODUCT.md`, potem `document`).
  Ograniczenia: naśladujemy **styl** (paleta, kształt, charakter), bez logo, znaków towarowych i zastrzeżonych
  fontów Lidl; zastrzeżenie „nieoficjalny, niepowiązany z Lidl” zostaje widoczne w UI i README.
  Decyzje (2026-10-07): wzorzec = **aplikacja** (strona i aplikacja są do siebie podobne; przy różnicach wygrywa
  aplikacja); motyw **jasny**; D1 robimy **przed E2**; zrzuty z aplikacji dostarcza użytkownik wklejając je do
  czatu; zgoda na wgranie referencji do prywatnego artefaktu Claude Design (po osobnym „go” przy kroku 2).
- **E2 Historia paragonów:** import całej historii wszystkich kont (powoli, z przerwami), deduplikacja pozycji,
  normalizacja produktów, ranking „najczęściej kupowane” (częstość, cena, ostatni zakup). Na początek **punkt
  odniesienia oszczędności**: lista paragonów ma pola `savings` i `couponsUsedCount` — suma „ile oszczędzaliśmy
  zanim add-on cokolwiek zmienił”, do porównania w KPI. Plan i decyzje (2026-10-07): `docs/PLAN_E2_historia.md`
  — ranking i KPI dla całego domu, pierwszy import ręcznie potem codziennie, grupowanie po kodzie artykułu.
  Podetapy: E2.1 dane (parser, SQLite, sync), E2.2 UI „Produkty”, E2.3 wydanie 0.3.0 i import na żywo.
- **Wnioski z E2 (ważne dla E3–E8):** (1) Paragony mają dwa formaty: HTML (od 2026-03-27) i NATIVE (`itemsLine`, 2019–03.2026);
  kody produktów się nie pokrywają (NATIVE: EAN/PLU, HTML: numer artykułu = kody kuponów), więc produkty łączymy
  po jednoznacznej nazwie (28 połączonych na próbce), reszta zostaje pod kluczem `n:<EAN>`. (2) Pole `savings` z listy
  paragonów jest wypełnione tylko dla 6 najnowszych paragonów i zaniża oszczędności ~30×; liczymy z rabatów pozycji
  (opis „Lidl Plus kupon/voucher” = kupon, reszta = promocja). (3) Wersja 0.3.0 cicho pomijała starsze paragony —
  dlatego 0.3.1 liczy i pokazuje paragony nierozpoznane. (4) Dla E7: ceny jednostkowe z obu formatów są w bazie
  (`items.unit_price`, ważone w kg); dla produktów tylko ze starego formatu jest tylko klucz `n:<EAN>`.
- **Kaucje i dane z paragonów (0.3.2–0.3.3, 2026-10-07):** kaucje czytamy z podsumowania paragonu HTML — „wydania” to kaucje
  pobrane, „przyjęcia” to zwroty (zwrot kaucji plus „Opak bez kau”); pozycje po rabatach + pobrane − zwrócone = kwota paragonu
  (zweryfikowane na 14 prawdziwych paragonach i na żywo: dom 100 952,74 zł zapłacone, kaucje pobrane 76,00 zł, zwrócone 42,70 zł).
  W NATIVE kaucje są tylko pobierane. Przy okazji ponownego pobrania zapisujemy: godzinę zakupu (czas lokalny, nie przeliczać
  strefy — końcówka `+00:00` z listy jest mylna), sklep (kod, nazwa, adres, kod pocztowy, miejscowość), sposób płatności, użyte
  kupony (`ticket_coupons`), opis rabatu i flagę ważenia przy pozycji oraz oczyszczoną, skompresowaną kopię szczegółu paragonu
  (`ticket_raw`, ~1,3 MB na ~520 paragonów, bez karty/kasjera/danych fiskalnych). Zmiany parsera przetwarzamy teraz lokalnie z kopii
  (`PARSER_VERSION`), bez pytania Lidla. Dane czekają na ekrany: heatmapa dzień × godzina i ranking sklepów (dane już są;
  mapa wymaga współrzędnych sklepów — geokodowanie w zewnętrznej usłudze albo ręcznie, decyzja otwarta), analiza kuponów (E3),
  ceny w czasie (E7), przeglądarka paragonów (E8).
- **Kolejność (2026-10-07): E11 → E3.**
- **E11 Lista „produkty kuponowe” — reguły dla E3** (zatwierdzone 2026-10-07; plan: `docs/PLAN_E11_kupony.md`):
  produkty kupione ≥3 razy w ostatnich 12 miesiącach, lista wspólna dla domu, przełącznik „auto-aktywuj”
  domyślnie włączony (zapisujemy tylko odznaczenia); produkty z samym kluczem `n:<EAN>` bez kodu kuponu.
  E3 czyta zbiór kodów z `auto_activate_codes()`. Podetapy: E11.0 docs ✅, E11.1 dane ✅, E11.2 ekran „Kupony”
  (`/kupony`) ✅, E11.3 wydanie 0.4.0 ✅ (2026-10-07, na żywo: 206 kandydatów, 187 z auto-aktywacją, 19 bez kodu
  kuponu; odznaczenie przetrwa przeładowanie). Próg 3 zostaje (decyzja 2026-10-07), bez filtra.
- **E13 Wyszukiwanie i zmiany na żywo, spójny okres rankingu** (zgłoszone 2026-10-07; plan:
  `docs/PLAN_E13_na_zywo.md`): ranking liczony z zakresu dat wykresu (naprawa pustego „Wykres” dla produktów
  niekupowanych od roku), wyszukiwanie na żywo (htmx jak w Budżecie) na Produktach i Kuponach, kontrolki,
  przełączniki i aktywacja bez przeładowania. Wydanie razem z E3 (0.5.0). Podetapy: E13.0 docs ✅, E13.1 ranking ✅,
  E13.2 Produkty ✅, E13.3 Kupony ✅ (2026-10-07; wydanie w 0.5.0).
- **E14 Którą kartę wziąć** (zgłoszone 2026-10-07 po pierwszej aktywacji; plan: `docs/PLAN_E14_karta.md`): kupony
  różnią się między kontami, a na zakupach skanuje się jedną kartę — poranne powiadomienie poleca kartę (aktywne
  kupony na nasze produkty × częstotliwość zakupów), czytelniejszy format, z grupy kuponów SSC najniższy rabat,
  poprawka wyszukiwania (top 200). Wydanie 0.6.0. Podetapy: E14.0 docs ✅, E14.1 wyszukiwanie ✅, E14.2 logika ✅,
  E14.3 powiadomienie ✅, E14.4 wydanie ✅ (0.6.0, 2026-10-07; powiadomienie z rekomendacją karty dotarło na oba telefony, dotknięcie otwiera panel — potwierdzone). **E14.5** (prośba 2026-10-07): listy kuponów kont jako
  zakładki w jednym rzędzie, na starcie zwinięte; znacznik „wspólny” / „tylko <osoba>” przy kuponie ✅ (0.6.1 na żywo).
- **E15 Obserwowane produkty** (zlecone 2026-10-07): z listy kupowanych produktów wybieram produkt (wyszukiwanie
  na żywo jak na Produktach) i włączam śledzenie; gdy produkt pojawi się w kuponach albo promocjach, przychodzi
  powiadomienie. Kupony: dopasowanie po kodzie artykułu (`articleIds`), dla produktów z samym `n:<EAN>` po nazwie.
  Promocje: wymagają danych z gazetek (E4), tam tylko po nazwie. **Wywiad 2026-10-08** (plan:
  `docs/PLAN_E15_obserwowane.md`): E3/E4 już powiadamiają o całej liście E11, więc E15 = **wyróżnienie** kilku
  ważnych produktów — gwiazdka na liście „Kupowane regularnie” (tylko kod artykułu, gwiazdka włącza auto-aktywację),
  lista wspólna, osobny push `notify.family` (tag `lidl-obserwowane`) tylko o nowych kuponach i promocjach od dziś,
  poranne bez zmian. Podetapy: E15.0 docs ✅, E15.1 dane i powiadomienie ✅, E15.2 panel ✅ (gwiazdka, obserwowane na górze listy), E15.3 wydanie ✅ (0.11.0 na żywo 2026-10-08; test: gwiazdka na 2 produktach + 2× „Sprawdź teraz” → jeden push `lidl-obserwowane`, bez powtórki — potwierdzone na telefonach). **E15 ZAKOŃCZONE.** E15.4 (2026-10-08): gwiazdka także dla produktów spoza listy przez Szukaj w Kuponach („Inne kupowane produkty”), wydanie 0.12.0 ✅ (na żywo 2026-10-08 16:52; gwiazdka na „Filet z indyka XXL” działa).
- **Propozycje z przeglądu rynku** (zlecone 2026-10-07; każdy wymaga wywiadu przed startem, kolejność z użytkownikiem):
  - **E16 Skuteczność auto-aktywacji i licznik efektu** (wywiad 2026-10-08, plan: `docs/PLAN_E16_skutecznosc.md`;
    E16.1 archiwum kuponów zamiast kasowania ✅ 0.9.2 → E16.2 sekcja „Efekt kuponów” w Kuponach ✅ 0.10.0, 2026-10-08;
    0.12.1: porównanie z okresem sprzed add-onu ukryte do 6.11 (wcześniej okno 30 dni zawiera dni sprzed add-onu, „−40%” było artefaktem);
    wyniki kuponów aktywowanych przed 0.9.2 i kupony ogólne mają status „Brak danych” — dopasowanie ogólnych po
    `ticket_coupons` do rozpoznania na prawdziwych paragonach): ile aktywowanych kuponów faktycznie wykorzystaliśmy
    (`coupons` ↔ `ticket_coupons`), a ile przepadło; miesięczne oszczędności przed add-onem i po nim (punkt
    odniesienia z E2). Realizuje miarę sukcesu z nagłówka roadmapy. Dane już są.
  - **E17 Przypomnienie przy sklepie:** gdy telefon wejdzie w strefę HA wokół sklepu Lidl — którą kartę wziąć
    i ile kuponów aktywnych (dziś stałe 07:00 z E14). Wymaga stref sklepów, czyli współrzędnych (decyzja z E10:
    geokodowanie albo ręcznie); do ustalenia: strefy w HA czy w add-onie, kto/które telefony, jak nie dublować.
  - **E18 Shrinkflation:** mniejsza gramatura przy tej samej cenie — gramatura z nazwy produktu, porównanie ceny
    za kg/l w czasie. Rozszerzenie E7; do ustalenia: odczyt gramatury (reguły czy AI), produkty ze zmienionym kodem.
  - **E19 Miesięczne podsumowanie** (w stylu rocznego „Lidl Wrapped”): powiadomienie raz w miesiącu — wydatki,
    oszczędności, top produkty, zmiana vs poprzedni miesiąc. **Wywiad 2026-10-09** (plan: `docs/PLAN_E19_podsumowanie.md`):
    ciekawostka, nie narzędzie decyzji; push 1. dnia o 10:00 do obojga (tag `lidl-podsumowanie`) + nowa zakładka
    „Miesiące” z archiwum; treść: liczby miesiąca, produkty, rekordy i rytm, historia. Podetapy: E19.0 docs ✅,
    E19.1 dane ✅, E19.2 strona ✅ (bez osobnej makiety — user: bez checkpointów; zweryfikowana w przeglądarce
    na danych demo), E19.3 push ✅, E19.4 wydanie 0.16.0. Ustalenie: HA ignoruje podstronę w `/app/<slug>/…`
    (sprawdzone na żywo), więc dotknięcie powiadomienia otwiera Konta — tam przez 7 dni link do podsumowania;
    bieżący miesiąc bez porównań i miejsca do jego końca. Do sprawdzenia: push 2026-11-01 10:00.
  - **E20 Zdrapki, progi nagród, Pieczątka Plus:** postęp do progu („brakuje 23 zł do nagrody”), przypomnienie
    o niezdrapanych zdrapkach i ich ważności. **Najpierw rozpoznanie:** czy API (biblioteka upstream lub ruch
    aplikacji) udostępnia te dane; bez tego etap odpada. Wstępne rozpoznanie (2026-10-07): klienci open source tego
    nie mają, ale istnieją hosty `purchaselottery`, `couponplus`, `stampcard` `.lidlplus.com`. E20.0 ✅ (2026-10-08,
    analiza statyczna APK 17.11.6): **wykonalne** — GET-y tylko do odczytu na zdrapki (`v2/{country}/lotteries`:
    typ, status, `expirationDate`), progi Coupon Plus (`reachedAmount`, `goals[].value`) i pieczątki (`unitsAchieved`,
    `unitsPerPrize`). E20.1 ✅ (próbny GET): zdrapki i Coupon Plus działają, pieczątek brak (404). Projekt zatwierdzony
    2026-10-08: zdrapki w porannym + przypomnienie 18:00 w ostatnim dniu, Coupon Plus graficznie w panelu;
    podetapy E20.2–E20.6 (wydanie 0.7.0) w `docs/PLAN_E20_nagrody.md`. E20 ✅ (0.7.0 i 0.7.1 na żywo 2026-10-08;
    przypomnienie 18:00 czeka na pierwszą zdrapkę).
- **E21 Łączenie starych i nowych nazw** (z pomysłu; wywiad przed startem): łączenie produktów, którym zmieniła się
  nazwa i kod (np. „Banany Premium luz” → „Banany luz”) — dziś most działa tylko przy identycznej nazwie. Diagnoza E7.5
  (2026-10-08): 316 produktów ze starych paragonów (20 pp. wydatków z 12 mies.) nie łączy się z nowymi kodami, bo stare
  paragony skracają nazwy inaczej („Winog.jas.bezp.500g” ↔ „Winogrono j.bezp.500”). Dotyczy też rankingu Produktów,
  listy kuponowej E11 (zaniżone liczby zakupów) i porównania cen E7. **Wywiad 2026-10-08** (plan:
  `docs/PLAN_E21_laczenie.md`): pary stary `n:` ↔ nowy kod dopasowuje jednorazowo Claude z eksportu, pewne łączą się
  same, wątpliwe do potwierdzenia w Produktach. Podetapy: E21.0 docs ✅, E21.1 eksport (0.14.0, 0.14.1 wszystkie nowe kody) ✅, E21.2 dopasowanie ✅, E21.3 połączenia (uproszczone: import samych pewnych par, bez karty) ✅ 0.14.2.
  **ZAKOŃCZONE 2026-10-08:** 87 połączeń, pokrycie Cen 45% → 47% — luka to głównie zmiana koszyka, nie nazwy. Przegląd wątpliwych par: 18 z 39 przyjętych → 107 połączeń, pokrycie 48%.
- **E22 Wydajność, domyślne Kupony, gazetka bez stron nie-spożywczych** (zlecone 2026-10-09; plan:
  `docs/PLAN_E22_wydajnosc.md`): Kupony jako widok domyślny, bez „Sprawdź teraz”; zakładki < 300 ms (na żywo
  Ceny ~2 s, Kupony ~1,1 s); gazetka pomija strony informacyjne, porównania cen, odzież, narzędzia, rośliny i znicze
  (żywność + drogeria zostają). Podetapy: E22.0 docs, E22.1 Kupony domyślne, E22.2 cache i Ceny w jednym przejściu,
  E22.3 lżejsze Kupony, E22.4 filtr stron gazetki, E22.5 wydanie 0.18.0 i pomiar. **E22 ZAKOŃCZONE 2026-10-09
  (0.18.0 na żywo):** Ceny 2,0 s → 31 ms, Kupony 1,1 s → 240 ms, Produkty/Miesiące ~200 ms; gazetka 8.10 = 15 paczek zamiast 20.
- **E3 Kupony — automatyczna aktywacja** (wywiad 2026-10-07; plan: `docs/PLAN_E3_kupony.md`): sekcje AllStores
  i SSC; kupon produktowy, gdy trafia kod z `auto_activate_codes()`, ogólne zawsze; raz dziennie o `run_time`
  (07:00) + „Sprawdź teraz”; jedno powiadomienie `notify.family` z datami ważności; panel z bieżącymi kuponami
  i ręczną aktywacją; start w trybie próbnym (`auto_activate` wyłączone). Podetapy: E3.0 docs ✅, E3.1 test
  aktywacji ✅, E3.2 dane i logika ✅, E3.3 harmonogram i powiadomienie ✅, E3.4 panel ✅, E3.5 wydanie 0.5.0 ✅ (2026-10-07: 0.5.0 na żywo, `auto_activate`
  włączone, pierwsza aktywacja 17:09 — kupony aktywne w aplikacji, potwierdzone). **E3 i E14 ZAKOŃCZONE 2026-10-08:**
  pierwszy samodzielny przebieg 07:00 zaimportował oba konta i aktywował nowe kupony; ujawnił codzienne 409 — Lidl
  pozwala na jeden aktywny rabat od kwoty zakupów, także między sekcjami („min. 200 zł” leży w AllStores bez kodów
  artykułów). Poprawka: kupony ogólne to jedna grupa, aktywujemy najniższy, gdy żaden nie jest aktywny (0.7.1 SSC,
  0.7.2 wszystkie sekcje; „Sprawdź teraz” na 0.7.2 bez 409).
- **E4 Gazetki — promocje na nasze produkty** (wywiad 2026-10-08; plan: `docs/PLAN_E4_gazetki.md`): linia
  „Promocje od dziś” w porannym powiadomieniu 07:00, produkty = lista E11. E4.0 rozpoznanie ✅ (2026-10-08): kody
  i daty bez logowania z lidl.pl (`q/api/search`, Żywność i napoje) i `offers.lidlplus.com/app/api/v4/PL/{sklep}/offers`;
  gazetka (JSON/PDF) bez kodów żywności → AI (freellmapi, przypięty model). Podetapy: E4.1 źródła z kodami ✅ (0.8.0 na żywo
  2026-10-08; lista promocji w pamięci, bez tabeli; na lidl.pl większość „promocji” to ceny kuponowe Lidl Plus → pomijane,
  bo aktywuje je E3; dziś 4 zwykłe obniżki na lidl.pl + 16 ofert sklepu, 1 trafienie w nasze produkty),
  E4.2 próba AI ✅ (2026-10-08: tekst PDF niewystarczający, obrazy Gemini najlepsze; limity darmowe 20 zapytań/dzień
  na model Gemini Flash), E4.3 AI w add-onie ✅ wydane (0.9.0 + 0.9.1, 2026-10-08: obrazy stron w paczkach po 5,
  kolejka modeli, postęp w bazie) — czeka weryfikacja pełnego przebiegu gazetki i pierwszej porannej linii z gazetki. **0.12.2 (2026-10-08, diagnoza):** (1) lidl.pl odpowiadał 401 na KAŻDE
  zapytanie add-onu przez `Accept: application/json` (CDN cache'uje 200 na 5 min bez względu na Accept, stąd pozorna
  losowość) — lidl.pl pytamy bez `Accept`; (2) poranna linia brała tylko promocje ze startem dziś, więc gazetka
  przetworzona po 07:00 dnia startu przepadała — teraz „Nowe promocje” = trwające i jeszcze niezgłoszone (klucze `m:`
  w `watched_sent`). Na żywo: start bez 401, „Promocje: 67 pozycji”.
- **E5 Proponowana lista zakupów:** produkty „pora kupić” (cykl zakupów) + promocje/kupony → `todo.*`; licznik oszczędności.
- **E6 Integracja z Budżetem Domowym:** dopasowanie paragonu do transakcji kartą (data + kwota), podział na kategorie.
- **E7 Śledzenie cen produktów w czasie** (zlecone 2026-10-07): z bazy historii (E2) bierzemy ceny jednostkowe
  produktów (`items.unit_price` per kod artykułu) i porównujemy je w czasie. Panel z prezentacją wyników:
  zmiana ceny produktu (pierwsza ↔ ostatnia, wykres ceny w czasie), sortowanie listy po zmianie ceny, **top 5
  inflacji** (największe podwyżki) i inne analizy do ustalenia. Do rozstrzygnięcia w wywiadzie przed startem:
  cena półkowa czy po rabatach (paragon ma obie), produkty ważone (cena za kg), kody, które zmieniły się w
  czasie (grupujemy po kodzie — zob. E2), minimalna liczba zakupów i okres do porównania, inflacja koszyka
  jako całości. **Wywiad 2026-10-08** (plan: `docs/PLAN_E7_ceny.md`): cena półkowa główna + zapłacona na wykresie,
  zmiana r/r (mediana 3 mies. vs te same 3 mies. rok wcześniej), koszyk ważony wydatkami 12 mies., nowa zakładka
  „Ceny”, bez powiadomień. Podetapy: E7.0 rozpoznanie ✅, E7.1 obliczenia ✅, E7.2 zakładka ✅ (makieta zaakceptowana; wykresy z całej historii), E7.3 wydanie 0.13.0 ✅ (pokrycie r/r 30%), E7.4 diagnoza pokrycia ✅ (0.13.1: porównane 30%, niekupowane od 3 mies. 46%, nowe 14%), E7.5 udział starych kodów `n:` ✅ (0.13.2: 20 pp. wydatków to niepołączone stare kody, ~26 pp. rzadkie zakupy), E7.6 okna 6 mies. (0.13.3); łączenie nazw → E21; E7.7 próg top 5 ≥ 50 zł/rok ✅ (0.14.3). **E7 ZAKOŃCZONE 2026-10-08** (Kiwi: prawdziwe ceny, nie błąd).
- **E8 Moduł paragonów — przeglądarka historii** (zlecone 2026-10-07; w E2 świadomie pominięta, teraz dochodzi jako
  osobny moduł/zakładka obok Produktów i Kont): lista wszystkich paragonów wraz ze szczegółami do przeglądania.
  Dane już są w bazie (`tickets` + `items`: data, sklep, konto, kwota, pozycje z ilością i ceną, rabaty z podziałem
  na kupony i promocje, kaucja), więc to głównie widok. Zakres wg zlecenia: przegląd listy paragonów, widok
  szczegółów paragonu (pozycje, rabaty, suma), **wyszukiwanie produktu: kiedy był kupowany i na jakich paragonach**
  (z cenami), „itp.” — do dopracowania w wywiadzie przed startem: filtry (zakres dat, sklep, konto, kwota),
  sortowanie i paginacja (setki paragonów), przejścia z rankingu Produktów i wykresu do paragonów danego produktu
  (i odwrotnie), pokazanie paragonów nierozpoznanych (dziś tylko licznik), czy pokazywać oryginalny wygląd
  paragonu czy własny układ. Niezależny od E3–E7, korzysta z danych E2; kolejność do ustalenia.
  **Wywiad 2026-10-08 (plan: `docs/PLAN_E8_paragony.md`):** cel = znaleźć zakup produktu (kiedy, gdzie, za ile);
  nowa zakładka „Paragony”: Szukaj w całej historii → produkty → zakupy produktu → paragon (własny układ,
  podświetlony produkt); lista paragonów po miesiącach z filtrami konto/sklep/daty, nierozpoznane oznaczone;
  tylko odczyt. Podetapy: E8.0 docs ✅, E8.1 dane ✅, E8.2 zakładka ✅, E8.3 zakupy produktu + linki ✅, E8.4 wydanie
  0.15.0 ✅ (na żywo 2026-10-08 ~23:36: 524 paragony na liście = KPI Produktów, wszystkie 524 rozliczają się do grosza
  — pozycje − rabaty + kaucje = zapłacono; Szukaj znajduje stare nazwy). **E8 ZAKOŃCZONE.** Do decyzji: produkty
  o tej samej nazwie pod różnymi kodami (np. dwa „Winogrono Red Globe”) pokazują się osobno — kandydaci do łączenia (E21).
- **Propozycje na bazie danych z 0.3.3** (2026-10-07; to pomysły, nie zatwierdzone etapy — każdy wymaga wywiadu przed startem,
  kolejność z użytkownikiem; dane potrzebne do E9–E11 są już w bazie):
  - **E9 Rytm zakupów (heatmapa):** heatmapa dzień tygodnia × godzina (liczba zakupów i/lub wydatki), trendy w czasie. Dane:
    `tickets.purchased_at` (czas lokalny; nie przeliczać strefy). Bez zewnętrznych usług.
  - **E10 Sklepy:** ranking sklepów (wizyty, wydatki, średni paragon, ostatnia wizyta), podział per konto; na próbce pierwszego
    konta 13 sklepów, jeden z ~216 wizytami z 327. **Mapa sklepów** wymaga współrzędnych, których paragon nie ma: geokodowanie adresów
    w zewnętrznej usłudze (publiczne adresy sklepów, ale wysyłka na zewnątrz — zgoda użytkownika) albo ręczne wpisanie kilkunastu
    sklepów; decyzja otwarta. Dane: `tickets.store_*`.
  - **E9 + E10 razem: zakładka „Rytm”** (wywiad 2026-10-09; plan: `docs/PLAN_E9_rytm.md`): ciekawostka bez powiadomień;
    heatmapa dzień × godzina (wizyty, przełącznik na wydatki), tabela sklepów z linkiem do Paragonów i mapa sklepów.
    Współrzędne z publicznej listy sklepów Lidl Plus (`stores.lidlplus.com/api/v2/PL`, anonimowo; Nominatim
    niepotrzebny); tabela `store_geo`. Podetapy: E9.0 docs ✅, E9.1 dane ✅, E9.2 rozpoznanie współrzędnych ✅, E9.3 współrzędne
    w add-onie ✅, E9.4 strona ✅ (makieta zaakceptowana), E9.5 wydanie 0.17.0 ✅. **E9 i E10 ZAKOŃCZONE 2026-10-09:**
    na żywo 15 z 15 sklepów ze współrzędnymi, 524 z 524 paragonów z godziną, wizyty sklepu = liczba paragonów
    w Paragonach z jego filtrem (262 = 262). Jeden paragon ma godzinę 01:46 (dane Lidla), więc heatmapa „Cała
    historia” zaczyna się od 1:00. Do decyzji: nazwa sklepu powtarza adres („Miasto A, ul. X” + „X, kod Miasto A”).
  - **Analiza kuponów i promocji** (pierwotny opis E11; zakres E11 zmieniony 2026-10-07 na listę produktów
    kuponowych — poniższe zostaje jako opcjonalne rozszerzenie później): które kupony faktycznie wykorzystujemy i jak często (`ticket_coupons`: tytuł, opis, rabat),
    ile dają złotówek, jakie promocje cenowe łapiemy („Rabat grupowy”, „Taniej za 2”, opisy rabatów przy pozycjach `items.promo`),
    kupony z wielokrotnym użyciem. Wejście dla E3: wiemy, na czym oszczędzamy dziś, zanim add-on zacznie aktywować kupony.
  - **E12 Drobne usprawnienia ekranu Produkty:** (a) miara „Sztuki” mieszała kilogramy ze sztukami — rozdzielić po `items.is_weight`
    (jednostka przy produkcie: kg albo szt.); (b) kaucje w czasie (pobrane/zwrócone) na wykresie obok wydatków; (c) struktura płatności
    (`tickets.payment`) gdy pojawi się więcej niż jedna metoda; (d) przy filtrze na produkt pokazać też liczbę zakupów i średnią cenę
    w wybranym zakresie.

## Ryzyka

Regulamin Lidla (ryzyko blokady konta), zmiany API i `App-Version`, rotacja refresh tokenu (utrata = ponowne
logowanie), jakość dopasowań nazw skróconych. Awaryjnie: analiza aplikacji (APK).

Tokeny sesji są w `/data/accounts/` i wchodzą do kopii zapasowych add-onu — kopie traktować jak dane poufne
(unieważnienie: wylogowanie urządzeń / zmiana hasła w Lidl Plus).
