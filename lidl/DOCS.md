# Zakupy (Lidl + Biedronka)

Nieoficjalny add-on do kont Lidl Plus (Polska). Obsługuje wiele kont (np. po jednym na osobę w domu).

## Logowanie konta

Lidl loguje przez stronę z captcha i kodem MFA, więc robisz to w przeglądarce na komputerze:

1. W panelu dodaj konto i kliknij **Zaloguj**.
2. Otwórz okno prywatne, narzędzia deweloperskie (F12), zakładka **Network**, zaznacz **Preserve log**.
3. Wejdź na adres logowania z panelu i zaloguj się. Strona zostanie na ekranie logowania — to normalne.
4. W Network znajdź odpowiedź **302** z żądania `callback` i skopiuj nagłówek **Location**
   (zaczyna się od `com.lidlplus.app://callback?code=`).
5. Wklej go w panelu i kliknij **Połącz konto**. Adres jest ważny kilka minut i działa tylko raz.

Token sesji odnawia się automatycznie (Lidl wydaje nowy przy każdym odświeżeniu, add-on zapisuje go od razu).
Jeśli sesja wygaśnie, panel poprosi o ponowne logowanie.

## Historia zakupów (zakładka Produkty)

Po zalogowaniu konta kliknij **Pobierz historię** (zakładka Produkty). Pierwsze pobranie obejmuje wszystkie
paragony konta, idzie powoli (jeden paragon na kilka sekund, kilkanaście minut) i działa w tle — panel możesz
zamknąć. Jeśli Lidl ograniczy liczbę żądań albo zerwie się połączenie, import zatrzymuje się, a **Wznów teraz**
dokańcza tylko to, czego brakuje. Potem nowe paragony pobierają się same: w porannym przebiegu (opcja
**Godzina dziennego przebiegu**, domyślnie 7:00) oraz co godzinę od 7:00 do 23:00 w dni, gdy sklepy są
otwarte — od poniedziałku do soboty i w niedziele handlowe (add-on wylicza je z ustawy; w zwykłe niedziele
godzinnego pobrania nie ma). Godzinne pobranie dotyczy tylko paragonów: bez kuponów i bez powiadomień, a nowy
paragon jest w panelu i w Budżecie najpóźniej godzinę po zakupie.

- **Oszczędności** to suma rabatów na pozycjach paragonów (osobno kupony Lidl Plus i promocje) — punkt odniesienia sprzed aktywacji kuponów przez add-on.
- **Zapłacono łącznie** to suma kwot paragonów (po rabatach, z saldem kaucji). **Kaucje pobrane** i **zwrócone**
  czytamy wprost z paragonu (sekcje „Opakowania zwrotne wydania” i „…przyjęcia”): pozycje po rabatach plus pobrane
  minus zwrócone daje kwotę paragonu. Obie liczby są w karcie oszczędności i pod wykresem.
- **Wykres** pokazuje wydatki na pozycje (po rabatach, bez kaucji) w wybranym zakresie dat i kroku; można
  zawęzić do jednego produktu albo pokazać sztuki zamiast złotych. Zmiana dat, kroku czy miary działa od razu.
- **Najczęściej kupowane** liczymy z tego samego zakresu dat co wykres (domyślnie 12 miesięcy). Pole **Szukaj
  produktu** filtruje listę w trakcie pisania (wszystkie słowa, bez względu na polskie znaki); **Wykres** przy
  produkcie pokazuje jego wydatki.
- Produkt to kod artykułu z paragonu. Starsze paragony (sprzed marca 2026) mają inne kody niż nowsze, więc
  łączymy je po nazwie, gdy jednoznacznie pasuje; zmiana kodu przez Lidl tworzy nowy produkt.
- Gdy z jakiegoś paragonu nie da się odczytać pozycji, panel pokazuje ich liczbę.

## Kupony (zakładka Kupony)

Codziennie o godzinie dziennego przebiegu (domyślnie 7:00) add-on pobiera kupony Lidl Plus każdego konta
(sekcje „wszystkie sklepy” i „Twój sklep”) i aktywuje **kupony na produkty kupowane regularnie** — co najmniej
3 razy w ostatnich 12 miesiącach, na wszystkich kontach razem (lista „Kupowane regularnie”; domyślnie zaznaczone są
wszystkie, odznacz to, czego nie chcesz).

