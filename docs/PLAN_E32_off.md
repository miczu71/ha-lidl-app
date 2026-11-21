# E32 — Zewnętrzna baza produktów (Open Food Facts) dla par Biedronka ↔ Lidl

## Context
Pary Biedronka→Lidl (`chain_pairs.propose`) dają 0 par EAN: Lidl od 2026-03 (paragony HTML) ma tylko numer artykułu,
API Biedronki nie wystawia katalogu z EAN (spike E31.1). Pytanie usera (2026-11-21): czy z góry zaczytać EAN-y Lidla
i Biedronki z zewnętrznych baz i sparować je, ewentualnie wczytać cały dostępny katalog Biedronki.
To zmienia decyzję „bez OFF” z E31. Decyzja usera: najpierw spike bez kodu add-onu.

## E32.0 — Wynik spike'u (2026-11-21)
Metoda: kopia `history.db` z żywego add-onu (tylko odczyt, poza repo), EAN-y z ostatnich 365 dni, zapytania do
`world.openfoodfacts.org` po samym EAN-ie (≤1/s) oraz listy PL z tagiem sklepu. Skrypty: `~/dev/biedronka-spike/scripts/e32_*.py`,
surowe dane `~/dev/biedronka-spike/data/e32/` (poza repo).

| Pomiar | Wynik |
|---|---|
| Własne produkty 12 mies. | Biedronka 57 (55 z EAN, 1 482 zł); Lidl z EAN 381 (6 910 zł); **Lidl bez EAN 602 (16 007 zł)** |
| Własne EAN-y Biedronki w OFF (zapytanie po EAN) | 35/55, **56% wydatków**; z kategorią+gramaturą 21 (27%) |
| Własne EAN-y Lidla w OFF | 290/381, 77% wydatków; z kategorią+gramaturą 198 (63%) |
| Katalog OFF z tagiem sklepu, Polska | Biedronka 696, Lidl **171** (tag sklepu prawie nie bywa ustawiony) |
| Własne EAN-y w tych katalogach | Biedronka 1/55, Lidl 5/381 |
| Wspólne EAN-y Biedronka ∩ Lidl (katalogi OFF) | 3; wśród własnych zakupów też 3 |
| Top 30 Biedronki wg wydatków | 12 ma kategorię+gramaturę; 11 z nich ma kandydata Lidla (ta sama kategoria, ±25% gramatury) |

Wnioski:
- „Wczytanie całego katalogu” z OFF nie działa: katalogi po tagu sklepu pokrywają ~2% waszych EAN-ów, a Lidl PL ma w OFF
  tylko 171 pozycji. Pełny katalog sieci nie istnieje w żadnym otwartym źródle; API Biedronki daje tylko nazwy+SAP.
- Parowanie po samym EAN-ie: ~3 wspólne EAN-y (marki markowe). Obie sieci sprzedają głównie marki własne, więc to sufit.
- Odpytanie OFF po EAN-ie jest skuteczniejsze niż katalog (56%/77% wydatków), ale daje kategorię i gramaturę tylko
  dla 27% wydatków Biedronki; kandydaci po kategorii+gramaturze wyglądają sensownie (np. Pringles, pomidory krojone),
  lecz po stronie Lidla działają tylko dla produktów ze starym EAN-em (181 z 983), a 602 produkty Lidla (16 tys. zł)
  nie mają EAN-u, więc OFF ich nie wzbogaci.
- Próbka cen/stanu dla EAN-ów z OFF (`products/price/{sklep}/{ean}`) niewykonana: wymaga tokenu Biedronki, a katalog
  OFF i tak nie pokrywa waszych zakupów.

**Bramka: B (niskie pokrycie).** Rekomendacja: nie budować importu katalogu. Ewentualnie tani dodatek: wzbogacanie
promptu AI (`chain_pairs`) kategorią i gramaturą z OFF po EAN-ie dla produktów, które OFF zna (Biedronka 56%
wydatków), z atrybucją ODbL w NOTICE — do decyzji usera po ocenie zysku (liczba trafnych propozycji AI z/bez OFF; skill `pomiar`).
Prywatność: do OFF szły tylko EAN-y.

## Rollback
Spike nic nie zmienił w add-onie ani w żywej bazie. Cofnięcie: `git revert` commitu docs, usunięcie `~/dev/biedronka-spike/data/e32/`.
