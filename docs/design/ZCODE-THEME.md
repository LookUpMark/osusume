# ZCode Theme — Reverse-engineering del tema standard (macOS)

Fonte unica: `/Applications/ZCode.app/Contents/Resources/app.asar` (Electron, **app v3.17.2**, build `a2d1ba73`, 2026-11-02 — da `out/metadata/build-meta.json`).

Tutti i valori sono **misurati** dai file estratti dall'asar (nessuna stima). Estrazioni mirate via `npx @electron/asar extract-file` e reader node sull'header asar in `/tmp/zcode-css`; l'asar non è mai stato estratto per intero né copiato nel repo.

File esaminati:

| File nell'asar | Contenuto |
|---|---|
| `out/renderer/assets/styles-NK68EN_n.css` (480 KB) | CSS del design system (Tailwind v4 + blocchi tema) + KaTeX/xterm/streamdown inlinati |
| `out/renderer/assets/styles-Dv5E6Odo.js` (6.7 MB) | Bundle UI principale: tutte le className Tailwind dei componenti |
| `out/renderer/assets/button-DeDmlciX.js` | Componente `Button` (cva completa) |
| `out/main/index.js` (849 KB) | BrowserWindow: chrome macOS |
| `out/renderer/assets/index-CbMOaeRT.js` | Risoluzione tema runtime |
| `out/renderer/assets/pdf-viewer-Dgb4oCkS.css` | **VENDATO** (pdf.js) — ignorare |

---

## 1. Architettura del tema (come ZCode applica i temi)

Da `out/renderer/assets/index-CbMOaeRT.js`:

```js
t = matchMedia(`(prefers-color-scheme: dark)`).matches ? `dark` : `light`
n = e===`system` ? (t===`dark` ? `zai-dark` : `zai-light`)
  : e===`dark` ? `zai-dark` : e===`light` ? `zai-light` : e
t===`dark` && document.documentElement.classList.add(`dark`)
document.documentElement.classList.toggle(`theme-zai-light`, n===`zai-light`)
document.documentElement.classList.toggle(`theme-zai-dark`, n===`zai-dark`)
```

- In dark mode `<html>` porta **entrambe** le classi `dark` **e** `theme-zai-dark`.
- In light mode `<html>` porta solo `theme-zai-light`.
- Il CSS ha quindi due livelli: i **fallback generici** `:root,:host` (light) e `.dark` (dark), scritti in oklch sulla scala Tailwind v4; poi i **temi reali** `.theme-zai-light` / `.theme-zai-dark` che sovrascrivono quasi tutto con **hex letterali** (regola 1d della skill: il tema vero è lo scope hex, il generico è il cross-platform fallback).
- Ogni token è scritto due volte nel CSS: versione hex letterale + versione `color-mix(in oklab, …)` dentro `@supports (color:color-mix(in lab, red, red))` — in Electron (Chromium recente) **vince la versione color-mix**; le due letture coincidono matematicamente (es. `#0a0a0a1a` ≡ `color-mix(in oklab, var(--color-neutral-950) 10%, transparent)` perché `neutral-950` = `oklch(14.5% 0 0)` = `#0a0a0a`).

---

## 2. Scala Tailwind v4 in oklch → hex sRGB

Definita in `:root,:host` (blocco `@layer theme`, 8.5 KB) di `styles-NK68EN_n.css`. Conversione con le formule OKLab→sRGB (Björn Ottosson): `oklch → oklab → linear sRGB → gamma encode`. I valori coincidono con la palette Tailwind v4 ufficiale (sanity check superato).

### Neutral (asse del tema)
| Token | oklch | hex | uso nel tema |
|---|---|---|---|
| `--color-neutral-50` | `oklch(98.5% 0 0)` | `#fafafa` | fallback terminal-bg light |
| `--color-neutral-100` | `oklch(97% 0 0)` | `#f5f5f5` | header/panel/sidebar fallback light |
| `--color-neutral-200` | `oklch(92.2% 0 0)` | `#e5e5e5` | hover fallback light, tag, card-selected fallback |
| `--color-neutral-300` | `oklch(87% 0 0)` | `#d4d4d4` | **foreground dark** (`--color-foreground`) |
| `--color-neutral-500` | `oklch(55.6% 0 0)` | `#737373` | mid-gray |
| `--color-neutral-700` | `oklch(37.1% 0 0)` | `#404040` | **foreground light**, background-alt dark |
| `--color-neutral-800` | `oklch(26.9% 0 0)` | `#262626` | card/popover/input fallback dark, background-win-alt dark |
| `--color-neutral-900` | `oklch(20.5% 0 0)` | `#171717` | background fallback dark |
| `--color-neutral-950` | `oklch(14.5% 0 0)` | `#0a0a0a` | base dei color-mix light, sidebar/tab fallback dark |

