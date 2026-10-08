# E16 Skuteczność auto-aktywacji i licznik efektu — plan

## Context

Następny etap roadmapy Lidl wybrany 2026-10-08: E16. Cel roadmapy to „zł zaoszczędzone miesięcznie”, a dziś
nic tego nie mierzy. Wywiad:
- **Cel:** „wszystko po trochu”: licznik efektu add-onu, a obok lista kuponów aktywowanych i niewykorzystanych
  (do strojenia progu E11 i opt-outów).
- **Miejsce:** sekcja na górze zakładki Kupony (obok „Nagrody”); bez nowych powiadomień (raport miesięczny → E19).
- **Miara:** rabaty „Lidl Plus kupon” z paragonów — bieżący miesiąc vs średnia z 12 pełnych miesięcy przed
  2026-10-07 (pierwsza aktywacja add-onu); promocje pokazane osobno, informacyjnie.
- **Kolejność:** najpierw archiwum kuponów (E16.1, szybkie wydanie), potem ekran (E16.2).

Odkrycie: `History.save_coupons` (`lidl/app/src/lidl/history.py:496`) **usuwa** kupony, których nie ma już na
liście Lidla. Dziś nie zostaje ślad po aktywacjach, więc „wykorzystany / przepadł” nie da się policzyć. Każdy
dzień zwłoki to utracone dane, dlatego E16.1 idzie pierwsze.

## Ograniczenia (do potwierdzenia)
1. Korzysta: domownicy w panelu (zakładka Kupony). Automatycznie tylko zbieranie danych, bez powiadomień.
2. E16.1 nie zmienia tego, co widać w panelu ani jak działa aktywacja (kupony zarchiwizowane są ukryte tak jak dziś).
3. Sukces E16.1: po wydaniu kupon, który znika z listy Lidla, zostaje w bazie z `gone_at` i `article_ids`.
4. Sukces E16.2: licznik „kupony w tym miesiącu vs średnia 12 mies.” od razu z danymi; lista
   wykorzystanych/przepadłych zapełnia się z czasem.

## E16.0 — docs (po zgodzie)
- `docs/PLAN_E16_skutecznosc.md`: wywiad, decyzje, podetapy E16.1–E16.3, pytania otwarte do E16.2 (definicja
  „wykorzystany”: kupon produktowy = pozycja z `items.coupon > 0` i `art_id ∈ article_ids` na paragonie tego
  konta w oknie ważności; ogólny = `ticket_coupons` po tytule — do sprawdzenia na danych).
- `docs/ROADMAP.md`: przy E16 wpis „wywiad 2026-10-08, plan …, podetapy”; przy E20 dopisać ✅ (0.7.0).
- Commit `docs: E16 plan (coupon effectiveness)` (poza oknem 02:45–03:15).

## E16.1 — archiwum kuponów, wydanie 0.9.2 (osobna zgoda, dokładne kroki przed startem)
Plik `lidl/app/src/lidl/history.py`:
- `SCHEMA_VERSION = 4`; `_SCHEMA` → `coupons` dostaje `article_ids TEXT NOT NULL DEFAULT ''` i `gone_at TEXT`.
- `_migrate_v3()` (gdy `version < 4`): dwa `ALTER TABLE coupons ADD COLUMN …`, tylko jeśli tabela `coupons`
  istnieje (starsze bazy jej nie mają, utworzy ją `_SCHEMA`).
- `save_coupons`: zapis `article_ids` (lista po przecinku), `gone_at = NULL` przy ponownym pojawieniu się;
  zamiast `DELETE` → `UPDATE coupons SET gone_at = ? WHERE account = ? AND seen_at != ? AND gone_at IS NULL`.
- `account_coupons`: `WHERE account = ? AND gone_at IS NULL` (panel i `CouponRunner` bez zmian zachowania).

Testy (`lidl/app/tests/test_history.py` albo `test_coupons.py`, TDD): kupon znika → zostaje z `gone_at`, nie
wraca w `account_coupons`; kupon wraca → `gone_at` NULL; `article_ids` zapisane; migracja bazy v3 z tabelą
`coupons` dodaje kolumny i zachowuje wiersze.

