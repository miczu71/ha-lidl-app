# Plan E11 — Lista „produkty kuponowe” (reguły dla E3, add-on Lidl Plus 0.4.0)

## Kontekst
E2 jest zamknięte (0.3.3): w bazie jest historia obu kont domu, z rabatami na pozycjach (`items.discount`,
`items.coupon`, `items.promo`) i użytymi kuponami (`ticket_coupons`). Kolejność ustalona 2026-10-07:
**E11 → E3**. E11 nie jest raportem do oglądania, tylko **wejściem dla automatu E3**: ustala, na które
produkty E3 ma automatycznie aktywować kupony. Nic nie pobieramy z Lidla.

## Ograniczenia (z wywiadu)
1. **Kto korzysta:** E3 (auto-aktywacja kuponów) oraz domownik, który w panelu odznacza wyjątki.
2. **Kandydat** = produkt kupiony **≥3 razy (na różnych paragonach) w ostatnich 365 dniach**. Lista jest
   **wspólna dla domu** (oba konta), E3 aktywuje pasujące kupony na każdym koncie.
3. **Domyślnie włączony (opt-out):** każdy kandydat jest do auto-aktywacji, dopóki ktoś go nie odznaczy.
   Nowe produkty po przekroczeniu progu wchodzą same. W bazie zapisujemy tylko odznaczenia.
4. **Produkty bez kodu kuponu:** produkt z samym kluczem `n:<EAN>` (stary format NATIVE, bez mostu po nazwie)
   nie da się dopasować do kuponu (`articleIds` kuponów to kody z paragonów HTML). Pokazujemy go z oznaczeniem
   „bez kodu kuponu”, przełącznik jest nieaktywny.
5. **Sukces:** lista w panelu odpowiada intuicji („to kupujemy stale”), odznaczenia przetrwają restart, a E3
   dostaje jedną funkcję `auto_activate_codes()` ze zbiorem kodów. E11 niczego nie aktywuje — to E3, za osobnym „go”.

## Projekt
**Dane (`lidl/app/src/lidl/history.py`)**
- Nowa tabela `coupon_optout (art_id TEXT PRIMARY KEY)` — tylko odznaczenia; `CREATE TABLE IF NOT EXISTS`
  w `_SCHEMA` wystarcza, więc `SCHEMA_VERSION` zostaje 3 (bez migracji).
- `coupon_candidates(today=None) -> list[CouponCandidate]`: wspólna agregacja z `ranking()` (`_products(since)`,
  ten sam most nazw `_resolver()`), tylko paragony z ostatnich 365 dni i próg `CANDIDATE_MIN_PURCHASES = 3`. Pola: `art_id`, `name`, `purchases`, `last_date`,
  `coupon_uses` (pozycje z `coupon < 0`), `coupon_saved`, `promo_saved` (rabat − kupon), `matchable`
  (`not art_id.startswith("n:")`), `enabled` (`matchable` i brak w `coupon_optout`). Sortowanie: liczba
  zakupów malejąco, potem nazwa.
- `set_auto_activate(art_id, enabled)` — wstawia albo usuwa wiersz w `coupon_optout`.
- `auto_activate_codes(today=None) -> set[str]` — kody kandydatów z `enabled` (API dla E3).

**UI (`web/app.py`, `web/templates/coupons.html`, nawigacja w `base.html`)**
- Zakładka „Kupony” obok Produktów i Kont: `GET /kupony` — nagłówek (kandydaci, do auto-aktywacji, bez kodu),
  lista z polami `CouponCandidate` i przełącznikiem; na telefonie karty.
- `POST /kupony/{art_id}` (formularz `enabled`) → przekierowanie na `/kupony` (wzorzec PRG jak `start_history`).
- Styl wg `docs/DESIGN.md`, istniejące komponenty; cache-busting jak dotąd (`?v=`).

**Testy (`lidl/app/tests/`)**
- Próg i okno: zakup sprzed 366 dni się nie liczy, 2 zakupy to za mało.
- Most `n:` → kod HTML sumuje zakupy obu formatów; `n:` bez mostu ma `matchable=False`.
- Odznaczenie zapisane i odczytane; `auto_activate_codes` pomija odznaczone i `n:`.
- Trasy `GET`/`POST /kupony`. Do tego `ruff` i `mypy` jak w CI.

## Etapy (każdy z checkpointem; przed etapem dokładne kroki i „go”)
- **E11.0** Dokumentacja: ten plik + wpis w `docs/ROADMAP.md`.
- **E11.1** Dane i testy (TDD) w `history.py`.
- **E11.2** Ekran „Kupony” + weryfikacja w przeglądarce (desktop i telefon, konsola) na lokalnym uruchomieniu.
- **E11.3** Wydanie 0.4.0 skillem `release`, aktualizacja w Supervisorze, weryfikacja na żywo w panelu.

Cofnięcie: revert commitów; tabela `coupon_optout` jest addytywna (starsza wersja ją ignoruje).

## Ryzyka
- `ticket_coupons` nie ma kodów artykułów, więc użycia kuponów liczymy z `items.coupon`, nie z tej tabeli.
- Próg 3 zakupy / 12 miesięcy może dać długą listę (setki pozycji) — wtedy sortowanie i prosty filtr
  tekstowy, bez paginacji.

## Weryfikacja
`pytest`, `ruff`, `mypy` lokalnie i zielony CI; zrzut ekranu i konsola przeglądarki przed wydaniem; po wydaniu
wersja w Supervisorze = 0.4.0, ekran działa na żywo, odznaczenie przetrwa przeładowanie.
