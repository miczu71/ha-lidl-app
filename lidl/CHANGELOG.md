# Changelog

## 0.13.2

- **Ceny — „Co nie jest porównane”:** przy każdej grupie, ile wydatków jest pod kodami ze starych paragonów
  (sprzed zmiany formatu), oraz przykładowe nazwy: stare produkty niekupowane od 3 miesięcy i produkty
  z pierwszym zakupem w ostatnim roku. Pomaga ocenić, czy niskie pokrycie porównania wynika z niepołączonych kodów.

## 0.13.1

- **Ceny — „Co nie jest porównane”:** w karcie „Nasz koszyk” zwinięte rozbicie wydatków z 12 miesięcy: porównane,
  niekupowane w ostatnich 3 miesiącach, kupowane wcześniej ale nie w tych samych miesiącach rok temu, pierwszy
  zakup w ostatnim roku (nowy produkt albo zmieniony kod lub nazwa). Pomaga ocenić, ile koszyka obejmuje porównanie.
- Poprawna odmiana: „Porównanie dla 83 produktów”.

## 0.13.0

- **Nowa zakładka „Ceny”:** jak zmieniają się ceny tego, co kupujemy (cena z półki, rok do roku: mediana
  z ostatnich 3 miesięcy wobec tych samych miesięcy rok wcześniej).
  - **Nasz koszyk:** zmiana cen ważona tym, ile na produkt wydajemy, z wykresem miesięcznym od początku
    historii i informacją, jaką część wydatków obejmuje porównanie.
  - **Najbardziej podrożały / potaniały:** po 5 produktów.
  - **Wszystkie porównane produkty:** wyszukiwanie na żywo, kolejność wg zmiany ceny albo wydatków.
  - **Wykres ceny produktu:** cena na półce w czasie i cena zapłacona przy każdym zakupie (po kuponach
    i promocjach), najtańszy zakup i liczba zakupów z rabatem.

## 0.12.2

- **Promocje z lidl.pl znów działają:** lidl.pl odrzucał zapytanie add-onu (401) z powodu nagłówka `Accept`;
  sporadyczne sukcesy brały się z 5-minutowej pamięci podręcznej po stronie Lidla.
- **Spóźniona gazetka w porannym powiadomieniu:** linia „Nowe promocje” (dawniej „Promocje od dziś”) pokazuje
  trwające promocje, których jeszcze nie zgłoszono — każdą raz. Trafienia z gazetki przetworzonej po 07:00 dnia
  startu przychodzą następnego ranka, póki promocja trwa. Obserwowane produkty dostają te same promocje
  („od 8 paź”, gdy zaczęła się wcześniej).

## 0.12.1

- **Efekt kuponów bez mylącego porównania:** do 6 listopada okno „ostatnie 30 dni” obejmuje jeszcze dni sprzed
  add-onu, więc paski i „X% mniej niż zwykle” są ukryte; zamiast nich informacja, od kiedy porównanie będzie
  miarodajne. Kwota z kuponów, promocje i lista aktywowanych kuponów zostają.

## 0.12.0

- **Gwiazdka także dla produktów spoza listy:** pole Szukaj w „Kupowane regularnie” pokazuje pod wynikami „Inne
  kupowane produkty” — kupione rzadziej, niż wymaga lista (np. raz). Gwiazdka przenosi produkt na górę listy z dopiskiem
  „spoza listy”; kupony na niego są aktywowane, a kupony i promocje trafiają do powiadomienia o obserwowanych.
  Produkty znane tylko ze starych paragonów (bez numeru artykułu) nie mają gwiazdki.

## 0.11.0

- **Obserwowane produkty:** gwiazdka przy produkcie na liście „Kupowane regularnie” (zakładka Kupony). Obserwowane
  są na górze listy, a licznik „Obserwowane” pokazuje ich liczbę. Gwiazdka włącza też auto-aktywację kuponów
  produktu; wyłączenie auto-aktywacji zdejmuje gwiazdkę.
