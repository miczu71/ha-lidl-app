# Lidl E27 — zakładka „Oszczędności” (analiza kuponów i promocji)

## Context
Pomysł z ROADMAP Lidla („Analiza kuponów i promocji”, pierwotny opis E11, odłożony 2026-10-07). E16 „Efekt kuponów”
pokazuje tylko sumy (30 dni vs przed add-onem). Brakuje rozbicia: które produkty i kupony dały najwięcej, jakie rodzaje
promocji łapiemy, co wraca, jak to wygląda w czasie. Cel z wywiadu (2026-11-04): **ciekawostka**, bez powiadomień
i bez wpływu na auto-aktywację.

## Ustalenia z wywiadu
1. Kto korzysta: domownicy w panelu, nowa zakładka **„Oszczędności”** (9. chip, obok Kuponów).
2. Automatycznie: liczenie z istniejących danych (`items.coupon`, `items.discount`, `items.promo`, `ticket_coupons`),
   bez migracji i bez nowych zapytań do Lidla.
3. Za zgodą: nic (bez powiadomień, bez zmian w aktywacji kuponów). Wydanie 0.23.0 jak zwykle na końcu, bez pytania.
4. Sukces: kwoty się domykają (suma rankingu = suma kuponów, suma grup = suma promocji, razem = rabaty z E2/Efektu
   dla tego samego okresu); 390 i 1280 px bez przewijania w poziomie; konsola czysta; na żywo etykiety bez masy „Inne”.

## Treść zakładki (decyzje)
- **Filtry jak w Rytmie:** konto (Wszystkie / każde), okres (Ostatnie 12 mies. — domyślnie / Cała historia), htmx na żywo.
- **KPI:** kupony zł, promocje zł, razem; % wydatków okresu.
- **Trend miesięczny:** słupki w stosie, 2 serie: kupony (`SUM(coupon)`) i promocje (`SUM(discount) − SUM(coupon)`);
  nowy builder w `web/chart.py` wzorowany na `build_deposit_chart`.
- **Ranking kuponów po produkcie:** suma `items.coupon` na produkt (tożsamość produktu z łączeniami E21 jak w Produktach),
  kolumny: zł, **użyty N×** (paragony z kuponem na produkt), średnio na użycie, ostatnie użycie; tytuł i rabat kuponu
  z `ticket_coupons` dopisane, gdy pasują do pozycji tego paragonu (dopasowanie nazwy bez ogonków/wielkości liter).
  Kupony ogólne (bez pasującej pozycji) — osobny wiersz/sekcja. Przy nagłówku: liczba produktów z kuponem ≥2×.
  Wiersz linkuje do `/paragony/produkt/{art_id}`.
- **Rodzaje promocji:** grupy po regułach (np. `Rabat -\d+%` → „Rabat procentowy”, „grupowy”, „Taniej za N”, „Lidl Plus
  rabat”, reszta → „Inne”), w `<details>` dokładne etykiety z kwotami. Pozycja z kilkoma etykietami: część kuponowa
  idzie do kuponów, reszta do etykiety niekuponowej; kilka niekuponowych → grupa „Kilka promocji naraz”.
  Reguły w jednym module, testowane tabelą przykładów; „Inne” zawsze rozwijalne (odporne na nieznane etykiety).

## Etapy (commity; jedno wydanie na końcu)
- **E27.0 docs:** wpis E27 w `docs/ROADMAP.md` (zastępuje punkt „Analiza kuponów i promocji”) + `docs/PLAN_E27_oszczednosci.md`
  (ten plan + sekcja **Wykonawca** dla E27.1). Rollback: revert commitu.
- **E27.1 dane (TDD, `haiku-worker` w `wt new`, potem claimcheck + `verifier`):**
  `lidl/app/src/lidl/savings.py` (grupowanie etykiet, dopasowanie tytułu, dataklasy wyniku) + `History.savings_breakdown(f: ReceiptFilter)`
  w `history.py` (zapytania, filtr konta/okresu jak `rhythm`) + `tests/test_savings.py`. Test domknięcia sum.
  Rollback: revert commitu (brak migracji).
- **E27.2 strona (sam, `impeccable`, styl Rytm/Miesiące):** trasa `/oszczednosci` w `web/app.py` (wzór `/rytm`, wariant
  `hx-target` z samymi wynikami), `templates/savings.html` + `_savings_results.html`, chip w `base.html`, builder wykresu
  w `chart.py`, style w `app.css`, testy trasy. Dane demo: dopisać `ticket_coupons` i etykiety do seeda demo
  w `~/lidl_dev` (dziś `receipts_demo` ma 0 `ticket_coupons`). Weryfikacja: devserve, Playwright 390/1280 px,
  `browser_console_messages`. Rollback: revert commitu.
- **E27.3 wydanie 0.23.0:** `simplify` → `code-review` (+ `silent-failure-hunter`, `pr-test-analyzer`, security
  `general-purpose`, repo + `v0.22.1..HEAD`) → `release` → na żywo przez Ingress (`playwright-ha`): sumy vs Efekt
  kuponów (30 dni) i Miesiące, udział „Inne”, odsetek kuponów z dopasowanym tytułem; wynik do ROADMAP.
  Rollback: `ha_manage_updates` z backupem add-onu / poprzedni tag.

