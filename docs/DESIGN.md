# Design — Lidl Plus (nieoficjalny add-on)

Nieoficjalny, jasny styl wzorowany na wyglądzie aplikacji mobilnej Lidl Plus. Nie zawiera logo, znaków towarowych
ani fontów Lidl i nie jest z nimi powiązany; w stopce UI zostaje zastrzeżenie „nieoficjalny, niepowiązany z Lidl”.
Źródło: system „Lidl Plus styl” (Claude Design, prywatny) i makiety „Lidl Plus makiety”; tokeny żyją w
`lidl/app/src/lidl/web/static/app.css` (`:root`).

## Kolory
| Token | Wartość | Rola |
|---|---|---|
| `--surface` | `#ffffff` | tło ekranu na telefonie, karty, pola |
| `--surface-tint` | `#f5f8fc` | tło strony na komputerze (≥ 720 px) |
| `--surface-inset` | `#f1f2f4` | chipy statusu, komunikaty, pola tylko do odczytu |
| `--line` | `#dde0e3` | obrys kart i separatory (dekoracyjne) |
| `--control-border` | `#818b96` | obrys pól i przycisków wtórnych (≥ 3:1) |
| `--ink` / `--ink-muted` | `#1e2124` / `#636d79` | tekst główny / pomocniczy (5,3:1 na białym) |
| `--blue` | `#0050aa` | jedyny kolor akcji: przycisk główny, linki, numery kroków |
| `--blue-deep` | `#002466` | stan hover przycisku głównego |
| `--blue-soft` / `--blue-wash` | `#c2dfff` / `#f0f7ff` | numer kroku, awatar |
| `--green` / `--green-deep` | `#00a170` / `#00704e` | ptaszek (graficznie) / tekst „Połączone” |
| `--red-deep` | `#ad080f` | błędy i usuwanie (tekst 7,5:1) |

Żółty `#fff000`, bursztyn `#ffc400` i czerwień `#e60a14` z systemu dojdą z kuponami (E3).

## Typografia
Figtree (SIL OFL, lokalnie, wagi 400–800, latin + latin-ext). Tytuł ekranu 28/34 waga 800, sekcja 20/26 waga 700,
treść 16/22, podpisy 13–14. Ceny i rabaty (Barlow Condensed 800) dojdą z kuponami.

## Kształt i odstępy
Płaskie karty: obrys 1,5 px `--line`, promień 16 px, bez cienia. Przyciski, statusy i chipy to pigułki, pola 8 px.
Odstępy: 4 / 8 / 12 / 16 / 24 / 32 px; boczny margines ekranu 16 px, odstęp sekcji 24 px. Cele dotyku ≥ 44 px.
Kontener treści do 720 px, wyśrodkowany.

## Zasady
- Jeden kolor akcji (`--blue`); drugi przycisk to obrys `--control-border`, trzeci to link; usuwanie czerwonym tekstem.
- Stan zawsze słowem lub ikoną, nie samym kolorem (status „Połączone” z ptaszkiem, błąd z ikoną i ramką).
- Ikony kreskowe, inline SVG (24 px, obrys 1,75 px, okrągłe końce). Bez emoji, PNG i gradientów.
- Kroki są ponumerowane tylko tam, gdzie liczy się kolejność (logowanie).
- Cache WebView: HTML `no-store`, statyki z `?v=<wersja>` i `immutable`, wersja widoczna w stopce.