### Sky (famiglia brand/accanto)
| Token | oklch | hex | | Token | oklch | hex |
|---|---|---|---|---|---|---|
| `--color-sky-50` | `oklch(97.7% .013 236.62)` | `#f0f9ff` | | `--color-sky-400` | `oklch(74.6% .16 232.661)` | `#00bcff` |
| `--color-sky-100` | `oklch(95.1% .026 236.824)` | `#dff2fe` | | `--color-sky-500` | `oklch(68.5% .169 237.323)` | `#00a6f4` |
| `--color-sky-200` | `oklch(90.1% .058 230.902)` | `#b8e6fe` | | `--color-sky-600` | `oklch(58.8% .158 241.966)` | `#0084d1` |
| `--color-sky-300` | `oklch(82.8% .111 230.318)` | `#74d4ff` | | `--color-sky-700` | `oklch(50% .134 242.749)` | `#0069a8` |
| | | | | `--color-sky-900` | `oklch(39.1% .09 240.876)` | `#024a70` |
| | | | | `--color-sky-950` | `oklch(29.3% .066 243.157)` | `#052f4a` |

### Famiglie usate dai token semantici del fallback
Solo i step effettivamente referenziati dai token del DS:

| Token | oklch | hex | | Token | oklch | hex |
|---|---|---|---|---|---|---|
| `--color-green-50` | `98.2% .018 155.826` | `#f0fdf4` | | `--color-yellow-300` | `90.5% .182 98.111` | `#ffdf20` |
| `--color-green-200` | `92.5% .084 155.995` | `#b9f8cf` | | `--color-yellow-500` | `79.5% .184 86.047` | `#f0b100` |
| `--color-green-300` | `87.1% .15 154.449` | `#7bf1a8` | | `--color-yellow-600` | `68.1% .162 75.834` | `#d08700` |
| `--color-green-500` | `72.3% .219 149.579` | `#00c950` | | `--color-yellow-800` | `47.6% .114 61.907` | `#894b00` |
| `--color-green-600` | `62.7% .194 149.214` | `#00a63e` | | `--color-red-500` | `63.7% .237 25.331` | `#fb2c36` |
| `--color-green-700` | `52.7% .154 150.069` | `#008236` | | `--color-red-600` | `57.7% .245 27.325` | `#e7000b` |
| `--color-blue-50` | `97% .014 254.604` | `#eff6ff` | | `--color-red-800` | `44.4% .177 26.899` | `#9f0712` |
| `--color-blue-300` | `80.9% .105 251.813` | `#8ec5ff` | | `--color-violet-50` | `96.9% .016 293.756` | `#f5f3ff` |
| `--color-blue-700` | `48.8% .243 264.376` | `#1447e6` | | `--color-violet-400` | `70.2% .183 293.541` | `#a684ff` |
| `--color-blue-950` | `28.2% .091 267.935` | `#162456` | | `--color-violet-600` | `54.1% .281 293.009` | `#7f22fe` |
| `--color-teal-400` | `77.7% .152 181.912` | `#00d5be` | | `--color-violet-950` | `28.3% .141 291.089` | `#2f0d68` |
| `--color-teal-600` | `60% .118 184.704` | `#009689` | | `--color-amber-600` | `66.6% .179 58.318` | `#e17100` |
| `--color-slate-300` | `86.9% .022 252.894` | `#cad5e2` | | `--color-slate-600` | `44.6% .043 257.281` | `#45556c` |

Scala completa (132 token oklch) disponibile nel dump `/tmp/zcode-css` durante la sessione di mining; le altre famiglie (orange, emerald, cyan, indigo, fuchsia, pink, rose, gray, zinc) sono presenti nel tema ma nessun token del DS le referenzia, tranne dove indicato.

---

## 3. Token del tema REALE — light e dark

`.theme-zai-light` e `.theme-zai-dark` in `styles-NK68EN_n.css` (hex letterali). Colonna "hex risolto": i valori var() sono risolti via scala §2; gli alpha hex `#rrggbbaa` sono mantenuti.

> Nota palette: il tema zai usa una **scala grigia proprietaria** `#0d0d0d / #161616 / #202020 / #2b2b2b / #363636` (light: `#f8f8f8 / #f0f0f0 / #e6e6e6 / #fff`), che **non** è la neutral Tailwind. È il tratto distintivo del brand.

