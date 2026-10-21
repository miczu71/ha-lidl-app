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

### E25.3 E18
- Pliki: `history.py` (`History.shrinkflation()`, cache `_cached`), moduł Cen w `web/`, szablony Cen, testy.
- Zmiana: grupy po kodzie/połączeniu E21/`base_name`; wiersz, gdy gramatura spadła, a cena za sztukę nie spadła; sekcja „Mniej w
  opakowaniu” w Cenach (stara→nowa gramatura, cena za kg/l przed/po, data); cena za kg/l na wykresie `/ceny/produkt/{kod}`.
- DONE: testy (spadek gramatury, ten sam kod, nowy kod z tą samą nazwą bazową, brak fałszywych trafień przy innej nazwie),
  pytest i mypy zielone, sekcja renderuje się na danych demo.
