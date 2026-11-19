# E28.3 — Budżet: paragony obu sieci z logo przy transakcji

**STATUS: ZROBIONE 2026-11-19 — Budżet 0.77.0 wydany i zweryfikowany na żywo (szczegóły w ROADMAP.md, E28.3).**

Repo: `/config/addons/ha-budget-app` (aplikacja `budget/app`, wersja w `budget/config.yaml` i `budget/app/src/budget/__init__.py`, dziś 0.76.0).
Źródło decyzji: `docs/PLAN_E28_biedronka.md` (E28.3), wywiad z 2026-11-04. Lidl dostarcza `receipts.json` z polem `chain`
(`lidl`/`biedronka`) od 1.3.0 (`budget_feed.receipts_export`).

## Cel i sukces
- Kto korzysta: user w Budżecie (Transakcje, karta transakcji).
- Automatycznie: dopasowanie paragonu do wydatku według sieci; podział na kategorie z paragonu jak dla Lidla.
- Za zgodą: wybór paragonu przy niejednoznacznym dopasowaniu, „to nie ten paragon” — jak dziś.
- Sukces: transakcja z Biedronki ma logo sieci i działający link „paragon” do `/app/f0987e0f_lidl/paragony/<id>`; paragon jednej
  sieci nigdy nie łączy się z wydatkiem drugiej; testy czerwone przed kodem, zielone po.

## Decyzje
- Dopasowanie po polu `chain` z pliku, NIE po prefiksie `b:` (prefiksu nie zweryfikowano na żywym eksporcie z tego kontenera).
  Brak `chain` w paragonie (stary eksport) = `lidl`.
- Wzorce wydatku: Lidl `lidl`; Biedronka `biedronka`, `jeronimo` (po `fold`, całe słowa nie są wymagane — jak dziś `LIKE`).
- Tabele `txn_lidl`, `txn_lidl_reject` zostają (bez migracji); jedna transakcja = najwyżej jeden paragon z dowolnej sieci.
- Kategorie: jedno `lidl_category_map` dla obu sieci (te same kategorie produktów).
- Nazwy kodu zostają (`lidl_link.py`, `txn_lidl`) — zmiana nazwy to osobny, nieopłacalny refaktor.
- Loga: `store_logos.py` + `web/static/stores/{lidl,biedronka}.svg` wg wzorca `bank_logos.py`; źródło i licencja w
  `web/static/stores/SOURCES.md` PRZED commitem (repo publiczne). Ikony wyłącznie SVG (reguła usera).

## Kroki
1. `wt new /config/addons/ha-budget-app e28-3` → WORKTREE. Stan bazowy: `git status --short` (BASELINE) i `uv run pytest -q` w `budget/app`.
2. Testy (czerwone): `tests/test_lidl_link.py` — Biedronka łączy się z wydatkiem „BIEDRONKA …”/„JERONIMO MARTINS”; paragon Lidla
   nie łączy się z wydatkiem Biedronki i odwrotnie; `chain` brak = lidl; `receipts_for_txn` zwraca tylko paragony sieci wydatku;
   `links` zwraca też sieć. `tests/test_store_logos.py` (jak `test_bank_logos.py`): mapowanie sieć → plik, nieznana → brak logo.
3. Kod: `lidl_link.py` (pole `Receipt.chain`, `load` czyta `chain`, `_EXPENSE` → per sieć, `match`/`receipts_for_txn` filtrują sieć,
   `chain_for_txn`/`links` do szablonu); `store_logos.py`; filtr `store_logo` w `web/common.py` (jak `bank_logo`).
4. Szablony: `_txn_category.html` (logo + link „paragon”, nie „paragon Lidl”; chipy wyboru z logo), lista Transakcji
   (`routes_transactions.py` przekazuje sieć per paragon obok `foreign_receipts`). Link „ceny za granicą” tylko dla Lidla.
5. Loga SVG + `SOURCES.md`; `app.css` (`.store-logo`, jak `.bank-logo`).
6. `uv run pytest -q`, `ruff check`, `ruff format --check`, `mypy src`; zrzut Playwright (390 px i desktop) karty z logo Biedronki na danych testowych.
7. Etap końcowy roadmapy nie jest to — wydanie łączę: E28.3 jest potrzebne od razu Budżetowi, więc osobne wydanie Budżetu
   (0.77.0): `simplify` → `code-review` (+ `silent-failure-hunter`, `pr-test-analyzer`, security) → `release` → weryfikacja na żywo
   (transakcja z Biedronki: logo + link). Kopia `budget.db` przed wydaniem.