### Superfici e struttura
| Token | Light (grezzo) | Light hex | Dark (grezzo) | Dark hex | Uso |
|---|---|---|---|---|---|
| `--color-background` | `#f8f8f8` | `#f8f8f8` | `#161616` | `#161616` | canvas della finestra |
| `--color-background-alt` | `#fafafab3` → `color-mix(oklab, background 70%, transparent)` | `#f8f8f8` @70% | `#e5e5e599` → `color-mix(oklab, win-alt 60%, transparent)` | `#2b2b2b` @60% | sfondo alternato |
| `--color-background-win-alt` | `#ececee` | `#ececee` | `#2b2b2b` | `#2b2b2b` | solo Windows (mica) |
| `--color-header` | `#fff` | `#ffffff` | `#202020` | `#202020` | titlebar/intestazioni |
| `--color-panel` | `#fff` | `#ffffff` | `#202020` | `#202020` | pannelli |
| `--color-sidebar` | `#f0f0f0` | `#f0f0f0` | `#161616` | `#161616` | sidebar |
| `--color-card` | `#fff` | `#ffffff` | `#2b2b2b` | `#2b2b2b` | card |
| `--color-popover` | `#fff` | `#ffffff` | `#2b2b2b` | `#2b2b2b` | popover |
| `--color-popover-header` | `#f8f8f8` | `#f8f8f8` | `#202020` | `#202020` | header popover |
| `--color-input` | `#fff` | `#ffffff` | `#2b2b2b` | `#2b2b2b` | campi input / composer |
| `--color-input-focused` | `var(--color-input)` | `#ffffff` | `var(--color-input)` | `#2b2b2b` | input in focus |
| `--color-menu` | `#fff` | `#ffffff` | `#2b2b2b` | `#2b2b2b` | menu dropdown |
| `--color-tab` / `-active` | `#f0f0f0` / `#fff` | `#f0f0f0` / `#ffffff` | `#202020` / `#161616` | `#202020` / `#161616` | tab |
| `--color-secondary` | `#e6e6e6` | `#e6e6e6` | `#363636` | `#363636` | bottoni secondary |
| `--color-tooltip` | `#f0f0f0` | `#f0f0f0` | `#2b2b2b` | `#2b2b2b` | tooltip |
| `--color-toast` | `#fff` | `#ffffff` | `#2b2b2b` | `#2b2b2b` | toast |
| `--color-tag` | `#e6e6e6` | `#e6e6e6` | `#363636` | `#363636` | chip/tag |
| `--color-tooltip-tag` | `#e6e6e6` | `#e6e6e6` | `#363636` | `#363636` | tag dentro tooltip |
| `--color-hover` | `#0d0d0d0d` | `#0d0d0d` @5% | `#ffffff0d` | `#ffffff` @5% | hover generico |
| `--color-surface` | `#0d0d0d08` → `color-mix(oklab, neutral-950 3%, transparent)` | `#0d0d0d` @3% | `#ffffff0d` | `#ffffff` @5% | superficie alzata (bolla utente, item) |
| `--color-surface-hover` | `#0d0d0d0d` | `#0d0d0d` @5% | `#ffffff1a` | `#ffffff` @10% | hover superficie |
| `--color-selected` | `#0d0d0d0d` | `#0d0d0d` @5% | `#ffffff1a` | `#ffffff` @10% | selezione item (NEUTRA, non tintata) |
| `--color-user-message-bubble` | `#0d0d0d0d` | `#0d0d0d` @5% | `#ffffff14` | `#ffffff` @8% | bolla messaggio utente |

### Bordi
| Token | Light | Dark | Uso |
|---|---|---|---|
| `--color-border` | `#0d0d0d1a` → `mix(neutral-950 10%)` | `#ffffff1a` (`#fff` @10%) | bordo standard |
| `--color-border-hover` | `#0d0d0d26` (`#0d0d0d` @15%) | `#ffffff26` (`#fff` @15%) | bordo hover |
| `--color-input-border` | `var(--color-border)` | `var(--color-border)` | bordo input |
| `--color-input-border-hover` | `var(--color-border-hover)` | `var(--color-border-hover)` | bordo input hover |
| `--color-input-border-focused` | `var(--color-border-hover)` | `var(--color-border-hover)` | **focus input = border-hover (non brand!)** |
| `--color-card-border` | `var(--color-border)` | `var(--color-border)` | bordo card |
| `--color-popover-border` | `var(--color-border)` | `var(--color-border)` | bordo popover |

