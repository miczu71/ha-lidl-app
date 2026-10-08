# E8 Paragony — plan

## Cel
Szybka odpowiedź na pytanie „kiedy, gdzie i za ile kupiliśmy X” (zwrot, reklamacja, porównanie ceny).
Wyszukiwarka produktu jest główna, lista paragonów jest dodatkiem. Tylko odczyt: bez powiadomień,
bez zapisów w bazie, bez zapytań do Lidla.

## Ustalenia z wywiadu (2026-10-08)
1. Cel: znaleźć zakup produktu; lista paragonów drugorzędna.
2. Wyszukiwanie: fraza → pasujące **produkty** (z połączeniami E21) → klik → wszystkie zakupy produktu
   (data, sklep, konto, ilość, cena, rabat, link do paragonu). Niepołączone warianty nazw = osobne produkty.
3. Nowa zakładka **Paragony** (pole Szukaj u góry, przeszukuje całą historię; pod nim lista paragonów);
   strona zakupów `/paragony/produkt/{kod}`; linki „Zakupy” z Produktów i z Cen.
4. Szczegół paragonu: **własny układ** dla obu formatów (HTML i NATIVE), szukany produkt podświetlony.
5. Lista paragonów: od najnowszych, pogrupowana po miesiącach z sumą, „Pokaż więcej”; filtry: konto, sklep,
   zakres dat; paragony nierozpoznane widoczne z oznaczeniem.
6. Strona zakupów produktu: krótkie podsumowanie (ile razy, łączna ilość, wydano, najniższa–najwyższa cena,
   ostatni zakup) + linki do Cen i Wydatków; bez wykresu.
7. Sukces: wpisuję „indyk” → w 2 kliknięciach widzę wszystkie zakupy z datą, sklepem i ceną → przejście do
   paragonu; suma na paragonie zgadza się z kwotą zapłaconą.
8. Realizacja (decyzja usera 2026-10-08 23:15): wszystkie podetapy po kolei bez pytania o „go” przed każdym.

## Projekt
- **Wyszukiwanie** dopasowuje KAŻDĄ nazwę, jaka wystąpiła pod danym produktem (po moście nazw i `merges`),
  więc skrót ze starego paragonu też trafia. `matches()` jak wszędzie (słowa w dowolnej kolejności, bez polskich znaków).
- **Dane** (`history.py`, bez zmiany schematu):
  - `_products()` zbiera też wszystkie nazwy produktu (`names`); `product_search(q)` → `RankedProduct` z całej
    historii, gdy któraś nazwa pasuje.
  - `product_purchases(art_id)` → zakupy produktu od najnowszych (paragon, dzień, godzina, konto, sklep, nazwa,
    ilość, cena półkowa, wartość, rabat, w tym kupon, ważony, opis rabatu).
  - `tickets(filtry, limit)` → paragony od najnowszych + liczba wszystkich pasujących; `ticket_months(filtry)` →
    liczba i suma na miesiąc (całe miesiące, niezależnie od „Pokaż więcej”); `stores()` → sklepy z liczbą paragonów.
  - `ticket(id)` → koperta paragonu + pozycje (z kodem produktu po moście, do linków i podświetlenia) + kupony.
  - Sklep: nazwa (+ miejscowość) z koperty, inaczej to, co dała lista API, inaczej „Sklep nieznany”; filtr po
    kodzie sklepu (`store_code`, a bez niego `store`).
  - Status paragonu: bez szczegółów (`detail_fetched = 0`) i nierozpoznany (`parsed = 0`) — oznaczenie na liście.
- **Widoki** (`web/receipts.py` + szablony `receipts.html`, `_receipts_*.html`, `receipt.html`,
  `receipt_product.html`):
  - `/paragony?q=&konto=&sklep=&od=&do=&limit=` — Szukaj (htmx na żywo, blok produktów), filtry (htmx na
    żywo, blok listy), lista po miesiącach.
  - `/paragony/{id}?produkt=` — szczegół: data i godzina, sklep, konto, płatność; pozycje (ilość × cena, wartość,
    rabat z podziałem kupon / promocja i opisem); kaucje; użyte kupony; podsumowanie (pozycje, rabaty, kaucje,
    zapłacono). Nazwa pozycji prowadzi do zakupów produktu.
  - `/paragony/produkt/{kod}` — podsumowanie + lista zakupów, każdy prowadzi do paragonu z podświetleniem.
  - Linki: nazwa produktu w rankingu Produktów → zakupy; strona produktu w Cenach → „Zakupy tego produktu”.
  - Zakładka „Paragony” w nawigacji (między Ceny a Kupony). Cache-busting jak dotąd (`?v=<wersja>`).
- **Dane prywatne:** testy tylko z neutralnymi nazwami („Sklep X”, „Miasto A”, „Osoba 1”).

## Podetapy (realizacja ciągła, checkpoint = wpis w ROADMAP po każdym)
- **E8.0 docs** — ten plan + wpis w ROADMAP.
- **E8.1 dane** — metody `History` + testy.
- **E8.2 zakładka Paragony** — lista z filtrami, szukanie, szczegół paragonu; weryfikacja w przeglądarce
  (serwer dev, telefon i komputer).
- **E8.3 zakupy produktu + linki** — `/paragony/produkt/{kod}`, linki z Produktów i Cen.
- **E8.4 wydanie 0.15.0** — skill `release`, weryfikacja na żywo (Playwright, konsola, liczby vs Produkty).

## Weryfikacja
`pytest`, `ruff`, `mypy` lokalnie i zielone CI. Dev: dane demo, wszystkie widoki na 390 px i 1280 px,
konsola bez błędów. Na żywo: liczba paragonów na liście = KPI w Produktach; suma pozycji po rabatach + kaucje
= zapłacono na kilku paragonach (HTML i NATIVE); wyszukanie produktu ze starą i nową nazwą.

## Wynik (2026-10-08)
- E8.1 6e61d09, E8.2 0275016, E8.3 cff2d3d, porządki `simplify` 3c95b14 (zapytanie zakupów po indeksie, wspólne
  helpery), wydanie 0.15.0 (release v0.15.0, Supervisor zaktualizowany).
- Dev (dane demo `~/dev/lidl-spike/seed_receipts_demo.py`): 390/360/1280 px, konsola czysta, detektor impeccable bez uwag.
- Na żywo: 524 paragony = KPI; rozliczenie do kwoty zapłaconej zgodne na 524/524; Szukaj „indyk” 24 produkty,
  „winog” pokazuje stare nazwy przy produktach. Nawigacja: 5 zakładek w jednym rzędzie od 360 px.
- Pominięte przy `simplify` (świadomie): wyszukiwanie w Produktach nadal tylko po bieżącej nazwie (zmiana zachowania
  innej zakładki), makra `notice`/zakres dat (wzorzec sprzed E8).

## Cofnięcie
Etap tylko dodaje widoki i zapytania (bez migracji), więc cofnięcie = poprzednia wersja add-onu (0.14.3)
w Supervisorze albo `git revert` commitów E8.
