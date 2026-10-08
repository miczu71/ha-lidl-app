# E4 Gazetki: promocje na nasze produkty w porannym powiadomieniu

## Kontekst
E3/E14/E20 są zamknięte, a 0.7.2 działa na żywo. Użytkownik wybrał E4, żeby domknąć wątek promocji, od którego zależą E15 (promocje),
E5 i miara sukcesu „kupony + promocje”. Wywiad z 2026-10-08:
- **Cel:** powiadomienie o promocji na produkt, który kupujemy (bez osobnego panelu jako celu głównego).
- **Kiedy:** linia „Promocje od dziś: …” w istniejącym porannym powiadomieniu 07:00 (`notify.family`), tylko w dniu startu promocji.
  Jedno powiadomienie dziennie, bez duplikatów.
- **Które produkty:** ta sama lista co na zakładce Kupony (E11: ≥3 zakupy/12 mies., wspólna, ten sam opt-out, `auto_activate_codes()`).
- **Automatycznie:** pobieranie gazetek (publiczne API, bez logowania, kont nie dotykamy) i dopasowanie. Za zgodą: wszystko, co wysyła dane
  na zewnątrz (model AI), i każde wydanie.
- **Sukces:** w dniu startu promocji poranne powiadomienie wymienia nasze produkty w promocji z ceną i datami, z małą liczbą fałszywych trafień.

## Najpierw E4.0: rozpoznanie tylko do odczytu (bez zmian w add-onie i kontach)
Ryzyko etapu to jakość danych, więc zanim zaprojektujemy E4.1+, sprawdzamy źródła:
1. **Uporządkowane oferty z API aplikacji.** Statyczne przeszukanie zdekompilowanego APK 17.11.6 z E20.0 (bez jadx), tymi samymi
   metodami co przy zdrapkach (adnotacje Retrofit w dex), pod kątem endpointów ofert i promocji (`offers`, `campaign`, `leaflet`,
   `highlights`). Jeśli taki endpoint istnieje i zwraca produkty z kodem artykułu, ceną i datami, dopasowanie idzie po kodzie jak przy
   kuponach, a PDF i AI odpadają.
2. **Gazetki z publicznego API.** `GET endpoints.leaflets.schwarz/v4/overview?client_locale=lidl/pl-PL` → lista bieżących gazetek
   z datami. Sprawdzamy, czy szczegóły gazetki dają strukturę stron i produktów (np. `v4/flyer?…`), czy tylko PDF.
3. **Jeśli zostaje tylko PDF:** jedna bieżąca gazetka → `pdftotext -bbox-layout` → ręczna ocena, czy da się złożyć kafelki
   (nazwa, cena, „od dnia”). Skrypt w `~/dev/lidl-spike` (bez tokenów, dane w `~/dev/lidl-spike/data`).
4. **Dopasowanie nazw (tylko gdy brak kodów):** w HA są `ai_task.google_ai_task` i `ai_task.openai_ai_task`. Add-on ma
   `homeassistant_api: true`, więc może wołać `ai_task.generate_data` bez nowych sekretów. Próba na ~20 kafelkach przeciw liście E11
   **tylko za osobną zgodą** (wysyłka do Google/OpenAI).
5. Wynik: tabela źródeł (co daje, kody tak/nie, daty tak/nie) w nowym `docs/PLAN_E4_gazetki.md` i wpis w `docs/ROADMAP.md`;
   checkpoint i wybór ścieżki z użytkownikiem.

Wszystkie kroki 1–3 to odczyty publicznych zasobów i lokalnych plików. Mutacje: tylko nowe pliki w `~/dev/lidl-spike` i docs w repo
add-onu (commit/push po akceptacji, poza oknem 02:45–03:15).

## Etapy E4 (ustalone po E4.0, 2026-10-08)

Decyzje: AI na tekst gazetki od razu (nie później); model = **freellmapi** (`http://192.168.0.106:3003/v1`, zgodne z
OpenAI) z **przypiętym modelem** w opcjach (kandydaci z testów 2026-10-04: `gpt-oss-120b`, `llama-3.3-70b-fp8-fast`),
klucz freellmapi wkleja użytkownik w opcjach add-onu. Odpowiedź sprawdzana schematem; przy błędzie AI zostają
źródła z kodami. Promocje typu „kupon Lidl Plus” pomijamy (to robota E3).

- **E4.1 Promocje z kodami → poranna linia** (wartość sama z siebie, wydanie 0.8.0): `promotions.py` pobiera
  lidl.pl (Żywność i napoje) i oferty najczęstszego sklepu (`tickets.store_code`), tabela `promotions` (schemat v4),
  dopasowanie do `auto_activate_codes()`, linia „Promocje od dziś: …” w `notify.compose` tylko w dniu startu,
  zapis „już powiadomione” per (produkt, start). Bez AI, bez nowych opcji.
- **E4.2 Próba AI na gazetce (spike, bez add-onu):** tekst stron z JSON gazetki (`keyWords` + `altText`, bez PDF —
  obraz Alpine nie potrzebuje poppler) + nazwy produktów E11 → freellmapi, schemat JSON `{art_id, opis, cena, od, do}`;
  ręczna ocena trafień i fałszywych trafień na bieżącej gazetce, wybór modelu. Wymaga klucza freellmapi
  (`~/.secrets/freellmapi.env`, uruchamia użytkownik `! secret-run …` albo ja za zgodą).