### Primo piano
| Token | Light | Dark | Uso |
|---|---|---|---|
| `--color-foreground` | `var(--color-neutral-800)` = `#262626` | `var(--color-neutral-300)` = `#d4d4d4` | testo primario |
| `--color-foreground-subtle` | `#26262699` → `mix(neutral-800 60%)` | `#d4d4d499` → `mix(neutral-300 60%)` | testo secondario |
| `--color-foreground-subtlest` | `#26262666` → `mix(neutral-800 40%)` | `#d4d4d44d` → `mix(neutral-300 30%)` | testo terziario/placeholder |
| `--color-foreground-inverse` | `#fff` | `#000` | testo su primario |
| `--color-remote-foreground-muted` | `#595959` | `#b3b3b3` | muted remoto |
| `--color-primary` | `#000` | `#fff` | bottone primario (bg) |
| `--color-primary-foreground` | `#fff` | `#000` | testo bottone primario |
| `--color-brand` | `#000` | `#fff` | brand/focus ring fallback |
| `--color-accent` | `#ebf4ff` | `#001d3d` | superficie accento (sky tint) |
| `--lucide-subtlest-opacity` | `.4` | `.3` | icone lucide attenuate |

### Semantici (success / warning / danger reale)
| Token | Light | Dark | Uso |
|---|---|---|---|
| `--color-success` | `#1e8a3e` | `#46bf72` | stato successo |
| `--color-success-foreground` | `#fff` | `#000` | testo su success |
| `--color-success-surface` | `#eaf7ee` | `#46bf7229` (`#46bf72` @16%) | superficie success |
| `--color-success-surface-foreground` | `#166b32` | `#87d9a4` | testo su surface success |
| `--color-warning` | `#e07b00` | `#ff8a30` | stato warning |
| `--color-warning-foreground` | `#fff` | `#000` | testo su warning |
| `--color-warning-surface` | `#cd89001f` → `mix(warning 12%)` | `#cd890029` → `mix(warning 16%)` | superficie warning |
| `--color-warning-surface-foreground` | `#914e00` | `#ffa159` | testo su surface warning |
| `--color-destructive` | `#e03131` | `#ff5c5c` | **"danger" reale si chiama destructive** |
| `--color-destructive-foreground` | `#fff` | `#fff` | testo su destructive |
| `--color-destructive-surface` | `#e400141a` → `mix(destructive 10%)` | `#e4001429` → `mix(destructive 16%)` | superficie destructive |
| `--color-destructive-surface-foreground` | `#b42020` | `#ff8585` | testo su surface destructive |
| `--color-idle-task` / `-surface` | `#9e77ed` / `#f5f3ff` | `#7b5ce5` / `#160d38` | task inattivo |
| `--color-interaction-ask-surface` / `-foreground` | `#ebf4ff` / `#06d` | `#001d3d` / `#80beff` | domanda interattiva |
| `--color-interaction-ask-fill` | `#46bf7233` | `#46bf723d` | fill ask |
| `--color-interaction-confirmation-surface` / `-foreground` | `#eaf7ee` / `#166b32` | `#46bf7229` / `#87d9a4` | conferma interattiva |
| `--color-progress-surface` / `-foreground` | `var(--color-blue-50)`/`var(--color-blue-700)` = `#eff6ff`/`#1447e6` | `#4682f029` / `var(--color-blue-300)`=`#8ec5ff` | progresso |
| `--color-feedback-privacy-hint` | `var(--color-yellow-600)`=`#d08700` | `var(--color-yellow-300)`=`#ffdf20` | hint privacy |

### Diff / Git
| Token | Light | Dark |
|---|---|---|
| `--color-diff-added` (+fg) | `#1e8a3e` (`#fff`) | `#46bf72` (`#000`) |
| `--color-diff-removed` (+fg) | `#e03131` (`#fff`) | `#ff5c5c` (`#000`) |
| `--color-git-modified`/`descendant` | `#e07b00` | `#ff8a30` |
| `--color-git-added`/`untracked` | `#1e8a3e` | `#46bf72` |
| `--color-git-deleted` | `#e03131` | `#ff5c5c` |
| `--color-git-renamed` | `#0b7fff` | `#4099ff` |

