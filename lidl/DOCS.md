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
dokańcza tylko to, czego brakuje. Potem nowe paragony pobierają się same raz dziennie.

- **Oszczędności** to suma rabatów na pozycjach paragonów (osobno kupony Lidl Plus i promocje) — punkt odniesienia sprzed aktywacji kuponów przez add-on.
- **Wykres** pokazuje wydatki na pozycje (po rabatach, bez kaucji) w wybranym zakresie dat i kroku; można
  zawęzić do jednego produktu albo pokazać sztuki zamiast złotych.
- Produkt to kod artykułu z paragonu. Starsze paragony (sprzed marca 2026) mają inne kody niż nowsze, więc
  łączymy je po nazwie, gdy jednoznacznie pasuje; zmiana kodu przez Lidl tworzy nowy produkt.
- Gdy z jakiegoś paragonu nie da się odczytać pozycji, panel pokazuje ich liczbę.

## Opcje

- **Poziom logów** — debug nie wypisuje tokenów ani kodów logowania.

## Prywatność

Hasła nie trafiają do add-onu. Tokeny są w `/data/accounts/` (0600), a historia zakupów w `/data/history.db`;
oba wchodzą do kopii zapasowych add-onu — traktuj kopie jak dane poufne.
