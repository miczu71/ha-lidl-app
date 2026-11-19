# PLAN E28.5 — Oszczędzanie w Biedronce (wydanie 1.5.0)

Wywiad 2026-11-19. Źródłem prawdy jest `docs/ROADMAP.md`.

## Ustalenia
- Zakres: vouchery (`promos/coupons/`) + oferty „Tylko dla Ciebie” + Shakeomat/Shakeomarka. Naklejki/punkty POZA zakresem.
- Zakładka „Oszczędzanie” (osobna od „Oszczędności” Lidla), widoczna przy ≥1 koncie Biedronki.
- Push: linia „Biedronka” w istniejącym porannym powiadomieniu, voucher wygasający w ≤3 dni; nowe oferty tylko licznik.
- Shakeomat: opcja `biedronka_auto_shakeomat` domyślnie wyłączona + ręczny przycisk „Odsłoń teraz”; push z wynikiem
  (`notify.family`, tag `biedronka-shakeomat`) tylko po włączeniu opcji.
- Bezpiecznik: jeśli `reveal-and-activate` ma koszt/nieodwracalny skutek → staję i pytam z dokładnym opisem przed kodem.
- Sukces: panel pokazuje realne vouchery i oferty, user porównuje liczbę i daty z aplikacją Moja Biedronka.

## Podetapy
- **E28.5.0 Spike (tylko GET, na żywo).** `~/dev/biedronka-spike`, tokeny konta z add-onu (bez wypisywania). Kształt odpowiedzi
  vouchery/ofert (klucze, typy, daty; bez danych osobowych) → tu. Shakeomat: metoda, ciało i skutki z APK, endpointu nie wołam.
  Bramka: koszt/nieodwracalność → stop i pytanie. Rollback: brak zmian w repo poza docs.
- **E28.5.1 Odczyt i model.** `coupons()`/`offers()` w `client/biedronka.py`; schemat v10 `chain_savings` + kopia
  `.pre-chain-savings`; zapis w hooku `after_import` tylko dla kont Biedronki; tdd, fixtures bez prawdziwych danych.
  Test: `cd lidl/app && uv run --extra dev pytest -q --deselect tests/test_leaflet.py`, ruff, mypy. Rollback: revert (migracja addytywna).
- **E28.5.2 Zakładka „Oszczędzanie”.** Trasa + szablony wg makiety D2, `.bdr-saving`; vouchery z datą ważności, oferty, stan pusty.
  Playwright 390/1280 px na demo, potem na żywo. Rollback: revert.
- **E28.5.3 Push.** Linia Biedronki w porannym powiadomieniu (≤3 dni; oferty jako licznik); test progu. Rollback: revert.
- **E28.5.4 Shakeomat.** `reveal_and_activate` (POST, przerwa ~0,3 s), przycisk „Odsłoń teraz”, opcja w `config.yaml` (off),
  poranny run + push tylko po włączeniu; błędy do Statusu. Test: mock HTTP, opcja off = brak wywołania. Rollback: opcja off / revert.
- **E28.5.5 Wydanie 1.5.0.** simplify → code-review + silent-failure-hunter + pr-test-analyzer + security → release →
  weryfikacja na żywo. Przed `update`: kopia `history.db` i backup add-onu.

## Wykonawca
Podetapy 5.1–5.4 robię sam (zależą od wyniku spike); paczki workerów dopiero po spike, jeśli listy plików będą rozłączne.

## Ryzyka
Nieznany kształt API (spike). Zapis na koncie przez nieoficjalne API (opcja off, bramka). Wygaśnięcie sesji → spike wstrzymany, prośba o ponowne logowanie.

## Wynik E28.5.0 (spike GET, 2026-11-19, konto osoba1; bez wartości osobistych)
- `GET promos/coupons/` → `{"coupons": [], "meta": {…}}` — konto nie miało teraz voucherów; kształt elementu nieznany (upstream
  nie opisuje). Parser tolerancyjny + test na pustej liście; element zweryfikować, gdy pojawi się voucher.
- `GET dashboards/dashboard/` → `sections[14]`; sekcje `type: Carousels` mają `param` = id karuzeli (slug `Just4You` = oferty
  „Tylko dla Ciebie”, `biedronkowe-oszczednosci`, `biedronew` …).
- `GET promos/carousels/<id>/` (`type: j4u`) → `items[]` o typach: `STATIC_CONTENT`/`AD` (banery, pomijamy),
  `SHAKEOMAT` (`offer_type: SHAKEOMAT`, `offer_id`, `available_from/to`, `meta`) i `SINGLE_PRODUCT_PROMOTION`
  (`offer_type`, np. WELCOME; pola: `name`, `price`, `regular_price`, `omnibus_price`, `unit_price`, `product_main_ean_code`,
  `start`, `end`, `from_shakeomat`, `only_with_moja_biedronka_card`, `limit_message`).
- `GET promos/shakeomats/` → lista kampanii (`name` `shakeomat*`/`shakeomarka_<marka>`, `start`, `end`, `result.message`);
  typy do auto: `SHAKEOMAT`, `SHAKEOMAT_2`, `SHAKEOMARKA` (upstream `const.py`).
- Shakeomat: `PATCH offers/{offer_id}/reveal-and-activate/` (upstream `api.py`), `offer_id` z elementu karuzeli o `offer_type`
  ∈ typy Shakeomatu. Skutek = odsłonięcie dziennej oferty i jej aktywacja w aplikacji (tak jak potrząśnięcie w aplikacji), bez
  płatności; nie wołane w spike. Bramka kosztu: GET jej nie rozstrzyga — ręczny przycisk najpierw (jak w planie), auto dopiero
  po Twoim potwierdzeniu, że przycisk robi to samo co aplikacja.
