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

**Wniosek:** E20 = zdrapki (przypomnienie o ważności) + Coupon Plus (postęp i brakująca kwota).

## Projekt E20.2–E20.6 (wywiad 2026-10-08, zatwierdzony)

Ustalenia:
1. Cel: nie tracić zdrapek (ważne ~3 dni) — priorytet; Coupon Plus — pomoc w planowaniu zakupów pod próg.
2. Zdrapki: linia w porannym powiadomieniu 07:00 (`notify.family`, z osobą) + w dniu wygaśnięcia przypomnienie
   ~18:00 do obojga (`notify.family`), jeśli zdrapka nadal jest na liście.
3. Coupon Plus: tylko panel, bez powiadomień — w formie graficznej jak w aplikacji.
4. Automatycznie tylko odczyt (GET) i powiadomienia; add-on nie zdrapuje (`redeemed`, `start`, `view` — nigdy).
5. Sukces: żadna zdrapka nie wygasa niezauważona; w panelu per konto „brakuje X zł do progu Y, do <data>”.

Założenia do sprawdzenia: zdrapuje się w aplikacji Lidl; zdrapana zdrapka znika z listy (E20.2).

**Dane:** `client/api.py` — `lotteries()` (`userId` = `sub` z tokenu) i `coupon_plus()` (`Segment-Ids`). Bez tabel
w bazie: stan w pamięci, odświeżany przy porannym przebiegu, o 18:00, przy „Sprawdź teraz” i przy starcie add-onu.
Nowy `rewards.py` zbiera oba źródła dla wszystkich kont; błąd jednego konta nie blokuje reszty (jak `CouponRunner`).

**Powiadomienia:** `notify.compose` dostaje linię „Zdrapki: Osoba 1 — do śr 23:59”; zdrapka sama też wysyła poranne
powiadomienie (gdy brak kuponów). Drugi `at_time_loop` o 18:00 (stała godzina, bez opcji) odpytuje tylko zdrapki i przy
wygasających dziś wysyła „Lidl: zdrapka wygasa dziś o 23:59 (Osoba 1)”, tag `lidl-zdrapki` (nie zastępuje porannego),
tap → panel.

**Panel:** sekcja „Nagrody” w zakładce Kupony, nad kuponami, per konto:
- Coupon Plus graficznie (jak w aplikacji): pasek z progami rozmieszczonymi proporcjonalnie (`left = value / max`),
  wypełnienie do `reachedAmount`, dymek z kwotą, ✓ przy `Won`, prezent przy `Uncompleted`, pole „Następny kupon”
  (`prize.coupon.title` + `discountTitle`), „Dni do końca” z `endDate`, dodatkowo „brakuje X zł do Y zł”. Czysty
  HTML/CSS, ikony SVG (iconify), styl D1, bez grafik Lidla.
- Zdrapki: wiersz „Zdrapka z 05.10 — kończy się dziś” (wyróżnienie w ostatnim dniu); bez przycisku „Odbierz”.
- UI przez skill `impeccable`, weryfikacja Playwright przed pokazaniem.

**Podetapy** (przed każdym dokładne kroki i „go”):
- **E20.2 weryfikacja:** po zdrapaniu zdrapki przez użytkownika `probe_rewards.py --only zdrapki` — czy znika z listy
  (logika „nadal jest”); sonda konta osoby 2, jeśli spike ma jego tokeny.
- **E20.3 dane:** klient API, `rewards.py`, testy na neutralnych fixtures.
- **E20.4 powiadomienia:** linia poranna, job 18:00, testy `compose`.
- **E20.5 panel:** sekcja „Nagrody”.
- **E20.6 wydanie 0.7.0:** skill `release`, weryfikacja na żywo.

## Stan

- [x] E20.0 rozpoznanie APK — 2026-10-08: wykonalne, endpointy i pola wyżej. Katalogi `apk/` i `tools/` usunięte.
- [x] E20.1 próbny GET z tokenem jednego konta — 2026-10-08: zdrapki i Coupon Plus działają, pieczątki 404 (brak akcji).
- [x] Wywiad i projekt E20.2–E20.6 — 2026-10-08.
- [x] E20.2 weryfikacja po zdrapaniu — 2026-10-08: po zdrapaniu w aplikacji lista `lotteries` osoby 1 pusta
  (`len=0`) → obecność na liście = niezdrapana, `status` niepotrzebny. Spike nie ma tokenów osoby 2 — jej konto
  sprawdzamy na żywo w E20.6 (add-on).
- [x] E20.3 dane: klient API (`lotteries`, `coupon_plus`, 404 → None), `rewards.py`, testy — 2026-10-08 (0942bfc).
- [x] E20.4 powiadomienia: linia poranna, job 18:00 (`EVENING`, tag `lidl-zdrapki`) — 2026-10-08.
- [x] E20.5 panel „Nagrody” (zdrapki, Kupon Plus graficznie, odczyt przy starcie) — 2026-10-08.
- [x] E20.6 wydanie 0.7.0 — 2026-10-08 ~01:10 na żywo (oba konta: Kupon Plus czytany, zdrapek brak; konsola i log czyste). Do obserwacji: poranne 07:00 i 18:00. Znane: etykiety progów nachodzą przy bliskich progach (50/300/500 zł na początku akcji) → 0.7.1.
- [x] 0.7.1 (2026-10-08): podpis ma zawsze najbliższy i ostatni próg, pozostałe tylko przy ≥ 20% paska odstępu
  (`LABEL_GAP`); rabat nagrody bez „*”. Na żywo 390 px: bez nachodzenia. Do obserwacji nadal: przypomnienie 18:00
  (dziś bez zdrapek, więc nie wyśle się).
