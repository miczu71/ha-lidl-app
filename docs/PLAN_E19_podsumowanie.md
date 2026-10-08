# E19 Podsumowanie miesiąca („Lidl Wrapped”) — plan

## Cel
Ciekawostka dla przyjemności, w stylu rocznego „Lidl Wrapped”, ale co miesiąc. Nie służy do decyzji;
oszczędności to jedna z liczb, nie oś podsumowania.

## Ustalenia z wywiadu (2026-10-09)
1. Cel: ciekawostka „Wrapped”.
2. Forma: krótki push (2–3 ciekawostki) + strona w panelu z pełnym zestawem i archiwum miesięcy.
3. Push: 1. dnia miesiąca o 10:00 (po imporcie paragonów o `run_time`), `notify.family`, tag `lidl-podsumowanie`,
   tap → strona miesiąca.
4. Strona: nowa zakładka **Miesiące** (`/miesiace`) — ostatni pełny miesiąc, nawigacja po wszystkich miesiącach
   od pierwszego paragonu.
5. Treść (wszystkie cztery grupy):
   - **Liczby miesiąca:** wydatki, wizyty, średni paragon, oszczędności, kaucje; zmiana vs poprzedni miesiąc
     i ten sam miesiąc rok wcześniej.
   - **Produkty:** top produkty (sztuki/zł), nowość miesiąca (pierwszy zakup w historii), największa
     oszczędność na jednym produkcie.
   - **Rekordy i rytm:** największy paragon, ulubiony dzień tygodnia i godzina, najczęstszy sklep, podział kont.
   - **Historia:** suma od początku, „N-ty paragon”, miejsce miesiąca w rankingu wszystkich miesięcy.
6. Założenia (nie zakwestionowane): wspólne dla domu, podział kont jako jeden kafelek; liczone na żywo z bazy
   (bez nowej tabeli); miesiąc bez paragonów → strona „brak zakupów”, push się nie wysyła.
7. Sukces: 1.11 o 10:00 push dociera na oba telefony, tap otwiera październik, suma miesiąca zgadza się
   z listą miesiąca w Paragonach.

## Projekt
- **Dane** (`history.py`, bez zmiany schematu): `month_summary(year, month) -> MonthSummary` na istniejących
  `_products(start, end)`, `purchase_totals(start, end)`, `ticket_months(...)` i połączeniach E21 (`_resolver`);
  czas z `tickets.purchased_at` jest lokalny — bez przeliczania strefy.
- **Push** (`notify.py`, `daily.py`): `compose_month(summary)` + `TAG_MONTH`; `DailyJob.monthly()` uruchamiane
  przez `at_time_loop(time(10, 0), …)` obok `EVENING`, działa tylko 1. dnia miesiąca; klucz `s:<RRRR-MM>`
  w `watched_sent` chroni przed powtórką po restarcie (jak `m:` w E4).
- **Strona** (`web/months.py`, `months.html`, chip w `base.html`): kafelki z linkami do Paragonów (filtr miesiąca)
  i `/paragony/produkt/{kod}`; odmiany i liczby z `text.py`. Styl wg `docs/DESIGN.md`; makieta do akceptacji
  przed kodem strony.

## Podetapy
- **E19.0 docs:** ten plan + wpis w `ROADMAP.md`.
- **E19.1 dane:** `MonthSummary`, `month_summary`, testy (fixtures neutralne).
- **E19.2 strona:** makieta → akceptacja → zakładka `/miesiace` + testy web; weryfikacja w przeglądarce na danych demo.
- **E19.3 push:** `compose_month`, `DailyJob.monthly`, pętla 10:00, klucz `s:`; testy: dzień ≠ 1 → nic, drugi raz → nic.
- **E19.4 wydanie 0.16.0:** simplify, release (bump `config.yaml` i `pyproject.toml`); na żywo: strona
  października/września vs Paragony; push sprawdzony 1.11 (albo jednorazowo wymuszony za zgodą).

Cofnięcie: każdy podetap w osobnych commitach; wydanie cofa się poprzednią wersją add-onu (schemat bazy bez zmian).
