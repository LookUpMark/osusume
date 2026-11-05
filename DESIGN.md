# DESIGN.md — design system ZCode

Il design language di Osusume è il **tema ZCode** (light + dark), replicato dai valori **misurati** su ZCode.app v3.17.2 — fonte unica e metodologia in `docs/design/ZCODE-THEME.md`. I token canonici vivono in `frontend/src/design-system/tokens.css` (importato prima di `styles.css`); questo documento è la spec di riferimento. Vincoli architetturali in `frontend/README.md` (contratti `lib/logic/`, marker `data-od-id`, i18n).

Storia: fino alla v1.4.x il look era "Verba" (warm minimal-editoriale Claude/Anthropic, serif). Dalla migrazione ZCode il look Verba **resta selezionabile** da Impostazioni → Design (o `localStorage['osusume-design'] = 'verba'`); la sua spec è in coda a questo documento.

## Principi (da ZCode)

1. **Monocromo + focus sky.** Superfici su grigia neutra proprietaria (`#0d0d0d`-based in light, `#161616/#202020/#2b2b2b/#363636` in dark); il primario è il foreground invertito (nero in light, bianco in dark). L'UNICO colore di brand è il sky `#00a6f4/#00bcff`, e serve **solo** al focus ring — mai a selezioni o stati attivi.
2. **Selezione neutra.** Hover e selezione sono il token neutro (`--hover-bg` 5%, `--selected-bg` 5–10% del foreground inverso): nessuna tinta, nessun blu. È la firma del tema.
3. **Superfici piatte.** Card = fondo + bordo 1px `--border`, nessuna ombra; le ombre (`shadow-md`) sono riservate agli overlay (dropdown, dialog, toast).
4. **Tinte derivate.** Badge e banner derivano dai semantici via `color-mix(... transparent 88–94%)` — nessun nuovo colore.
5. **Sistema, non webfont.** Stack `ui-sans-serif/system-ui` (SF su macOS) per display e corpo; `ui-monospace…` per numeri tabulari e meta.
6. **Due assi indipendenti.** `data-theme` (light/dark, persistito in `osusume-theme`) × `data-design` (zcode/verba, persistito in `osusume-design`), entrambi su `<html>`, letti al bootstrap accanto a `prefers-color-scheme`.

## Palette (light = zai-light, dark = zai-dark — hex misurati)

| Token | Light | Dark | Uso |
| --- | --- | --- | --- |
| `--bg` | `#f8f8f8` | `#161616` | canvas finestra |
| `--surface` | `#ffffff` | `#2b2b2b` | card, popover, menu |
| `--surface-warm` | `#e6e6e6` | `#363636` | bottoni secondary, tag, track barre, bubble assistant |
| `--sidebar` | `#f0f0f0` | `#161616` | sidebar (translucente sotto vibrancy) |
| `--input-bg` | `= --surface` | `= --surface` | campi input (in ZCode input = card) |
| `--fg` / `--fg-2` | `#262626` / `#595959` | `#d4d4d4` / `#b3b3b3` | testo primario / muted remoto |
| `--muted` / `--meta` | `#26262699` / `#26262666` | `#d4d4d499` / `#d4d4d44d` | foreground-subtle (60%) / subtlest (40%) |
| `--border` / `--border-soft` / `--border-hover` | `#0d0d0d1a` / idem / `#0d0d0d26` | `#ffffff1a` / idem / `#ffffff26` | bordo standard (= input-border in ZCode) / hover |
| `--hover-bg` / `--selected-bg` / `--selected-fg` | `#0d0d0d0d` / `#0d0d0d0d` / `= --fg` | `#ffffff0d` / `#ffffff1a` / `= --fg` | hover generico / selezione neutra |
| `--user-bubble` | `#0d0d0d0d` | `#ffffff14` | bolla messaggio utente (coda 2px in alto a destra) |
| `--accent` / `--accent-on` | `#000000` / `#ffffff` | `#ffffff` / `#000000` | bottone primario (primary) |
| `--brand` | `#00a6f4` (sky-500) | `#00bcff` (sky-400) | SOLO focus ring |
| `--success` / `--warn` / `--danger` | `#1e8a3e` / `#e07b00` / `#e03131` | `#46bf72` / `#ff8a30` / `#ff5c5c` | semantici (destructive = danger reale) |

