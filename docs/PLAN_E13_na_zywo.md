# Plan E13 — Wyszukiwanie i zmiany na żywo, spójny okres rankingu (wydanie razem z E3 jako 0.5.0)

## Kontekst
Zgłoszenia użytkownika (2026-10-07, przed wydaniem E3):
1. **„Wykres” przy pierwszym produkcie rankingu „wyrzuca błąd”.** Diagnoza na żywych danych: „Banany Premium luz”
   (`n:50100`) mają w rankingu 120 zakupów, ale ostatni 13.12.2024. Ranking liczy **całą historię**
   (`History.ranking()` → `_products()` bez daty początkowej), a wykres domyślnie pokazuje **ostatnie 12 miesięcy**,
   więc link „Wykres” trafia w pusty zakres i panel pokazuje „Brak zakupów w tym zakresie” (wygląda jak błąd).
   Z zakresem „Od początku” wykres działa (90 miesięcy, 669 zł). Dodatkowo data „ostatnio 13 gru” jest bez roku.
2. Ranking bez filtra — z całej historii (potwierdzone w kodzie i na danych).
3. Prośba: **wyszukiwanie na żywo** jak w Budżecie (pole tekstowe, wyniki od razu) we wszystkich wyszukiwaniach
   add-onu; inne zmiany też na żywo.

Wzorzec z Budżetu (`ha-budget-app`, `_macros.html`): htmx (lokalny `htmx.min.js`), formularz z
`hx-get`, `hx-trigger="input delay:200ms"`, `hx-select`/`hx-target` na fragment z wynikami, `hx-replace-url`,
`hx-sync="this:replace"`; pole `type="search"`; licznik „N z M · wyczyść”.

## Ograniczenia (z wywiadu)
1. **Wspólny okres:** ranking „Najczęściej kupowane” liczony z zakresu dat wykresu (domyślnie 12 miesięcy,
   „Od początku” = cała historia); „Wykres” przy produkcie zawsze pokazuje jego dane; rok przy dacie „ostatnio”,
   gdy to nie bieżący rok.
2. **Wyszukiwanie na żywo:** Produkty (ranking + wybór produktu do wykresu), Kupony (kupony w tym tygodniu i
   lista „Kupowane regularnie”).
3. **Na żywo, bez przycisku i przeładowania:** kontrolki wykresu (znika „Pokaż wykres”), przełączniki
   auto-aktywacji (bez skoku strony), „Aktywuj” i „Sprawdź teraz” (stan „Sprawdzam…” odświeża się sam).
4. **Kolejność:** E13 przed wydaniem; jedno wydanie 0.5.0 z E3 i E13 (E3.5 na końcu).

Założenia (zaakceptowane):
- htmx skopiowany z Budżetu (licencja BSD, wpis w `THIRD_PARTY_NOTICES.md`), to samo makro; bez JS formularze
  działają jak dziś (progressive enhancement).
- Na Kuponach jedno pole „Szukaj” u góry filtruje obie sekcje.
- Lista rozwijana ~1000 produktów przy wykresie znika; zastępuje ją pole „Szukaj produktu” (wynik = wykres).
- Poza zakresem: łączenie produktów, którym Lidl zmienił nazwę i kod (np. „Banany Premium luz” ↔ „Banany luz”) —
  osobny pomysł w roadmapie.
- **Sukces:** „Wykres” przy każdym produkcie rankingu pokazuje dane; wpisanie fragmentu nazwy filtruje listy
  w ~200 ms bez przeładowania; kontrolki wykresu, przełączniki i aktywacja działają bez przeładowania i bez
  skoku strony, a adres URL odtwarza stan po odświeżeniu.

## Etapy (każdy z checkpointem; przed etapem dokładne kroki i „go”)
- **E13.0 Dokumentacja:** ten plik + wpis w `docs/ROADMAP.md`.
- **E13.1 Ranking według zakresu dat:** `History.ranking(start, end)`; ekran Produkty liczy ranking z zakresu
  wykresu; link „Wykres” zachowuje zakres; rok przy „ostatnio”; testy.
- **E13.2 Produkty na żywo:** htmx + makro wyszukiwania; pole „Szukaj produktu” filtruje ranking i zastępuje
  listę rozwijaną; kontrolki wykresu bez przycisku; weryfikacja w przeglądarce (komputer i telefon).
- **E13.3 Kupony na żywo:** wyszukiwanie w obu sekcjach; przełączniki, „Aktywuj” i „Sprawdź teraz” bez
  przeładowania (podmiana fragmentu); weryfikacja w przeglądarce.
- **Wydanie:** E3.5 z `docs/PLAN_E3_kupony.md` obejmuje E13 (0.5.0).

Cofnięcie: revert commitów; htmx to jeden plik statyczny.
