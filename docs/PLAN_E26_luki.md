# E26 Domknięcie luk E25 — add-on Lidl Plus

## Context
Code-review wydania 0.22.0 (E25 gramatura/shrinkflation) zostawił 5 znanych luk, wpisanych do `docs/ROADMAP.md`
jako propozycja E26 (c71a9fc). Wywiad 2026-10-21: user bierze **wszystkie 5**. Decyzje:
- (1) produkt kupowany i na wagę, i na sztuki → **obie średnie osobno**, każda z własnego wydatku; wykres „Ilość”
  w jednostce z większym wydatkiem + dopisek „bez M zakupów na sztuki/na wagę”;
- (2) mnożnik PO gramaturze („100 g x2”, „125g x4”, „1,5l*6”) mnoży ilość i znika z `base_name`;
- (3) shrinkflation: przebieg starej i nowej gramatury **≥2 zakupy każdy**;
- (4) kaucje: „zwrócone” w kolorze `--green` + legenda z kwadracikami; (5) wiersz shrinkflation pokazuje cenę
  półkową („6,00 zł → 6,30 zł na półce”), `Shrink.spend` **usunięte** (nieużywane).

Kto korzysta: domownicy w panelu (Produkty, Ceny). Automatycznie: liczone przy odczycie (cache `_cached`), bez schematu.
Za zgodą: nic poza wydaniem. Sukces: na żywo średnie kg/szt. poprawne dla produktu mieszanego (jeśli istnieje),
wykres kaucji z legendą i dwoma kolorami, wiersz shrinkflation z ceną półkową; testy + mypy zielone.

Repo `/config/addons/ha-lidl-app` (PUBLIC, `main`), kod `lidl/app/src/lidl/`, testy `lidl/app/tests/`.
Wydanie łączone: **0.22.1** na końcu (bez etapu pilnego/ryzykownego).

## Etapy
- **E26.0 docs:** plan → `docs/PLAN_E26_luki.md`, wpis E26 w ROADMAP (propozycja → podetapy), commit.
- **E26.1 gramatura + shrinkflation** (sonnet-worker, worktree `wt new ha-lidl-app e26-1`): (2), (3), (5).
- **E26.2 Produkty: kg+szt. i kaucje** (sonnet-worker, `wt new ha-lidl-app e26-2`): (1), (4).
  Sekwencyjnie po E26.1 (oba dotykają `history.py` i testów — nie rozłączne).
- **E26.3 wydanie:** simplify → code-review + `silent-failure-hunter` + `pr-test-analyzer` + second-opinion
  (pomiar 3 wydań, równolegle) → release 0.22.1 → weryfikacja na żywo.

Każdy etap: claimcheck → `verifier` → `wt land` → pełny zestaw testów; po E26.1 i E26.2 `stage-end`.

## Wykonawca

Wspólne: skill `addon-conventions`; test `cd lidl/app && UV_LINK_MODE=copy uv run --extra dev pytest -q <pliki>`,
typy `uv run --extra dev mypy src`. Dane testowe neutralne („Produkt A 100 g x2”). NIE RÓB: commitów, zmian schematu,
`lidl/config.yaml`/`pyproject.toml`, nowych zależności, Jev/AI, przeformatowania sąsiedniego kodu, plików spoza listy.

### E26.1 (2)(3)(5)
- Pliki: `src/lidl/packsize.py`, `src/lidl/history.py` (`Shrink` ~l.362, `_shrinkflation` ~l.645),
  `src/lidl/web/prices.py` (`shrink_rows` ~l.57), `src/lidl/web/templates/prices.html` (~l.74) lub `_macros.html`
  (`price_row` l.17 — dodać opcjonalną drugą linię bez zmiany wyglądu innych wywołań); testy `tests/test_packsize.py`,
  `tests/test_history.py`, `tests/test_web.py`.
- (2) `_PACK_RE`: opcjonalny mnożnik po jednostce `\s*[x×*]\s*(?P<mult2>\d+)` (bez kolizji z istniejącym prefiksem
  „2x500g”); `pack_size` mnoży przez `mult2`; `base_name` usuwa całość (z mnożnikiem). Nie łapać „x” będącego
  początkiem słowa (np. „500g XXL”).
