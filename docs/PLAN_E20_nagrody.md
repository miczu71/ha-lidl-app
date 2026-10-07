# Plan E20 — zdrapki, progi nagród, Pieczątka Plus

Cel etapu: postęp do progu nagrody („brakuje 23 zł”), przypomnienie o niezdrapanych zdrapkach i ich ważności.
Najpierw rozpoznanie (E20.0): czy i jak API udostępnia te dane. Bez tego etap odpada.

## Wyniki wstępnego rozpoznania (2026-10-07)

- Żaden znany klient API (upstream Przemko92/home-assistant-lidlplus, Andre0512/lidl-plus) nie obsługuje zdrapek,
  progów ani pieczątek — znają tylko `tickets`, `coupons`, `profile`, `segments`.
- DNS (bez logowania; zmyślona nazwa się nie rozwiązuje, więc to nie wildcard): istnieją
  `purchaselottery.lidlplus.com` (prawdopodobnie zdrapki), `couponplus.lidlplus.com` (progi „wydaj X → kupon”),
  `stampcard.lidlplus.com` (Pieczątka Plus); `/` na dwóch pierwszych zwraca 404. Nie istnieją: `lotteries`,
  `scratchcards`, `rewards`, `stamps`, `loyalty`, `goals`, `collecting`.
- Nasze dane: pole `collectingModel` w szczegółach paragonu jest `null` we wszystkich próbkach; w kuponach tylko typy
  `Standard` i `AssignablePromotion`. Upstream wymienia typ `PRIZE` (nagrody ze zdrapek jako kupony) — jeśli się
  pojawi, przypomnienie o niewykorzystanej nagrodzie jest możliwe już dziś; niezdrapane zdrapki i postęp do progu — nie.
- Ścieżki API na tych hostach nieznane → analiza statyczna APK (plan awaryjny z sekcji „Ryzyka” roadmapy).

## Ograniczenia środowiska

- Kontener nie ma Javy (jadx jej wymaga); nic nie instalujemy w `~/.local`.
- Wolne ~2 GB RAM z 31 GB (host produkcyjny) — jadx na dużej aplikacji może wywołać OOM i zabić stacki. Dlatego
  najpierw lekka analiza napisów z `.dex` w Pythonie; jadx tylko w razie potrzeby, z limitem pamięci.
- Strony APKPure/APKMirror zwracają 403 dla `curl`; API `api.pureapk.com/m/v3/cms/app_version?package_name=com.lidl.eci.lidlplus`
  (nagłówki `x-cv`, `x-sv`, `x-abis`, `x-gp`) odpowiada 200 i zawiera linki `download.pureapk.com/b/APK…`;
  najnowsza wersja prawdopodobnie 17.9.3.

## E20.0 — kroki

| # | Krok | Szczegóły |
|---|---|---|
| 1 | Katalogi | Pobrany plik w nowym, pustym `~/dev/lidl-spike/apk/` (poza repo); skrypty osobno w `~/dev/lidl-spike/tools/` |
| 2 | Pobranie | `curl` API APKPure → link APK → `curl -L` do `apk/`; zapisać sha256 i wersję |
| 3 | Pochodzenie | Certyfikat podpisu z `META-INF/*.RSA` (`openssl pkcs7 -inform DER -print_certs`), oczekiwany wystawca Lidl. APK nigdy nie uruchamiamy |
| 4 | Lekka analiza | `python3 -I tools/dex_strings.py apk/<plik>.apk`: napisy z `classes*.dex`, filtr `purchaselottery`, `couponplus`, `stampcard`, `collectingModel`, `scratch`, `lottery`, ścieżki `v\d/{country}`; wynik: metody, ścieżki, parametry, nazwy pól (próg, postęp, ważność) |
| 5 | Tylko jeśli 4 nie wystarczy (osobna zgoda) | Temurin JRE (tarball) + jadx w `tools/`, `-Xmx1500m -j 2`, tylko znalezione klasy |
| 6 | Wynik | Endpointy i pola przy E20 w `docs/ROADMAP.md` + decyzja wykonalne/odpada; bez tokenów i danych kont |
| 7 | Sprzątanie | `rm -rf ~/dev/lidl-spike/apk ~/dev/lidl-spike/tools` po zapisaniu wniosków |

Potem, za osobną zgodą: jeden GET na znaleziony endpoint z tokenem jednego konta (ścieżka i nagłówki jak w aplikacji),
skrypt `~/dev/lidl-spike/probe_rewards.py`, uruchamia użytkownik (`! …`) albo ja ad hoc po jego zgodzie.

**Ryzyka:** APKPure to źródło trzeciej strony (plik może być zmodyfikowany) — nie uruchamiamy, sprawdzamy podpis.
Kroki 1–4 nie dotykają kont Lidl (bez ryzyka blokady). ~100 MB na dysku.
**Cofnięcie:** usunięcie `apk/` i `tools/`; nic poza `~/dev/lidl-spike` się nie zmienia.

## Stan

- [ ] E20.0 rozpoznanie APK — plan zapisany 2026-10-07, czeka na start w nowej sesji.
