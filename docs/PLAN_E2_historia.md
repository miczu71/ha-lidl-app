# Plan E2 — Historia paragonów (add-on Lidl Plus 0.3.0)

## Kontekst
E1 (logowanie kont, 0.1.0) i D1 (nowy styl, 0.2.0) są zamknięte. Cel add-onu to oszczędność. E2 daje
dwie rzeczy: wiedzę, co kupujemy (ranking), i punkt odniesienia oszczędności sprzed add-onu. Na tym
bazują E3 (kupony dopasowywane po kodzie artykułu) i E5 (cykl zakupów).

Dane ze spike'a (`~/dev/lidl-spike/data/osoba1`):
- 334 paragony z okresu 2019-05 do 2026-10.
- Lista paragonów ma pola `savings`, `couponsUsedCount` i `totalAmount`, więc KPI liczymy bez szczegółów
  paragonów.
- W `htmlPrintedReceipt` każdy artykuł to **2 spany** z tym samym `data-art-id`: linia nazwy i linia
  ilości. Stąd bierze się wymagana deduplikacja.
- Rabaty to spany `class="discount"` z `data-promotion-id`, zawsze po artykule, którego dotyczą.
- Ilość ważona ma przecinek (`0,448`). Brak `data-art-quantity` oznacza 1. Kaucja jest w
  `purchase_summary`, a nie w `purchase_list`.

## Ograniczenia (z wywiadu)
1. **Kto korzysta:** domownicy w panelu add-onu. Ranking i KPI liczymy **dla całego domu**, bez filtra konta.
2. **Pierwszy import ręcznie:** przycisk „Pobierz historię” przy koncie. Działa w tle, ma postęp, ~1 żądanie
   co 2–3 s i można go wznowić. **Potem automatycznie raz dziennie** pobiera tylko `yearOffset=0` i
   szczegóły nowych paragonów.
3. **Grupowanie po kodzie artykułu** (`data-art-id`). Nazwa produktu to ostatnia nazwa z paragonu. Bez AI i
   bez scalania kodów.
4. **Widok po E2:** ekran „Produkty” z rankingiem (liczba zakupów, łączna ilość, ostatnia cena, ostatni zakup,
   średni cykl w dniach) i KPI „dotychczasowe oszczędności” (łącznie + ostatnie 12 miesięcy). Bez listy paragonów.
5. **Sukces:** pełna historia konta osoby 1 zaimportowana na żywo. Liczba paragonów zgadza się z API, suma
   `totalAmount` też. Ranking pokazuje sensowne produkty, a KPI ma wartość. Wiemy też, czy `yearOffset=5`
   obejmuje całą historię.

## Pliki (repo `/config/addons/ha-lidl-app`, gałąź `main`)
- `docs/ROADMAP.md`: E2 rozbite na podetapy, decyzje z wywiadu.
- `docs/PLAN_E2_historia.md`: ten plan, zapisywany jako pierwszy krok.
- `lidl/app/src/lidl/receipt_html.py` (nowy): parser `htmlPrintedReceipt` na stdlib `html.parser`.
  Każdy artykuł jest zapisywany raz, a rabat doklejany do poprzedzającego go artykułu.
- `lidl/app/src/lidl/history.py` (nowy): SQLite `/data/history.db` (stdlib `sqlite3`) z tabelami
  `tickets`, `items` i `sync_state`. Zawiera też zapytania rankingu i KPI.
- `lidl/app/src/lidl/sync.py` (nowy): zadanie importu. Kolejne `yearOffset` aż do HTTP 400, upsert listy,
  potem szczegóły paragonów bez `detail_fetched` z pauzą. Używa `LidlService._api` i `_lock`
  (`service.py:27,54`), dzięki czemu rotacja tokenu idzie jednym torem. Dzienna pętla działa jako
  `asyncio` task w `lifespan` (`web/app.py:57`).
- `lidl/app/src/lidl/web/app.py`, `templates/index.html`, nowy `templates/products.html` i `static/app.css`:
  przycisk importu, postęp, ekran „Produkty” i link w nawigacji.
- `lidl/app/tests/`: `test_receipt_html.py`, `test_history.py`, `test_sync.py` (fałszywe API) i
  `test_web.py`. Fixtures to **syntetyczny** HTML paragonu z neutralnymi nazwami („Sklep X”, „Produkt A”).
- `lidl/config.yaml` (0.3.0), `lidl/CHANGELOG.md`, `lidl/DOCS.md`.
- Bez nowych zależności, bo `sqlite3` i `html.parser` są w stdlib. Obraz musl bez zmian.

## Podetapy (każdy z checkpointem i „go”)
**E2.1 Dane** (bez UI):
1. Zapis planu do `docs/PLAN_E2_historia.md` i aktualizacja `ROADMAP.md`, commit.
2. Parser i baza z testami w TDD. Lokalna walidacja parsera na 5 prawdziwych szczegółach ze spike'a
   (odczyt `~/dev/lidl-spike/data`, nic z tego nie trafia do repo). Sprawdzenie: suma pozycji minus rabaty
   = `totalAmount` minus kaucja.
3. `sync.py` z testami na fałszywym API: wznawianie po przerwaniu, brak duplikatów przy drugim przebiegu,
   tryb dzienny tylko offset 0.
4. `ruff`, `mypy` i `pytest` lokalnie, hook pre-commit, commit. Bez wydania.

**E2.2 UI:**
1. Makieta ekranu „Produkty” (telefon i PC) dopisana do artefaktu makiet D1
   (QZrsn5Vf3MXYcoDxQnGCvS) przez skill `impeccable`. Akceptacja przez użytkownika.
2. Implementacja szablonów i tras oraz weryfikacja lokalna w trybie dev (`LIDL_DEV=1`, dane testowe)
   przez Playwright: screenshot i konsola, desktop i telefon. Cache-busting `?v=`.

**E2.3 Wydanie i import na żywo:**
1. Skill `release`: 0.3.0, opublikowany release, aktualizacja przez Supervisora.
2. Użytkownik klika „Pobierz historię” dla osoby 1 (~334 paragony × ~2,5 s ≈ 15 min). Sprawdzam logi
   (`ha_get_logs`) i panel.
3. Weryfikacja: liczba paragonów i suma kwot zgodne z listą ze spike'a, najstarsza data (odpowiedź na
   pytanie o `yearOffset`), screenshot rankingu. Wnioski trafiają do `ROADMAP.md`.

## Ryzyka
- Blokada konta za zbyt częste żądania. Ograniczenie: pauza, import sekwencyjny, przerwanie przy HTTP 429
  lub 5xx z zapisem miejsca.
- Rotacja tokenu w długim imporcie: każde żądanie przez `_lock` konta.
- Baza `/data/history.db` wchodzi do backupu add-onu, bo zawiera dane zakupowe.
- Inne formaty paragonów (zwroty, faktury, `ticketType` inny niż HTML): parser je pomija i liczy w logu,
  zamiast przerywać import.

## Jak cofnąć
`git revert` commitów E2. Powrót do wersji 0.2.0 add-onu przez kolejny release (Supervisor nie robi
downgrade sam). Usunięcie `/data/history.db` nie rusza tokenów w `/data/accounts/`.

## Weryfikacja end-to-end
- `cd lidl/app && uv run pytest && uv run ruff check && uv run mypy src`, zielone CI.
- Playwright na panelu HA (`playwright-ha`): ekran Produkty, brak błędów konsoli, znacznik 0.3.0 w stopce.
- Liczby z bazy porównane ze spike'iem (334 paragony, suma `savings`).
