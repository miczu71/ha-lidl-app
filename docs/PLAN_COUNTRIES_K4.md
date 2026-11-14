# PLAN K4 — kategorie AI dla pozycji zagranicznych i eksport do Budżetu

Zależy od K2 (pozycje) i K1. Wartość: zagraniczne zakupy w Budżecie z kategoriami. Dwa repo: add-on Lidl (ten) i Budżet
(`/config/addons/ha-budget-app`, osobne wydanie). Wykonawca: `sonnet-worker` (pieniądze + dwa repo = „ryzyko”).

## Decyzje
- `classify_new`: pozycje z `foreign_items` (kod z prefiksem kraju) w tym samym wywołaniu LLM co polskie; prompt dostaje
  zdanie „nazwy mogą być po czesku lub włosku”; te same 4 kategorie. Wyniki do `product_category` pod kluczem z prefiksem.
- `receipts_export` (plik `/share/lidl/receipts.json`, `version` zostaje 1 — dodajemy pola opcjonalne, stary Budżet je ignoruje):
  `country`, `currency`, `paid_orig`, `fx_rate`; `paid` = PLN po NBP; `parts` z `foreign_items` (suma = `paid`, korekta zaokrągleń
  na największej części).
- Budżet (`budget/lidl_link.py`): dla paragonów z `country != PL` tolerancja kwoty 5% zamiast „co do grosza”, data ±3 dni,
  „lidl” w opisie i dokładnie jeden kandydat po obu stronach bez zmian; po sparowaniu w Budżecie liczy się kwota z banku;
  niejednoznaczne → `receipts_for_txn` do ręcznego wyboru jak dziś. W UI Budżetu przy powiązaniu: kraj i oryginał.

## Wykonawca
Repo Lidl:
1. `history.py`: `uncategorized(since)` zwraca też pozycje z `foreign_items`; `receipts_export` jak wyżej (testy
   `tests/test_budget_feed.py`: zagraniczny paragon, suma części = `paid`, pola opcjonalne obecne, PL bez zmian bajt w bajt).
2. `budget_feed.py`: `PROMPT` + zdanie o językach (PL bez zmian zachowania — test na treść promptu dla polskich pozycji).
Repo Budżet (`/config/addons/ha-budget-app`, w osobnym worktree `wt new`; skill `addon-conventions`):
3. `budget/app/src/budget/lidl_link.py`: czytanie `country`/`paid_orig` (brak = PL), tolerancja 5% dla zagranicznych w `match`;
   testy `tests/` z nowymi przypadkami (zagraniczny w tolerancji, poza tolerancją, dwóch kandydatów → ręcznie, PL nadal co do grosza).
4. Widok powiązania w Budżecie: etykieta kraju + oryginał (szablon przy transakcji; sprawdzić grep `lidl_link` w `web/`).

Komendy testu: Lidl — jak K1; Budżet — komenda z jego `pyproject.toml`/CI (worker ją podaje w raporcie przed edycją).

DONE: testy obu repo zielone; PL: export bez zmian dla polskich paragonów; zagraniczny paragon z demo trafia do Budżetu z częściami.
NIE RÓB: zmiany `version` w pliku eksportu; zmian w innych modułach Budżetu; wydań (robi je skill `release` po K4);
prawdziwych opisów transakcji w testach (tylko syntetyczne).

## Kolejność wydań
Najpierw Lidl (nowe pola opcjonalne), potem Budżet — kolejność odwrotna też działa (brak pól = PL).

## Rollback
Revert commitów; plik eksportu odtwarza się przy następnym przebiegu. Opcja `extra_countries: []` zatrzymuje napływ zagranicznych.
