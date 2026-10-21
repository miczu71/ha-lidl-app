# E25 = E12 (a, b, d) + E18 shrinkflation — add-on Lidl Plus

## Context
User zapytał o następny krok roadmapy Lidl (0.21.2 na żywo, brak wyznaczonego etapu). Wybrał połączenie E12
(drobiazgi Produktów) z E18 (shrinkflation). Wywiad 2026-10-21:
- gramatura z nazwy **tylko regex** (bez Jev, bez AI);
- „ten sam produkt” = ten sam kod / połączenie E21 **albo** nowy kod z identyczną nazwą po usunięciu gramatury;
- wynik: **sekcja w zakładce Ceny** („Mniej w opakowaniu”) + cena za kg/l na wykresie produktu; bez powiadomień;
- E12: (a) kg vs szt. po `items.is_weight`, (b) kaucje w czasie na wykresie, (d) liczba zakupów i średnia cena
  przy filtrze produktu; (c) płatności — poza zakresem.

Kto korzysta: domownicy w panelu (Ceny, Produkty). Automatycznie: wyliczenie przy odczycie (cache `History._cached`).
Za zgodą: nic produkcyjnego poza wydaniem. Sukces: na żywo lista shrinkflation z prawdziwymi przypadkami
(albo potwierdzony brak) i pokrycie regexu ≥ ~60% wydatków na produktach niewagowych.

Repo: `/config/addons/ha-lidl-app` (PUBLIC, `main`), kod `lidl/app/src/lidl/`, testy `lidl/app/tests/`.
Kluczowe miejsca: `history.py` (`PRICE_WINDOW_DAYS`, `price_changes/price_overview/product_prices` ~l.1553–1570,
`_resolver` l.833, `ranking` l.1032), `web/products.py` (`ranking_rows`), moduł Cen w `web/` (`TOP_MIN_SPEND`),
`text.py` (`fmt_pln`, plural). Wersja: `lidl/config.yaml` + `pyproject.toml` (test_versions_match).

## Etapy (jedno wydanie 0.22.0 na końcu)
- **E25.0 docs:** skopiować ten plan do `docs/PLAN_E25_gramatura.md`, wpis E25 w `docs/ROADMAP.md` (E12/E18 → E25),
  sekcja **Wykonawca** dla E25.1–E25.3 (pliki, zmiana, `cd lidl/app && uv run pytest`, DONE, NIE RÓB). Commit.
- **E25.1 gramatura (fundament):** czysta funkcja `pack_size(name) -> (ilość_bazowa, 'kg'|'l'|'szt') | None`
  w nowym `lidl/app/src/lidl/packsize.py` (g/kg/ml/l/cl, „2x500g”, „6x1,5l”, przecinek dziesiętny, sklejone
  „500g”); `base_name(name)` = nazwa bez gramatury, znormalizowana. TDD na neutralnych nazwach. Pomiar pokrycia
  na danych demo + na żywo (fetch przez playwright-ha, tylko liczby, bez danych do repo).
- **E25.2 E12(a,d):** Produkty: jednostka kg/szt. zamiast mieszanych „Sztuk”; przy filtrze produktu liczba
  zakupów i średnia cena w zakresie. **E12(b):** kaucje pobrane/zwrócone na wykresie obok wydatków.
- **E25.3 E18:** `History.shrinkflation()` — grupy po kodzie/E21/`base_name`, zmiana gramatury w dół przy
  cenie za szt. ≥ ~poprzedniej → wiersz (stara→nowa gramatura, cena/kg przed/po, data). Sekcja „Mniej w
  opakowaniu” w Cenach + cena za kg/l na wykresie `/ceny/produkt/{kod}`. Wynik w cache `_cached`.
- **E25.4 wydanie:** simplify → code-review (+ second-opinion równolegle, pomiar 3 wydań) → release 0.22.0 →
  weryfikacja na żywo (Ceny, Produkty, Playwright screenshot + console).