- **Osobne powiadomienie** (obok porannego, które się nie zmienia): po porannym sprawdzeniu i po „Sprawdź teraz”,
  gdy na obserwowany produkt jest ważny kupon (z kontem) albo promocja startująca dziś. O każdym kuponie i każdej
  promocji tylko raz.

## 0.10.1

- **Nowy układ zakładki Kupony:** kupony w tym tygodniu (z zakładkami kont), Nagrody, Efekt kuponów, a na końcu
  Kupowane regularnie z wyszukiwarką.
- **Szukaj dotyczy tylko „Kupowanych regularnie”** i stoi przy tej liście. Kupony kont na zakładkach są zawsze
  pełne i nie otwierają się same po wpisaniu frazy.

## 0.10.0

- **Efekt kuponów:** nowa sekcja na górze zakładki Kupony — kwota rabatów kuponowych z ostatnich 30 dni
  i porównanie ze średnią 30-dniową z 12 miesięcy przed 7.10.2026 (start add-onu), z promocjami osobno.
  Pod spodem zwinięta lista aktywowanych kuponów z wynikiem: wykorzystany (rabat na paragonie tego konta),
  przepadł, w toku albo brak danych (kupony ogólne i sprzed 0.9.2 nie mają kodów artykułów, więc ich nie
  rozstrzygamy). Do ok. 6.11.2026 okno 30 dni nachodzi jeszcze na okres sprzed add-onu.

## 0.9.2

- **Archiwum kuponów:** kupon, który znika z listy Lidla, zostaje w bazie (z kodami artykułów i datą zniknięcia)
  zamiast być kasowany. Panel i auto-aktywacja widzą tylko bieżące kupony — bez zmian; archiwum posłuży do
  policzenia, które kupony wykorzystaliśmy, a które przepadły.

## 0.9.1

- **Gazetka:** gdy model jest przeciążony po stronie dostawcy, add-on od razu próbuje następnego z listy
  zamiast czekać 10 minut na ten sam.

## 0.9.0

- **Promocje z gazetki:** add-on czyta cotygodniową gazetkę przez model językowy z obsługą obrazów (opcje
  **Adres i klucz API modelu językowego**, **Modele wizyjne**; puste = wyłączone). Strony idą w paczkach po 5,
  w tle; przy limicie modelu add-on przechodzi do następnego z listy. Promocje na produkty z zakładki Kupony
  trafiają do linii „Promocje od dziś” w porannym powiadomieniu (bez kuponów Lidl Plus — te aktywuje add-on).
- Każdy produkt w linii „Promocje od dziś” występuje raz, nawet gdy ofertę ma kilka źródeł.
- Promocje odświeżają się też przy starcie add-onu, więc „Sprawdź teraz” po aktualizacji nie czeka do rana.

## 0.8.0

- **Promocje od dziś w porannym powiadomieniu:** gdy w sklepie startuje promocja na produkt z listy „Kupowane
  regularnie” (ten sam przełącznik co przy kuponach), powiadomienie o 07:00 dostaje linię z rabatem i datą końca,
  np. „Produkt A −20% przy 2 szt. (do 10 paź)”. Źródła: promocje z lidl.pl (bez cen kuponowych Lidl Plus — te
  aktywuje add-on) i oferty sklepu, w którym robicie najwięcej zakupów. Bez logowania, bez nowych opcji.

## 0.7.2

- **Rabaty od kwoty zakupów w różnych sekcjach:** kupon „min. 200 zł” Lidl pokazuje wśród zwykłych kuponów, nie
  w rabatach od zakupów, a i tak pozwala na jeden taki rabat naraz. Add-on traktuje wszystkie kupony ogólne (bez
  konkretnych produktów) jako jedną grupę — koniec codziennych nieudanych prób.

## 0.7.1

- **Kupony ogólne (rabat od zakupów):** add-on traktuje je jako jedną grupę — Lidl pozwala na jeden aktywny naraz,
  także przy różnych progach („min. 100 zł” i „min. 200 zł”). Koniec codziennych nieudanych prób i „Nie udało się”.
