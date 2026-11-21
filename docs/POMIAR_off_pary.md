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
`gemma-4-31b-it` (ostatni z `DEFAULT_VISION_MODELS`), `temperature 0`, bez kolejki modeli: błąd/limit = przebieg
nie odpowiedział → naprawa przyczyny i powtórka tego samego wariantu (nie zamiana modelu).
Historia: pierwotnie `gemini-3.5-flash`; 2026-11-21 dwa przebiegi A1 bez odpowiedzi (502, 429 — limit dzienny), zero
wyników. User zdecydował o zmianie modelu → nowy pomiar od zera z `gemma-4-31b-it` (wyniki Gemini nie istnieją).
Wniosek z pomiaru dotyczy Gemmy, nie głównego modelu produkcji (Gemini).

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
**PRZERWANY 2026-11-21 przez usera, bez wyniku.** Zero przebiegów odpowiedziało: Gemini 3.5 flash 502/429, Gemma-4-31b
timeout 180 s / 502 / 429 / 503 (freellmapi, dostawcy przeciążeni; 3 próby sterownika co 10 min). Nie ma GO ani NO-GO;
hipoteza „OFF poprawia prompt AI” pozostaje niezmierzona. Zamiast pomiaru user wybrał jednorazowe parowanie ręczne
(Claude, po nazwach): 40 z 57 produktów Biedronki ma odpowiednik w Lidlu (8 ten sam produkt, 21 odpowiednik, 11 słaby),
17 bez odpowiednika. Do żywej bazy trafiły tylko 4 nowe zatwierdzenia (`/sieci/para`; Salami ×2, Grycan, Coca-Cola Zero);
25 par już było zatwierdzonych, 11 słabych nie zapisano (trasa nie przyjmuje propozycji z kandydatami). Wniosek: dane OFF
nie są potrzebne do nadrobienia luki — część par powstaje z EAN-ów i zatwierdzeń ręcznych, reszta to produkty bez odpowiednika.
