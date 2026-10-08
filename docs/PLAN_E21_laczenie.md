# E21 Łączenie starych i nowych nazw — plan

## Context

Diagnoza E7.5 (2026-10-08, `docs/PLAN_E7_ceny.md`): 316 produktów ze starych paragonów (format NATIVE, kody
`n:<EAN>`, do 27.03.2026) — 20 pp. wydatków z 12 mies. — nie łączy się z nowymi kodami artykułów (paragony HTML),
bo most w `History._resolver` wymaga identycznej znormalizowanej nazwy, a stare paragony skracają nazwy inaczej
(„Winog.jas.bezp.500g” ↔ „Winogrono j.bezp.500”). Skutki: zaniżone liczby zakupów w Produktach, niepełna lista
kuponowa E11 i niskie pokrycie porównania cen E7 (45% po oknach 6 mies.).

Rozpoznanie: paragon HTML ma tylko kod artykułu Lidla (`data-art-id`), NATIVE tylko EAN (`codeInput`) — wspólnego
klucza nie ma, zostaje nazwa + sygnały pomocnicze (typ ważony/sztuki, cena, daty).

## Wywiad (2026-10-08)
- **Automatyzm:** pewne pary łączą się same (z możliwością cofnięcia), wątpliwe czekają na potwierdzenie.
- **Zakres:** tylko stary kod `n:` ↔ nowy kod HTML.
- **Miejsce:** zwinięta karta w Produktach („Do połączenia (N)”: „Połącz” / „To inne”; lista połączonych z „Rozdziel”).
- **Dopasowanie:** robi Claude, jednorazowo, poza add-onem (prośba użytkownika). Zbiór starych kodów jest zamknięty
  (od 27.03.2026 nie przybywa), więc silnik reguł w add-onie nie jest potrzebny.

## Ograniczenia
1. Korzystają domownicy (Produkty, Kupony E11, Ceny E7). Automatycznie nic się nie łączy poza parami, które Claude
   oznaczy jako pewne i które przejdą przegląd użytkownika na próbce.
2. Nic nie jest kasowane ani przepisywane w `items`: połączenia żyją w osobnej tabeli, „Rozdziel” przywraca stan.
3. Dane produktów (nazwy, ceny) nie trafiają do repo — eksport ląduje w katalogu tymczasowym sesji Claude.
4. Sukces: pokrycie porównania cen wyraźnie > 50%; przykładowe pary połączone; brak błędnych połączeń w próbce,
   którą ocenia użytkownik.

## Etapy (każdy po „go”, dokładne kroki przed startem)
- **E21.0 docs** ✅ — ten plan, wpis w ROADMAP.
- **E21.1 eksport kandydatów, 0.14.0:** `GET /produkty/laczenie/kandydaci.json` (tylko odczyt, Ingress): stare kody
  `n:` bez mostu i nowe kody HTML, na które nie wskazuje żaden stary kod; dla każdego: kod, nazwy (wszystkie
  warianty), ważony, mediana ceny półkowej, liczba zakupów, pierwszy i ostatni zakup. Test w `test_web.py`.
- **E21.2 dopasowanie (Claude, poza add-onem):** pobranie eksportu przez `playwright-ha`, dopasowanie par z oceną
  „pewne” / „do potwierdzenia” i uzasadnieniem; podsumowanie + próbka do oceny użytkownika przed importem.
- **E21.3 połączenia w add-onie, 0.14.1:** tabele `merges(old, new, status, created)` (`confirmed` | `proposed`) i
  `merge_rejects(old, new)`; `_resolver` najpierw `merges` (confirmed), potem identyczna nazwa; karta w Produktach
  (makieta przed kodem, skill `impeccable`); `POST /produkty/laczenie/import` (JSON par, jednorazowo przez
  `playwright-ha`). Weryfikacja: pokrycie w Cenach, liczby w Produktach i liście E11 przed/po.

Cofnięcie: E21.1 bez zmian w bazie; E21.3 — „Rozdziel” per para albo downgrade (tabele zostają, starsza wersja
ich nie czyta).

## E21.1 ✅ 0.14.0 na żywo (2026-10-08 19:43)
Eksport: **3 150 starych kodów** bez mostu (od 2019; 630 z ostatnim zakupem od 04.2025, 741 kupionych ≥ 3 dni) i
**188 nowych kodów** bez starszej historii. Wniosek do E21.2: dopasowujemy od strony nowych (188) — każdy nowy kod
szuka swoich starych odpowiedników (może być kilka wariantów nazw); stare bez pary to produkty, których już nie kupujemy.
