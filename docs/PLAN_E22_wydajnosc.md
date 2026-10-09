# E22 Wydajność, domyślne Kupony, gazetka bez stron nie-spożywczych

## Kontekst (zlecenie 2026-10-09)
- Domyślnym widokiem panelu mają być Kupony.
- „Sprawdź teraz” w Kuponach jest zbędne — kupony sprawdzają się same codziennie o `run_time`.
- Przełączanie zakładek „trochę trwa” — dokładna analiza i optymalizacja.
- Gazetka: oszczędzać limity modelu, skupić się na stronach spożywczych.

## Pomiar wyjściowy (0.17.0 na żywo, `fetch` w ramce ingress, 3 próby)

| Zakładka | Serwer | HTML |
|---|---|---|
| Konta | ~25 ms | 5 KB |
| Rytm | ~70 ms | 24 KB |
| Paragony | ~150 ms | 18 KB |
| Miesiące | ~350 ms | 14 KB |
| Produkty | ~350–600 ms | 13 KB |
| Kupony | ~1,1 s | 413 KB (4 900 węzłów DOM, 460 formularzy) |
| Ceny | ~2,0–2,7 s | 16 KB |

Ingress i sieć ~20 ms, statyki z cache. Czas to obliczenia serwera:
1. `price_overview` liczy `_price_changes` od nowa dla każdego miesiąca serii (~79 × wszystkie pozycje).
2. Każde żądanie skanuje całe `items`; `_resolver()` buduje się kilka razy na żądanie, choć dane zmieniają się
   zwykle raz dziennie.
3. Kupony renderują ~230 wierszy z dwoma formularzami htmx każdy.
4. Handlery `async def` wołają SQLite synchronicznie — długie liczenie blokuje inne żądania.

## Ustalenia
- **Kto korzysta:** domownicy w panelu HA (telefon, WebView) i poranny przebieg. Bez zmian w logice kuponów i kontach.
- **Gazetka:** pomijamy strony informacyjne/reklamowe, porównania cen z konkurencją (ceny regularne), odzież,
  narzędzia, rośliny, znicze. Żywność i drogeria/chemia zostają (lista ma ręczniki, papier toaletowy itp.).
  Filtr po `altText` strony (opis od Lidla), bez AI. Wątpliwa strona → zostaje.
- **Sukces:** każda zakładka < 300 ms w tym samym pomiarze; gazetka 8.10 → ~14 paczek zamiast 20 bez utraty
  stron z trafieniami z wzorca E4.2.

## Etapy
- **E22.0** ten plan + ROADMAP.
- **E22.1** `/` pokazuje Kupony (Konta pod `/konta`), baner podsumowania miesiąca na Kuponach; bez „Sprawdź teraz”
  i trasy `POST /kupony/sprawdz` (odświeżanie w trakcie porannego przebiegu zostaje).
- **E22.2** cache wyników `History` (most nazw, produkty per zakres, wiersze i przegląd Cen) do następnego zapisu
  pozycji lub połączeń i do końca dnia; rozgrzewanie po starcie i po porannym imporcie (`History.warm`).
  Zmiana względem pierwotnego planu: zamiast `total_changes` (rośnie też przy zapisach kuponów i paczek gazetki
  co 2 min, cache by nie żył) licznik w tabeli `revision` podbijany triggerami na `items` i `merges`; zamiast przepisywać serię Cen na jedno przejście
  (dokładna mediana w oknach przesuwnych = dużo kodu) — rozgrzewanie, więc 2 s liczy się raz dziennie w tle.
- **E22.3** lżejsze wiersze „Kupowane regularnie” (mniej HTML i formularzy).
- **E22.4** filtr stron gazetki + testy na zapisanym JSON gazetki 8.10.
- **E22.5** wydanie 0.18.0, pomiar na żywo przed/po.

## Wynik (0.18.0 na żywo, 2026-10-09, ten sam pomiar)

| Zakładka | Przed | Po (kolejne wejścia) |
|---|---|---|
| Kupony (`/`) | ~1,1 s, 413 KB | ~240 ms, 341 KB |
| Ceny | ~2,0–2,7 s | ~31 ms |
| Produkty | ~350–600 ms | ~170–210 ms |
| Miesiące | ~350 ms | ~205 ms |
| Paragony | ~150 ms | ~110 ms |
| Rytm | ~70 ms | ~65 ms |
| Konta | ~25 ms | ~18 ms |

Wyszukiwanie na żywo w Kuponach ~390 ms (ranking do „Inne kupowane produkty”) — do ewentualnej poprawki.
Gwiazdka i przełącznik zwracają jeden wiersz (sprawdzone na dev; na żywo bez klikania, żeby nie zmieniać danych).
Pierwsze wejście w zakładkę po restarcie bywa wolniejsze, dopóki rozgrzewanie (5 s po starcie) nie skończy liczenia.