**Kuponów ogólnych** (np. 10 zł rabatu na zakupy od 100 zł) add-on nie aktywuje — Lidl pozwala na jeden aktywny
naraz, więc wybierasz go sam przyciskiem **Aktywuj** w panelu albo w aplikacji. Kupony tylko do sklepu internetowego
mają w panelu znacznik „online” i też nie są aktywowane automatycznie.

Kupony, które jeszcze nie obowiązują, aktywuje w dniu ich startu; kuponów już aktywnych nie rusza.

**Którą kartę wziąć:** kupony różnią się między kontami, a przy kasie skanuje się jedną kartę. Rano add-on wysyła
na `notify.family` jedno powiadomienie (gdy któraś karta ma aktywne kupony na Wasze produkty): w tytule karta z lepszą
oceną (aktywne kupony na produkty z listy, ważone tym, jak często je kupujecie), w treści kupony każdej karty w skrócie,
wspólne w linii „Obie:” i te, które kończą się dziś. Dotknięcie otwiera panel; nowe powiadomienie zastępuje poprzednie.

Zakładka Kupony otwiera się jako pierwsza i pokazuje
kupony tego tygodnia na każdym koncie ze statusem; resztę aktywujesz przyciskiem **Aktywuj**. Kupony sprawdzają się
same codziennie o `run_time`. Pole **Szukaj** filtruje kupony i listę produktów w trakcie pisania.

**Tryb próbny:** dopóki opcja **Automatyczna aktywacja kuponów** jest wyłączona (domyślnie), add-on niczego nie
aktywuje — panel i powiadomienie pokazują tylko, co zostałoby aktywowane.

Produkt oznaczony „bez kodu kuponu” znamy tylko ze starszych paragonów, bez numeru artykułu, którym posługują się
kupony — do niego kuponu nie dopasujemy.

## Nagrody: zdrapki i Kupon Plus (zakładka Kupony)

Na górze zakładki, osobno dla każdego konta:

- **Zdrapki** do zdrapania (Lidl daje je po zakupach, ważne zwykle ok. 3 dni) z datą ważności; w ostatnim dniu na
  czerwono. Zdrapuje się w aplikacji Lidl Plus — zdrapana znika z listy.
- **Kupon Plus** (akcja „wydaj X zł → kupon”): pasek z progami jak w aplikacji, wydana kwota, ile brakuje do
  następnego progu, nagroda za niego i ile dni zostało do końca akcji.

Zdrapki są też w porannym powiadomieniu (linia „Zdrapki”; powiadomienie przychodzi także bez kuponów), a o 18:00
add-on wysyła osobne przypomnienie, gdy któraś zdrapka wygasa tego dnia. Add-on niczego nie zdrapuje ani nie
uruchamia — tylko odczytuje.

## Nowe promocje (poranne powiadomienie)

Gdy w sklepie trwa promocja na produkt z zakładki Kupony (ten sam przełącznik), poranne powiadomienie dostaje
linię „Nowe promocje” z rabatem i datą końca — każdą promocję raz, także gdy gazetka została przetworzona dopiero
po porannym przebiegu (wtedy następnego dnia, o ile promocja jeszcze trwa). Źródła: promocje z lidl.pl, oferty sklepu, w którym robicie
najwięcej zakupów, i — gdy ustawisz model językowy — cotygodniowa gazetka. Ceny kuponowe Lidl Plus pomijamy:
te kupony add-on aktywuje sam.

Gazetkę add-on czyta raz na wydanie: w tle, po 5 stron na zapytanie, wysyła do modelu obrazy stron (z serwera
Lidla); całość trwa od kilkudziesięciu minut do kilku godzin, zależnie od limitów modelu. Do modelu trafiają
obrazy publicznej gazetki i nazwy produktów z zakładki Kupony — bez kont, kwot i dat zakupów.

Gdy modele wizyjne zawodzą (przeciążenie, limity), add-on ponawia paczkę co 10 minut. Po kilku nieudanych
rundach (albo od razu, gdy modele Google wyczerpały limity) dołącza **modele awaryjne** — szybkie, ale mniej dokładne, więc ich oferty przechodzą dodatkowy filtr
(nazwa oferty musi mieć wspólne słowo z Twoim produktem i podany rabat). Paczka, której nie uda się przetworzyć
po 30 próbach, jest odkładana do następnego dnia (6:00) i wraca do kolejki, dopóki gazetka trwa; w zakładce Status
widać ją jako „odłożoną”.

## Opcje

