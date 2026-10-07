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
- Nie wiadomo, czy `yearOffset=5` zawiera całą starszą historię, czy jest limitem API — E2 to sprawdza
  (porównanie liczby i dat paragonów).

## Stan i otwarte sprawy (2026-10-07)

- [x] E0 rozpoznanie, E1 add-on 0.1.0 (release `v0.1.0`), CI (testy, ruff, mypy, budowa arm64/amd64), D1 nowy styl (0.2.0).
- [x] E2.1–E2.2 kod: parser, baza, import, ekran Produkty z wykresem (0.3.0). [ ] E2.3: wydanie i pierwszy import na żywo (wnioski o `yearOffset` po imporcie).
- [x] Konto pierwszej osoby połączone w panelu (add-on 0.2.0 na żywo).
- [ ] Zalogować w panelu konto drugiej osoby.
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

## Ryzyka

Regulamin Lidla (ryzyko blokady konta), zmiany API i `App-Version`, rotacja refresh tokenu (utrata = ponowne
logowanie), jakość dopasowań nazw skróconych. Awaryjnie: analiza aplikacji (APK).

Tokeny sesji są w `/data/accounts/` i wchodzą do kopii zapasowych add-onu — kopie traktować jak dane poufne
(unieważnienie: wylogowanie urządzeń / zmiana hasła w Lidl Plus).
