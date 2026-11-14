# ROADMAP: paragony z innych krajów (CZ, IT)

Status: **etap 0 zrobiony 2026-11-14 (wariant A), dalej wywiad i plany etapów 1–5; nic nie wdrożone.**

## Cel
Pobierać do add-onu e-paragony z zakupów w Lidlu za granicą (w 2026: Czechy, Włochy). Paragony są widoczne w aplikacji
Lidl Plus po przełączeniu kraju. Kwoty w statystykach i w Budżecie przeliczamy na PLN po średnim kursie NBP z dnia zakupu,
z zapisem oryginalnej kwoty i waluty (decyzja usera).

## Stan kodu (sprawdzone 2026-11-13)
- Kraj na sztywno: `lidl/app/src/lidl/settings.py:11` (`COUNTRY="PL"`, `LANGUAGE="pl-PL"`), użycie w `service.py:35,70`.
- Klient API już przyjmuje kraj: `client/api.py` (`/v3/{country}/tickets`, `/v3/{country}/tickets/{id}`).
- Założenie PLN wszędzie: `text.fmt_pln`, tabela `tickets` (`history.py:69`) bez kolumny waluty, `budget_feed.py`, widoki w `web/`.

## Niewiadoma (rozstrzyga etap 0)
Czy token z logowania „PL” dostaje paragony z `/v3/CZ|IT/tickets`, czy trzeba logować się osobno w każdym kraju.

## Etap 0 — spike (tylko odczyt, bez zmian w add-onie)
Skrypt: `docs/spike_countries.py`. Tokeny zostają w pamięci, wypisuje tylko liczby, daty, sumy, waluty i nazwy kluczy.

1. Uruchom (user, bo wymaga logowania w przeglądarce):
   `! cd /config/addons/ha-lidl-app/lidl/app && uv run python ../../docs/spike_countries.py PL`
2. Otwórz wypisany adres, zaloguj się, wklej nagłówek `Location` (`com.lidlplus.app://…code=…`).
3. Wynik:
   - **A**: CZ/IT zwracają paragony przy tokenie PL → jedno konto, lista krajów do pobrania.
   - **B**: 403 albo pusto → uruchom z `CZ`, potem `IT` jako argumentem; osobny token na kraj (model jak osobne konto w `accounts.py`).
4. Zapisz wynik (bez danych osobowych) w tym pliku, sekcja „Wynik etapu 0”.

Rollback: brak zmian do cofnięcia.

## Decyzje z wywiadu (2026-11-14)
- Produkty, Ceny, Oszczędności, kupony i nagrody zostają polskie; pozycje zagraniczne w osobnej tabeli `foreign_items`.
  Porównanie między krajami = osobna zakładka „Kraje” (K6), nie standardowe porównania.
- Sumy, Paragony, Miesiące i Budżet liczą zagranicę w PLN po kursie NBP (ostatni dzień roboczy przed zakupem), oryginał w nawiasie. Rytm (mapa, heatmapa) tylko PL.
- Kategorie dla Budżetu: AI na pozycjach CZ/IT. Parowanie z transakcją z karty: tolerancja kwoty 5%, kwota z banku po sparowaniu.
- Kraje z opcji `extra_countries` (start CZ, IT); import raz dziennie 07:00 + „Sprawdź teraz”; oba konta; pełna historia, dedup po `id`.
- Jedno wydanie zbiorcze po K1–K5 (Lidl, potem Budżet); K6 osobno po obejrzeniu prawdziwych danych.
- Zgoda usera 2026-11-14 („Go”): etapy idą po kolei bez czekania na zgodę; stop przy kroku spoza planu.

## Etapy (kontrakt Wykonawca w `docs/PLAN_COUNTRIES_K<n>.md`)
- **K1** model danych + pobieranie list + kurs NBP (migracja v6, `.pre-countries`, `extra_countries`) — `sonnet-worker` (migracja = ryzyko).
- **K2** szczegóły i pozycje zagraniczne (parser cs/it, `foreign_items`) — czeka na fixtures od usera (anonimowy fragment HTML CZ i IT) — `sonnet-worker`.
- **K3** widoki: flaga/oryginał w Paragonach, filtr kraju, linia „za granicą” w Miesiącach, Rytm tylko PL — `sonnet-worker`.
- **K4** kategorie AI + eksport do Budżetu + parowanie 5% w Budżecie (dwa repo) — `sonnet-worker`.
- **K5** wydanie zbiorcze: `simplify` → `code-review` (+ `silent-failure-hunter`, `pr-test-analyzer`, security-review diffu) → `release` Lidl, potem Budżet → weryfikacja na żywo (4 paragony CZ/IT).
- **K6** (później, osobny wywiad) zakładka „Kraje”: pary produktów PL↔CZ/IT (AI proponuje, user zatwierdza jak E21), koszyk porównawczy w PLN.

Otwarte rozpoznania (rozstrzyga K1/K2, nie wywiad): kształt pola `currency` na liście, format pozycji HTML cs/it, obecność EAN, historia sprzed 2 lat (offset ≥2).

## Wynik etapu 0
**2026-11-14: wariant A.** Jedno logowanie „PL” wystarcza; `/v3/CZ|IT/tickets` działają na tym samym tokenie
(spike odczytowy, `docs/spike_countries.py`, tokeny tylko w pamięci).
- Pobrane: PL 83 + 39 paragonów (offset 0/1), CZ 3 (+1 w offset 1), IT 1 (0 w offset 1). Zagranica to dziś garstka paragonów.
- Lista: te same klucze co PL, w tym `currency` (nie jest wartością prostą — prawdopodobnie obiekt; **sprawdzić kształt w etapie 1**,
  skrypt pomijał dicty), `totalAmount` w walucie kraju (CZ np. 175,4 / 2433,8 / 760,0 — korony; IT 43,91 — euro).
- Detal: te same klucze co PL, **bez `currency`** (waluta tylko z listy), jest `languageCode`, `htmlPrintedReceipt`, `isDeleted`.
- **Duplikat między oknami:** paragon CZ z 2025-11-15 jest zarówno w `yearOffset=0`, jak i `1` (okno kroczące ~12 mies.)
  → deduplikacja po `id` obowiązkowa przy imporcie wielu krajów/offsetów.
- Wniosek dla modelu: `country` + `currency` bierzemy z listy, pobieranie = pętla po `extra_countries` na jednym tokenie
  (nie trzeba modelu „osobne konto na kraj”).
- Otwarte do etapu 1: kształt `currency`; czy `totalAmount` w CZ to korony (nie hellery); format pozycji w HTML czeskim/włoskim
  (fixtures neutralne); czy `/v3/{country}/tickets` zwraca historię sprzed 2 lat (offset ≥2).
