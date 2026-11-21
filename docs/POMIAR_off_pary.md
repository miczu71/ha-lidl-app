# POMIAR E32.1 — czy dane z Open Food Facts poprawiają propozycje par Biedronka → Lidl

Kontekst: `docs/PLAN_E32_off.md` (spike E32.0, bramka B). Skill `pomiar`; kontrakt stały — zmiana danych,
komendy lub kryterium otwiera nowy pomiar od zera.

## Pytanie i kryterium
Czy dopisanie kategorii i gramatury z OFF (po EAN-ie) do promptu `chain_pairs.propose` zwiększa liczbę trafnych
propozycji odpowiedników Lidla?

**GO (wzbogacić prompt), gdy wariant B lub C ma średnio z 2 powtórzeń: `hit@3` ≥ `hit@3` wariantu A + 10 pp
ORAZ `top1` ≥ `top1` wariantu A.** W przeciwnym razie NO-GO (zostaje A, parowanie po samych nazwach).
Różnica < 10 pp = bez wniosku → NO-GO (n = 57, jeden osąd; mały efekt nie uzasadnia zależności od OFF/ODbL).

Metryki (mianownik zawsze 57 produktów Biedronki):
- `hit@3` — odsetek produktów z ≥1 trafnym kandydatem wśród ≤3 zwróconych,
- `top1` — odsetek produktów, których pierwszy kandydat jest trafny,
- `zle` — liczba nietrafnych kandydatów (pomocniczo).

## Zestaw danych (zamrożony, poza repo: `~/dev/biedronka-spike/data/e32/m1/`)
- `bprod.json`: wszystkie 57 produktów Biedronki z 365 dni (kod, ostatnia nazwa z paragonu), z `own.json` (kopia bazy z 2026-11-21);
- `catalog.json`: `History.chain_catalog("lidl")` na tej kopii (≤600 pozycji, kod + nazwa);
- `off/products.json` (E32.0): kategoria i gramatura po EAN-ie (Biedronka 35/55 ma rekord OFF, 21 z kategorią+gramaturą).

## Skrypt i model
`~/dev/biedronka-spike/scripts/e32_measure.py <wariant> <powtórzenie>` przez `secret-run freellmapi` (klucz z env, wyjście
tylko metryki i statusy). PROMPT, SCHEMA, CHUNK=40 i MAX_CANDIDATES=3 importowane z `chain_pairs.py`. Jeden model:
`gemini-3.5-flash` (pierwszy z `DEFAULT_VISION_MODELS`), `temperature 0`, bez kolejki modeli: błąd/limit = przebieg
nie odpowiedział → naprawa przyczyny i powtórka tego samego wariantu (nie zamiana modelu).

## Warianty (różnią się wyłącznie treścią linii w prompcie)
- **A** — nazwy (produkcja dziś): `Katalog Lidla: <kod>: <nazwa>`; `Produkty Biedronki: <nazwa>`.
- **B** — A + linia Biedronki `<nazwa> | kategoria: <najgłębsza en: z OFF>; gramatura: <quantity>` tam, gdzie OFF ma rekord.
- **C** — B + linie katalogu Lidla `<kod>: <nazwa> | kategoria; gramatura` dla pozycji z `n:<EAN>` mających rekord OFF.
Powtórzenia: 2 na wariant (rep 1, 2); porządek produktów i porcji stały.

## Osąd (ślepy, pooled)
Po wszystkich przebiegach scalam kandydatów ze wszystkich wariantów i powtórzeń per produkt (bez etykiety wariantu,
kolejność losowa) i osądzam ja wg jednego kryterium z promptu: „porównywalne opakowanie, produkt do kupienia zamiast
niego”, po samych nazwach (to widzi user w karcie). Osąd zapisuję w `m1/judged.json` PRZED odsłonięciem wariantów.
Ograniczenia: jeden osądzający (model), jeden model AI, 57 produktów.

## Stop
Kryterium spełnione albo 3 kolejne przebiegi gorsze od A. Dwa przebiegi z rzędu bez odpowiedzi → stop i pytanie.

## Werdykt
(po pomiarze)
