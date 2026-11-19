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
- Flagi krajów paragonów (CZ, IT; inne: neutralna `i-flag-other`) to własne proste SVG 24×16 w sprite'cie z makra
  `flag_sprite` (`_macros.html`), użycie `flag(kod)`; 18×12 px, promień 2 px, obrys `--line`. Kwota główna zawsze w PLN,
  oryginał w nawiasie (`pr__orig`, `fmt_money`), nigdy sama flaga jako jedyny nośnik informacji (jest `aria-label`).

## Biedronka (D2, 2026-11-19)
Sekcje tylko dla Biedronki (konto i logowanie, paragon, oszczędzanie E28.5) mają własny, ciemny styl pod zakresem
`.chain-biedronka` w `app.css`; styl Lidla poza zakresem się nie zmienia. Źródło: system „Biedronka” (Claude Design,
prywatny, https://claude.ai/artifact/FpBQURrSJZKhU9QXDmHxJr), makiety „Makiety Biedronki”, zrzuty aplikacji lokalnie
w `~/dev/biedronka-design-refs` (poza repo, dane osobowe). Bez logo, maskotki i fontów Biedronki (Figtree zostaje).
- Zakres nadpisuje te same tokeny (`--surface`, `--ink`, `--blue` jako koral `#f2605b` z tekstem `#17181f`…), więc
  istniejące komponenty (karty, przyciski, pola) działają w nim bez zmian. Czerwień marki `--bdr-ladybug` tylko na dużych polach.
- Żółty (`--bdr-sun`) zarezerwowany dla oszczędności (`.bdr-saving`, „Taniej!”), tekst zawsze `--bdr-on-sun`; turkus
  informacja, zieleń stan dodatni, pomarańcz `--bdr-shake` tylko kafle gier.
- Akcent sieci we wspólnych widokach (styl Lidla): `.chain-tag--lidl` / `.chain-tag--biedronka` (pigułka z kropką
  `#0050aa` / `#d6192c`), segmenty filtra `?siec=` z kropką sieci; wykresy: Lidl niebieski, Biedronka czerwony, zawsze z etykietą.
- Rollback: usunąć blok `.chain-biedronka` … `.bdr-saving` z `app.css` i tę sekcję.
