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

- [x] E0 rozpoznanie, E1 add-on 0.1.0 (release `v0.1.0`), CI (testy, ruff, mypy, budowa arm64/amd64).
- [ ] Zalogować w panelu konta obu osób (pierwsze konto zalogowane w spike E0, drugie jeszcze nie).
- [ ] Włączyć „Show in sidebar” dla add-onu (domyślnie wyłączone).
- [ ] Test rotacji tokenu: ponowne pobranie danych po >1 h od logowania (potwierdza zapis nowego refresh tokenu).
- [ ] Opcjonalnie `impeccable init` (`PRODUCT.md`) — UI na razie wzorowany na Budżecie.

## Etapy

Każdy etap niesie wartość sam z siebie; po każdym checkpoint.

- **E1 Szkielet add-onu i logowanie kont** — ✅ 0.1.0 (wydane, zainstalowane, UI sprawdzone w HA; CI zielony).
- **E2 Historia paragonów:** import całej historii wszystkich kont (powoli, z przerwami), deduplikacja pozycji,
  normalizacja produktów, ranking „najczęściej kupowane” (częstość, cena, ostatni zakup). Na początek **punkt
  odniesienia oszczędności**: lista paragonów ma pola `savings` i `couponsUsedCount` — suma „ile oszczędzaliśmy
  zanim add-on cokolwiek zmienił”, do porównania w KPI.
- **E3 Kupony:** lista per konto, dopasowanie po kodzie artykułu, auto-aktywacja pasujących, ręczna reszta,
  powiadomienia przez aliasy `notify.*`.
- **E4 Gazetki:** pobieranie bieżących gazetek, ekstrakcja produktów i cen, dopasowanie do historii. Na wstępie
  sprawdzić, czy któryś model z puli (freellmapi) czyta obrazy stron; jeśli nie, zostaje tekst z PDF.
- **E5 Proponowana lista zakupów:** produkty „pora kupić” (cykl zakupów) + promocje/kupony → `todo.*`; licznik oszczędności.
- **E6 Integracja z Budżetem Domowym:** dopasowanie paragonu do transakcji kartą (data + kwota), podział na kategorie.

## Ryzyka

Regulamin Lidla (ryzyko blokady konta), zmiany API i `App-Version`, rotacja refresh tokenu (utrata = ponowne
logowanie), jakość dopasowań nazw skróconych. Awaryjnie: analiza aplikacji (APK).

Tokeny sesji są w `/data/accounts/` i wchodzą do kopii zapasowych add-onu — kopie traktować jak dane poufne
(unieważnienie: wylogowanie urządzeń / zmiana hasła w Lidl Plus).
