# Changelog

## 0.4.0

- Nowa zakładka **Kupony**: produkty kupione co najmniej 3 razy w ostatnich 12 miesiącach (na wszystkich kontach razem), z liczbą zakupów, datą ostatniego, użyciami kuponów i kwotami z kuponów i promocji.
- Przy każdym produkcie przełącznik **auto-aktywacji kuponów** — domyślnie włączony, odznaczenie zapisuje się od razu. Sama aktywacja kuponów przyjdzie w kolejnej wersji; ta lista będzie dla niej regułą.
- Produkty znane tylko ze starszych paragonów (bez numeru artykułu, który mają kupony) są oznaczone „bez kodu kuponu” — do nich kuponu nie da się dopasować.

## 0.3.3

- **Kaucje pobrane i zwrócone osobno.** Poprzednia wersja wyliczała jedno saldo kaucji i obcinała je do zera, więc zwroty (kaucja za zgrzewki, skrzynki, opakowania bez kaucji) znikały, a kaucje wychodziły zawyżone. Teraz karta oszczędności i podsumowanie pod wykresem pokazują „kaucje pobrane” i „kaucje zwrócone”, a „zapłacono łącznie” to pozycje po rabatach plus pobrane minus zwrócone.
- Przy pobieraniu paragonów zapisujemy też: godzinę zakupu (czas lokalny z paragonu), sklep (kod, nazwa, adres, miejscowość), sposób płatności, użyte kupony, opis rabatu przy pozycji i flagę ważenia. Na razie bez nowych ekranów, to baza pod kolejne etapy (sklepy, godziny zakupów, kupony, ceny w czasie).
- Zapisujemy oczyszczoną, skompresowaną kopię szczegółu każdego paragonu (bez danych karty, kasjera i danych fiskalnych, ok. 1,3 MB na ~500 paragonów). Dzięki niej kolejne zmiany sposobu czytania paragonów przetwarzamy lokalnie, bez ponownego pobierania z Lidla.
- Po aktualizacji paragony pobierają się od nowa (ok. 20 minut, w tle, panel pisze, z ilu paragonów liczone są kaucje); pozycje, wykres i oszczędności są widoczne przez cały czas.

## 0.3.2

- Ekran Produkty pokazuje **ile zapłacono łącznie** (suma kwot paragonów po rabatach, z kaucją) i **ile z tego to kaucje** — w karcie oszczędności za całą historię oraz pod wykresem dla wybranego zakresu dat.
- Kaucje wyliczamy z paragonów (kwota paragonu minus pozycje po rabatach), więc nie wymaga to ponownego pobierania historii. Przy filtrze na jeden produkt i w mierze „Sztuki” pod wykresem zostaje sama suma wydatków na produkt (kaucja i kwota paragonu nie są przypisane do produktu).

## 0.3.1

- **Starsze paragony są teraz czytane.** Paragony sprzed 27 marca 2026 przychodzą z API w innym formacie (lista pozycji zamiast HTML); wersja 0.3.0 pobierała je, ale nie rozpoznawała, więc ranking i wykres obejmowały tylko ostatnie pół roku. Teraz cała historia (od 2019) trafia do wykresu i rankingu.
- Ten sam produkt ze starszych i nowszych paragonów jest łączony po nazwie, gdy nazwa pasuje do dokładnie jednego produktu z nowszych paragonów (kody w obu formatach są różne).
- **Oszczędności liczone z rabatów na pozycjach paragonów**, osobno kupony Lidl Plus i promocje. Pole „zaoszczędzono” z listy paragonów Lidl wypełnia tylko od sierpnia 2026, więc dawało zaniżoną kwotę (210,70 zł). Przy niepełnym imporcie panel pisze, z ilu paragonów liczy.
- Paragony, z których nie udało się odczytać żadnych pozycji, są zliczane i pokazywane w panelu zamiast cichego pominięcia.
- Konto bez historii (np. dodane później druga osoba) ma w panelu Produkty własny przycisk **Pobierz historię**.
- Po aktualizacji historia zakupów pobiera się od nowa (ok. 15 minut, automatycznie w tle); tokeny kont nie są ruszane.

## 0.3.0

- Nowy ekran **Produkty** (zakładka obok Kont): oszczędności z dotychczasowych paragonów (łącznie i z ostatnich 12 miesięcy), ranking najczęściej kupowanych produktów (liczba zakupów, ostatnia cena, średni cykl) oraz wykres wydatków.
- Wykres wydatków w dowolnym zakresie dat, krok tydzień / miesiąc (domyślny) / kwartał / rok, opcjonalnie dla jednego produktu, w złotych lub sztukach.
- Import historii paragonów: przycisk **Pobierz historię** przy koncie (pierwszy raz, wszystkie lata, powoli i z wznawianiem), potem codziennie tylko nowe paragony. Produkt to kod artykułu z paragonu.
- Baza historii w `/data/history.db` (SQLite) wchodzi do kopii zapasowych add-onu — traktuj kopie jak dane poufne (to Wasze zakupy).

## 0.2.0

- Nowy wygląd panelu wzorowany na aplikacji Lidl Plus (styl „Lidl Plus styl”, `docs/DESIGN.md`): płaskie karty, pigułkowe przyciski, awatary kont, statusy z ikoną, ponumerowane kroki logowania.
- Font Figtree (OFL) zamiast Inter i Source Serif; ikony inline SVG.
- Układ zgodny z makietami na telefon i komputer; funkcje bez zmian.

## 0.1.0

- Panel Ingress: dodawanie, logowanie, sprawdzanie i usuwanie kont Lidl Plus.
- Logowanie ręczne przez przeglądarkę (OAuth PKCE), tokeny w `/data/accounts/` (0600), zapis atomowy.
- Blokada per konto przy odświeżaniu tokenu (Lidl rotuje refresh token).