### Traiettorie / workflow / charts (identità chat)
| Token | Light | Dark |
|---|---|---|
| `--color-trajectory-user` | `#2563eb` | `#60a5fa` |
| `--color-trajectory-assistant` | `#0f766e` | `#2dd4bf` |
| `--color-trajectory-reasoning` | `#7c3aed` | `#a78bfa` |
| `--color-trajectory-tool-call` | `#d97706` | `#f59e0b` |
| `--color-trajectory-tool-result` | `#0284c7` | `#38bdf8` |
| `--color-workflow-rule` / `-trace` / `-trace-strong` | `#0d0d0d0e` / `#0d0d0d4d` / `#0d0d0d8c` | `#fff1` / `#ffffff59` / `#fff9` |
| `--color-usage-chart-1..6` | `#0b7fff` `#1e8a3e` `#9e77ed` `#e03131` `#e07b00` `#0aa7a7` | `#4099ff` `#46bf72` `#7b5ce5` `#ff5c5c` `#ff8a30` `#42c8c8` |
| `--color-context-breakdown-1..7` | `#0b7fff`→`#e0ecff` (scala sky) | `#4099ff`→`#e4f1ff` (scala sky) |
| `--color-find-highlight` / `-active` | `#fff4eb` / `#ffb26b` | `#542500` / `#ff8a30` |

### Terminale (il DS colora il terminale xterm vendato)
| Ruolo | Light | Dark |
|---|---|---|
| `--color-terminal-bg` / `fg` | `var(--color-background)` / `var(--color-foreground)` | idem |
| `--color-terminal-cursor` (+accent) | `#0d0d0d` (bg) | `#f8f8f8` (`#161616`) |
| `--color-terminal-selection` | `#0b7fff38` | `#4099ff47` |
| black / red / green / yellow | `#5c5c5c` / `#e03131` / `#1e8a3e` / `#e07b00` | `#363636` / `#ff5c5c` / `#46bf72` / `#ff8a30` |
| blue / magenta / cyan / white | `#0b7fff` / `#9e77ed` / `#0aa7a7` / `#adadad` | `#4099ff` / `#7b5ce5` / `#42c8c8` / `#adadad` |
| bright-black … bright-white | `#888` `#e03131` `#1e8a3e` `#e07b00` `#06d` `#9e77ed` `#0aa7a7` `#0d0d0d` | `#747474` `#f99` `#87d9a4` `#ffb26b` `#80beff` `#a888f2` `#8ee5e5` `#f8f8f8` |

### Feature "highspeed" (modalità rapida, viola)
| Token | Light | Dark |
|---|---|---|
| `--color-highspeed-accent` | `#9e77ed` | `#b392ff` |
| `--color-highspeed-composer-surface` | `#fff` | `#151515` |
| glow 01→26 | `#6041ff03` → `#6041ff42` | `#a888f203` → `#a888f242` |
| particle / highlight | `#7453b0c2` / `#7453b0` | `#b392ffc2` / `#b392ff` |
| sidebar model icon | `#6041ff` | `#b09aff` |
| sidebar model gradient | `90deg, #4830c8 0%, #6041ff 50%, #8955db 100%` | `90deg, #9b85ff 0%, #b09aff 50%, #ceacff 100%` |

---

## 4. Anatomia componenti (className verbatim dal bundle)

Fonte: `styles-Dv5E6Odo.js` (bundle UI) e `button-DeDmlciX.js`. `min-h-7` = 1.75rem = 28px; `--spacing` = `.25rem` (4px/step Tailwind v4).

### Button (cva completa, `button-DeDmlciX.js`)
Base: `group/button inline-flex shrink-0 items-center justify-center rounded-md border border-transparent bg-clip-padding text-ui-base/relaxed whitespace-nowrap transition-colors outline-none select-none disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4`

Varianti (bg/fg/hover):
- `default`: `bg-primary text-primary-foreground hover:bg-primary/80`
- `outline`: `border-border text-foreground hover:border-border-hover hover:bg-input/50 hover:text-foreground aria-expanded:bg-input/50 aria-expanded:text-foreground`
- `secondary`: `bg-secondary text-foreground hover:bg-secondary/80`
- `ghost`: `text-foreground hover:bg-hover hover:text-foreground`
- `destructive`: `bg-destructive text-destructive-foreground hover:bg-destructive/90 focus-visible:border-destructive/40 focus-visible:ring-destructive/20`
- `warning`: `bg-warning text-warning-foreground hover:bg-warning/90 …`
- `link`: `text-primary underline-offset-4 hover:underline`

