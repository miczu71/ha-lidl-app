# Changelog

## 0.1.0

- Panel Ingress: dodawanie, logowanie, sprawdzanie i usuwanie kont Lidl Plus.
- Logowanie ręczne przez przeglądarkę (OAuth PKCE), tokeny w `/data/accounts/` (0600), zapis atomowy.
- Blokada per konto przy odświeżaniu tokenu (Lidl rotuje refresh token).
