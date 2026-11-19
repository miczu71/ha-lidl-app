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
