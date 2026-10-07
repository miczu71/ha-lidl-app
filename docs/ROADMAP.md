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
- [ ] Włączyć „Show in sidebar” dla add-onu (domyślnie wyłączone).
- [ ] Test rotacji tokenu: ponowne pobranie danych po >1 h od logowania (potwierdza zapis nowego refresh tokenu).
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
  kuponu; odznaczenie przetrwa przeładowanie). Lista jest długa — filtr tekstowy do decyzji przy E3.
- **E3 Kupony:** lista per konto, dopasowanie po kodzie artykułu, auto-aktywacja pasujących, ręczna reszta,
  powiadomienia przez aliasy `notify.*`.
- **E4 Gazetki:** pobieranie bieżących gazetek, ekstrakcja produktów i cen, dopasowanie do historii. Na wstępie
  sprawdzić, czy któryś model z puli (freellmapi) czyta obrazy stron; jeśli nie, zostaje tekst z PDF.
- **E5 Proponowana lista zakupów:** produkty „pora kupić” (cykl zakupów) + promocje/kupony → `todo.*`; licznik oszczędności.
- **E6 Integracja z Budżetem Domowym:** dopasowanie paragonu do transakcji kartą (data + kwota), podział na kategorie.
- **E7 Śledzenie cen produktów w czasie** (zlecone 2026-10-07): z bazy historii (E2) bierzemy ceny jednostkowe
  produktów (`items.unit_price` per kod artykułu) i porównujemy je w czasie. Panel z prezentacją wyników:
  zmiana ceny produktu (pierwsza ↔ ostatnia, wykres ceny w czasie), sortowanie listy po zmianie ceny, **top 5
  inflacji** (największe podwyżki) i inne analizy do ustalenia. Do rozstrzygnięcia w wywiadzie przed startem:
  cena półkowa czy po rabatach (paragon ma obie), produkty ważone (cena za kg), kody, które zmieniły się w
  czasie (grupujemy po kodzie — zob. E2), minimalna liczba zakupów i okres do porównania, inflacja koszyka
  jako całości.
- **E8 Moduł paragonów — przeglądarka historii** (zlecone 2026-10-07; w E2 świadomie pominięta, teraz dochodzi jako
  osobny moduł/zakładka obok Produktów i Kont): lista wszystkich paragonów wraz ze szczegółami do przeglądania.
  Dane już są w bazie (`tickets` + `items`: data, sklep, konto, kwota, pozycje z ilością i ceną, rabaty z podziałem
  na kupony i promocje, kaucja), więc to głównie widok. Zakres wg zlecenia: przegląd listy paragonów, widok
  szczegółów paragonu (pozycje, rabaty, suma), **wyszukiwanie produktu: kiedy był kupowany i na jakich paragonach**
  (z cenami), „itp.” — do dopracowania w wywiadzie przed startem: filtry (zakres dat, sklep, konto, kwota),
  sortowanie i paginacja (setki paragonów), przejścia z rankingu Produktów i wykresu do paragonów danego produktu
  (i odwrotnie), pokazanie paragonów nierozpoznanych (dziś tylko licznik), czy pokazywać oryginalny wygląd
  paragonu czy własny układ. Niezależny od E3–E7, korzysta z danych E2; kolejność do ustalenia.
- **Propozycje na bazie danych z 0.3.3** (2026-10-07; to pomysły, nie zatwierdzone etapy — każdy wymaga wywiadu przed startem,
  kolejność z użytkownikiem; dane potrzebne do E9–E11 są już w bazie):
  - **E9 Rytm zakupów (heatmapa):** heatmapa dzień tygodnia × godzina (liczba zakupów i/lub wydatki), trendy w czasie. Dane:
    `tickets.purchased_at` (czas lokalny; nie przeliczać strefy). Bez zewnętrznych usług.
  - **E10 Sklepy:** ranking sklepów (wizyty, wydatki, średni paragon, ostatnia wizyta), podział per konto; na próbce pierwszego
    konta 13 sklepów, jeden z ~216 wizytami z 327. **Mapa sklepów** wymaga współrzędnych, których paragon nie ma: geokodowanie adresów
    w zewnętrznej usłudze (publiczne adresy sklepów, ale wysyłka na zewnątrz — zgoda użytkownika) albo ręczne wpisanie kilkunastu
    sklepów; decyzja otwarta. Dane: `tickets.store_*`.
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
