# PLAN E23 — zakładka „Status”

## Context
Dziś stan techniczny add-onu widać tylko w logu (po każdym etapie „do sprawdzenia: log 07:00”). Postęp importu
(`SyncProgress`) i `DailyJob.last_check` żyją w pamięci, AI (gazetka E4, kategorie E6) nie ma liczników, trwale
zapisany jest tylko postęp gazetki (`leaflet_batches`). Cel (wywiad 2026-10-12): **zastąpić czytanie logów** —
jedna strona z bieżącym stanem i historią 30 dni, plus sygnał, gdy coś wymaga uwagi.

## Ustalenia z wywiadu
- Korzysta: Osoba 1 (technicznie); Osoba 2 nie dostaje alertów.
- Zakres: przebiegi zaplanowane (07:00 krok po kroku, 18:00, 1. dnia, powiadomienia), import paragonów (postęp
  na żywo + wyniki), gazetki i AI (paczki, zapytania per model, limity, kategorie E6), system i konta (wersja,
  uptime, sesje, baza, plik Budżetu, zadania w tle).
- Historia: tabela zdarzeń, 30 dni (sprzątanie w porannym przebiegu).
- Automatycznie: kropka na chipie „Status”, gdy jest problem + push do usługi z nowej opcji `alert_notify` (puste w repo, wpisuje użytkownik; puste = tylko kropka)
  raz na problem (ponownie po powrocie do normy) przy: wygasłej sesji konta, nieudanym/pominiętym porannym przebiegu, odrzuconym kluczu AI,
  porzuconej paczce gazetki. Strona tylko do podglądu (bez przycisków; przy problemie link, np. do Kont).
- Układ: kafle-światła per obszar → sekcje rozwijane → wspólna oś czasu z filtrem obszaru.
- Sukces: przez tydzień nie muszę czytać logu, żeby wiedzieć, czy 07:00/gazetka/AI przeszły.

## Repo / gałąź
`/config/addons/ha-lidl-app` (miczu71/ha-lidl-app), `main`. Jedno wydanie na koniec: **0.20.0**.

## Etapy (zapisane w `docs/ROADMAP.md` + `docs/PLAN_E23_status.md` jako pierwszy krok)

**E23.0 Plan w repo** — wpis E23 w ROADMAP, `docs/PLAN_E23_status.md` (ten plan). Commit docs.

**E23.1 Dziennik zdarzeń (TDD)** — `src/lidl/history.py`:
- tabela `events (ts, area, kind, level ok|warn|error, summary, detail JSON, duration_ms)` + indeks `(area, ts)`,
  `CREATE TABLE IF NOT EXISTS` bez bumpu schematu (jak `watched` w E15); `log_event()`, `events(since, area)`,
  `prune_events(30 dni)`.
- Instrumentacja (tylko zapis, zachowanie bez zmian):
  - `daily.py` `DailyJob.__call__` — jedno zdarzenie przebiegu z wynikiem każdego kroku (paragony per konto,
    promocje, kupony: aktywowane/błędy, nagrody, sklepy, powiadomienie), czas; wyjątek → `error`; też `evening`,
    `monthly`.
  - `sync.py` `import_account` — wynik `SyncResult` (ręczny/poranny), błąd przerwania.
  - `leaflet.py` — odkrycie gazetki, każda próba modelu (OK/odmowa/przeciążenie/klucz, czas), porzucenie paczki.
  - `budget_feed.py` — klasyfikacja AI (model, liczba) i eksport pliku.
  - `notify.send` — tag + wynik; `service.check`/błąd autoryzacji — sesja konta.
  - start add-onu (wersja) w `web/app.py` lifespan.
- Testy w `tests/test_history.py`, `test_daily.py`, `test_leaflet.py`, `test_sync.py`.

**E23.2 Strona `/status`** — najpierw makieta (`prototype` → `impeccable`, zgodnie z `docs/DESIGN.md`), akceptacja,
potem kod:
- `web/status.py` (widok: kafle-światła + sekcje + oś czasu), `templates/status.html`, `_status_live.html`;
  trasa w `web/app.py`, chip „Status” po „Konta” w `base.html`.
- Stan bieżący z istniejących źródeł: `HistorySync.progress()`, `DailyJob.running/last_check`,
  `leaflet_batches` (zrobione/czekają/porzucone, `next_try`), `LeafletRunner._refused` (modele wyłączone limitem),
  `AccountStore` (sesje), `BudgetFeed.path` (mtime, liczba), rozmiar bazy, następne `run_time`/18:00/1. dnia.
- Na żywo: htmx poll co kilka sekund tylko, gdy coś trwa (wzorzec bloku live z Kuponów); oś czasu z filtrem
  obszaru (htmx), 30 dni.
- Testy `tests/test_web.py`; dane demo przez seed w `~/dev/lidl-spike`; weryfikacja Playwright (zrzut + konsola).
- **Wynik makiety (2026-10-12):** z trzech wariantów (A pas stanu + sekcje, B tablica obszarów + dziennik,
  C najpierw problem + zakładki) wybrany **C**: werdykt „Wszystko działa” / „N spraw wymaga działania” z linkiem
  naprawy, reszta obszarów w dwóch kolumnach, szczegóły w zakładkach, oś czasu z filtrem. Reguły problemów
  w `web/status.py` (`build()`, czysta funkcja migawki) — te same posłużą kropce i alertom w E23.3.

**E23.3 Alerty** — `src/lidl/alerts.py` (mało kodu):
- `problems()` liczone ze stanu + dziennika (sesja z błędem autoryzacji, ostatni poranny `error` albo brak
  przebiegu po `run_time` dnia, klucz AI 401/403, paczka `failed`) → kropka na chipie (`base.html`, każda strona).
- Push do `notify.<alert_notify>` (opcja w `config.yaml`/`settings.py`, parametr usługi w `notify.send`, tag `lidl-alert`) raz na problem: klucz `a:<problem>`
  w `watched_sent`, kasowany po powrocie do normy. Sprawdzanie po każdym przebiegu/paczce + przy starcie
  (pominięty 07:00).
- Testy `tests/test_alerts.py`.

**E23.4 Wydanie 0.20.0** — `simplify`, `code-review`, skill `release` (bump `config.yaml` + `pyproject.toml`,
CHANGELOG, opublikowany release), aktualizacja przez Supervisor, weryfikacja na żywo.

## Ryzyka
- Instrumentacja może zmienić zachowanie przebiegu (wyjątek w zapisie zdarzenia) → zapis zdarzeń w `try`
  z logiem, nigdy nie przerywa przebiegu.
- Fałszywy alarm „pominięty 07:00” po restarcie z aktualizacji → tolerancja (np. 2 h po `run_time`) i dedup.
- Szczegóły zdarzeń nie mogą zawierać tokenów/kluczy (tylko kody HTTP, nazwy modeli, liczby).
- Wolny CPU hosta HA: oś czasu z limitem wierszy i indeksem.

## Weryfikacja
- `pytest` + mypy/ruff (CI) zielone; dev serwer `LIDL_DEV=1` z danymi demo, Playwright zrzut tel/PC.
- Na żywo po 0.20.0: strona Status pokazuje start add-onu, stan gazetki i sesji; następnego dnia przebieg 07:00
  z krokami; test alertu: chwilowo zła opcja `llm_key`? — tylko za zgodą (zmiana opcji add-onu), inaczej test
  jednostkowy + jeden ręczny push testowy w trybie dev.