Size (la **spec di default** dei bottoni ZCode):
| Size | Classi verbatim | Geometria |
|---|---|---|
| `default` | `h-7 gap-1 px-2 text-ui-base` | **28px alto, gap 4px, padding orizz. 8px** |
| `xs` | `h-5 gap-1 rounded-sm px-2 …size-2.5` | 20px |
| `sm` | `h-6 gap-1 px-2 text-ui-base/relaxed …size-3` | 24px |
| `lg` | `h-8 gap-1 rounded-lg px-2.5 …size-4` | 32px |
| `icon` | `size-7 …size-4` | 28×28 |
| `icon-xs` / `icon-sm` | `size-5 rounded-sm` / `size-6` | 20 / 24 |
| `icon-md` / `icon-lg` | `size-7 rounded-lg` / `size-8 rounded-lg` | 28 / 32 |

### Menu (dropdown)
- Content: `rounded-lg border border-popover-border bg-menu p-1 text-foreground shadow-md duration-100 data-[side=bottom]:slide-in-from-top-2 …` (variante compatta: `rounded-2xl bg-menu p-0 shadow-xs`)
- Item (spec completa): `menu-item relative flex min-h-7 cursor-default items-center gap-2 rounded-md px-2 py-1 text-ui-base/relaxed text-foreground outline-hidden select-none data-[highlighted]:bg-menu-hover data-[highlighted]:text-foreground data-inset:pl-7.5 data-[variant=destructive]:text-destructive …`
- Hover menu: `bg-menu-hover` (dark `#363636`, light `#f0f0f0`); selezione item: `data-[selected=true]:bg-selected`

### Input / Composer
- Textarea composer (spec completa): `rounded-2xl border-[0.5px] border-input-border bg-input p-3 shadow-(--shadow-composer-soft) transition-colors hover:border-input-border-hover focus-within:!border-input-border-focused focus-within:bg-input-focused`
- Input semplice: `rounded-xl border-input-border bg-input px-3 text-ui-base text-foreground placeholder:text-foreground-subtlest`
- Placeholder: `placeholder:text-foreground-subtlest` (4 occorrenze) / `placeholder:text-foreground-subtle`
- `--shadow-composer-soft` = `0 1px 3px #0000000a, 0 6px 18px #0000000a` (solo light; in dark `0 0 #0000` — niente ombra)

### Chat
- **Bolla messaggio utente**: `rounded-xl rounded-tr-xs border border-border bg-surface px-4 py-3 text-ui-base text-foreground` — il `rounded-tr-xs` (2px) in alto a destra è la firma della bolla
- Contenitore conversazione: `mx-auto flex w-full max-w-4xl flex-col px-4 py-4 md:px-6 md:py-6`; variante: `mx-auto flex max-w-[720px] flex-col gap-3`
- Messaggio: `mx-auto w-full max-w-4xl min-w-0 break-words text-foreground`

### Tooltip
- Content: `rounded-lg border border-border bg-tooltip px-3 py-1.5 text-ui-sm text-tooltip-foreground` (variante: `w-80 rounded-xl border bg-tooltip p-1 shadow-md ring-0`)
- Tag nel tooltip: `rounded-md h-4 inline-flex shrink-0 items-center bg-tooltip-tag px-1.5 text-ui-xs font-medium text-tooltip-tag-foreground`

### Popover/Dialog
- Dialog: `rounded-2xl border border-popover-border bg-popover p-0 text-foreground shadow-md backdrop-blur-2xl`
- Popover: `rounded-xl border border-popover-border bg-popover px-4 py-3 text-left text-popover-foreground shadow-md`

### Focus ring (pattern misurato)
- pattern dominante (50 occ.): `focus-visible:outline-none focus-visible:ring-2` con `focus-visible:ring-input-border-focused` (34 occ.)
- input: `focus-visible:border-input-border-focused focus-visible:bg-input-focused` (15 occ.)
- Le classi `ring-ring/40` presenti nel JS **non generano CSS** (`--color-ring` non è definita nel tema) — classe morta, non riprodurre.

### Istogrammi utility (475 chunk JS renderer >8KB, scan completo dell'asar)

```
rounded-*   lg:347  full:286  xl:258  md:197  sm:79  2xl:46  xs:9  3xl:4
h-*         8:79  7:75  9:65  10:52  5:41  6:39  4:36
size-*      4:710  3:632  5:103  2:50  6:40          (icone: 16px/12px dominanti)
px-*        3:301  2:294  4:226  1:131  5:36  6:36
gap-*       2:664  1:521  3:309  0:105  4:75
text-ui-*   base:1248  sm:567  xs:298  lg:57  caption:28  xl:22
hover:bg-*  hover:88  surface-hover:71  input:8  primary/80:4
bg-token    surface:207  card:108  input:52  popover:44  surface-hover:30  selected:27  menu:19
duration-*  200:21  150:20  100:10  300:8  500:6      ease-out:37  ease-in-out:4
focus       outline-none+ring-2:50  ring-input-border-focused:34
```

