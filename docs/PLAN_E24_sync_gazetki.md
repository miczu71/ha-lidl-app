# E24 — Lidl: paragony co godzinę + naprawa gazetek

## Kontekst

Add-on `ha-lidl-app` (klon `/config/addons/ha-lidl-app`, wersja na żywo 0.20.0, slug `f0987e0f_lidl`).

**Sync paragonów** działa dziś tylko raz dziennie, w porannym przebiegu (`run_time` 07:00, `daily.py` → `HistorySync.run_daily`).
User chce, żeby paragon był widoczny w panelu i w Budżecie do godziny po zakupach.

**Gazetki — diagnoza na żywo (2026-10-14):**
- Od restartu freellmapi (~13 h) modele wizyjne zadziałały **1 raz na 73 próby**. Gemma-4-31b dostaje od Google
  błąd 500 „Internal error”, Gemini 3.5/3.6 błąd 503 „high demand”, a Gemini 3.7 ma wyczerpany limit (429).
- Add-on wysyła zapytania do **nazwanych** modeli Google (`DEFAULT_VISION_MODELS` w `settings.py`, opcja
  `llm_vision_models`). Nie korzysta więc z łańcucha `auto:vision` we freellmapi (8 modeli, w tym ministral-14b
  od Mistrala, który w testach freellmapi najlepiej radził sobie z obrazami; zob. `~/docs/ROADMAP-freellmapi.md`, Etap 4).
- Paczka 12 bieżącej gazetki została porzucona po 30 próbach (`MAX_ATTEMPTS`, status `failed`) i już nie wraca.
  Paczka 15 przeszła dopiero za 15. razem. Jedyny sukces miał tylko ok. 4,8 tys. tokenów wejścia, więc możliwe,
  że błędy 500 zależą od rozmiaru zapytania.

**Decyzje usera (wywiad):**
1. Sync co godzinę obejmuje **tylko paragony**: bez kuponów i bez powiadomień. Poranny przebieg 07:00 zostaje bez zmian.
2. Godziny 7–23, pn–sob, plus **niedziele handlowe wyliczane z ustawy**. Pozostałe niedziele bez syncu.
3. Gazetki: (a) modele spoza Google przez `auto:vision`, po teście jakości; (b) porzucone paczki wracają do kolejki,
   dopóki gazetka trwa; (c) mniejsze paczki, jeśli pomiar to uzasadni.

**Kto korzysta / co automatycznie / co za zgodą / sukces:**
- Korzystają: domownicy (panel Lidl, Budżet Domowy przez `/share/lidl/receipts.json`).
- Automatycznie: sync paragonów co godzinę w godzinach sklepów, ponawianie paczek gazetki.
- Za zgodą usera: zmiana opcji `llm_vision_models` na żywo (robi user w UI add-onu, bo opcje zawierają `llm_key`).
- Sukces: paragon w panelu najpóźniej godzinę po zakupie; gazetka przetworzona w całości (0 porzuconych paczek)
  w ciągu doby od pojawienia się; w logu freellmapi przewaga `ok` nad `fail` dla zapytań gazetki.

## Etapy (jedno wydanie 0.21.0 na końcu; gazetki pierwsze, bo są zepsute teraz)

### E24.0 — dokumentacja
- Skopiować ten plan do `docs/PLAN_E24_sync_gazetki.md`, dopisać E24 do `docs/ROADMAP.md` (status, kroki, rollback). Commit lokalny.

### E24.1 — pomiar modeli wizyjnych (bez zmian w kodzie add-onu)
- Uruchomić `~/dev/lidl-spike/probe_leaflet_ai.py` + `score_leaflet_ai.py` (dane wzorcowe `data/e4/truth.json`,
  `e11.json`, strony gazetki 08.10) przez `secret-run freellmapi -- …`, z wyjściem ograniczonym do wyników.
  Przed uruchomieniem sprawdzić, że skrypt nie wypisuje klucza.
- Macierz: model `auto:vision` i `ministral-14b-2512` × paczki po 5 / 2 / 1 stronie. Mierzyć trafność (gemini miał
  8/10), odsetek błędów i czas.
- Bramka: jeśli `auto:vision` (albo ministral) daje ≥ 7/10 i większość odpowiedzi OK → idziemy dalej z najlepszym
  wariantem. Jeśli nie → stop i pytanie do usera (wynik podważa założenie (a)).

### E24.2 — gazetki: kolejka modeli, rozmiar paczki, porzucone wracają (TDD, `tests/test_leaflet.py`, `test_history.py`)
- `settings.py`: `DEFAULT_VISION_MODELS` ustawić wg E24.1 (np. `("auto:vision",)`); to samo w `config.yaml` → `options.llm_vision_models`.
- `leaflet.py`: `BATCH` ustawić wg E24.1 (zmienia tylko nowe gazetki; bieżąca ma paczki zapisane w bazie).
  Jeśli mniejsze paczki zwiększą liczbę zapytań, sprawdzić `PAUSE` (120 s) względem limitów łańcucha.
- Porzucone wracają:
  - `LeafletRunner._retry`: po `MAX_ATTEMPTS` status `failed` + `next_try` = jutro 06:00 + wpis `warn` w dzienniku
    „odłożona do jutra” (zamiast porzucenia na zawsze).
  - Nowe `History.revive_leaflet_batches(now)`: `failed` z `end >= dziś` i `next_try <= now` → `pending`,
    `attempts = 0`. Wywoływane w `LeafletRunner.step()` przy sprawdzaniu nowych gazetek (co `IDLE`). Ratuje też
    paczkę 12 bieżącej gazetki zaraz po wydaniu.
  - `next_leaflet_batch` i `has_pending_leaflet`: tylko `end >= dziś`, bo paczki zakończonej gazetki nie mają sensu.
  - Zakładka Status (`web/status.py`) dalej pokazuje `failed` jako problem, dopóki paczka czeka na jutro.
