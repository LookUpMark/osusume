# DESIGN.md — design system "Claude (Anthropic)" (identico a Verba)

Il design language di Osusume, allineato 1:1 a Verba (`~/Documents/github/verba/index.html`): **warm minimal-editorial**. I token canonici vivono in `frontend/src/design-system/tokens.css` (importato prima di `styles.css`); questo documento è la spec di riferimento. Vincoli architetturali in `frontend/README.md` (contratti `lib/logic/`, marker `data-od-id`, i18n).

Storia: fino alla v1.3.3 l'app usava il sistema dark-only "Seanime" (viola #9f92ff, Geist, rail di icone). Il redesign 2026-10-11 lo ha sostituito integralmente — audit del prima/dopo in `docs/audits/REDESIGN-20261011-verba.md`.

## Principi (da Verba)

1. **Caldo e quieto.** Crema e charcoal caldi, mai nero freddo né bianco puro; un solo accento terracotta/coral; zero glassmorphism, zero gradienti di UI (l'unico gradiente è il marchio).
2. **Editoriale.** I titoli sono serif (Georgia di fatto) weight 500; il corpo è sans neutro; i numeri sono tabulari in mono.
3. **Superfici oneste.** Card `--surface` con bordo 1px e ombra nebulosa `0 4px 24px rgba(0,0,0,.05)`; nessun effetto vetro, nessun glow.
4. **Tinte, non nuovi colori.** Stati e badge derivano dai semantici via `color-mix(... transparent 88–94%)`.
5. **Il movimento è cortesia.** 150/200ms con `cubic-bezier(0.2,0,0,1)`; `prefers-reduced-motion` spegne tutto.
6. **Due temi, audit indipendenti.** Light di fabbrica (segue `prefers-color-scheme` al primo avvio), dark su toggle persistente (`osusume-theme`); il dark NON è derivato dal light: sfondi e semantici sono ricalibrati per ≥4.5:1.

## Palette

| Token | Light | Dark | Uso |
| --- | --- | --- | --- |
| `--bg` | `#f5f4ed` | `#1f1e1b` | fondo pagina |
| `--surface` | `#faf9f5` | `#262521` | card, pannelli, input |
| `--surface-warm` | `#e8e6dc` | `#30302e` | bottoni secondari, hover, track barre |
| `--fg` / `--fg-2` | `#141413` / `#3d3d3a` | `#faf9f5` / `#e8e6dc` | testo / testo secondario |
| `--muted` / `--meta` | `#5e5d59` / `#87867f` | `#b0aea5` / `#87867f` | metadati / meta |
| `--border` / `--border-soft` | `#f0eee6` / `#e8e6dc` | `#30302e` / `#3d3c38` | bordi card / bordi caldi |
| `--accent` | `#c96442` | `#d97757` | accento unico (terracotta/coral) |
| `--accent-on` | `#faf9f5` | `#141413` | testo su accent |
| `--success` / `--warn` / `--danger` | `#17a34a` / `#eab308` / `#b53333` | `#2aa65a` / `#eab308` / `#e0685a` | semantici (dark alleggeriti per contrasto) |

Hover/active dell'accento: `color-mix(in oklab, var(--accent), black 8%/14%)` (light) o `white 12%/18%` (dark).

## Tipografia

- `--font-display`: `"Anthropic Serif", Georgia, …` — **solo h1/h2/h3, brand, punteggi grandi** (weight 500, line-height 1.1). Nessun webfont: il rendering reale è Georgia (identico a Verba, local-first).
- `--font-body`: `"Anthropic Sans", Arial, system-ui…` — corpo 16px/1.6.
- `--font-mono`: `"Anthropic Mono", ui-monospace, JetBrains Mono, Menlo…` — numeri tabulari, meta, log.
- Scala: `--text-xs 10 · sm 14 · base 16 · lg 20 · xl 25 · 2xl 32 · 3xl 52 · 4xl 64`. `.eyebrow`: xs uppercase ls 0.5px.

## Spacing, raggi, ombre, z-index, motion

- Spacing: `--space-1..12` = 4, 8, 12, 16, 20, 24, 32, 48.
- Raggi: `--radius-sm 8` (bottoni/card/input) · `md 12` (card grandi, bubble) · `lg 16` (modali) · `pill 9999` (badge, barre, chip).
- Ombre: `--elev-ring` (bordo 1px) · `--elev-raised` (`rgba(0,0,0,.05/.35) 0 4px 24px`). Mai ombre dure.
- Focus: `--focus-ring` = `0 0 0 3px rgba(56,152,236,.3)` su `:focus-visible` di ogni interattivo (outline: none); input focus anche `border-color: #3898ec`.
- Motion: `--motion-fast 150ms` · `--motion-base 200ms` · `--ease-standard cubic-bezier(0.2,0,0,1)`.
- Z-index: onboarding/wizard 40 · bottombar 50 · toast/dropdown 60 · login 100.
- Barre: dato = pill 6px (profilo, breakdown) · processo = pill 10px (progress SSE, download). Poster sempre `550/780`.

## Primitive (tokens.css)

- **Bottoni**: `.btn` base (padding 9/16/12, radius 8, min-height 40, active translateY(1px)) + `btn-primary` (accent + ring self 1px) / `btn-secondary` (surface-warm + ring #d1cfc5) / `btn-ghost` / `.btn-sm` (32px, xs). Nessun bottone nudo.
- **Badge**: `.badge-*` / `.chip-badge` pill 3/10 xs uppercase con tinte `color-mix` (success/muted/accent/danger; gem=accent, entry=muted). `.badge-dot` 6px.
- **Card**: `.card` surface + border + radius 8 + raised. Varianti con radius 12/16 per lesson-size e modali.
- **Toast**: `#toast` invertito fg/bg, radius 12, bottom 28, auto-hide 2600ms — per feedback transienti (watchlist aggiunto, impostazioni salvate).
- **Skeleton**: shimmer `translateX` 1.1s su surface-warm.
- **Empty state**: icona accent + titolo serif + azione.

## Layout

Shell grid `240px minmax(0,1fr)`: **sidebar testuale** sticky (brand serif + tag uppercase, nav 7 voci icona 18px + label min-height 44, `aria-current` = surface-warm + peso 500; footer con card stato LLM/modello, toggle local-mode, chip update, media-seg ANIME/MANGA pill, switch lingua). Main centrato max 1040px padding 32/24/48 con **utility header** (ricerca + toggle tema + chip utente) e un **screen-head per vista** (titolo serif + sub). ≤900px: sidebar nascosta, **bottombar mobile** fixed (item 11px, attivo coral). Impostazioni/Evita vincolate e centrate (760/860px).

## Regole d'uso

1. Nuovo colore? Prima i token: se non c'è, probabilmente è una tinta (`color-mix`) di uno esistente.
2. Titoli sempre serif weight 500; mai serif per testo corrente o controlli.
3. Ogni interattivo: hover, `:focus-visible` (ring blu), target ≥44px sulle nav, disabled opacity .45.
4. Stringhe solo via `tr(lang, …)` con parità en/it; gli aria-label si localizzano.
5. I marker `data-od-id` (35, `frontend/od-ids.txt`) sopravvivono a ogni restyling: `pnpm build && node scripts/check-od-ids.mjs`.
6. Il tema si tocca solo via `data-theme` su `<html>` + token CSS; mai colori hardcoded nei componenti (le sole eccezioni: focus `#3898ec` e ring `#d1cfc5`, ereditate da Verba).