- **E4.3 AI w add-onie** (wydanie 0.9.0): opcje `llm_url`, `llm_model`, `llm_key` (typ `password`), jedno
  przetworzenie na gazetkę (cache po `flyer.id`), trafienia AI w tej samej linii porannej; panel bez zmian
  (opcjonalnie później). Kolejność i zakres E4.3 potwierdzamy po wynikach E4.2.

## Weryfikacja E4.0
Pokazuję surowe przykłady (1–2 oferty z każdego źródła) i liczby: ile bieżących promocji, ile trafia w listę E11.

## Wyniki E4.0 (2026-10-08)

| Źródło | Co daje | Kody artykułów | Daty | Pokrycie |
|---|---|---|---|---|
| `endpoints.leaflets.schwarz/v4/flyer` (gazetka) | strony: obraz, `altText`, `keyWords` (rozsypany tekst), `links`; `products` tylko artykuły ze sklepu online (np. 8 sztuk odzieży w gazetce 08.10) | nie (dla żywności) | tylko daty całej gazetki | pełne, ale bez struktury |
| `www.lidl.pl/q/api/search?category.id=10068374` (Żywność i napoje, publiczne, bez logowania) | `fullTitle`, `ians` (= kody z paragonów/kuponów, dopełnić zerami do 7 cyfr), cena i cena przed obniżką, cena Lidl Plus w `lidlPlus[]` (`highlightText` np. „-57%”, „-50% przy zakupie 3”) | **tak** | **tak** (`stockAvailability.badgeInfoV2[].validFrom/validUntil`, epoch) | częściowe: 53 produkty, głównie hity z pierwszych stron gazetki |
| **`offers.lidlplus.com/app/api/v4/PL/{sklep}/offers`** (z APK 17.11.6; anonimowy GET, nagłówki `Accept`, `Accept-Language: pl-PL`; sklep = kod z paragonu, np. `PL1094`) | `title`, `brand`, `offerType` (procent na produkt, „przy zakupie X”, cena specjalna), `priceBox` (`-20%`, „przy zakupie 2 szt.”, „2 + 1 gratis”), `productIds[]` | **tak** | **tak** (`startValidityDate`/`endValidityDate`, czas lokalny) | 16 promocji wielosztukowych w sklepie, rozłącznych z lidl.pl |
| `brochures.lidlplus.com/api/v2/PL/Brochures` (z APK) | te same gazetki co `leaflets.schwarz` + `offerStartDate`/`offerEndDate` | nie | daty gazetki | jak gazetka |

Próba dopasowania (na żywo, lista E11 z panelu, 187 kodów): **6 z 53 ofert to nasze produkty** (masło Pilos, kiwi,
filety z piersi XXL, banany luzem, winogrona, awokado) — dopasowanie po kodzie, bez AI. Część to kupony Lidl Plus,
które E3 i tak aktywuje → w powiadomieniu nie dublować z kuponami.
Luka: wiele promocji z gazetki 08.10 nie ma na lidl.pl (Milka, Fin Carré, krewetki, olej Kujawski, praliny, kawa,
piwo, jabłka) — są tylko w tekście stron gazetki, bez kodów.

Inne hosty z APK (`productshowcase`, `product-catalog`, `digital-leaflet`, `branddeals`, `personalized-campaigns`) bez
oczywistego publicznego endpointu ofert (404/400 bez parametrów) — nie drążone. APK usunięte po analizie.
Promocje z gazetki oznaczone „z aplikacją Lidl Plus” (kawa -60%, chemia -70%, praliny -80%, krewetki) to kupony —
obsługuje je E3 (auto-aktywacja), więc nie są luką E4.

**Wniosek:** dwa publiczne źródła z kodami i datami (lidl.pl Żywność ~53 + oferty sklepu ~16) dają dopasowanie po
kodzie bez AI i bez logowania. Luka: zwykłe obniżki z dalszych stron gazetki, których nie ma na lidl.pl (np. Milka,
olej Kujawski, jabłka) — tylko tekst gazetki, wymagałby AI.

## Wynik E4.1 (2026-10-08, 0.8.0 na żywo)

- `promotions.py`: `parse_web`, `parse_offers`, `PromotionRunner` (oba źródła równolegle, lista `latest` w pamięci do
  następnego porannego przebiegu — tabela okazała się zbędna, jedynym czytelnikiem jest powiadomienie);
  `History.main_store()`, `History.enabled_codes()`; linia „Promocje od dziś” w `notify.compose`.
- Na prawdziwych danych z 08.10: lidl.pl daje 4 zwykłe obniżki (reszta to ceny kuponowe Lidl Plus — robota E3),
  oferty sklepu 63 pozycje (16 ofert × kody); trafienie w listę E11: 1 (szynka, −20% przy 2 szt.).
  Wniosek: główna wartość promocji przyjdzie z gazetki (E4.2–E4.3).
- Po restarcie lista jest pusta do 07:00 — pierwszy prawdziwy odczyt źródeł z hosta HA: 2026-10-09 07:00.
