# DESIGN.md — design system marcantonio-lopez

Il design language di Osusume è, dalla v1.6.0, il **brand "Marc'Antonio Lopez"** — unico design dell'app, senza selettore né fallback. Canone estratto con Open Design dal profilo `github.com/LookUpMark`: fonte unica, metodologia, mappatura canone→token e **deviazioni dichiarate** in `docs/design/MARCANTONIO-LOPEZ-BRAND.md`. I token canonici vivono in `frontend/src/design-system/tokens.css` (importato prima di `styles.css`); questo documento è la spec di riferimento. Vincoli architetturali in `frontend/README.md` (contratti `lib/logic/`, marker `data-od-id`, i18n).

Storia: v1.4.x = "Verba" (warm minimal-editoriale Claude/Anthropic) · v1.5.x = tema "ZCode" misurato da ZCode.app (Verba selezionabile) · **v1.6.0 = brand marcantonio-lopez, unico e esclusivo** — il selettore Design in Impostazioni è stato rimosso insieme ai temi precedenti (`localStorage['osusume-design']` non è più letto; valori residui sono innocui).

## Principi (dal canone di brand)

1. **Paper bianco, surface grigia.** Canvas pagina `#ffffff` light / `#131311` dark; card e sidebar su `--surface` `#f5f5f5`/`#1c1c1a`, delineate dal bordo 1px hairline. Canvas *warm neutral, not beige*.
2. **Un solo accent, usato con parsimonia.** Il rosso `#d43511` (coral `#ff6b4f` in dark) è l'unico colore di brand: punteggi, chip gem, icone attive, barre dato, tinta di selezione. **I bottoni primari sono ink** (nero/bianco invertito), non rossi. Link e focus informativi al secondario blu `#023b95`.
3. **Selezione = tinta accent.** `--selected-bg` è l'accent-tint del canone (`#fdecea` light / `#2a110b` dark) con testo `--selected-fg` accent-strong; hover resta neutro. È la firma del brand (sostituisce la "selezione neutra" del tema ZCode).
4. **Superfici piatte, ombre leggerissime.** Card = fondo + bordo 1px, nessuna ombra; le ombre (molto leggere) sono riservate agli overlay (dropdown, dialog, toast). Niente gradienti dominanti, niente glassmorphism.
5. **Inter self-hosted.** `@font-face` OFL in tokens.css (`public/fonts/`, 400/600/700, `font-display: swap`), fallback system-ui; mono per numeri tabulari e meta.
6. **Un asse: light/dark.** `data-theme` su `<html>` (persistito in `osusume-theme`, default da `prefers-color-scheme`). Dark **progettato a parte** (carta calda `#131311`, coral `#ff6b4f`), non inversione. Niente asse design.

## Palette (light + dark, hex canonici)

| Token | Light | Dark | Uso |
| --- | --- | --- | --- |
| `--bg` | `#ffffff` | `#131311` | canvas finestra (paper) |
| `--surface` / `--sidebar` | `#f5f5f5` | `#1c1c1a` | card, hero, chat panel, sidebar |
| `--surface-warm` | `#ececec` | `#22221e` | bottoni secondary, tag, track barre, bubble assistant |
| `--input-bg` / `--mark-bg` | `#ffffff` | `#1f1f1b` | campi input e tile marchio = raised |
| `--fg` / `--fg-2` | `#000000` / `#3d3d3d` | `#f5f5f0` / `#c4c2b9` | testo primario / secondario (v. deviazione 1) |
| `--muted` / `--meta` | `#8c8c8c` / `#8c8c8c99` | `#a3a3a3` / `#a3a3a380` | etichette, small, placeholder |
| `--border` / `--border-soft` / `--border-hover` | `#dbdbdb` / `#e8e8e8` / `#c6c6c6` | `#303030` / `#2a2a27` / `#3f3f38` | hairline canonica / alleggerita / rinforzata |
| `--hover-bg` | `#0000000a` | `#ffffff0f` | hover neutro |
| `--selected-bg` / `--selected-fg` | `#fdecea` / `#d43511` | `#2a110b` / `#ff6b4f` | selezione = tinta accent (canone) |
| `--user-bubble` | `#0000000d` | `#ffffff14` | bolla utente (coda 2px in alto a destra) |
| `--accent` / `--accent-on` | `#d43511` / `#ffffff` | `#ff6b4f` / `#14140f` | accent (uso parsimone) |
| `--accent-hover` / `--accent-active` | `#e05b36` / `#ad1f05` | mix white 12% / black 8% | scala primaria 10-step |
| `--accent-secondary` | `#023b95` (anche dark) | idem | link (chat markdown) |
| `--btn-primary-bg` / `-fg` | `#000000` / `#ffffff` | `#f5f5f0` / `#14140f` | **bottone primario = ink** (canone) |
| `--brand` | `#d43511` | `#ff6b4f` | SOLO focus ring (canone: focus = accent) |
| `--mark-fg` / `--mark-accent` | `#242629` / `#829f68` | `#f5f5f0` / `#829f68` | line-art torii + dettaglio sage |
| `--success` / `--warn` / `--danger` | `#389e0d` / `#d48806` / `#d9363d` | `#64b537` / `#dcaa37` / `#dc6966` | semantici, varianti contrast-safe per testo |

Focus: `--focus-ring = 0 0 0 3px color-mix(in oklab, var(--brand), transparent 70%)` + input focus `border-color: var(--brand)`. Hover/active del primario: `color-mix` verso il fg del bottone.

## Tipografia

