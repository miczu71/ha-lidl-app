# Plan E14 — Którą kartę wziąć, czytelne powiadomienie, reguła kuponów SSC (add-on Lidl Plus 0.6.0)

## Kontekst
0.5.0 (E3 + E13) jest na żywo; 2026-10-07 o 17:09 pierwsza prawdziwa aktywacja: po 5 kuponów na konto
(Osoba 1: Kiwi Gold, Papryka, Sałata rzymska, Włoszczyzna, kupon ogólny; Osoba 2: Brokuły, Buraki, Kiwi Gold, Ogórki
konserwowe, kupon ogólny), po 2 „nie udało się”.

Obserwacje:
1. **Kupony różnią się między kontami:** 34 wspólne, 7 tylko u Osoby 1, 6 tylko u Osoby 2 (Lidl dobiera część kuponów
   per konto). Do tego wspólny kupon bywa aktywny tylko na jednej karcie (np. Osoba 1 aktywowała brokuły sama).
   Na zakupach skanuje się **jedną kartę** — kupony z drugiej przepadają.
2. **Kupony ogólne SSC** („na zakupy za min. 100 zł”, 10/20/30 zł): w API różnią się tylko kwotą
   (`discount.title`), tytuł, ważność i `purchaseType: SSC` takie same, opis pusty. Lidl pozwala aktywować
   **tylko jeden** z grupy — add-on wziął pierwszy (10 zł), 20 i 30 zł skończyły się błędem.
3. Powiadomienie (`notify.family`) jest mało czytelne: długie nazwy z „| luzem”, wszystko w jednej linii na konto.
4. Błąd z weryfikacji 0.5.0: wyszukiwanie na Produktach przeszukuje tylko pierwsze 200 pozycji rankingu
   (`History.ranking(limit=200)`), licznik pokazuje „N z 200”.

## Ograniczenia (z wywiadu 2026-10-07)
1. **Cel:** kto idzie na zakupy, z porannego powiadomienia wie, **którą kartę wziąć**.
2. **Kryterium:** aktywne kupony na produkty z listy „Kupowane regularnie”, ważone częstotliwością zakupów
   (liczba paragonów z produktem w ostatnich 12 miesiącach).
3. **Powiadomienie o `run_time`:** tytuł z rekomendacją („Lidl: weź kartę Osoby 1 (4 kupony na Wasze produkty)”);
   treść: kupony per karta w skrócie (nazwa bez części po „|”, krótki rabat), wspólne w linii „Obie:”, osobno
   „Koniec dziś: …”; dotknięcie otwiera panel Lidl.
4. **SSC:** z grupy kuponów SSC add-on aktywuje ten z **najniższym** rabatem (decyzja użytkownika); gdy jeden
   z grupy jest już aktywny, pozostałych nie próbuje.

Założenia (zaakceptowane):
- Ocena kart liczona w przebiegu z bieżącej listy kuponów konta (kody artykułów są w odpowiedzi API) — bez
  zmian w bazie.
- Aktywnego kuponu nie zamieniamy.
- W tym samym wydaniu poprawka wyszukiwania (pełny ranking, limit tylko na wyświetlanie).
- **Sukces:** o 7:00 (albo po „Sprawdź teraz”) jedno czytelne powiadomienie z rekomendacją karty, dotknięcie
  otwiera panel; z grupy SSC aktywny dokładnie jeden (najniższy) kupon, bez codziennych błędów; wyszukiwanie
  znajduje każdy produkt z zakresu dat.

## Etapy (każdy z checkpointem; przed etapem dokładne kroki i „go”)
- **E14.0 Dokumentacja:** ten plik + wpis w `docs/ROADMAP.md`.
- **E14.1 Poprawka wyszukiwania:** pełny ranking do filtrowania; licznik „N z M” z całości.
- **E14.2 Logika:** ocena kart (aktywne kupony produktowe × częstotliwość zakupów) zwracana z przebiegu;
  reguła SSC (najniższy rabat, pomiń resztę grupy, gdy jeden aktywny); testy.
- **E14.3 Powiadomienie:** nowy format (rekomendacja, skróty nazw i rabatów, „Obie:”, „Koniec dziś”),
  dotknięcie otwiera panel (`data.clickAction`/`url`); testy.
- **E14.4 Wydanie 0.6.0** (skill `release`), weryfikacja na żywo, testowe powiadomienie przez „Sprawdź teraz”.

Cofnięcie: revert commitów / przywrócenie 0.5.0 z kopii Supervisora; `auto_activate: false` zatrzymuje aktywacje.