- **Kupon Plus:** kwoty progów leżących blisko siebie (np. 50/300/500 zł) już na siebie nie nachodzą — podpis ma
  zawsze najbliższy i ostatni próg; rabat nagrody bez gwiazdki.

## 0.7.0

- **Nagrody na górze zakładki Kupony:** niezdrapane **zdrapki** każdego konta z datą ważności (w ostatnim dniu na
  czerwono) i **Kupon Plus** jako pasek z progami jak w aplikacji — wydana kwota, ile brakuje do następnego progu,
  nagroda za niego i dni do końca akcji.
- **Zdrapki w powiadomieniach:** linia „Zdrapki” w porannym powiadomieniu (przychodzi także bez kuponów) i osobne
  przypomnienie o 18:00, gdy zdrapka wygasa tego dnia — nie zastępuje porannego.
- Nagrody odczytują się przy starcie add-onu i z „Sprawdź teraz”; add-on tylko czyta, niczego nie zdrapuje.

## 0.6.1

- **Kupony kont jako zakładki:** listy kuponów każdej osoby są zakładkami w jednym rzędzie (na starcie zwinięte),
  z podsumowaniem „aktywne N z M · tylko tu: K”; łatwo przejść od jednej karty do drugiej.
- Przy każdym kuponie znacznik **„wspólny”** (jest na obu kontach) albo **„tylko <osoba>”**.
- Na telefonie znacznik, status i „Aktywuj” są pod nazwą kuponu (nic nie nachodzi na tekst).

## 0.6.0

- **Którą kartę wziąć:** poranne powiadomienie poleca kartę z lepszymi kuponami na Wasze produkty (aktywne kupony
  na produkty z listy „Kupowane regularnie”, ważone tym, jak często je kupujecie) — kupony różnią się między kontami,
  a przy kasie skanuje się jedną kartę.
- **Czytelniejsze powiadomienie:** kupony każdej karty w skrócie, wspólne w linii „Obie:”, osobno „Koniec dziś”;
  dotknięcie otwiera panel, nowe powiadomienie zastępuje poprzednie. Przychodzi codziennie rano, gdy jest co polecić.
- **Kupony „Twój sklep” do wyboru** (np. 10/20/30 zł na zakupy od 100 zł, można aktywować jeden): add-on bierze
  najniższą kwotę i nie próbuje pozostałych.
- Poprawka: wyszukiwanie na Produktach znajduje każdy produkt z zakresu dat (wcześniej tylko z pierwszych 200).

## 0.5.0

- **Automatyczna aktywacja kuponów (na start w trybie próbnym).** Codziennie o 7:00 add-on pobiera kupony każdego
  konta (wszystkie sklepy i „Twój sklep”) i aktywuje kupony ogólne oraz kupony na produkty z listy „Kupowane
  regularnie”. Dopóki nowa opcja **Automatyczna aktywacja kuponów** jest wyłączona, tylko pokazuje, co by aktywował.
- **Powiadomienie** na `notify.family`: jedno na przebieg, z nowymi kuponami obu kont i datami ważności. Add-on
  dostał do tego uprawnienie do API Home Assistanta.
- **Zakładka Kupony:** kupony tego tygodnia na każdym koncie ze statusem, przycisk **Aktywuj** przy pozostałych
  i **Sprawdź teraz**.
- **Opcja Godzina dziennego przebiegu** (domyślnie 07:00): o tej porze pobierają się też nowe paragony (wcześniej
  co 24 h od startu add-onu).
- **Wyszukiwanie i zmiany na żywo:** pole Szukaj na Produktach i Kuponach filtruje w trakcie pisania; daty, krok,
  przełączniki i aktywacja działają bez przeładowania strony. Lista rozwijana produktów przy wykresie zastąpiona
  wyszukiwaniem.
- **Najczęściej kupowane** liczone z zakresu dat wykresu (wcześniej z całej historii, przez co „Wykres” produktu
  niekupowanego od roku był pusty); przy dacie „ostatnio” rok, gdy to nie bieżący rok.

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
