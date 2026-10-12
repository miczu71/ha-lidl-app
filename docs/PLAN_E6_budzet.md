# E6 Integracja z Budżetem Domowym — kategorie produktów i eksport paragonów

## Context
Budżet Domowy (osobny add-on) dostaje zakup w Lidlu jako jedną transakcję kartą, w całości w „Spożywcze”, choć paragon
zawiera też drogerię i rzeczy dla dzieci. Po stronie Budżetu: M29 (`ha-budget-app/docs/PLAN_M29.md`) — ręczny podział
transakcji (wydany w Budżecie 0.49.0), a w grupie C dopasowanie paragonu do płatności i automatyczny podział.
Ten etap daje Budżetowi dane: kategorię każdego produktu i plik z paragonami podzielonymi na kategorie.

## Wywiad (2026-10-12, wspólny z M29)
1. Cztery kategorie produktu: `food` (spożywcze), `drugstore` (drogeria i chemia), `kids` (dzieci), `nonfood` (reszta).
2. Historia: jednorazowo klasyfikuje Claude z eksportu (wzór E21); nowe produkty przy imporcie paragonu → AI przez
   istniejące `llm_url`/`llm_key`; brak odpowiedzi = `food` + „do sprawdzenia”; ręczna zmiana w karcie produktu wygrywa.
3. Transport: plik `/share/lidl/receipts.json`, zapisywany przez Lidl po każdym imporcie, czytany przez Budżet.

## Ograniczenia
- Korzysta Budżet (plik) i domownicy (kategoria w karcie produktu, sumy w paragonie). Automatycznie: klasyfikacja AI
  nowych produktów i eksport. Za zgodą użytkownika: przegląd wątpliwych klasyfikacji z historii (E6.2).
- Nazwy produktów nie trafiają do repo — eksport kandydatów ląduje w katalogu tymczasowym sesji Claude.
- Sukces: każdy paragon w pliku ma części, które sumują się do zapłaconej kwoty; drogeria/dzieci widoczne w sumach paragonu.

## Etapy
- **E6.0 docs** — ten plan, wpis w ROADMAP.
- **E6.1 dane:** tabela `product_category(art_id PK, category CHECK IN (food, drugstore, kids, nonfood),
  source CHECK IN (claude, ai, manual))`; kategoria liczona po moście `_resolver` (stary kod `n:` dziedziczy kategorię
  nowego); brak wiersza = `food` „do sprawdzenia”. `GET /produkty/kategorie/kandydaci.json` (kod, nazwy, liczba zakupów,
  wydatek, obecna kategoria i źródło) i `POST /produkty/kategorie/import` (`[{art_id, category}]`, źródło `claude`, ręczne
  `manual` nie są nadpisywane).
- **E6.3 AI dla nowych produktów:** po imporcie paragonów produkty bez kategorii → jedno zapytanie tekstowe (kolejka
  modeli jak w gazetkach); błąd albo brak klucza = zostają „do sprawdzenia”, ponowna próba przy następnym imporcie.
- **E6.4 UI:** kategoria w karcie produktu (zmiana ręczna), filtr „do sprawdzenia” w Produktach, sumy kategorii w widoku
  paragonu. Skill `impeccable`, Playwright 390 px + desktop.
- **E6.5 eksport** `/share/lidl/receipts.json` po każdym imporcie (atomowo `.tmp` + rename): na paragon `id, account, day,
  purchased_at, paid, payment, url_path, parts{food, drugstore, kids, nonfood}`; części = sumy pozycji po rabatach i
  kuponach; kaucja i różnica groszy → największa część, tak by `sum(parts) = paid`. `config.yaml`: `map: share:rw`.
- **Wydanie 0.19.0** (E6.1–E6.5 razem): `simplify` → `code-review` → `release`, weryfikacja na żywo.
- **E6.2 klasyfikacja historii (na żywo, po wydaniu):** eksport kandydatów przez `playwright-ha`, klasyfikacja przez
  Claude, import; raport rozkładu i lista wątpliwych → **przegląd użytkownika** (punkt zatrzymania).

Kolejność zmieniona względem planu M29 (E6.2 po wydaniu): klasyfikacja historii potrzebuje eksportu z żywej bazy, więc
jedno wydanie z całym kodem, a E6.2 to już tylko import danych.

Cofnięcie: downgrade do 0.18.x (tabela zostaje, starsza wersja jej nie czyta); plik w `/share/lidl` można usunąć.

## Wynik (2026-10-12)
- **0.19.0 na żywo** (E6.1, E6.3–E6.5 + simplify + code-review). Start: kolejka modeli przeszła dwa 502, trzeci
  model sklasyfikował 13 z 13 nowych produktów; plik `/share/lidl/receipts.json` — 529 paragonów.
- **E6.2 klasyfikacja historii (Claude):** 3495 produktów bez kategorii; zaimportowane 3471 — spożywcze 3182
  (94,7 tys. zł), drogeria 225 (4,8 tys. zł), dla dzieci 17 (0,3 tys. zł), inne 47 (0,8 tys. zł). Chemia domowa,
  worki, folie i papier do pieczenia liczone jako drogeria; karma dla zwierząt i rośliny w doniczce jako spożywcze;
  kwiaty cięte, reklamówki, narzędzia jako inne.
- **Wniosek:** wydatki „dla dzieci” w Lidlu są małe (pieluszki kupowane rzadko); główny efekt podziału to
  drogeria i chemia (ok. 5% wydatków), która dziś ląduje w Spożywczych.
- **Przegląd użytkownika:** 24 wątpliwe produkty (odzież bez oznaczenia rozmiaru, gra planszowa, mazaki,
  gazetka) — decyzja: wszystkie „Inne”; zaimportowane, do sprawdzenia: 0. E6 zamknięte.
