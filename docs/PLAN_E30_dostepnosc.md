# E30 Dostępność produktu w sklepie Biedronki — plan

Repo: `/config/addons/ha-lidl-app` (public `miczu71/ha-lidl-app`), gałąź `main`, add-on 1.7.0 → wydanie **1.8.0**
(ścieżka B bez dostępności: **1.7.1**). Kod: `lidl/app/src/lidl`, testy `lidl/app/tests`.

## Context
E29 czyta tylko cenę półkową (`products/price/{sklep}/{ean}/`); 404 = „pominięty”, bez rozróżnienia „sklep nie ma
produktu” / „chwilowy brak”. W kliencie spike'u jest nieużyty endpoint stanu: GET `products/stock/{sklep}/{ean}/`
(code, city, street, coverage) i POST `products/stock/` (sklepy wokół punktu) — `~/dev/biedronka-spike/vendor/biedronka/api.py:277-294`.
Cel: wiedzieć, czy obserwowany produkt jest na półce w wybranym sklepie, i dostać push, gdy wróci.

**Wywiad 2026-11-21 (decyzje usera):**
- Spike: GET stock w wybranym sklepie + POST okolica (współrzędne z `zone.home`, czytane na żywo, nie wypisywane/zapisywane).
- Zakres w add-onie: **znacznik w `/sieci`** (kolumna „dziś na półce”: brak/mało/jest) + **push „wrócił na półkę”**.
  „Inne sklepy w okolicy” poza zakresem (POST tylko w spike'u jako wiedza).
- Push promocji E29 przy braku na półce: **wysyłany z dopiskiem** „brak na półce w <sklep>”.
- „Wrócił na półkę”: tylko obserwowane (gwiazdka E15), raz na przejście brak→jest między porannymi odczytami, tag `lidl-obserwowane`.
- Porządki z review E29: **osobny podetap** w E30.
- Bramka niezaliczona → opis 404 w panelu + porządki, wydanie 1.7.1.

**Podsumowanie:** korzystają domownicy (push) i ja w `/sieci`; automatycznie: poranny odczyt ceny + stanu, push
„wrócił” i dopisek przy promocji; ręcznie: `/polka/sprawdz`, weryfikacja stanu z aplikacją Moja Biedronka; sukces =
stan 2–3 produktów w panelu zgadza się z aplikacją, push „wrócił” w teście na fałszywym API i bez duplikatu, `/sieci`
pokazuje znacznik na 390/1280.

## Etapy

### E30.0 Docs
ROADMAP (`docs/ROADMAP.md`: punkt E30 → podetapy E30.0–E30.5), ten plan → `docs/PLAN_E30_dostepnosc.md`. Commit docs.
Rollback: `git revert`.

### E30.1 Spike (bramka) — poza repo, tylko odczyt
- `~/dev/biedronka-spike`: GET `spike.py probe osoba1 products/stock/<sklep>/<ean>/` (istniejący `cmd_probe`, zapis
  do `data/` lokalnie, bez tokenów na ekranie) dla 6–8 EAN w sklepie z ustawienia `biedronka_store`: 2–3 obserwowane
  z ceną, 1–2 z 404 w `products/price`, 1 ważony, 1 nieistniejący, 1 zły sklep. ~1 req/s.
- POST okolica: nowa komenda `probe-nearby <slug> <ean>` w `spike.py` (wzór `cmd_probe`, `api.product_stock_nearby`),
  lat/lon z env `SPIKE_LAT/SPIKE_LON` (wartości z `zone.home` przez ha-mcp, nie wypisywane); 1–2 wywołania;
  wynik zapisywany bez współrzędnych (tylko klucze, liczba sklepów, pola stanu).
- Zapis w planie: kształt odpowiedzi (pole stanu: bool/liczba/poziom „coverage”), 404 vs brak, relacja do 404 z ceny,
  429/limit, czy stan zgadza się z aplikacją (user sprawdza 2–3 produkty).
- **Bramka:** jest pole, które odróżnia „jest/brak” (albo poziom) dla EAN znanego sklepowi → ścieżka A (E30.2–E30.5).
  Brak takiego pola / wymaga geo/innych nagłówków → ścieżka B. Wynik podważający założenia → stop i pytanie.

### E30.2 Backend stanu (ścieżka A; paczka W1, `haiku-worker`, `verifier`)
Kontrakt **Wykonawca** dopisuję do `docs/PLAN_E30_dostepnosc.md` po spike'u (znane pola). Zakres:
- `client/biedronka.py`: `product_stock(store, ean)` (wzór `product_price`, `biedronka.py:272`; nie-dict → `bad_shape`).
- `history.py`: **v14** — `ALTER TABLE shelf_prices ADD COLUMN stock TEXT` (`'yes'|'low'|'no'|NULL`) i `stock_at TEXT`;
  `_migrate_v13(path)` z kopią `.pre-stock` (wzorzec `_migrate_v12`, `history.py:1085`); `ShelfPrice` + `shelf_replace`/`shelf_list` z nowymi polami.
  Wiersz stanu bez ceny (404 w price, stan znany) też zapisywany (cena NULL).
- `shelf_prices.py`: `parse_stock(data) -> str | None`; `refresh` czyta stan po cenie dla każdego EAN (pauza 1 s,
  łącznie ≤120 req/dzień; przy 429 w spike'u — stan tylko dla `watched_eans`); błąd stanu nie psuje ceny (licznik
  `stock_failed`); `RefreshResult.back_in_stock: list[str]` = obserwowane EAN-y z poprzednim `stock='no'` i nowym `yes|low`.
- Testy (TDD): fałszywe API (jest/mało/brak/404/zły kształt), migracja v14 z kopią, przejście brak→jest, brak przejścia przy pierwszym odczycie.
- Rollback: revert; migracja tylko dodaje kolumny, kopia `.pre-stock`.

### E30.3 Push i panel (ścieżka A; paczka W1 po E30.2, `haiku-worker`, `verifier`)
- `notify.py`: `_shelf_line` z dopiskiem „brak na półce w <sklep>” gdy `stock='no'` (`ShelfOffer` + pole `stock`);
  nowa linia/wiadomość „wrócił na półkę: <nazwa> (<sklep>)” w tym samym pushu obserwowanych (tag `TAG_WATCHED`).
- `daily.py`: `_morning_shelf` przekazuje `back_in_stock` do kroku obserwowanych; klucz deduplikacji
  `bb:<ean>:<data odczytu>` w `mark_watched_sent` (wzór `_shelf_fresh`, `daily.py:302`).
- `web/chains.py` `_shelf_cell` (`:265`) + szablon `/sieci`: znacznik „brak na półce”/„mało”/„jest”, wiek odczytu; bez ceny a stan znany → sam znacznik.
- Testy: compose z dopiskiem, push „wrócił” raz, `/sieci` render (test_web).
- Rollback: revert.

### E30.2B Opis 404 (tylko ścieżka B, zamiast E30.2–E30.3)
- `refresh` zapisuje EAN z 404 jako wiersz bez ceny ze znacznikiem `not_listed` (v14: kolumna `not_listed INTEGER`,
  kopia `.pre-stock`); `/sieci` pokazuje „sklep nie zna produktu (404)” zamiast pustej komórki. Testy jak wyżej. Wydanie 1.7.1.

### E30.4 Porządki z review E29 (paczka W1, `haiku-worker`, `verifier`)
- `/polka/sprawdz` (`web/app.py:387`): `asyncio.Lock` w `app.state`; trwa odczyt (ręczny albo poranny) → `?m=shelf_busy`
  zamiast drugiego przebiegu; komunikat w szablonie `/polka`.
- `_shelf_fresh` (`daily.py:302`): nazwy jednym zapytaniem (nowe `History.product_names(codes)` albo istniejąca metoda zbiorcza, jeśli jest) zamiast `product_name` na ofertę.
- `promo_to`: wypełniany ISO-datą z `parse_promo_end` w `parse_price`; `shelf_offers` czyta `promo_to` (fallback na parsowanie `promo_from` dla starych wierszy).
- `refresh_morning` → `None` (brak sklepu/konta) loguje zdarzenie `shelf/info` z powodem zamiast cicho.
- Testy do każdego punktu. Rollback: revert.

### E30.5 Wydanie (ostatni etap: bez pytania)
`simplify` → `code-review` (+ równolegle `silent-failure-hunter`, `pr-test-analyzer`, security `general-purpose` na
`git -C /config/addons/ha-lidl-app diff <baza E30.0>..HEAD`) → `release` 1.8.0 (B: 1.7.1) → na żywo: `/polka/sprawdz`,
`/sieci` w Playwright 390/1280, stan 2–3 produktów vs aplikacja (user), zdarzenie `shelf/ok`.
Rollback: wersja 1.7.0 z poprzedniego wydania + backup add-onu (migracja v14 tylko dodaje kolumny; kopia `.pre-stock`).

## Przebieg
Etapy po kolei bez czekania; po każdym zweryfikowanym `stage-end`. Stop: bramka E30.1 (wynik → ścieżka A/B wg planu;
stop tylko, gdy wynik podważa założenia), krok produkcyjny spoza planu.

## Weryfikacja
- Testy: `cd /config/addons/ha-lidl-app/lidl/app && uv run pytest -q` (+ ruff/mypy wg `addon-conventions`).
- Migracja: test v13→v14 na kopii bazy z fixture; na żywo log startu add-onu + istnienie `.pre-stock`.
- Na żywo po wydaniu: `/polka/sprawdz` → `shelf/ok`, `/sieci` znacznik (Playwright 390/1280), porównanie z aplikacją.