Wykonanie E25.1–E25.3: `wt new ha-lidl-app e25` → `sonnet-worker` wg sekcji Wykonawca → claimcheck → `verifier`
→ `wt land`. Po każdym etapie (poza ostatnim) `stage-end`.

## Rollback
Kod bez zmian schematu (liczone przy odczycie) → cofnięcie = poprzednia wersja add-onu (`ha_manage_updates`
z backupem add-onu) albo `git revert`. Brak migracji danych.

## Weryfikacja
- `cd lidl/app && uv run pytest` (obecnie 373+ testów) + mypy (CI).
- Dev: `LIDL_DEV=1 LIDL_DATA_DIR=~/lidl_dev/prices_demo` + Playwright (zakładki Ceny/Produkty, console bez błędów).
- Na żywo po 0.22.0: pokrycie gramatury, liczba przypadków shrinkflation (ręcznie sprawdzić 2–3), jednostki kg/szt.,
  kaucje na wykresie zgodne z 76,00 / 42,70 zł.

## Wykonawca

Wspólne: repo `/config/addons/ha-lidl-app`, test `cd lidl/app && uv run pytest -q`, typy `uv run mypy src`. Dane tylko neutralne
(„Produkt A 500g”). NIE RÓB: commitów, zmian schematu bazy, `lidl/config.yaml`/`pyproject.toml` (wersja), plików poza wymienionymi,
wywołań Jev/AI, nowych zależności.

### E25.1 gramatura
- Pliki: nowy `lidl/app/src/lidl/packsize.py`, nowy `lidl/app/tests/test_packsize.py`.
- Zmiana: `pack_size(name) -> tuple[float, str] | None` (ilość w kg/l/szt; g/kg/ml/cl/l, „2x500g”, „6x1,5l”, przecinek
  dziesiętny, „500g” sklejone, wielkość liter); `base_name(name) -> str` = nazwa bez gramatury, małe litery, spacje zwinięte.
- DONE: testy dla ≥15 form nazw (w tym brak gramatury → None, skróty „Winog.jas.bezp.500g”), pytest i mypy zielone.

### E25.2 E12 (a, b, d)
- Pliki: `lidl/app/src/lidl/history.py` (`SpendBucket`, `spend_series`), `web/chart.py` (`build_chart`, nowy `build_deposit_chart`),
  `web/app.py` (widok `/produkty`, ok. l.400–425), `web/templates/products.html` (miara l.138–139, podsumowanie l.159, wykres l.151–157),
  testy `tests/test_history.py`, `tests/test_chart.py`, `tests/test_web.py` (istniejące pliki; nowe testy obok testów `spend_series`/`build_chart`).
- (a) Jednostka: `SpendBucket.quantity` = TYLKO sztuki (`items.is_weight = 0`); nowe pole `weight: float` (kg, `is_weight = 1`;
  ilość pozycji ważonej to kg — sprawdź w `web/receipts.py` ~l.88). `build_chart(buckets, step, metric, unit="szt.")`: `unit` "szt." → słupki
  z `quantity`, "kg" → z `weight`; sufiks i aria z jednostką. W `app.py`: gdy `query.art_id` i produkt ważony (suma `weight` > 0 w serii) → "kg",
  inaczej "szt."; bez filtra produktu → "szt." (podpis przy sumie: „bez produktów na wagę”). Etykieta radia „Sztuki” → „Ilość” (wartość `sztuki` w URL bez zmian).
- (d) Filtr produktu (`query.art_id`, dowolna miara): w podsumowaniu (l.159) dopisz „{N zakup/zakupy/zakupów}, średnio {X zł} za szt./kg”:
  N = suma `purchases` z serii, X = suma `spend` / suma ilości (ważona), `count_text` + `fmt_pln(…, 2)`; przy ilości 0 pomiń cenę.
