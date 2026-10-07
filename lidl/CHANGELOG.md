# Changelog

## 0.3.0

- Nowy ekran **Produkty** (zakładka obok Kont): oszczędności z dotychczasowych paragonów (łącznie i z ostatnich 12 miesięcy), ranking najczęściej kupowanych produktów (liczba zakupów, ostatnia cena, średni cykl) oraz wykres wydatków.
- Wykres wydatków w dowolnym zakresie dat, krok tydzień / miesiąc (domyślny) / kwartał / rok, opcjonalnie dla jednego produktu, w złotych lub sztukach.
- Import historii paragonów: przycisk **Pobierz historię** przy koncie (pierwszy raz, wszystkie lata, powoli i z wznawianiem), potem codziennie tylko nowe paragony. Produkt to kod artykułu z paragonu.
- Baza historii w `/data/history.db` (SQLite) wchodzi do kopii zapasowych add-onu — traktuj kopie jak dane poufne (to Wasze zakupy).

## 0.2.0

- Nowy wygląd panelu wzorowany na aplikacji Lidl Plus (styl „Lidl Plus styl”, `docs/DESIGN.md`): płaskie karty, pigułkowe przyciski, awatary kont, statusy z ikoną, ponumerowane kroki logowania.
- Font Figtree (OFL) zamiast Inter i Source Serif; ikony inline SVG.
- Układ zgodny z makietami na telefon i komputer; funkcje bez zmian.

## 0.1.0

- Panel Ingress: dodawanie, logowanie, sprawdzanie i usuwanie kont Lidl Plus.
- Logowanie ręczne przez przeglądarkę (OAuth PKCE), tokeny w `/data/accounts/` (0600), zapis atomowy.
- Blokada per konto przy odświeżaniu tokenu (Lidl rotuje refresh token).