## Ryzyka
- Prawdziwe etykiety i tytuły `couponsUsed` znam tylko z testów — reguły odporne („Inne” + rozwinięcie), korekta reguł
  po pomiarze na żywo w E27.3 jako poprawka przed zamknięciem.
- Stare paragony (parser v1) mogą nie rozdzielać kuponu od promocji — wtedy trafiają do promocji; sprawdzić na żywo.

## Weryfikacja
`cd lidl/app && uv run pytest && uv run ruff check && uv run mypy` (komendy wg `addon-conventions`), devserve na demo,
Playwright 390/1280 px + konsola, na żywo po wydaniu jak w E27.3.

## Wykonawca — E27.1 (dane; `haiku-worker` w `wt new`, potem claimcheck + `verifier`)
Kontrakt dla workera. TDD: testy czerwone przed kodem. Skill `addon-conventions`. Katalog pracy: `lidl/app`.

**Pliki**
1. `src/lidl/savings.py` (nowy) — czysta logika bez SQL:
   - `classify_promo(label: str) -> tuple[str, str]` → (grupa, dokładna etykieta). Grupy: „Rabat procentowy” (`Rabat -N%`),
     „Rabat grupowy”, „Taniej za N” (`Taniej za 2` itd.), „Lidl Plus rabat”, „Inne”. Etykiety `Lidl Plus kupon`/`Lidl Plus voucher`
     = kupon (nie promocja). Porównanie bez wielkości liter i nadmiarowych spacji (`_norm`).
   - `split_promo(promo: str) -> list[str]` — rozbicie `items.promo` po `"; "`.
   - dataklasy `CouponRow` (art_id, name, amount, uses, last_day, title, discount), `PromoGroup` (name, amount, labels: list[(label, amount)]),
     `SavingsMonth` (month `RRRR-MM`, coupons, promos), `Savings` (coupons_total, promos_total, spend_total, months, coupon_rows,
     general_coupons_amount, repeat_products, groups).
   - `match_title(item_name, coupons: list[dict]) -> dict | None` — dopasowanie `ticket_coupons.title` do nazwy pozycji
     bez ogonków i wielkości liter (kolejność: równa, zawiera).
2. `src/lidl/history.py` — metoda `History.savings_breakdown(f: ReceiptFilter | None = None) -> Savings` obok `rhythm` (ok. l. 1875).
   Filtr przez `_receipt_where(f)`; pozycje z `items i JOIN tickets t`; kod produktu przez `self._resolver()(art_id, name)`.
   Znaki: w bazie `items.discount` i `items.coupon` są UJEMNE (rabat to minus); kwoty w wyniku dodatnie, jak w `SavingsKpi`
   (`history.py` ok. l. 1496–1503: `0 − SUM(...)`). Kupony = `−SUM(i.coupon)`; promocje = `−SUM(i.discount) − kupony`.
   Istniejąca klasa `SavingsKpi` i jej metoda zostają nietknięte; nowa metoda nazywa się `savings_breakdown`
   (nie `savings`), wynik to `Savings` z `savings.py`. Trend: miesiąc z `t.day[:7]`.
   Kupony ogólne = `ticket_coupons` danego paragonu bez pasującej pozycji (kwota z różnicy `t.savings` − suma pozycji, ≥0).
   `uses` = liczba różnych paragonów z `i.coupon != 0` na produkt; `repeat_products` = produkty z `uses >= 2`.
3. `tests/test_savings.py` (nowy) — tabela przykładów `classify_promo` (w tym nieznana etykieta → „Inne”), `split_promo`,
   `match_title`, oraz test integracyjny na `History` w pamięci/tmp (wzór: `tests/test_history.py:253` i fixtury tam użyte):
   (a) suma `coupon_rows` + `general_coupons_amount` = `coupons_total`; (b) suma `groups` = `promos_total`;
   (c) filtr konta i okresu zawęża obie sumy; (d) produkt z 2 paragonami → `uses == 2`, `repeat_products == 1`;
   (e) suma `coupons_total + promos_total` = suma rabatów z `History.effect`-owej metody dla tego samego okresu
   (znajdź metodę `SavingsKpi` przy `history.py:1496`, porównaj tylko z jej sumą łączną rabatów).

**Test:** `cd lidl/app && uv run pytest tests/test_savings.py -q && uv run pytest -q && uv run ruff check && uv run mypy`

**DONE:** nowe testy zielone, cały zestaw (dziś ~441) zielony, ruff i mypy czyste, `History.savings_breakdown` zwraca `Savings`
z domkniętymi sumami (a–e), zero zmian poza trzema wymienionymi plikami.

**NIE RÓB:** migracji i zmian schematu SQL; zmian w `web/*`, `templates/*`, `app.css`, `base.html`; zmian w `coupons.py`
i aktywacji kuponów; commitów (robi rodzic); dotykania `effect`-owej metody (tylko odczyt do porównania w teście);
formatowania sąsiedniego kodu.
