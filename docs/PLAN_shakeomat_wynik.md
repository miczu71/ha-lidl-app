# Shakeomat Biedronki w „Zakupach” (ha-lidl-app 1.6.1): fałszywy błąd 409 + niewidoczny wynik

## Context (sprawdzone na żywo, `/data/history.db` w `app_f0987e0f_lidl`)

```
17:46:48 ok    Shakeomat Biedronki: odsłonięto 1 z 1      (konto-B, przycisk „Odsłoń teraz”)
17:46:48 ok    migawka odświeżona                          (refresh() w shake(), PRZED przekierowaniem)
17:46:56 error Shakeomat Biedronki: odsłonięto 0 z 2 (LidlPlusError: http_409; http_409)
```
Migawka po odsłonięciu: oferta „Śmiejżelki Nimm 2” (WELCOME, `from_shakeomat=False`) + 2 kafelki Shakeomatu:
`SHAKEOMAT_2` z `available_from 16:47:48Z` (60 s po odsłonięciu → drugi Shakeomat jeszcze zablokowany) i `SHAKEOMAT`
bez dat (już odsłonięty). **Wylosowanej oferty nie ma w migawce.**

Problemy:
1. **Wynik niewidoczny (zgłoszenie usera):** `shake()` (`chain_savings.py:236`) odrzuca odpowiedź PATCH
   `reveal-and-activate`, a jedyne miejsce z wynikiem to właśnie ona (albo `GET promos/shakeomats/` z `result.message`).
   Komunikat `shake_ok` („Nowe oferty widać niżej po odświeżeniu migawki”) obiecuje coś, czego strona nie pokaże.
2. **Fałszywy błąd:** selekcja tylko po typie + `valid_to`; ignoruje `available_from` i stan „odsłonięty” →
   przycisk zostaje, drugie kliknięcie → 409 → „Uwaga” w Statusie i `shake_err`.

## Plan (repo `/config/addons/ha-lidl-app`, `main`, TDD, `addon-conventions`)

1. **Sonda (tylko odczyt, GET):** jednorazowy skrypt w kontenerze przez `service.chain_api("konto-B")`:
   `GET promos/shakeomats/` i karuzela, wypisane tylko pola pozycji Shakeomatu (`meta`, `result`, daty, flagi stanu),
   bez tokenów. Cel: kształt wyniku losowania + pole „odsłonięty”. Kształt odpowiedzi PATCH ustalę przy najbliższym
   odsłonięciu (drugi Shakeomat jest dostępny od 17:47:48, aplikacja/przycisk). Do tego czasu kod loguje treść ciała
   na DEBUG, a wynik pokazuje z `promos/shakeomats/`. Fixture z tego kształtu, bez danych osobowych.
2. **Wynik na stronie od razu:**
   - `reveal_and_activate` → parsuj odpowiedź (nazwa, cena/rabat, ważność); `ShakeResult.revealed: list[...]`;
     zapis jako wiersz migawki `kind="shakeomat_result"` (przetrwa odświeżenie strony do końca ważności).
   - Przycisk „Odsłoń teraz” przez htmx (`hx-post`, wzorzec z `_coupons_row.html`): odpowiedź podmienia kartę
     Shakeomatu na kartę wyniku („Wylosowano: X, −NN%, aktywne do 22:59”), bez przeładowania strony.
     Bez JS: dotychczasowy POST→redirect, karta wyniku z migawki.
   - Komunikat `shake_ok` przepisany: bez „po odświeżeniu migawki”.
3. **Fałszywy błąd:** pomijaj pozycje z `available_from` w przyszłości i już odsłonięte; HTTP 409 = „jeszcze/już
   niedostępny” (`skipped`), zdarzenie `ok`, bez „Uwagi”.
   **Przycisk nieaktywny z terminem:** gdy jedyny kafelek ma `available_from` w przyszłości → `<button disabled>`
   z podpisem „Następny Shakeomat od HH:MM” (czas lokalny), a dla < 1 h odliczanie „za 0:42”. Mały skrypt
   (`data-ready-at` = ISO UTC) odblokowuje przycisk o czasie, a htmx (`hx-get` karty) pobiera świeży stan.
   Bez JS: przycisk wyłączony i godzina w tekście. Gdy kafelek jest tylko odsłonięty, a następnego nie ma: zamiast
   przycisku „Dzisiejszy Shakeomat już odsłonięty” + karta wyniku. Serwer i tak pomija przedwczesne pozycje (pkt wyżej). Poranny auto-Shakeomat używa tej samej selekcji, a push z wynikiem zawiera nazwę oferty.
4. Testy: `cd lidl/app && uv run pytest -q tests/test_chain_savings.py tests/test_bdr_savings.py tests/test_status.py tests/test_bdr_push.py`, potem cały zestaw.
5. `simplify` → commit → `code-review` + `silent-failure-hunter` + `pr-test-analyzer` → `release` 1.6.2 → na żywo:
   karta wyniku po kliknięciu, Status bez „Uwagi”.

Rollback: `git revert` + 1.6.1 w Supervisorze; nowy `kind` w istniejącej tabeli, bez migracji schematu.

## Weryfikacja
- testy zielone; na żywo: kliknięcie → karta wyniku bez przeładowania; ponowne wejście → wynik nadal widoczny;
- kliknięcie przed `available_from` niemożliwe (brak przycisku, „Następny od …”); brak `http_409` w `events`.
