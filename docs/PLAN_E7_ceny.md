# E7 Śledzenie cen produktów w czasie — plan

## Context

Następny etap roadmapy Lidl wybrany 2026-10-08: E7. Wywiad:
- **Cel:** „wszystko po trochu”: rozpoznać „normalną” cenę produktu (czy promocja/kupon to okazja), wyłapać
  produkty, które najbardziej podrożały, i znać inflację naszego koszyka.
- **Cena:** półkowa jest główna (zmiana ceny, top 5, koszyk); na wykresie produktu druga seria = cena zapłacona
  po rabatach.
- **Porównanie:** rok do roku — mediana ceny półkowej z ostatnich 3 mies. vs mediana z tych samych 3 mies. rok
  wcześniej; produkt musi mieć zakup w obu oknach.
- **Koszyk:** średnia zmian r/r ważona wydatkami na produkt z ostatnich 12 mies. → liczba „+X% r/r” + wykres
  miesięczny (dla każdego miesiąca to samo porównanie liczone na jego koniec).
- **Miejsce:** nowa zakładka „Ceny”; bez powiadomień (ewentualne „najtaniej od X mies.” w porannym → później).

Założenia (przyjęte przy podsumowaniu wywiadu): produkty po moście nazw jak na Produktach (`_resolver`); ważone
porównywane w cenie za kg; shrinkflation → E18; łączenie zmienionych nazw/kodów poza zakresem; liczone na bieżąco
z `items`/`tickets`, bez nowej tabeli i bez zmiany schematu.

## Ograniczenia
1. Korzysta: domownicy w panelu (zakładka „Ceny”). Nic nie dzieje się automatycznie, add-on tylko liczy i pokazuje.
2. Bez zmian w bazie, harmonogramie i powiadomieniach — wydanie E7 da się cofnąć zwykłym downgrade'em.
3. Sukces: na żywo liczba koszyka + wykres, top 5 podwyżek i obniżek, które użytkownik uzna za wiarygodne,
   lista z wyszukiwarką, wykres ceny dowolnego produktu (półkowa + zapłacona).

## E7.0 — rozpoznanie ✅ (2026-10-08)
Próbka: 14 paragonów osoby 1 (`~/dev/lidl-spike/data/osoba1`, HTML 2026 i NATIVE 2019–2026) przez `parse_detail`.
- `unit_price` = **cena półkowa** w obu parserach; `total = quantity × unit_price` co do grosza w każdej pozycji.
- `discount` = **suma wszystkich rabatów** pozycji (ujemna), `coupon` to jej część. Cena zapłacona za jednostkę =
  `(total + discount) / quantity`.
- Ważone (`is_weight = 1`): `quantity` w kg, `unit_price` za kg (np. 0,448 × 14,99 = 6,72) — porównywalne wprost.
- Kupon ogólny (rabat od kwoty) Lidl rozkłada proporcjonalnie na pozycje (np. −0,25 zł przy 5,99 zł, ~4%) —
  cena zapłacona jest przez to lekko zaniżona względem „sam produkt”. Akceptujemy: to realnie zapłacona kwota.
- **Nie sprawdzone:** ile produktów ma zakupy w obu oknach r/r i jaki udział wydatków pokrywają — pełna baza jest
  tylko na hoście HA (nie czytamy jej z tego kontenera). Sprawdzimy na żywo przy E7.3 (linia w logu przy starcie
  albo licznik na ekranie: „porównanie dla N produktów, X% wydatków”); jeśli pokrycie wyjdzie niskie (< 50%
  wydatków), wracamy do decyzji o oknach (np. 6 mies.) przed wydaniem — powiedzieć to wprost.

## E7.1 — obliczenia w `history.py` (TDD, osobna zgoda z dokładnymi krokami)
Tylko odczyty, nowe metody `History`:
- `price_changes(today)` → lista `PriceChange(art_id, name, is_weight, old, new, pct, spend)`: mediana
  `unit_price` w oknie `[today − 3 mies., today]` vs `[today − 15 mies., today − 12 mies.]`; `spend` = suma
  zapłacona (`total + discount`) z ostatnich 12 mies. Produkty bez zakupu w którymś oknie pominięte.
- `basket_inflation(today)` → `pct` ważony `spend`, `products`, `coverage` (udział `spend` porównanych produktów
  w wydatkach 12 mies.).
- `basket_series(today)` → `[(miesiąc, pct)]` dla końców miesięcy od (pierwszy paragon + 15 mies.) do dziś.
- `price_history(art_id)` → `[(day, shelf, paid)]` per zakup.
Testy w `lidl/app/tests/test_history.py`: okna i mediana, produkt w jednym oknie pominięty, ważone za kg, most
nazw, wagi koszyka, pusta baza.

## E7.2 — zakładka „Ceny” (makieta przed kodem, skill `impeccable`, tokeny `docs/DESIGN.md`)
`/ceny`: na górze koszyk (+X% r/r, pokrycie, wykres miesięczny), top 5 podwyżek i top 5 obniżek, lista
produktów sortowana po zmianie z wyszukiwarką na żywo (htmx jak Produkty/Kupony). Produkt → wykres ceny w czasie
(dwie serie: półkowa i zapłacona). `web/chart.py` ma dziś tylko słupki wydatków — wykres liniowy to nowy kod SVG
(minimum: punkty + linia, bez biblioteki). Weryfikacja Playwright (desktop + telefon) na danych dev.

## E7.3 — wydanie 0.13.0
Skill `simplify` → skill `release` (bump `lidl/config.yaml` i `pyproject.toml`, CHANGELOG, published release,
aktualizacja przez Supervisora za zgodą), cache-busting, znacznik wersji. Na żywo: pokrycie r/r (zob. E7.0),
ocena top 5 przez użytkownika. Cofnięcie: downgrade do 0.12.2 (bez zmian schematu).
