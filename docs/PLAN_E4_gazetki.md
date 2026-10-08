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

## Wyniki E4.2 (2026-10-08, próba na gazetce 8.10, 20 stron, wzorzec: 10 pewnych + 23 niejednoznaczne)

Skrypty poza repo: `~/dev/lidl-spike/probe_leaflet_ai.py` (tryb `text`: `pdftotext -layout`, paczki po 5 stron;
tryb `image`: `pdftoppm` 100 dpi JPEG, strona na zapytanie), `score_leaflet_ai.py`; klucz: `secret-run freellmapi`.

| Wejście / model | Pewne | Fałszywe | Kupon LP poprawnie | Uwagi |
|---|---|---|---|---|
| tekst / `gpt-oss-120b` | 6/10 | 0 | 6/9 | gubi strony z zepsutą czcionką (Pikok, Rzeźnik: „Par wki”, „P K K”); 97 s |
| tekst / `llama-3.3-70b-fp8-fast` | 2/10 | 1 | 4/4 | słaby; 21 s |
| obraz / `gemini-3.5-flash` | 8/10 | 0 | 13/13 | 100% na przetworzonych stronach; od ~13. obrazu `429` (limit darmowy), str. 52–74 nieprzetworzone |
| obraz / `qwen3-vl-235b-a22b-instruct` | — | — | — | `503` na każdym zapytaniu (niedostępny w puli) |
| obraz / `gemma-4-31b-it` | 2/10 | 0 | 2/2 | poprawnie na 5 przetworzonych stronach; 15/20 błędów: Google `500`/`503 high demand` → cooldown klucza we freellmapi → `502` (inni dostawcy Gemmy w puli bez obsługi obrazów); ~30 s/stronę |

Wnioski: tekst PDF wystarcza na części stron, ale traci oferty na stronach z zepsutym tekstem; obraz + Gemini czyta
wszystko (mechanika „1+1”, daty, kupon LP) bez fałszywych trafień, ograniczeniem jest limit zapytań. Zwykłe
(niekuponowe) obniżki na nasze produkty w tej gazetce: parówki z szynki XXL, śliwki, salami — żadnej nie było w
źródłach z kodami (E4.1).

**Limity darmowe (tabela `models` we freellmapi, 2026-10-08; Google nie publikuje już liczb poza AI Studio):** Gemini
Flash/Flash-Lite 3.x — 10–15 RPM, **20 RPD na model**, 250k TPM; Gemma 4 (26B, 31B) — 15 RPM, **1000 RPD**. RPD
resetuje się o północy czasu pacyficznego, limity liczone per projekt. Dzisiejsze `429` Gemini = wyczerpane 20 RPD.

## E4.3 — AI w add-onie (wydanie 0.9.0)

**Rewizja 2026-10-08 (po teście paczek):** wykrywanie „trudnych” stron z tekstu nie działa — udział 1–2-literowych
„słów” 0,18–0,72 prawie wszędzie, próg obejmujący zgubione strony wybiera 88/97; część pominięć `gpt-oss` to słabe
dopasowanie przy czytelnym tekście (str. 56). Test **paczek obrazów** (`gemini-3.6-flash`, 5 stron/zapytanie,
4 zapytania): w 2 udanych paczkach 6/6 pewnych, 0 fałszywych, kupon LP 6/6; 2 paczki `503 high demand` (cooldown
freellmapi → `502`), nie limit. Paczka ~13 s, ~8,7k tokenów wejścia. Limit Gemini Flash to 20 **zapytań**/dzień
na model, więc cała gazetka (~20 paczek) mieści się w jednym–dwóch modelach.

Projekt:
- **Która gazetka:** z `v4/overview` pozycje o nazwie „Gazetka” (jedna na tydzień); JSON gazetki
  (`flyerJson`) daje obrazy stron (`pages[].image`, 1200 px) — bez PDF i bez popplera w obrazie Alpine.
- **Paczki po 5 stron** w tabeli (postęp przetrwa restart); jedno zapytanie = 5 obrazów (base64) + lista E11.
- **Kolejka modeli wizyjnych** (`llm_vision_models`): `gemini-3.5-flash` → `gemini-3.6-flash` →
  `gemini-3.7-flash` → `gemma-4-31b-it`; `429` → następny model, `5xx` → ta sama paczka później (~10 min).
- **Tempo:** w tle jedna paczka na raz, co ~2 min, aż do końca gazetki.
- **Wynik:** trafienia (kod z listy E11, nazwa z gazetki, rabat, daty DD.MM → rok z gazetki, kupon LP) w tabeli;
  kupony Lidl Plus pomijamy (E3); linia „Promocje od dziś” łączy E4.1 i gazetkę bez powtórzeń.
- **Opcje:** `llm_url`, `llm_key` (`password`), `llm_vision_models`. Puste adres/klucz = gazetka wyłączona.

## Wynik E4.3 (2026-10-08)

- 0.9.0 (`2b8b2a5`, wydanie `1485242`): `leaflet.py`, tabele `leaflet_batches`/`leaflet_matches`, opcje `llm_*`,
  odświeżanie promocji przy starcie; CI znów zielone (`eb193aa`, mypy od 0.7.1).
- 0.9.1: przeciążenie modelu (Google `503 high demand`, freellmapi `502`) → od razu następny model; modele z limitem
  w zbiorze `_refused` (czyszczonym, gdy wszystkie odmówią).
- Na żywo po restarcie z opcjami: gazetka 8.10 wykryta (97 stron, 20 paczek); `gemini-3.5-flash` i `3.6` z wyczerpanym
  dziennym limitem po testach E4.2; `401` z lidl.pl przy pierwszym starcie było jednorazowe (drugi start: 200).