- **Poziom logów** — debug nie wypisuje tokenów ani kodów logowania.
- **Automatyczna aktywacja kuponów** — wyłączona = tryb próbny (patrz wyżej).
- **Automatyczny Shakeomat Biedronki** — domyślnie wyłączony. Włączony: rano po imporcie odsłania Shakeomat
  i Shakeomarkę na kontach Biedronki (zapis na koncie przez nieoficjalne API) i wysyła wynik na `notify.family`.
  Bez tej opcji zostaje przycisk „Odsłoń teraz” w zakładce Kupony → Biedronka.
- **Godzina dziennego przebiegu** — GG:MM, czas lokalny; paragony, kupony i powiadomienie.
- **Dodatkowe kraje** (`extra_countries`) — kody krajów, z których pobieramy e-paragony po przełączeniu kraju
  w Lidl Plus, np. `CZ`, `IT`. Wystarcza jedno logowanie. Pusta lista = tylko Polska. Import raz dziennie
  (i przy „Sprawdź teraz”); kwoty w statystykach liczone w PLN po średnim kursie NBP z ostatniego dnia roboczego
  przed zakupem, oryginał widać przy paragonie. Produkty, ceny, kupony i Rytm zostają polskie.
- **Adres i klucz API modelu językowego, modele wizyjne i awaryjne** — odczyt promocji z cotygodniowej gazetki
  (niżej). Puste adres albo klucz = gazetka wyłączona. Pusta lista modeli awaryjnych wyłącza je.

- **Token API** (`api_token`) — wspólny sekret dla add-onu Dieta. Puste = API wyłączone (odpowiedź 503). Ustaw długi losowy token (≥32 znaki); API nie ogranicza liczby prób.

Add-on ma uprawnienie do API Home Assistanta (`homeassistant_api`) wyłącznie po to, żeby wysłać powiadomienie
przez `notify.family`.

## API dla Diety

`GET /api/v1/purchases?months=12` z nagłówkiem `Authorization: Bearer <api_token>` (poza Ingressem, w sieci
Supervisora). Zwraca agregat per produkt z ostatnich miesięcy: `code`, `chain`, `name`, `names`, `purchases`,
`spend`, `first`, `last`, `dates`, `category`. Bez paragonów i adresów sklepów. Kody: 401 brak/zły token,
503 pusty `api_token`. Reszta tras nadal działa tylko przez Ingress.

### Katalog cen

Zakupy zapisują historię cen produktów (tabele `catalog_products`, `catalog_obs`): ceny jednostkowe po rabacie
z paragonów (źródło `receipt`) i z publicznego feedu Frisco (`frisco`, pobierany co niedzielę o 03:00 do
`/data/catalog/` i kasowany po przetworzeniu). Obserwacja powstaje tylko przy zmianie ceny. Odczyt tym samym tokenem:

- `GET /api/v1/catalog?since=<data ISO>&source=receipt|frisco|biedronka&history=1` — produkty (`ean`, `name`, `brand`,
  `size`, `size_unit`, `frisco_id`, `lidl_art`) z `observations` (`source`, `store`, `price`, `regular`, `promo_from`,
  `promo_to`, `observed_at`); domyślnie ostatnia obserwacja per źródło, z `history=1` wszystkie.
- `GET /api/v1/shelf?store=` — cache cen półkowych Biedronki (`shelf_prices`, domyślnie sklep główny jak w „Cenach
  półkowych”) w polu `items`: cena, `regular`, okno promocji, `fetched_at`, `stock` i `product` z katalogu po EAN (`null`, gdy EAN spoza katalogu); `absent` to EAN-y „brak w Biedronce” (HTTP 404 w ostatnich 30 dniach).
- `POST /api/v1/shelf` — zlecenie odczytu cen po EAN (E6b.3b): `{"eans": ["5900…"], "store": "<opcjonalnie>"}`, 1–100 EAN-ów
  po 8–13 cyfr (400 przy błędzie). 202 `{accepted, skipped_fresh, skipped_absent}`, odczyt w tle (zapytanie próbne, partie po 20,
  1 s w partii, 10 s między partiami; 429 przerywa). 409 z `reason`: `no_store`, `no_account` albo `busy`.
- `POST /api/v1/catalog/frisco/refresh` — ręczne odświeżenie feedu (409, gdy trwa; 502 przy błędzie pobrania).

## Prywatność

Hasła nie trafiają do add-onu. Tokeny są w `/data/accounts/` (0600), a historia zakupów w `/data/history.db`;
oba wchodzą do kopii zapasowych add-onu — traktuj kopie jak dane poufne (historia zawiera sklepy, godziny
zakupów i płatności, a także oczyszczoną kopię szczegółów paragonów, bez danych karty i kasjera).
