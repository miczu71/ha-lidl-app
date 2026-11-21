# Zakupy (ha-lidl-app) — spłata długu z review → wydanie 1.9.1

## Kontekst
Wszystkie etapy roadmapy zakupów są wydane (repo 1.9.0). User wybrał spłatę długu z review, wszystkie 4 grupy,
jedno wydanie 1.9.1 na końcu. Stan sprawdzony dziś na żywo:
- **CI na `main` czerwone od 2026-11-09** (70 z ostatnich 100 przebiegów): pada na `ruff format --check` (1 plik),
  a za nim `pytest -q` bez `--deselect` → 13 czerwonych w `tests/test_leaflet.py` (`runner.step(NOW)` zwraca False;
  `NOW = 2026-10-07` w teście — hipoteza: zależność od prawdziwej daty, do sprawdzenia w D1).
- Ciche porażki w kodzie: `POST /sieci/para` ignoruje wynik `chain_pair_decide` i zły `lidl_art_id` daje 200 bez
  komunikatu (`lidl/app/src/lidl/web/app.py:1256-1282`); `geo.refresh_store_geo_biedronka` przy złej odpowiedzi
  jednego sklepu robi `return` i przerywa cały przebieg (`geo.py:85-91`); ostrzeżenie Shakeomatu w Statusie nie
  znika po późniejszym sukcesie (`web/status.py:267`).
- Luki testów: trasa `_savings_fetched` (`web/app.py:136`), nieudany push z linią Biedronki, filtr `store` w
  `savings_view`, słaba asercja `zero`.
- Wydajność/model: `chains.comparison_view` liczone przy każdym renderze `/sieci`; wiek migawki oszczędności z
  dziennika zamiast `fetched_at`; `store_geo (code PRIMARY KEY)` bez sieci (schemat v14).

Repo: `/config/addons/ha-lidl-app`, gałąź `main`, testy: `cd lidl/app && uv run --extra dev pytest -q`
(+ `ruff check .`, `ruff format --check .`, `mypy src`).

## Etapy (commity; jedno wydanie na końcu)
**D0 docs** — ten plan → `docs/ROADMAP_dlug.md`, wpis w `docs/ROADMAP.md`. Rollback: `git revert`.

**D1 CI zielone** (ja, skill `diagnose`; ryzyko niskie)
1. `ruff format` jednego pliku.
2. Diagnoza 13 testów `test_leaflet.py`: hipoteza → sprawdzenie (np. zamrożona data / `date.today()` w kodzie
   gazetki) → poprawka testu albo kodu (kod tylko gdy to realny błąd produkcyjny).
3. DONE: pełny `pytest -q` bez `--deselect` zielony, ruff/format/mypy czyste, CI na GitHubie zielone po pushu.
   Rollback: `git revert`.

**D2 Ciche porażki** (`haiku-worker` w `wt new`, plan `docs/PLAN_DLUG_D2.md` z sekcją Wykonawca; verifier)
- `/sieci/para`: wynik `chain_pair_decide`/`has_lidl_item`/`is_known_product` → komunikat (`?m=` dla zwykłego
  POST, fragment z komunikatem dla htmx), test trasy dla złego `lidl_art_id` i nieznanej pary.
- Geokodowanie: zła odpowiedź jednego sklepu = pominięcie tego sklepu (log warn), dalej pętla; błąd sieci nadal
  przerywa przebieg (ponowienie jutro). Test: 3 sklepy, środkowy z błędną odpowiedzią → 2 zapisane.
- Status: ostrzeżenie Shakeomatu liczone tylko, gdy po nim nie ma sukcesu. Test.

**D3 Brakujące testy** (`haiku-worker`, plan `docs/PLAN_DLUG_D3.md`, tylko `tests/`; verifier)
- `_savings_fetched` (trasa `/oszczedzanie` z i bez zdarzenia `savings/ok`), nieudany push z linią Biedronki
  (`compose_watched`), filtr `store` w `savings_view`, wzmocnienie asercji `zero`.
- NIE RÓB: zmian w `src/` — test, który wykaże błąd, zgłasza się w raporcie.

**D4 Wydajność i model danych** (ryzyko: migracja → `sonnet-worker`, plan `docs/PLAN_DLUG_D4.md`; verifier)
1. Pomiar `comparison_view` na kopii żywej bazy (czas renderu `/sieci`); cache (jak `savings_breakdown`) tylko
   gdy > ~100 ms — inaczej zapis wyniku i pominięcie.
2. `fetched_at` w migawce oszczędności (zamiast czytania dziennika), `_savings_fetched` z migawki.
3. Migracja v15: `store_geo` z kluczem `(chain, code)` + kopia `.pre-geo-chain`; testy migracji na kopii v14.
   Rollback: przywrócenie `.pre-geo-chain` + poprzednia wersja add-onu.

**D5 Wydanie 1.9.1** (od razu, bez pytania): `simplify` → `code-review` + `silent-failure-hunter` +
`pr-test-analyzer` + security (general-purpose, `git -C … diff v1.9.0..HEAD`) → `release` (bump 1.9.1 w
`lidl/config.yaml`, release non-draft, backup add-onu) → weryfikacja na żywo.

## Weryfikacja
- Każdy etap: pełny pytest (bez `--deselect`), ruff, format, mypy; CI zielone po pushu.
- Na żywo po 1.9.1: wersja w Supervisorze i stopce, start bez ERROR, `/sieci` (zła para → komunikat),
  `/rytm` punkty obu sieci, `/status` bez starego ostrzeżenia Shakeomatu, `/oszczedzanie` z wiekiem migawki,
  konsola przeglądarki czysta, migracja v15 w logu.
