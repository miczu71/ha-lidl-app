# Plan E3 — Automatyczna aktywacja kuponów (add-on Lidl Plus 0.5.0)

## Kontekst
E11 (0.4.0) dało listę produktów kupowanych regularnie z przełącznikiem „auto-aktywacja” i API
`History.auto_activate_codes()`. Na żywo (2026-10-07): 206 kandydatów, 187 włączonych, 19 bez kodu kuponu;
próg 3 zakupy / 12 miesięcy zostaje. E3 to właściwy cel add-onu: **nie przegapić kuponów na to, co i tak
kupujemy** — aktywować je automatycznie na każdym koncie domu i powiadomić o tym.

Klient API ma już `promotions_list()` (`/v4/promotionslist`) i `activate_promotion()`
(`POST /v2/promotions/{id}/activation`); aktywacja nie była testowana na żywo.

Próbka ze spike'a (jedno konto, tydzień 4–10.10): 90 kuponów w sekcjach SSC 3, AllStores 36, OtherStores 40,
OnlineShop 11; 79 z `articleIds` (zwykle 1 kod, czasem cała kategoria: 114, 203 kody); 11 ogólnych
(np. „10 zł rabatu” od kwoty zakupów); ważność tygodniowa (`validity.start`/`end`), pole `isActivated`.

## Ograniczenia (z wywiadu 2026-10-07)
1. **Sekcje:** tylko `AllStores` i `SSC`. Pomijamy `OtherStores` i `OnlineShop`.
2. **Dopasowanie:** kupon produktowy jest aktywowany, gdy którykolwiek kod z `articleIds` jest w
   `auto_activate_codes()`. **Kupony ogólne** (bez `articleIds`) aktywujemy zawsze.
3. **Pora:** raz dziennie o stałej godzinie (opcja add-onu `run_time`, domyślnie `07:00`, czas lokalny),
   niezależnie od restartów; plus przycisk „Sprawdź teraz” w panelu. Ten sam przebieg pobiera paragony.
4. **Powiadomienie:** jedno na `notify.family`, tylko gdy coś nowego aktywowano; oba konta w jednej
   wiadomości, **przy każdym kuponie data ważności**. Bez nowych — cisza.
5. **Panel (zakładka Kupony):** bieżące kupony per konto ze statusem (aktywowany automatycznie / już aktywny /
   do aktywacji) i przyciskiem „Aktywuj” przy pozostałych; „Sprawdź teraz”.
6. **Wdrożenie ostrożne:** test aktywacji 1 kuponu → wydanie w **trybie próbnym** (opcja `auto_activate`
   domyślnie wyłączona: panel i powiadomienie pokazują, co *byłoby* aktywowane) → użytkownik włącza opcję.

Założenia (zaakceptowane):
- Kuponu już aktywnego (`isActivated`, np. ręcznie w aplikacji) nie ruszamy i nie umieszczamy w powiadomieniu.
- Kupon kategorii (wiele kodów) aktywujemy, gdy trafi choć jeden nasz produkt.
- Powiadomienia wymagają uprawnienia `homeassistant_api: true` (wywołanie `notify.family` przez API Core
  z `SUPERVISOR_TOKEN`).
- Między aktywacjami przerwa kilku sekund jak przy paragonach (ryzyko blokady konta).
- **Sukces:** dzienny przebieg aktywuje pasujące kupony na obu kontach (widoczne jako aktywne w aplikacji
  Lidl Plus), rano przychodzi jedno powiadomienie z listą i datami ważności, a bez włączonej opcji nic się
  nie aktywuje.

## Etapy (każdy z checkpointem; przed etapem dokładne kroki i „go”)
- **E3.0 Dokumentacja:** ten plik + wpis w `docs/ROADMAP.md`.
- **E3.1 Test aktywacji:** skrypt w `~/dev/lidl-spike` aktywuje jeden wybrany kupon na jednym koncie;
  uruchamia użytkownik (`! secret-run …`), potwierdzenie w aplikacji. Bez zmian w add-onie. Wynik (odpowiedź
  API, czy `isActivated` się zmienia, ewentualne limity) zapisujemy tu, zanim powstanie kod.
