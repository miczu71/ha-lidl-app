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

## Wyniki E20.0 (2026-10-08)

APK `com.lidl.eci.lidlplus` 17.11.6 z APKPure (sha256 `d980be1b…ae9323f`), podpis v2: Lidl E-Commerce International
GmbH & Co. KG, Neckarsulm (cert. 2017–2042) — oryginał. Bez v1 (`META-INF/*.RSA`). Analiza: tablice napisów `.dex`,
adnotacje Retrofit i stałe z adapterów Moshi (Python, bez jadx — krok 5 niepotrzebny). R8 zaciemnia klasy, ale ścieżki,
nagłówki i klucze JSON są jawne. Przypisanie interfejsu do hosta jest pośrednie (pakiet UI, typ modelu) — potwierdzi GET.

| Funkcja | Host (`https://<host>.lidlplus.com/api/`) | Endpointy | Kluczowe pola |
|---|---|---|---|
| Zdrapki / ruletka / „special” | `purchaselottery` | `GET v2/{country}/lotteries?userId=`, `GET v2/{country}/lotteries/{id}`, `PUT …/{id}/redeemed` (zdrapanie — nie wołamy) | `id`, `type` (Scratch/Roulette/Special), `status` (Available/Used/Expired/MinimumHours/None), `creationDate`, `expirationDate`, `promotionCode`; szczegóły: `prize`, `legalTerms` |
| Coupon Plus (progi „wydaj X → kupon”) | `couponplus` (prawdop.) | `GET v4/{country}/user/promotions` (nagłówek `Segment-Ids`), `PUT …/{id}/start`, `PUT …/{id}/goals/view` | `promotionId`, `endDate`, `clusters[]`: `status`, `reachedAmount`, `reachedPercent`, `goals[]`: `status`, `value`, `prize` (`coupon`/`discount.amount`) |
| Pieczątki — loteria | `stampcard` | `GET v3/{country}/user/promotions?storeId=`, `GET …/{id}/detail`, `…/congrats`; v4 z `cards/send`, `legalterms/accept` | `unitsAchieved`, `unitsPerPrize`, `unitValue`, `maxUnitsPerPurchase`, `endDate`, `participationsToSend`, `prizes[]` |
| Pieczątki — nagrody (kupony) | `stampcard` | jw. (`v3 …/cards/viewed`, `started`) | `unitsAchieved`, `completedCards`, `coupons[]` (`couponId`, `isRedeemed`) |
| Pieczątki — benefity | `stampcardbenefits` | jw. | `unitsAchieved`, `completedCards`, `unitsAvailable` (`available`/`total`), `maxBenefitsPerUser` |

Inne trafienia: `GET /bff-api/v3/{countryCode}/loyaltytab` (host `loyaltytab`, w APK tylko stg/uat — zbiorczy ekran
„lojalność”, prawdopodobnie agreguje powyższe), `GET v1/{country}/loyalty`. Ekran aplikacji zna też OPEN_GIFT,
SECRET_BOXES, DAILY_DEALS, BADGES (poza zakresem E20).

**Wniosek: wykonalne** — każdy z trzech celów (niezdrapane zdrapki z datą ważności, postęp do progu Coupon Plus,
postęp pieczątek) ma GET tylko do odczytu. Niewiadome: które promocje są aktywne w PL, skąd `userId` (prawdop. `sub`
z tokenu) i czy hosty przyjmują nasz token bez dodatkowych nagłówków. Rozstrzyga E20.1.

**E20.1 (za osobną zgodą):** `probe_rewards.py` — po jednym GET listy na `purchaselottery`, `couponplus`, `stampcard`,
`stampcardbenefits`, jedno konto, tylko odczyt (bez `start`, `redeemed`, `view`); wypisuje status HTTP i nazwy kluczy
oraz liczności, bez surowych odpowiedzi.

## Wyniki E20.1 (2026-10-08, konto osoby 1, tylko GET)

`~/dev/lidl-spike/probe_rewards.py` (wypisuje strukturę i pola z białej listy, bez tokenu i `userId`).

- **Zdrapki — działa (200).** `GET purchaselottery …/v2/PL/lotteries?userId=<sub z tokenu>` → lista; element:
  `id`, `promotionId`, `promotionCode`, `type` (`Scratch`), `creationDate`, `expirationDate` (lokalna strefa, koniec
  dnia), `logo`, `background`, `translations`. Brak pola `status` — lista zawiera tylko niezdrapane (do potwierdzenia
  po zdrapaniu). Ważność krótka: utworzona 05.10 wieczorem, ważna do 08.10 23:59 (3 dni) → przypomnienie ma sens.
- **Coupon Plus — działa (200)** bez dodatkowych parametrów (nagłówek `Segment-Ids` jak przy kuponach).
  `promotionCode`, `type` (`Standard`), `endDate`; `clusters[]`: `type` (`Store`), `status` (`Active`),
  `reachedAmount` (335,7), `reachedPercent` (22,38 → ostatni próg 1500 zł), `goals[]` (5): `value` (50, 300, 500, …),
  `status` (`Won`/`Uncompleted`), `prize.type` (`Coupon`), `prize.coupon.title` (nagroda). „Brakuje do progu” =
  pierwszy `Uncompleted.value − reachedAmount`.
- **Pieczątki (`stampcard` v3/v4, `stampcardbenefits` v3):** bez `storeId` → 400; ze `storeId` (=`storeCode` z
  paragonu) → 404 — najpewniej brak aktywnej akcji pieczątkowej dla konta. Do sprawdzenia, gdy w aplikacji pojawi
  się Pieczątka Plus; do tego czasu poza zakresem.

**Wniosek:** E20 = zdrapki (przypomnienie o ważności) + Coupon Plus (postęp i brakująca kwota). Następny krok: wywiad
o kształcie funkcji (gdzie pokazać, kiedy i komu powiadomienie, oba konta), potem plan E20.2+.

## Stan

- [x] E20.0 rozpoznanie APK — 2026-10-08: wykonalne, endpointy i pola wyżej. Katalogi `apk/` i `tools/` usunięte.
- [x] E20.1 próbny GET z tokenem jednego konta — 2026-10-08: zdrapki i Coupon Plus działają, pieczątki 404 (brak akcji).