8. `docs/ROADMAP.md` (Lidl) i `-config/memory/project_budget_app.md`: E28.3 ZROBIONE; potem `stage-end`.

Rollback: `wt drop /config/addons/ha-budget-app e28-3` przed wydaniem; po wydaniu przywrócenie 0.76.0 (backup add-onu + `git revert`);
dane nietknięte (brak migracji, nowe powiązania Biedronki można usunąć `DELETE FROM txn_lidl WHERE ticket_id` z sieci biedronka).

## Wykonawca (W1, jedna paczka; ≥5 edycji; domyślnie `haiku-worker`)

**Repo:** `/config/addons/ha-budget-app`, worktree z `wt new` (`WORKTREE:`). Test: `cd <WORKTREE>/budget/app && uv run pytest -q`,
`uv run ruff check . && uv run ruff format --check . && uv run mypy src`. TDD: najpierw testy (czerwone), potem kod.

Pliki i zmiany:
1. `budget/app/src/budget/lidl_link.py`: `Receipt.chain: str = "lidl"` (ostatnie pole z domyślną); `load` czyta `r.get("chain")`
   (tylko `lidl`/`biedronka`, inaczej `lidl`); `CHAIN_PATTERNS = {"lidl": ("lidl",), "biedronka": ("biedronka", "jeronimo")}`;
   `_expense(chain)` buduje SQL z `fold(...) LIKE` dla wzorców sieci (OR), reszta warunków jak `_EXPENSE`; `match` i
   `receipts_for_txn` dobierają kandydatów per sieć paragonu (paragon sieci X tylko do wydatku sieci X); `chains(path, ids) -> dict[str, str]`
   (id paragonu → sieć, z cache po mtime jak `_foreign_set`).
2. `budget/app/src/budget/store_logos.py` (nowy): `STATIC_DIR`, `slug_for(chain)`, wzór `bank_logos.py`.
3. `budget/app/src/budget/web/common.py`: filtr `store_logo(chain, base="")` → `<img class="store-logo" alt="" src="{base}/static/stores/{slug}.svg?v={__version__}">`; rejestracja jak `bank_logo`.
4. `budget/app/src/budget/web/routes_transactions.py` (obok l. 172 i 322): przekazać `receipt_chains` (id → sieć) do szablonów; bez zmiany reszty.
5. `budget/app/src/budget/web/templates/_txn_category.html` (l. 24–25, 40–42): przy `receipt` logo `store_logo(receipt_chains[receipt])` + link „paragon”;
   chipy wyboru z logo sieci; „ceny za granicą” tylko gdy sieć = lidl.
6. `budget/app/src/budget/web/static/stores/lidl.svg`, `biedronka.svg` + `SOURCES.md` + reguła `.store-logo` w `app.css`
   (SVG z faviconów oficjalnych stron, ≤64 px opakowane w SVG jak w `banks/SOURCES.md`; URL źródła i data pobrania w `SOURCES.md`).
7. Testy: `tests/test_lidl_link.py` (rozszerzyć), `tests/test_store_logos.py` (nowy), `tests/test_web_*` tylko jeśli szablon tego wymaga.

DONE: pytest, ruff, mypy czyste; nowe testy czerwone przed kodem i zielone po; `git diff --stat` tylko pliki wyżej.
NIE RÓB: migracji (`storage/migrations`), zmian tabel `txn_lidl*`, zmian w add-onie Lidl, zmiany nazw modułów/tabel, `__version__`/`config.yaml`
(bump robi `release`), commitów, pobierania loga z innego źródła niż faviconów oficjalnych stron.

## Ryzyka
- Prefiks id Biedronki niezweryfikowany → dlatego sieć z pola `chain`; weryfikacja na żywo w kroku 7.
- Opis płatności Biedronki w banku może mieć inną nazwę (np. „JMP S.A.”) → sprawdzić na żywo na realnych transakcjach; brak
  dopasowania nie psuje danych (paragon zostaje wolny); wzorce są w jednej stałej.
- Loga to znaki towarowe: tylko oznaczenie sieci przy paragonie, jak loga banków.