Accent hover/active: `color-mix(in oklab, var(--accent), transparent 20%/10%)` (equivalente di `bg-primary/80` e `/90`). Focus: `--focus-ring = 0 0 0 3px color-mix(in oklab, var(--brand), transparent 70%)` + input focus `border-color: var(--brand)`.

## Tipografia

- `--font-display` = `--font-body` = `ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", …` — **niente serif**: anche h1/h2/h3 usano il font di corpo (weight 600, come i titoli ZCode semibold).
- `--font-mono` = `ui-monospace, SFMono-Regular, Menlo, …` — numeri tabulari (`.mono`, `.stat .num`, score), meta, log.
- Scala app invariata: `--text-xs 10 · sm 14 · base 16 · lg 20 · xl 25 · 2xl 32 · 3xl 52 · 4xl 64` (la scala `ui-*` fluida di ZCode parte da 14px: è una misura dell'app host, non adottata). `.eyebrow`: xs uppercase ls 0.5px.

## Spacing, raggi, ombre, motion

- Spacing: `--space-1..12` = 4, 8, 12, 16, 20, 24, 32, 48 (invariato).
- Raggi (scala misurata): `--radius-sm 6` (btn, badge, chip — rounded-md) · `md 8` (card, hero, toast, chat panel — rounded-lg) · `xl 12` (input, bubble chat — rounded-xl) · `lg 16` (dialog, login — rounded-2xl) · `pill 9999` (filtri, barre).
- Ombre: `--elev-raised` = `shadow-md` ZCode (`0 4px 6px -1px #0000001a, 0 2px 4px -2px #0000001a`) solo su overlay (`top-results`, `#toast`, `.dlg`, `.login`); card e griglie piatte. `--elev-ring` resta disponibile.
- Motion: `--motion-fast 150ms` (= `--default-transition-duration` ZCode .15s) · `--motion-base 200ms` · `--ease-standard cubic-bezier(0.4, 0, 0.2, 1)`; `prefers-reduced-motion` spegne tutto.
- Z-index: onboarding/wizard 40 · bottombar 50 · toast/dropdown 60 · login 100.
- Barre: dato = pill 6px · processo = pill 10px. Poster sempre `550/780`.

## Primitive (tokens.css)

- **Bottoni** sulla geometria ZCode misurata: `.btn` = default size `h-7` → **min-height 28px**, padding orizzontale 8px (`px-2`), gap 4px, radius 6px, testo 14px weight 500; `.btn-primary` = `bg-primary` (nero/bianco) senza ring; `.btn-secondary` = `bg-secondary` + hover `transparent 20%`; `.btn-ghost` = testo fg + hover `--hover-bg`; `.btn-sm` = sm `h-6` 24px radius 4px. Active `translateY(1px)` mantenuto.
- **Badge** sulla geometria tag ZCode: radius 6px, padding 2px/6px, sentence case (niente uppercase), tinte `color-mix` dai semantici invariate (gem=accent, entry=fg-2).
- **Card**: surface + border 1px + radius 8, flat (nessuna ombra).
- **Toast**: superficie `--surface` + bordo + `shadow-md` (token toast ZCode), bottom 28, auto-hide 2600ms.
- **Skeleton**: shimmer invariato su `--surface-warm`.

## Layout (invariato come struttura)

Shell grid `240px minmax(0,1fr)`: sidebar sticky su `--sidebar` (brand tile nera + nav 7 voci min-height 44, `aria-current` = `--selected-bg` neutra + peso 500; footer con card stato LLM, toggle local-mode, chip update, media-seg, switch lingua). Main centrato max 1040px con utility header e screen-head per vista (titoli ora sans 600). ≤900px: sidebar nascosta, bottombar mobile fixed. Impostazioni/Evita vincolate e centrate (760/860px).

## Chrome macOS (desktop)

`desktop/main.ts`, **solo su darwin** (win/linux invariati, misure da ZCODE-THEME.md §7): `titleBarStyle: "hidden"`, `trafficLightPosition: {x: 22, y: 23}`, `vibrancy: "under-window"`, `visualEffectState: "active"`, `backgroundColor: "#00000000"`. `desktop/preload.ts` marca `html[data-chrome='vibrancy']`; tutte le superfici translucide sono gated su quell'attributo:

- `body` trasparente → la vibrancy shows through; sidebar `color-mix(--sidebar 65%, transparent)`.
- Drag region (`-webkit-app-region: drag`) sull'header sidebar (`.brand`) + `padding-top: 48px` per i traffic lights a (22,23).
- Build: `pnpm build:electron` bundla anche `desktop/preload.ts` → `dist-electron/preload.cjs` (CommonJS, sandbox-compatible); incluso dal pacchetto (`dist-electron/**` già nei `files`).
- Nel web (nessun preload) il fallback è il fondo opaco equivalente: nessuna regola `[data-chrome]` si applica.

## Selettore design

Impostazioni → Design: segmented ZCode/Verba (`.set-row` + `.seg`, come lingua/media). Stato in `App.tsx` (`useState` bootstrap da `localStorage['osusume-design']`, default `zcode`), effetto che scrive `document.documentElement.dataset.design` + persistenza. Chiavi i18n `setDesignLabel/setDesignZcode/setDesignVerba` in parità en/it.

## Verba (fallback selezionabile)

Sotto `[data-design="verba"]` (e `[data-design="verba"][data-theme="dark"]`) i token del look precedente sono ridichiarati **verbatim** in tokens.css: palette calda (`--bg #f5f4ed`, surface `#faf9f5`, accent terracotta `#c96442`/coral `#d97757`), serif display (`Anthropic Serif`/Georgia), focus blu storico (`--brand #3898ec`, ring `rgba(56,152,236,.3)`), raggi Verba (sm 8 / md 12 / lg 16), easing `cubic-bezier(0.2,0,0,1)`, elev nebulosa. Gli alias di stato rimappano il comportamento: hover/selezione su `--surface-warm`, pill attive su tinta accent, `--input-bg = --bg`, sidebar su `--bg`. In styles.css un blocco finale ripristina le differenze di superficie/geometria non coperte dai token: card con ombra nebulosa e radius 8, btn 40px con ring primario/`#d1cfc5`, badge pill uppercase, input su fondo `--bg` radius 8, toast invertito fg/bg, bolla chat utente accent, drag region/vibrancy mai attive.

## Regole d'uso

1. Nuovo colore? Prima i token: se non c'è, probabilmente è una tinta (`color-mix`) di uno esistente.
2. **Selected/attivo = token neutro** (`--selected-bg`/`--selected-fg`): mai tinte, mai blu. `--brand` (sky) esiste solo per il focus ring.
3. Titoli weight 600 senza serif; mai display font per testo corrente o controlli.
4. Ogni interattivo: hover (`--hover-bg`), `:focus-visible` (ring sky), target ≥44px sulle nav, disabled opacity .5.
5. Stringhe solo via `tr(lang, …)` con parità en/it; gli aria-label si localizzano.
6. I marker `data-od-id` (35, `frontend/od-ids.txt`) sopravvivono a ogni restyling: `pnpm build && node scripts/check-od-ids.mjs`.
7. Il tema si tocca solo via `data-theme`/`data-design` su `<html>` + token CSS; mai colori hardcoded nei componenti o in styles.css (l'unica eccezione residua è lo scrim del dialog `rgba(0,0,0,.4)`, non tematico).
