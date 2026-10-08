# E15 Obserwowane produkty — plan

## Cel
Kupony (E3) i promocje (E4) na ~187 produktów z „Kupowane regularnie” już przychodzą w porannym
powiadomieniu 07:00, więc kilka naprawdę ważnych produktów w nim ginie. E15 wyróżnia je osobnym powiadomieniem.

## Ustalenia z wywiadu (2026-10-08)
1. Cel: wyróżnić kilka ważnych produktów spośród ~187.
2. Lista wspólna dla domu, powiadomienie `notify.family` (do obojga).
3. Wybór: gwiazdka w wierszu „Kupowane regularnie” (zakładka Kupony); dopasowanie tylko po kodzie artykułu
   (bez dopasowania nazw); gwiazdka włącza auto-aktywację produktu (kasuje wpis z `coupon_optout`).
4. Osobny push z tagiem `lidl-obserwowane` po przebiegu 07:00 (i po „Sprawdź teraz”), tylko gdy jest coś NOWEGO;
   poranne powiadomienie bez zmian.
5. Sukces: kupon albo promocja na produkt z gwiazdką → jedno wyraźne powiadomienie tego dnia, bez powtórek.

## Projekt
- **Dane** (`history.py`): tabela `watched (art_id TEXT PRIMARY KEY)`, `SCHEMA_VERSION` 4 → 5 (migracja wg
  istniejącego wzorca); `watched_codes()`, `set_watched(art_id, on)` (włączenie kasuje też wpis z `coupon_optout`),
  pole `watched` w `CouponCandidate`.
- **Nowe kupony:** kupon na obserwowany kod (`coupons.article_ids`), którego pierwszy wiersz ma `seen_at` z bieżącego
  przebiegu — `History.new_watched_coupons(seen_at)` (konto, tytuł, rabat, ważność, kod).
- **Nowe promocje:** `PromotionRunner.starting(today)` zawężone do `watched_codes()` (start = dziś, więc bez powtórek).
- **Powiadomienie** (`notify.py`): `compose_watched(coupons, promos, today)` → `(tytuł, treść) | None`;
  `TAG_WATCHED = "lidl-obserwowane"`; tytuł „Lidl: <produkt> — kupon −30%” albo „Lidl: 3 obserwowane produkty
  z rabatem”; jedna linia na produkt: rabat, ważność, konto (przy kuponie). Wywołanie w `daily.py` obok `compose()`.
- **Panel** (`web/products.py`, `_coupons_regular.html`, `_coupons_results.html`): gwiazdka (htmx, POST
  `/kupony/produkt/{art_id}/obserwuj`), filtr „tylko obserwowane”; cache-busting.
- **Testy:** `compose_watched` (pusto / jeden / wiele), nowe kupony (pierwszy przebieg, kolejny, ten sam kupon
  następnego dnia), zawężenie promocji, gwiazdka ↔ `coupon_optout`, widok.

## Podetapy (każdy: dokładne kroki → „go” → checkpoint)
- **E15.0 docs** ✅ (ten plan + ROADMAP).
- **E15.1 dane, logika, powiadomienie** ✅ (history / notify / daily + testy; zamiast „pierwszego seen_at” tabela `watched_sent`, bo `save_coupons` nadpisuje `seen_at`).
- **E15.2 panel** ✅ (gwiazdka; zamiast filtra obserwowane na górze listy — decyzja 2026-10-08; weryfikacja w przeglądarce: komputer i telefon, serwer dev `LIDL_DEV=1`).
- **E15.3 wydanie 0.11.0** skillem `release` (opublikowany release, aktualizacja w Supervisorze, weryfikacja na żywo:
  gwiazdka na 1–2 produktach, „Sprawdź teraz”).

## Weryfikacja
`pytest`, `ruff`, `mypy` lokalnie i zielone CI; dev: gwiazdka przeżywa przeładowanie, filtr działa; na żywo po 0.11.0:
log add-onu bez błędów, push `lidl-obserwowane` przy nowym kuponie/promocji, brak drugiego pusha o to samo przy
kolejnym „Sprawdź teraz”.
