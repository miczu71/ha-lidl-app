# ROADMAP — Zakupy UX (nazwa, logo, menu)

Wywiad 2026-11-20. Wydanie jedno, na koniec E3 (etapy to commity). Makiety: https://claude.ai/artifact/46ifqGdFg4CQoVN7XUfzBH

## Ustalenia
- Kto korzysta: domownicy w panelu HA (telefon i komputer); sklep add-onów pokazuje logo.
- Automatycznie: nic nowego — zmiana tylko wyglądu i nawigacji, bez zmian w danych i adresach tras.
- Sukces: panel w pasku bocznym to „Zakupy"; nagłówek „Zakupy (Lidl + Biedronka)"; logo D w sklepie i nagłówku;
  menu = 5 działów, każda dotychczasowa strona osiągalna, głębokie linki z Budżetu (`/paragony/<id>`, `/kraje`, `/sieci`,
  `/biedronka`) działają bez zmian.
- Pasek boczny HA pokazuje tylko ikonę MDI (`panel_icon`), więc logo tam nie wejdzie — zostaje `mdi:cart-outline`.
- Logo: kierunek **D** (kwadrat dzielony po przekątnej, koszyk na linii podziału). Znak Biedronki: PNG 16×16 ze sklepu
  Budżetu (`ha-budget-app/.../static/stores/biedronka.svg`, wyjątek zatwierdzony już w M29) — będzie miękki w większych rozmiarach;
  wymiana na oficjalny wektor jest później tylko podmianą pliku.

## Mapa menu
| Dział | Podzakładki (trasy bez zmian) |
|---|---|
| Paragony | Paragony `/paragony`, Produkty `/produkty` |
| Kupony | `/kupony` (bez podzakładek) |
| Oszczędności | Oszczędności `/oszczednosci`, Oszczędzanie `/biedronka` (tylko `bdr_tab`) |
| Analiza | Ceny `/ceny`, Miesiące `/miesiace`, Rytm `/rytm`, Kraje `/kraje`, Sieci `/sieci` (tylko `multi_chain`) |
| Ustawienia | Konta `/konta`, Status `/status` (kropka alertu przechodzi na dział) |

Dział bez widocznych podzakładek (np. Oszczędności bez Biedronki) pokazuje jedną stronę bez drugiego rzędu.
Aktywny dział wynika z `section` istniejącego w szablonach — bez zmian w trasach Pythona.

## E1 — nazwy (fundament)
Kroki: (1) `lidl/config.yaml`: `panel_title: "Zakupy"`; (2) `base.html`: `<title>` i `bar` domyślnie „Zakupy (Lidl + Biedronka)";
(3) pozostałe szablony nadpisujące `bar`/`title` (grep „Lidl Plus" w `web/templates`) → ta sama nazwa; (4) README/DOCS/CHANGELOG
bez „Lidl Plus" jako nazwy add-onu (nazwy Lidl Plus jako usługi zostają); (5) testy `test_web.py` — tylko asercje o nazwie add-onu.
Test: `cd lidl/app && python -m pytest tests -q --ignore=tests/test_leaflet.py`, ruff, mypy. Rollback: `git revert` commitu.
DONE: panel w pasku bocznym „Zakupy" (sprawdzę po wydaniu), nagłówek nowy, testy zielone.

## E2 — logo D
Kroki: (1) `lidl/logo.svg` i `icon.svg` wg D (Lidl z istniejącego `icon.svg`, Biedronka = osadzony PNG 16×16, koszyk jak w makiecie);
(2) render `icon.png` 128×128 i `logo.png` (HA wymaga 128×128 / ≥250×100) — narzędzie wybieram po sprawdzeniu, co jest w kontenerze (Playwright/rsvg/Pillow);
(3) kopia znaku (28 px) w nagłówku panelu jako statyk SVG w `static/` (bez PNG-ów w UI poza wyjątkiem Biedronki);
(4) sprawdzenie wizualne 128/48/32 px. Rollback: przywrócić 4 pliki z gita.
DONE: pliki w repo, podgląd 128/48/32 px obejrzany, `?v=<wersja>` na statykach.

## E3 — menu 5 działów
Kroki: (1) makro nawigacji w `base.html`: rząd działów (ikony kreskowe inline SVG 24 px, cel dotyku ≥44 px, `aria-current`) + drugi rząd
podzakładek z mapy powyżej; (2) mapowanie `section` → dział w jednym miejscu (słownik Jinja albo mały helper w `web/`); (3) warunki `multi_chain`/`bdr_tab`
zachowane; kropka alertu na dziale Ustawienia; (4) CSS w `app.css` (pigułki, przewijany rząd podzakładek na 390 px, bez zmiany tokenów);
(5) test: dla każdej trasy `section` → właściwy dział i podzakładka `aria-current`; (6) Playwright 390 i 1280 px na demo (`~/lidl_dev`), konsola czysta;
(7) wydanie: simplify → code-review → release (bump wersji, tag non-draft) → weryfikacja na żywo (panel „Zakupy", menu, głęboki link `/kraje`).
Rollback: revert commitów E3; wersja poprzednia z tagu.
DONE: wszystkie 12 stron osiągalne, aktywny dział/podzakładka poprawne, brak poziomego przewijania strony na 390 px.

## Ryzyka
- Biedronka PNG 16×16 powiększony do ~52 px będzie rozmyty (akceptowane przez usera).
- Zmiana `panel_title` wymaga przeładowania panelu/aktualizacji add-onu, by pasek boczny pokazał nową nazwę.
- Nowa nawigacja zmienia nawyki — brak zmian adresów ogranicza ryzyko do wyglądu.