- (b) Kaucje w czasie: `SpendBucket` dostaje `charged`, `refunded` (z `tickets.deposit_charged/refunded`, tylko `t.parsed = 1 AND t.detail_version >= PARSER_VERSION`,
  tak jak `purchase_totals`; dodaj w `spend_series` osobne zapytanie po `tickets`, kubełki jak dla pozycji; ZAWSZE liczone dla całego domu —
  przy filtrze produktu zera). `build_deposit_chart(buckets, step) -> Chart | None`: osobny wykres pod głównym, własna oś, w każdej kolumnie dwa wąskie
  słupki (pobrane / zwrócone), `None` gdy wszystkie zera; pokazywany tylko dla miary wydatki bez filtra produktu; z podpisem „Kaucje: pobrane / zwrócone”
  i aria-label obu wartości. Styl: istniejące klasy `bars*`; dodaj minimalny CSS wariantu `bars--pair` w pliku CSS add-onu, bez nowych kolorów poza tokenami.
- Test: `cd lidl/app && UV_LINK_MODE=copy uv run --extra dev pytest -q tests/test_history.py tests/test_chart.py tests/test_web.py`, potem `uv run --extra dev mypy src`.
  (pełny zestaw ~235 s — uruchamiam sam po zakończeniu).
- DONE: testy: (a) produkt ważony w jednym kubełku i sztukowy w innym nie mieszają się, filtr ważonego daje kg; (d) liczba zakupów i średnia cena
  przy filtrze (wartości policzone ręcznie w teście); (b) kaucje w kubełkach, `None` przy zerach, brak przy filtrze produktu; strona `/produkty` renderuje
  się 200 na danych demo; pytest wskazanych plików i mypy zielone. Dane testowe neutralne („Produkt A”).
- NIE RÓB: zmian schematu bazy, innych plików/zakładek (Ceny, Paragony), `config.yaml`/`pyproject.toml`, commitów, nowych zależności, przeformatowania sąsiedniego kodu.

### E25.3 E18 (kontrakt doprecyzowany 2026-10-21)
- Pliki (`lidl/app/src/lidl/`): `history.py`, `web/prices.py`, `web/app.py` (widok `prices` ~l.495 i `product_prices` ~l.534),
  `web/templates/prices.html`, `web/templates/prices_product.html`; testy: `tests/test_history.py`, `tests/test_web.py` (obok testów cen).
- `history.py`: `from lidl.packsize import pack_size, base_name`. Nowy `@dataclass(frozen=True) class Shrink`: `art_id` (kod ostatniego zakupu),
  `name` (z ostatniego zakupu), `unit` ('kg'|'l'|'szt'), `old_pack`, `new_pack` (ilość bazowa), `old_shelf`, `new_shelf` (mediana ceny półkowej serii),
  `day` (str ISO: pierwszy zakup nowej gramatury), `spend` (zapłacono za grupę w 365 dni). Własności `old_unit`/`new_unit` = cena półkowa / ilość
  (zł za kg/l/szt), `pct` = zmiana ceny jednostkowej w %. Moduł-poziomowa `_shrinkflation(rows: list[_PriceRow], today: date) -> list[Shrink]`
  i `History.shrinkflation(today: date | None = None) -> list[Shrink]` przez `self._cached(("shrink", today), ...)` na `self._price_rows()`.
- Algorytm `_shrinkflation`: pomiń wiersze `weight=True`, wiersze po `today` i wiersze bez `pack_size(name)`. Grupy: kody z tą samą niepustą
  `base_name(name)` łączymy (union-find po kodach; kod już jest po moście E21). W grupie (wiersze są po dniu) seria przebiegów (runs) kolejnych
  zakupów o tej samej gramatura+jednostka; cena przebiegu = mediana `price`. Przejście run[i]→run[i+1] liczy się, gdy: ta sama jednostka;
  `0.5 <= new_pack/old_pack < 1`; `new_shelf >= old_shelf` (cena za sztukę nie spadła); gramatura `old_pack` NIE występuje w żadnym zakupie po
  przejściu, a `new_pack` nie występuje przed przejściem (równoległa sprzedaż dwóch rozmiarów to nie shrinkflation); dzień przejścia w ostatnich
  365 dniach. Na grupę najwyżej jedno (najnowsze) przejście. Wynik sortuj po `pct` malejąco, potem nazwie.