Lettura: **rounded-lg (8px) + gap-2 (8px) + px-2/px-3 + h-7 (28px) + text-ui-base** è la cella base di tutta la UI. Bordi molto arrotondati: `rounded-full` (pill) e `rounded-xl`/`rounded-2xl` per superfici composte (composer, dialog, menu).

---

## 5. Tipografia

Da `:root,:host` e `:root` in `styles-NK68EN_n.css`:

```css
--font-sans: ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", "Segoe UI Emoji",
             "Segoe UI Symbol", "Noto Color Emoji";
--font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
             "Courier New", "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
             "Noto Sans CJK SC", monospace;
```

Nessun webfont custom: il tema usa **stack di sistema macOS** (San Francisco via `system-ui`).

Scala UI fluida basata su `--ui-font-size: 14px` (default da `:root`; scalare con l'utente):

| Token | Valore | px @14 |
|---|---|---|
| `--text-ui-2xs` | `calc(var(--ui-font-size) - 5px)` | 9px |
| `--text-ui-xs` | `−4px` | 10px |
| `--text-ui-sm` | `−2px` | 12px |
| `--text-ui-caption` | `−1px` | 13px |
| `--text-ui-base` | `var(--ui-font-size)` | **14px** |
| `--text-ui-lg` | `+2px` | 16px |
| `--text-ui-xl` | `+4px` | 18px |
| `--text-ui-settings-title` | `+10px` | 24px |
| `--text-ui-settings-title-lg` | `+16px` | 30px |

Line-height di default: `/relaxed` = 1.625 sui componenti. Scala Tailwind nativa presente (`--text-xs:.75rem` … `--text-3xl:1.875rem`) ma la UI usa la scala `ui-*`.

Pesi dichiarati: `--font-weight-normal:400`, `medium:500`, `semibold:600`, `bold:700`. Uso misurato nel bundle UI: `font-medium` ×59, `font-semibold` ×23, `font-normal` ×23, `font-mono` ×53 — **medium è il peso "attivo"**, semibold per titoli/emphasis. Tracking: `--tracking-tight:-.025em`, `--tracking-wf-label:.09em` (label workflow).

---

## 6. Raggi, ombre, motion

### Radius (`--radius-*`, Tailwind v4)
| Token | rem | px |
|---|---|---|
| `--radius-xs` | .125rem | **2px** (coda bolla utente `rounded-tr-xs`) |
| `--radius-sm` | .25rem | 4px |
| `--radius-md` | .375rem | 6px |
| `--radius-lg` | .5rem | 8px |
| `--radius-xl` | .75rem | 12px |
| `--radius-2xl` | 1rem | 16px |
| `--radius-3xl` | 1.5rem | 24px |

### Ombre
| Token | Valore |
|---|---|
| `--shadow-xs` | `0 1px 2px 0 #0000000d` |
| `--shadow-sm` | `0 1px 3px 0 #0000001a, 0 1px 2px -1px #0000001a` |
| `--shadow-md` | `0 4px 6px -1px #0000001a, 0 2px 4px -2px #0000001a` |
| `--shadow-lg` | `0 10px 15px -3px #0000001a, 0 4px 6px -4px #0000001a` |
| `--shadow-composer-soft` | light: `0 1px 3px #0000000a, 0 6px 18px #0000000a`; dark: `0 0 #0000` (nessuna) |

### Motion
| Token/valore | Misura |
|---|---|
| `--default-transition-duration` | **.15s** |
| `--default-transition-timing-function` | `cubic-bezier(.4, 0, .2, 1)` |
| `--ease-out` | `cubic-bezier(0, 0, .2, 1)` |
| `--ease-in-out` | `cubic-bezier(.4, 0, .2, 1)` |
| `--animate-spin` | `spin 1s linear infinite` |
| `--animate-ping` | `ping 1s cubic-bezier(0, 0, .2, 1) infinite` |
| `--animate-pulse` | `pulse 2s cubic-bezier(.4, 0, .6, 1) infinite` |
| durata classi più usate | 200ms (×21), 150ms (×20), 100ms (×10) |

---

## 7. Chrome macOS (dal main process)

Fonte: `out/main/index.js` (estratto dall'asar). Codice:

```js
var hc = {x:22, y:23};      // traffic light finestra principale
var Hx = {x:10, y:10};      // traffic light finestra secondaria (quick panel, 512px)

function Mz() {
  return process.platform === "darwin" ? {
    backgroundColor: "#00000000",
    titleBarStyle: "hidden",
    trafficLightPosition: hc,
    vibrancy: "under-window",
    visualEffectState: "active"
  } : …
}
```

| Fatto | Valore | Fonte |
|---|---|---|
| `titleBarStyle` | `"hidden"` (finestra principale e quick panel) | `out/main/index.js` (`Mz()`, secondo costruttore) |
| `trafficLightPosition` (main) | **`{x: 22, y: 23}`** | `var hc={x:22,y:23}` |
| `trafficLightPosition` (quick panel) | `{x: 10, y: 10}` | `var Hx={x:10,y:10}` |
| `vibrancy` | `"under-window"` | `Mz()` |
| `visualEffectState` | `"active"` (vibrancy segue anche quando non a fuoco) | `Mz()` |
| `backgroundColor` | `"#00000000"` (trasparente, la vibrancy mac si vede) | `Mz()` |
| dimensioni main window | `minWidth: 480`, `minHeight: 640` | costruttore con `...Mz()` |
| quick panel | `width: 512`, `maxHeight: 224`, `resizable:false` | secondo costruttore |
| overlay titlebar | solo Windows: `titleBarOverlay: true` | stessa logica platform |

Conseguenza CSS: la UI non disegna una titlebar propria opaca su macOS; `--color-header` (`#fff`/`#202020`) copre la fascia sopra la quale i traffic light (22,23) flottano.

---

## 8. Cosa è vendato e va IGNORATO (non fa parte del DS ZCode)

| Elemento | Dove | Perché ignorarlo |
|---|---|---|
| `pdf-viewer-Dgb4oCkS.css` | `out/renderer/assets/` | 100% pdf.js: `.textLayer`, `--highlight-bg-color:#b400aa`, `--highlight-selected-bg-color:#006400`. Token di pdf.js, non di ZCode |
| Temi highlight.js | `node_modules/highlight.js/styles/*.css` | palette di terze parti; il DS non definisce `.hljs` (0 hit nel CSS principale) |
| KaTeX CSS | inlinato nel CSS principale + `node_modules/katex` | solo per il rendering formule: font `KaTeX_Main` ecc. Layout math, non token DS |
| xterm CSS | inlinato + `node_modules/@xterm/xterm/css/xterm.css` | engine terminale vendato; i **colori** arrivano dai token DS `--color-terminal-*` |
| `visualize.css` | `out/plugin-sandbox/` | sandbox plugin (echarts/d3), non la UI principale |
| github-markdown-css | **assente** dal bundle (0 hit nella lista file) | niente da filtrare |
| `.prose` / `--tw-prose-*` | CSS principale | plugin Tailwind Typography per il markdown della chat; usa la scala oklch Tailwind, non i token tematici — trattarlo come baseline tipografica, non palette |

Regola di classificazione applicata: sono token DS solo quelli definiti/sovrascritti in `:root,:host`, `.dark`, `.theme-zai-light`, `.theme-zai-dark` (o referenziati dalle className dei componenti) — tutto ciò che sta in un CSS di libreria vendata non è design system.

---

## 9. Note di mining

- I chunk `menu-*.js` e `tooltipContext-*.js` citati dall'ask **non sono i componenti UI**: `menu-CIjOha5U.js` è l'icona lucide "menu", `tooltipContext-BIbjmZ7b.js` è recharts. La spec verbatim di menu/tooltip/composer/chat è stata estratta da `styles-Dv5E6Odo.js` (bundle UI, x1238 `text-ui-base`). `button-DeDmlciX.js` è il vero componente Button (cva).
- `--color-ring` (usata dalle classi JS `ring-ring/40`) non è definita in nessun tema → nessuna utility CSS generata; il focus reale usa `--color-input-border-focused` (= `--color-border-hover`) e ring su `--color-border-hover`/`--color-brand`.
- I semantici esistono con i nomi **success / warning / destructive** (+ `*-surface`, `*-surface-foreground`); **non esiste** alcun token `--color-danger` o `--color-error` nel DS (l'unico hit `--color-danger` è un uso di classe in un selettore JS, non una definizione).
- La selezione (`--color-selected`) è **neutra** in entrambi i temi (5–10% di opacità su foreground-inverso), mai tintata blu: coerente con la regola 1d (selezione neutrale = segnale di design non-AI).
- `app-window-mac-CtEd6Dl7.js` del renderer è un'icona lucide (`app-window-mac`); il chrome macOS vero sta tutto in `out/main/index.js`.
- Esiste un secondo CSS per Windows: `--color-background-win-alt` (`#ececee`/`#2b2b2b`), non pertinente al tema macOS.
