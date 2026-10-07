# Lidl Plus

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
dokańcza tylko to, czego brakuje. Potem nowe paragony pobierają się same raz dziennie (o godzinie z opcji
**Godzina dziennego przebiegu**, domyślnie 7:00).

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
(sekcje „wszystkie sklepy” i „Twój sklep”) i aktywuje:

- **kupony ogólne** (np. rabat od kwoty zakupów); z kuponów „Twój sklep” różniących się tylko kwotą (np. 10/20/30 zł
  na zakupy od 100 zł) Lidl pozwala aktywować jeden — add-on bierze ten z najniższą kwotą,
- **kupony na produkty kupowane regularnie** — co najmniej 3 razy w ostatnich 12 miesiącach, na wszystkich kontach
  razem (lista „Kupowane regularnie”; domyślnie zaznaczone są wszystkie, odznacz to, czego nie chcesz).

Kupony, które jeszcze nie obowiązują, aktywuje w dniu ich startu; kuponów już aktywnych nie rusza.

**Którą kartę wziąć:** kupony różnią się między kontami, a przy kasie skanuje się jedną kartę. Rano add-on wysyła
na `notify.family` jedno powiadomienie (gdy któraś karta ma aktywne kupony na Wasze produkty): w tytule karta z lepszą
oceną (aktywne kupony na produkty z listy, ważone tym, jak często je kupujecie), w treści kupony każdej karty w skrócie,
wspólne w linii „Obie:” i te, które kończą się dziś. Dotknięcie otwiera panel; nowe powiadomienie zastępuje poprzednie.

Zakładka pokazuje
kupony tego tygodnia na każdym koncie ze statusem; resztę aktywujesz przyciskiem **Aktywuj**, a **Sprawdź teraz**
uruchamia sprawdzenie od razu. Pole **Szukaj** filtruje kupony i listę produktów w trakcie pisania.

**Tryb próbny:** dopóki opcja **Automatyczna aktywacja kuponów** jest wyłączona (domyślnie), add-on niczego nie
aktywuje — panel i powiadomienie pokazują tylko, co zostałoby aktywowane.

Produkt oznaczony „bez kodu kuponu” znamy tylko ze starszych paragonów, bez numeru artykułu, którym posługują się
kupony — do niego kuponu nie dopasujemy.

## Opcje

- **Poziom logów** — debug nie wypisuje tokenów ani kodów logowania.
- **Automatyczna aktywacja kuponów** — wyłączona = tryb próbny (patrz wyżej).
- **Godzina dziennego przebiegu** — GG:MM, czas lokalny; paragony, kupony i powiadomienie.

Add-on ma uprawnienie do API Home Assistanta (`homeassistant_api`) wyłącznie po to, żeby wysłać powiadomienie
przez `notify.family`.

## Prywatność

Hasła nie trafiają do add-onu. Tokeny są w `/data/accounts/` (0600), a historia zakupów w `/data/history.db`;
oba wchodzą do kopii zapasowych add-onu — traktuj kopie jak dane poufne (historia zawiera sklepy, godziny
zakupów i płatności, a także oczyszczoną kopię szczegółów paragonów, bez danych karty i kasjera).