- Testy: odłożenie po 30 próbach, wskrzeszenie następnego dnia, pomijanie gazetek po terminie.

### E24.3 — paragony co godzinę (TDD, `tests/test_shopdays.py`, `test_sync.py`, `test_daily.py`)
- Nowy moduł `lidl/shopdays.py`:
  - `easter(year)` (algorytm Gaussa/Meeusa),
  - `is_trading_sunday(d)`: ostatnia niedziela stycznia, kwietnia, czerwca i sierpnia, niedziela przed Wielkanocą
    oraz trzy niedziele przed 25 grudnia (od 2025). **Przed kodem zweryfikować aktualne brzmienie ustawy** (WebSearch).
  - `is_shopping_day(d)`: pn–sob albo niedziela handlowa.
  - Test z datami 2026: 25.01, 29.03, 26.04, 28.06, 30.08, 6/13/20.12. Daty 2027: 31.01, 21.03, 25.04, 27.06,
    29.08, 5/12/19.12. Zwykła niedziela → False.
- `sync.py`: `HistorySync.run_hourly(slugs) -> int`: import `full=False` kont z historią, z pominięciem kont, które już się
  synchronizują. Hook `after` (plik Budżetu + kategorie AI) i `history.warm()` tylko, gdy przyszły nowe paragony.
  `import_account(..., quiet=True)` zapisuje wpis w dzienniku tylko przy nowych paragonach albo błędzie.
  Bez tego oś czasu Statusu miałaby ok. 32 puste wpisy dziennie.
- `daily.py`: `SYNC_HOURS = range(7, 24)` i pętla `hourly_loop(job)` o pełnej godzinie. Pomija godzinę `run_time`
  (wtedy działa poranny przebieg), dni niehandlowe i chwile, gdy `job.in_progress`. Błąd jednego przebiegu nie
  zatrzymuje pętli (wzorzec z `at_time_loop`).
- `web/app.py`: dodać `asyncio.create_task(hourly_loop(...))` obok `at_time_loop` (linie ~148–152).
- Do decyzji później, poza zakresem: święta w dni robocze (sklepy zamknięte, sync i tak pusty, koszt pomijalny).

### E24.4 — wydanie 0.21.0
- `simplify` → `code-review` → skill `release` (bump `config.yaml` + `pyproject.toml`, CHANGELOG, opublikowane wydanie).
- **Krok usera:** opcja `llm_vision_models` w UI add-onu → wartość z E24.1, bo zapisana lista nadpisuje nową wartość domyślną.
- Weryfikacja na żywo (niżej), aktualizacja ROADMAP + notatki pamięci `project_lidl_addon`.

## Weryfikacja
- `uv run pytest` + `mypy` + `ruff` w `lidl/app` (CI musi być zielone).
- Na żywo (`ha_get_logs source=supervisor slug=f0987e0f_lidl`):
  - o pełnych godzinach wpisy `Import konta …`; paragon z zakupów widoczny w Paragonach w ciągu godziny;
  - `Gazetka …/12 (…): N trafień` po wskrzeszeniu; w `docker logs freellmapi` więcej `ok` niż `fail` dla gazetki;
  - zakładka Status (playwright-ha): Gazetka bez porzuconych paczek, oś czasu bez zalewu pustych wpisów sync.

## Rollback
- Kod: wydanie 0.21.1 z `git revert` commitów E24 (bez force-push), aktualizacja przez Supervisor.
- Opcja: user przywraca listę `gemini-3.5-flash, gemini-3.6-flash, gemini-3.7-flash, gemma-4-31b-it`.
- Baza: bez zmiany schematu (tylko UPDATE statusów paczek), więc cofnięcie nie wymaga migracji.

## Wynik E24.1 (2026-10-14) i decyzja

Wzorzec E4.2 (20 stron, 10 pewnych trafień), skrypt `~/dev/lidl-spike/probe_leaflet_ai.py` (`LEAFLET_BATCH`).

| Model | paczka | pewne /10 | fałszywe | błędy zapytań |
|---|---|---|---|---|
| Gemini 3.5 (E4.2) | 1 strona | 8 | 0 | — |
| `auto:vision` | 5 / 2 / 1 | 3 / 5 / 7 | 0 / 11 / 48 | 502: 3/4, 2/10, 1/20; 209–313 s |
| `ministral-14b-2512` | 5 / 2 / 1 | 5 / 5 / 8 | 15 / 14 / 50 | brak (przy 1 stronie 2× 429); 65–133 s |

Bramka z planu (≥ 7/10) niewystarczająca: precyzja jest równie ważna (fałszywa promocja trafia do powiadomienia).
Mniejsze paczki odpadają (1 strona = 75–100 zapytań na gazetkę wobec limitu Gemini 20 RPD).
**Decyzja usera:** mix — modele Google z ponawianiem, po `FALLBACK_AFTER` = 3 nieudanych rundach dochodzi Mistral
(`llm_fallback_models`), jego oferty przechodzą filtr (rabat + wspólny początek słowa z nazwą produktu).
Filtr sprawdzony offline na zapisanych wynikach: Mistral paczka 5: 15 → 5 fałszywych przy 5/10 pewnych (po odrzuceniu
kuponów Lidl Plus i ofert bez rabatu realnie 2–3).
Pytanie usera o lokalny model na RTX 2070 Super 8 GB: odpowiedź z wiedzy ogólnej, niemierzona — nie wchodzi do E24.