Wydanie: skill `simplify` → skill `release` (bump `lidl/config.yaml` 0.9.1 → 0.9.2, CHANGELOG, published
release, aktualizacja przez Supervisora; restart add-onu = aktualizacja, robi ją skill za zgodą).
Cofnięcie: wydanie 0.9.1 nie zna kolumn, ale je toleruje (SELECT *, INSERT z listą kolumn) — downgrade bezpieczny,
archiwum by tylko rosło.

## E16.2 — sekcja „Efekt” w Kuponach, wydanie 0.10.0 ✅ (2026-10-08; E16.1 ✅ 0.9.2)
Decyzje z wywiadu: układ = duża kwota + pasek względem średniej, pod spodem zwinięte szczegóły; porównanie =
**ostatnie 30 dni** vs średnia 30-dniowa z 12 miesięcy przed 2026-10-07 (suma ÷ 12,2), orientacyjnie (sezonowość),
promocje osobno informacyjnie; lista = **wszystkie aktywowane** kupony (add-on i ręcznie) ze statusem.

Dane (`history.py`, tylko odczyty):
- `coupon_effect(today)`: suma `-items.coupon` z ostatnich 30 dni, średnia z okna 2025-10-07…2026-10-06 przeliczona
  na 30 dni, różnica w zł i %, promocje z tych samych okresów.
- `activated_coupons(account)`: `activated = 1`, razem z archiwum (`gone_at`).
- Status: **wykorzystany** — kupon produktowy: na paragonie tego konta w oknie ważności jest pozycja
  `items.coupon < 0` z kodem w `article_ids`; ogólny (bez kodów): wpis w `ticket_coupons` o tym samym tytule
  w oknie ważności. **Przepadł** — okno minęło bez dopasowania. **W toku** — kupon jeszcze ważny. Kupony sprzed
  0.9.2 nie mają `article_ids` → „brak danych”, bez zgadywania.

UI: `_effect.html` pod „Nagrodami”, tokeny z `docs/DESIGN.md`; pasek zielony powyżej średniej, neutralny poniżej
(bez czerwieni); lista zwinięta, filtr konta jak przy kuponach, podsumowanie „wykorzystane X z Y”; stan pusty
„zbieramy dane od 8.10” (licznik działa od razu).

Podetapy (każdy po „go”): E16.2a makieta na danych dev (Playwright, desktop + telefon) → E16.2b zapytania w TDD →
E16.2c szablon i podpięcie → `simplify` → E16.2d wydanie 0.10.0 (skill `release`, cache-busting, znacznik wersji).

## Weryfikacja
- E16.1: `pytest`, `ruff`, `mypy` lokalnie + CI zielone; po wydaniu `ha_get_app(source="installed")` = 0.9.2,
  log add-onu bez błędów migracji, „Sprawdź teraz” w panelu działa, lista kuponów jak przed wydaniem;
  następnego dnia kupon wykorzystany/wygasły nadal w bazie (sprawdzenie przez endpoint/log — do ustalenia, bo
  bazy nie czytamy bezpośrednio z tego kontenera).

## Stan po 0.10.0 (2026-10-08)
- Na żywo wszystkie wiersze listy to „Brak danych”: kupony sprzed 0.9.2 nie mają `article_ids`; zapisują się przy
  najbliższym sprawdzeniu (07:00 albo „Sprawdź teraz”). Pierwsze wyniki wykorzystany/przepadł ok. 10–11.10.
- Do ok. 6.11.2026 okno „ostatnie 30 dni” nachodzi na okres sprzed add-onu, więc „mniej/więcej niż zwykle” jest
  wtedy mało miarodajne (na żywo 8.10: −40% przy średniej 271 zł / 30 dni) — rozważyć komunikat „za wcześnie”.
- Otwarte: dopasowanie kuponów ogólnych (po `ticket_coupons`), filtr konta na liście.
