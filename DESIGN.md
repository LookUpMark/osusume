# DESIGN.md — design system "Seanime"

Il design language di Osusume: dark-only, contenuto-prima, tipografia Geist. Questo documento è la spec di riferimento per qualunque modifica UI; i valori canonici vivono in `frontend/src/design-system/tokens.css` (importato prima di `styles.css`). Vincoli architetturali in `frontend/README.md` (contratti `lib/logic/`, marker `data-od-id`, i18n).

## Principi

1. **Contenuto prima del contenitore.** Poster e numeri parlano; le cornici sono sottili (`--border`), i pannelli scuri nonnerini, le statistiche sono numeri nudi senza card.
2. **Un solo accento.** Il viola `--accent` (#9f92ff) è l'unica tinta: selezione, azione primaria, dato vivo. Mai più di due usi d'accento per schermata visibile; tutto il resto è scala di grigio.
3. **Local-first anche nella forma.** Zero CDN (font self-hosted in `frontend/public/fonts`), zero risorse remote nell'UI; le copertine vengono da AniList, con fallback `cover-fallback` colorato dai metadati.
4. **Il movimento è cortesia, non spettacolo.** Transizioni 0.15–0.3s su background/colore/opacity; `prefers-reduced-motion` spegne tutto.
5. **Due lingue, una misura.** Ogni stringa passa da `tr()` con parità en/it; l'IT è mediamente più lunga: titoli con line-clamp, etichette con ellipsis, niente larghezze fisse sul testo.

## Palette

| Token | Valore | Uso |
| --- | --- | --- |
| `--bg` | `#121212` | sfondo app; base degli scrim (`--bg-rgb`) |
| `--surface` | `#1c1c1c` | pannelli, card, modali, input |
| `--surface-2` | `#282828` | hover, pill attive, campi, barre di track |
| `--fg` | `#ffffff` | titoli, numeri, testo enfatico (`--fg-rgb` per alpha) |
| `--body-text` | `#e5e5e5` | testo corrente |
| `--muted` | `#a3a3a3` | metadati, etichette, link secondari |
| `--border` | `#303030` | cornici sottili e divisori |
| `--accent` | `#9f92ff` | accento unico (azioni primarie, selezione, barre gusto) |
| `--ring` | `#c7c2ff` | focus ring, hover dell'accento, tinta entry-point |
| `--ok` | `#6ee7a0` | stato positivo (connessioni, "saved") |
| `--err` | `#ff9e9e` | messaggi d'errore (mai il viola) |
| `--glow-a/b` | `#34268a` / `#0c1d48` | glow radiali di sfondo, gradient wizard/login |
| `--ink` | `#121212` | testo su fondo accent |

Le trasparenze si compongono dalle triplette: `rgb(var(--accent-rgb) / 0.2)`. Il nero puro `rgb(0 0 0 / x)` è riservato a ombre, maschere e scrim neutri.

Contrasto: muted su bg ≥ 6.9:1, ink su accent ≥ 4.5:1 — nessuna combinazione sotto 4.5:1 (3:1 per testi ≥ 19px). In hover/disabled il contrasto non scende mai: il disabled usa opacity 0.5 su elementi non testuali o `--muted`.

## Tipografia

Geist (400/500/600/700) + Geist Mono (400/500), self-hosted (`frontend/src/design-system/fonts.css`, importato da `main.tsx`). Corpo 15px/1.55; i numeri usano Geist Mono con `tabular-nums` (`.mono`).

Scala canonica (px): **58→38** hero h1 (clamp) · **34** punteggio dialog · **27** statistiche · **22** dialog h2 · **21** wizard h1 · **19** sezioni h2 · **15** page-title/eyebrow · **14** enfasi/titoli card · **14.5** label impostazioni · **13.5** secondario/hint/controlli form · **13** bottoni toolbar/chat-card · **12.5** meta · **12** mono-label e `small` · **11.5** footer/micro-mono · **10.5** badge micro (mono, uppercase, tracking 0.07em) — **floor assoluto 10.5px**.

## Spacing, raggi, ombre, z-index

- Spacing: multipli di 4; gap ricorrenti 2/4/6/8/10/12/16/18, padding pannelli 12–16, sezioni 36px sopra, modale canone **28px**.
- Raggi: `--r-sm` 8 (controlli, thumb), `--r-input` 10 (campi), `--r-md` 12 (card/pannelli), `--r-lg` 16 (modali), `--r-pill` 999 (pill, segmenti).
- Ombre: `--shadow-tip` (tooltip), `--shadow-2` (pannelli), `--shadow-3` (dialog); le card hanno alone accent composito inline (unica eccezione consentita).
- Z-index (scala nominale, mai numeri sparsi): `--z-main 1 · --z-rail 2 · --z-car 3 · --z-topfade 4 · --z-topbar 5 · --z-tip 20 · --z-dialog 40 · --z-dropdown 60 · --z-login 100`.
- Barre: `--bar-h` 4px per barre di dato (profilo, breakdown), 6px per barre di processo (download); poster sempre `--poster-ar` (550/780).
- Bottoni icona: `--icon-btn` 34 inline (input/header), `--icon-btn-lg` 38 overlay flottante (carosello).

## Primitive (`tokens.css` + `styles.css`)

- **Bottoni**: `.btn` base + `.btn-primary` (accento) / `.btn-ghost` (vetro su hero) / `.btn-line` (secondario bordato) / `.linklike` (azione testuale) / `.seg` (segmentato canone: pill bordata con divisori) / `.seg-quiet` (gruppo pill senza bordo, per toolbar e filtri, coerente con `.genre-chip`). Nessun bottone nudo: anche il wizard usa `btn btn-primary`.
- **Barre**: `.bar` (dato) con fill `.taste`/`.quality`/`.community`/`.neg`; `.prog` (affinità su poster); `.progress` (stepper SSE) e `.progress-line` (download indeterminato).
- **Badge**: `.chips` + `.chip-badge` (+ `.gem` accento pieno, `.entry` tinta ring). Uppercase mono 10.5px.
- **Tooltip**: un solo meccanismo — `data-tip` + `.sidebar [data-tip]::after`; ogni controllo icon-only del rail ha `aria-label` + `data-tip`.
- **Stati**: `state-box` (vuoto/benvenuto), `error-box` (banner, icona accent), `.error`/`small.err` in `--err`, `small.ok` in `--ok`; skeleton `.sk` condiviso con la griglia `.grid`.
- **Focus**: outline 2px `--ring` offset 2 (tokens.css); dentro contenitori che tagliano (`.seg`) offset −3px.

## Layout

Shell a griglia `76px + 1fr`: rail icon-only sticky (nav 44×44, footer stato), main con topbar sticky (`1fr auto 1fr`: titolo · ricerca · utente), viste in `<section class="view">` con switch via `hidden`. Hero full-bleed, griglie `auto-fill minmax(186px)`, carosello snap 180px, impostazioni vincolate a 760px. Reflow a 920px e 560px.

## Regole d'uso

1. Nuovi colori? Prima guarda qui: se non c'è un token, probabilmente non serve un colore nuovo.
2. Nuova UI in px sulla scala tipografica sopra (mai rem: il blocco wizard/settings storico è stato convertito per uniformità).
3. Ogni controllo interattivo ha hover **e** `:focus-visible` distinguibili, target ≥ 34px, e stato disabled mai ambiguo.
4. Ogni stringa via `tr(lang, …)` in EN e IT; gli aria-label si localizzano come il testo visibile.
5. I marker `data-od-id` (inventario in `frontend/od-ids.txt`) devono sopravvivere a qualunque restyling: check con `pnpm build && node scripts/check-od-ids.mjs`.