- `--font-display` = `--font-body` = `"Inter", system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif`; `--font-mono` = `ui-monospace, SFMono-Regular, Menlo, …`. Inter 400/600/700 self-hosted con preload (index.html).
- Scala canonica adattata all'app: `--text-xs 11 · sm 14 · base 17 · lg 24 · xl 28 · 2xl 32 · 3xl 40 · 4xl 56` (meta 11 / small 14 / body 17 / h3 24 / h2 32 / h1 40 / display 56 — v. deviazione 2). `--leading-body 1.55`, `--leading-tight 1.2`, `--tracking-display -0.02em`. `.eyebrow`: xs uppercase ls 0.5px.

## Spacing, raggi, ombre, motion

- Spacing: `--space-1..8,12` = 4, 8, 12, 16, 20, 24, 32, 48 (invariato — griglia base 4px, deviazione 5).
- Raggi: `--radius-sm 6` (btn, badge, chip) · `md 8` (card, hero, toast, chat panel — **radius canon**) · `xl 12` (input, bubble) · `lg 12` (= xl, dialog/login; il 16 del tema precedente è caduto) · `pill 9999` (filtri, barre).
- Ombre: `--elev-raised` leggerissima (`0 1px 2px + 0 8px 24px` a 5–6% light, 40–50% dark) solo su overlay (`top-results`, `#toast`, `.dlg`, `.login`); card e griglie piatte (deviazione 3). `--elev-ring` resta disponibile.
- Motion: `--motion-fast 120ms` · `--motion-base 200ms` · `--ease-standard cubic-bezier(0.2, 0.65, 0.2, 1)` (canone app); `prefers-reduced-motion` spegne tutto.
- Z-index: onboarding/wizard 40 · bottombar 50 · toast/dropdown 60 · login 100 (invariato).
- Barre: dato = pill 6px · processo = pill 10px. Poster sempre `550/780`.

## Primitive (tokens.css)

- **Bottoni**: geometria compatta v1.5 mantenuta — `.btn` min-height 28px, padding orizzontale 8px, gap 4px, radius 6px, testo 14px weight 500; **`.btn-primary` = ink** (`--btn-primary-*`); `.btn-secondary` = `--surface-warm`; `.btn-ghost` = testo fg + hover neutro; `.btn-sm` 24px radius 4px. Active `translateY(1px)`.
- **Badge**: radius 6px, padding 2px/6px, sentence case, tinte `color-mix` dai token (gem/badge-accent = accent rosso, entry = fg-2).
- **Card**: surface + border 1px + radius 8, flat.
- **Toast**: superficie + bordo + ombra leggera, bottom 28, auto-hide 2600ms.
- **Skeleton**: shimmer su `--surface-warm` (invariato).

## Layout (struttura invariata)

Shell grid `240px minmax(0,1fr)`: sidebar sticky su `--sidebar` (tile marchio 36px con bordo hairline + torii line-art ink/kasagi sage, nav 7 voci min-height 44, `aria-current` = `--selected-bg` tinta accent + `--selected-fg` + peso 500; footer con card stato LLM, toggle local-mode, chip update, media-seg, switch lingua). Main centrato max 1040px con utility header e screen-head per vista. ≤900px: sidebar nascosta, bottombar mobile fixed. Impostazioni/Evita vincolate e centrate (760/860px).

## Chrome macOS (desktop)

`desktop/main.ts`, **solo su darwin**: `titleBarStyle: "hidden"`, `trafficLightPosition: {x: 22, y: 23}`, `backgroundColor: "#ffffff"` — **niente vibrancy** (il canone vieta il glassmorphism; canvas opaco su tutte le piattaforme, lezione v1.5.1 preservata). `desktop/preload.ts` marca `html[data-chrome='desktop']`: inset traffic lights (`padding-top: 48px` sulla sidebar) + `-webkit-app-region: drag` su `.brand`. Win/Linux: `backgroundColor: "#ffffff"`, titlebar standard.

## Regole d'uso

1. Nuovo colore? Prima i token: se non c'è, probabilmente è una tinta (`color-mix`) di uno esistente. Il rosso accent NON diventa il colore di bottoni o testo corrente.
2. **Selected/attivo = token `--selected-*`** (tinta accent del canone); hover = neutro `--hover-bg`. `--brand` esiste solo per il focus ring.
3. Titoli Inter weight 600, tracking display; mai il display per testo corrente o controlli.
4. Ogni interattivo: hover (`--hover-bg`), `:focus-visible` (ring accent), target ≥44px sulle nav, disabled opacity .5.
5. Stringhe solo via `tr(lang, …)` con parità en/it; gli aria-label si localizzano.
6. I marker `data-od-id` (35, `frontend/od-ids.txt`) sopravvivono a ogni restyling: `pnpm build && node scripts/check-od-ids.mjs`.
7. Il tema si tocca solo via `data-theme` su `<html>` + token CSS; mai colori hardcoded nei componenti o in styles.css (l'unica eccezione residua è lo scrim del dialog `rgba(0,0,0,.4)`, non tematico).
8. Il marchio (torii) si modifica solo come line-art stroke `--mark-fg` con l'unico dettaglio sage `--mark-accent` — stesso stile del logo-mark OD; niente gradienti, niente fill.

## Deviazioni dal canone

Tutte registrate e motivate in `docs/design/MARCANTONIO-LOPEZ-BRAND.md` §8: fg-2 schiarito in light, scala testate adattata alla densità, ombre overlay conservate ma leggere, semantici contrast-safe, spacing invariato, nessuna vibrancy, link dark su `#023b95`.
