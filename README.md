# Lidl Plus — add-on Home Assistant (nieoficjalny)

Add-on, który łączy się z kontami Lidl Plus kilku osób w jednym domu i — etapami — zbiera paragony,
sprawdza kupony i gazetki pod kątem produktów, które naprawdę kupujecie, aktywuje pasujące kupony
i proponuje listę zakupów. Cel: **oszczędność** (nie przegapić promocji na to, co i tak kupujemy).

**Nie jest powiązany z Lidl ani Schwarz Group.** Korzysta z prywatnego API aplikacji mobilnej, czego regulamin
nie przewiduje — używasz na własne ryzyko (zmiany API, blokada konta).

## Stan

| Etap | Zakres | Status |
|---|---|---|
| E0 | Rozpoznanie API (logowanie, paragony, kupony, gazetki) | ✅ |
| E1 | Add-on, logowanie wielu kont, magazyn tokenów | ✅ 0.1.0 |
| E2–E6 | Historia paragonów, kupony, gazetki, lista zakupów, integracja z Budżetem | [docs/ROADMAP.md](docs/ROADMAP.md) |

## Instalacja

1. Home Assistant → Ustawienia → Add-ony → Sklep z dodatkami → ⋮ → **Repozytoria** → dodaj
   `https://github.com/miczu71/ha-lidl-app`.
2. Zainstaluj **Lidl Plus**, uruchom, otwórz panel „Lidl”.
3. Dodaj konto i zaloguj je (instrukcja na ekranie i w zakładce Dokumentacja).

## Bezpieczeństwo

- Hasło wpisujesz wyłącznie na stronie Lidla. Add-on dostaje tylko tokeny sesji.
- Tokeny leżą w `/data/accounts/<konto>.json` (uprawnienia 0600), poza opcjami i poza repozytorium.
- Wklejony adres logowania nie jest zapisywany ani logowany.

Licencja: MIT. Kod klienta API pochodzi z [Przemko92/home-assistant-lidlplus](https://github.com/Przemko92/home-assistant-lidlplus)
(MIT) — patrz [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