- `ProductPrices` dostaje `unit: str | None` i `unit_points: list[PricePoint] | None`: gdy KAŻDY zakup produktu ma `pack_size(name)` w tej samej
  jednostce `kg`/`l` (nie 'szt'), `unit_points` = `PricePoint(day, shelf/pack, paid/qty/pack)` (zaokrąglone do 2 miejsc), inaczej `None`.
  `product_prices` ma do dyspozycji nazwy w `rows` (`r[1]`).
- `web/prices.py`: `shrink_rows(items: list[Shrink], href) -> list[dict]` z kluczami `name`, `href`, `packs` („500 g → 450 g”, ml/g dla <1 l/kg,
  „6 szt. → 5 szt.”), `prices` („{old_unit} → {new_unit}” w zł/kg|l|szt.), `shelf` („6,00 zł → 6,30 zł na półce”), `date` (`fmt_date`), `delta`
  (`delta(pct)`). `product_view` dodaje `unit_chart` (`build_line` schodkowy jak `chart`, etykieta „zł/kg”/„zł/l”, aria) i `unit_label`
  („Cena za kg”/„Cena za litr”) gdy `unit_points`.
- `web/app.py` `prices`: `shrink=shrink_rows(history.shrinkflation(today), lambda a: prices_href(request, a))` dla pełnej strony (nie dla odpowiedzi `ceny-wyniki`).
- Szablony: `prices.html` — sekcja `<section class="card" aria-labelledby="mniej-h">` „Mniej w opakowaniu” (lead: „Ta sama cena albo wyższa, a w opakowaniu
  mniej. Porównanie ceny za kg/l/szt.”) PO sekcji „Wszystkie porównane produkty”, poza `{% if not basket %}` (pokazuj gdy `has_history`); wiersze przez
  `price_row` (macro w `_macros.html` — sprawdź, jakie pola bierze; jeśli nie pasuje, osobna lista `rklist` w tym samym stylu); pusta lista: „Nie znaleźliśmy
  produktów, w których ubyło w opakowaniu.” `prices_product.html` — druga karta „{{ product.unit_label }}” z `product.unit_chart` pod „Cena w czasie”, tylko gdy jest.
- Test: `cd lidl/app && UV_LINK_MODE=copy uv run --extra dev pytest -q tests/test_history.py tests/test_web.py tests/test_chart.py`, potem `uv run --extra dev mypy src`.
- DONE: testy: (1) kod z 500 g → 450 g przy tej samej/wyższej cenie → wiersz z poprawnym `pct` i dniem; (2) ten sam przypadek, ale nowy kod z identyczną
  `base_name` → wiersz; (3) inna nazwa bazowa → brak; (4) cena za sztukę spadła → brak; (5) dwa rozmiary kupowane na przemian → brak; (6) wzrost gramatury → brak;
  (7) produkt ważony → brak; (8) `product_prices.unit_points` dla produktu z gramaturą i `None` bez; (9) `/ceny` zwraca 200 i sekcję „Mniej w opakowaniu”,
  `/ceny/produkt/{kod}` pokazuje kartę ceny za kg przy gramaturze; pytest wskazanych plików i mypy zielone. Dane neutralne („Produkt A 500g”).
- NIE RÓB: zmian schematu bazy, `packsize.py` (tylko import), innych zakładek, `config.yaml`/`pyproject.toml`, commitów, nowych zależności, przeformatowania sąsiedniego kodu, Jev/AI.
