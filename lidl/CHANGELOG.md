# Changelog

## 0.2.0

- Nowy wygląd panelu wzorowany na aplikacji Lidl Plus (styl „Lidl Plus styl”, `docs/DESIGN.md`): płaskie karty, pigułkowe przyciski, awatary kont, statusy z ikoną, ponumerowane kroki logowania.
- Font Figtree (OFL) zamiast Inter i Source Serif; ikony inline SVG.
- Układ zgodny z makietami na telefon i komputer; funkcje bez zmian.

## 0.1.0

- Panel Ingress: dodawanie, logowanie, sprawdzanie i usuwanie kont Lidl Plus.
- Logowanie ręczne przez przeglądarkę (OAuth PKCE), tokeny w `/data/accounts/` (0600), zapis atomowy.
- Blokada per konto przy odświeżaniu tokenu (Lidl rotuje refresh token).