- (3) w `_shrinkflation`: przejście liczy się tylko gdy `len(old) >= 2 and len(new) >= 2` (stała modułu
  `SHRINK_MIN_RUN = 2`).
- (5) usunąć pole `Shrink.spend` i jego wyliczenie; `shrink_rows` — klucz `shelf` faktycznie renderowany pod `prices`
  (w szablonie), klucz `date` zostaje tylko jeśli używany (dziś data jest już w `prices` — nie dublować).
- DONE: testy `pack_size("Produkt A 100 g x2") == (0.2, "kg")`, „125g x4” → 0.5 kg, „1,5l*6” → 9 l, „500g XXL” → 0.5 kg,
  `base_name` bez mnożnika; shrinkflation: 1 zakup przed albo po → brak wpisu, 2+2 → wpis; `/ceny` pokazuje
  „na półce” w sekcji „Mniej w opakowaniu”; istniejące testy przechodzą (dostosować tylko te, które asertowały `spend`);
  pytest `test_packsize.py test_history.py test_web.py` i mypy zielone.

### E26.2 (1)(4)
- Pliki: `src/lidl/history.py` (`SpendBucket` l.293, `spend_series` l.1605), `src/lidl/web/app.py` (~l.408–419),
  `src/lidl/web/chart.py` (`build_deposit_chart` l.179), `src/lidl/web/templates/products.html` (~l.159–170),
  `src/lidl/web/static/app.css` (`.bars--pair` l.169–171); testy `tests/test_history.py`, `tests/test_chart.py`, `tests/test_web.py`.
- (1) `SpendBucket` nowe pola z domyślnym 0: `weight_spend: float` (wydatek pozycji `is_weight=1`) i
  `weight_purchases: int` (paragony z pozycją ważoną); `piece` = reszta (`spend − weight_spend`, `purchases` liczone
  osobno dla sztuk — dodać `piece_purchases` albo wyliczyć ze zbiorów paragonów; paragon z obiema formami liczy się do obu).
  `app.py` przy `query.art_id`: jednostka wykresu = kg gdy `weight_spend` > wydatek na sztuki, inaczej szt.;
  podsumowanie: „N zakupów, średnio X zł za kg (K na wagę), Y zł za szt. (S na sztuki)” — tylko człony z ilością > 0;
  produkt jednorodny wygląda jak dziś („średnio X zł za kg”). Przy mieszanym i mierze ilość: dopisek „bez M zakupów
  na sztuki/na wagę”. N = liczba różnych paragonów (jak dziś `purchases`).
- (4) CSS: drugi słupek `.bars--pair .bars__bar + .bars__bar` → `background: var(--green)` zamiast `opacity`;
  w `products.html` podpis „Kaucje” + legenda (dwa kwadraciki `aria-hidden` w kolorach słupków + tekst „pobrane”,
  „zwrócone”) w miejscu obecnego `<p class="sum">Kaucje: pobrane / zwrócone</p>`. Tylko tokeny z `:root`.
- DONE: test produktu mieszanego (2 zakupy ważone 1,5 kg za 9 zł, 1 na sztuki 2 szt. za 4 zł → „6,00 zł za kg”,
  „2,00 zł za szt.”, wykres w kg, dopisek „bez 1 zakupu na sztuki”); produkt tylko ważony/tylko sztukowy — tekst jak
  przed zmianą; `/produkty` z kaucjami renderuje legendę; pytest wskazanych plików i mypy zielone.

## Rollback
Bez zmian schematu i migracji → poprzednia wersja add-onu (`ha_manage_updates` z backupem add-onu) albo `git revert`.

## Weryfikacja
- Pełny `uv run --extra dev pytest -q` (429+) i mypy po każdym `wt land`.
- Dev: `LIDL_DEV=1 LIDL_DATA_DIR=~/lidl_dev/prices_demo` + Playwright: Produkty (filtr produktu, kaucje), Ceny
  (sekcja „Mniej w opakowaniu”), console bez błędów; screenshot do `/config/playwright/`.
- Na żywo po 0.22.1 (playwright-ha): kaucje 76,00 / 42,70 zł z legendą i zielonymi słupkami; liczba wpisów
  „Mniej w opakowaniu” (oczekiwane 0 lub mniej niż przed); jeśli istnieje produkt mieszany — obie średnie;
  pokrycie gramatury nie spadło.