- **E3.2 Dane i logika:** pobieranie kuponów do tabeli `coupons` (konto, id, tytuł, rabat, ważność, kody,
  `isActivated`, kto aktywował, kiedy), dopasowanie i decyzja (aktywuj / pomiń / próbnie), opcja
  `auto_activate` (domyślnie `false`); testy na neutralnych danych.
- **E3.3 Harmonogram i powiadomienie:** dzienny przebieg o `run_time` (paragony + kupony), wiadomość na
  `notify.family` przez API Core (`homeassistant_api: true`), tylko o nowych aktywacjach, z datami ważności.
- **E3.4 Panel:** sekcja bieżących kuponów per konto w zakładce Kupony, „Aktywuj”, „Sprawdź teraz”;
  skill `impeccable`, weryfikacja w przeglądarce (komputer i telefon).
- **E3.5 Wydanie 0.5.0 w trybie próbnym** (skill `release`), weryfikacja na żywo; włączenie
  `auto_activate` przez użytkownika; po pierwszym prawdziwym przebiegu sprawdzenie w aplikacji Lidl Plus.

Cofnięcie: opcja `auto_activate` = `false` zatrzymuje aktywacje bez wydania; kod — revert; tabela `coupons`
jest addytywna.

## Wyniki E3.1 (test aktywacji, 2026-10-07, konto osoby 1)
- **Aktywacja działa w dwóch krokach.** Kupon z listy ma `id` wspólne (często równe `promotionId`). Pierwszy
  `POST /v2/promotions/{id}/activation` zwraca błąd (412 lub 499), ale tworzy **egzemplarz kuponu konta** —
  na liście ten sam `promotionId` ma odtąd nowe `id` (format `01a1…`). `POST` z nowym `id` kończy się sukcesem
  (pusta odpowiedź) i `isActivated` zmienia się od razu (`isProcessing` = false). Kupony z `id` w formacie `01a1…`
  (egzemplarz już istnieje) prawdopodobnie aktywują się za pierwszym razem.
- **Kupony nadchodzące:** lista zawiera kupony, które jeszcze nie obowiązują (11 z ~40 w AllStores+SSC);
  aktywacja zwraca 412 z `errors: ["UserPromotionStartValidityDateIsGreaterThanToday"]`. Aktywujemy tylko kupony
  z `validity.start` ≤ teraz; nadchodzące łapie dzienny przebieg w dniu startu (start zwykle o 00:00 czasu PL,
  więc przebieg o 07:00 je obejmie).
- Treść błędu jest w ciele odpowiedzi (`{"isSuccess":false,"errorType":"PreconditionFailed","errors":[…]}`) —
  klient add-onu ma ją logować (bez tokenów), żeby rozpoznawać przyczyny.
- Algorytm dla E3.2: `POST` po `id`; przy błędzie pobrać listę ponownie, znaleźć kupon po `promotionId` i, gdy ma
  nowe `id`, ponowić `POST` raz. Pomijać kupony nadchodzące i `isActivated`.
- SSC ma 3 kupony ogólne „na zakupy za min. 100 zł” (10/20/30 zł rabatu) — nie testowane; do sprawdzenia, czy
  aktywacja jednego blokuje pozostałe.

## Ryzyka
- Regulamin Lidla / blokada konta przy zbyt wielu żądaniach — przerwy, raz dziennie, tryb próbny na start.
- Nieznane zachowanie API aktywacji (limity, błędy, kupony „isProcessing”) — rozpoznanie w E3.1.
- Rotacja refresh tokenu przy dwóch klientach (add-on i skrypt spike'a) — skrypt używa osobnej sesji.
- Uprawnienie `homeassistant_api` poszerza dostęp add-onu — używamy go tylko do `notify.family`.
