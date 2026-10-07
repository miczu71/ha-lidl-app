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

## Opcje

- **Poziom logów** — debug nie wypisuje tokenów ani kodów logowania.

## Prywatność

Hasła nie trafiają do add-onu. Tokeny są w `/data/accounts/` (0600) i wchodzą do kopii zapasowych add-onu —
traktuj kopie jak dane poufne.
