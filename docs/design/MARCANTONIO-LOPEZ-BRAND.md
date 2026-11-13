# MARCANTONIO-LOPEZ-BRAND.md — estrazione del canone di brand

Fonte di verità del design system Osusume dalla v1.6.0: il **brand personale "Marc'Antonio Lopez"** estratto con **Open Design** dal profilo `https://github.com/LookUpMark` (misurato su lookupmark.github.io). Questo documento registra *cosa* è stato misurato, *dove* vive il canone e *come* è stato mappato sui token dell'app. La spec operativa è in [`DESIGN.md`](../../DESIGN.md).

## 1. Progetto Open Design

- Progetto OD: `brand-marcantonio-lopez` (brand id `marcantonio-lopez`, status `ready`; designSystemId `user:github-com` published)
- Dati utente OD: `~/Library/Application Support/Open Design/namespaces/release-stable/data/projects/brand-marcantonio-lopez/`
- **Fonti del canone** (in ordine di autorità):
  1. `brand.json` — palette + tipografia + voice + layout posture (dichiarato fonte di verità)
  2. `assets/tokens.css` — design system app light+dark ("single source of truth" CSS)
  3. `colors_and_type.css` — token semantici `--ct-*` + `@font-face` Inter + scala tipo
- `system/` (BRAND-SYSTEM.md, tokens.*.json, variables*.css) è **derivato** (seed antd, 218 token/tema): si rigenera con `od brand finalize`, non si copia. Da lì provengono solo i semantici di status e la scala primaria 10-step.
- **Decisione di canone (2026-11-13**, registrata anche in `~/.agents/skills/brand-canon-alignment-audit/.ledger.jsonl`): la palette **misurata dalla pagina GitHub** vince sui layer concorrenti (sito live, layer antd). Bianco `#ffffff`, accent `#d43511`, secondary `#023b95`, Inter, radius 8px.

## 2. Palette misurata (brand.json, hex ↔ oklch roundtrip-verified)

| Ruolo | Nome | Hex | oklch | Uso canonico |
|---|---|---|---|---|
| background | Background | `#ffffff` | oklch(100% 0 0) | canvas pagina |
| surface | Surface | `#f5f5f5` | oklch(97.02% 0 0) | card / superfici alzate |
| foreground | Foreground | `#000000` | oklch(0% 0 0) | testo |
| muted | Muted | `#8c8c8c` | oklch(64.01% 0 0) | testo secondario/etichette |
| border | Border | `#dbdbdb` | oklch(89.14% 0 0) | hairline 1px |
| **accent** | Accent | **`#d43511`** | oklch(57.24% 0.20 33.31) | colore di brand |
| accent-secondary | Accent secondary | `#023b95` | oklch(38.35% 0.158 260.46) | secondario / link |

**Dark progettato a parte** (`assets/tokens.css [data-theme="dark"]`, non inversione): paper `#131311`, surface `#1c1c1a`, raised `#1f1f1b`, ink `#f5f5f0`, ink-secondary `#c4c2b9`, muted `#a3a3a3`, hairline `#303030` / strong `#3f3f38`, **accent `#ff6b4f`** con tint `#2a110b`, accent-secondary invariato `#023b95` (la variante link dark `#1a4a8c` esiste solo nel layer derivato `system/` — non adottata).

**Status** (dal seed antd, "on-brand by construction"): light `#52c41a` / `#faad14` / `#ff4d4f`, dark `#64b537` / `#dcaa37` / `#dc6966`; varianti **contrast-safe per il testo** `#389e0d` / `#d48806` / `#d9363d` (canone: `#52c41a` su bianco è ~2:1, mai come testo). `--info` = accent-secondary **deliberatamente non rosso** (un info rosso si confonde col danger).

**Scala primaria 10-step** (`system/tokens.compact.json`, per hover/active dell'accent): `#ffeee6 #ffceb8 #faab8c #ed835f #e05b36 #d43511 #ad1f05 #871000 #610800 #3b0300`.

## 3. Tipografia

- **Inter**, pesi **400 / 600 / 700**, self-hosted (`assets/fonts/inter-*.woff2`, OFL) — nel repo: `public/fonts/`, `@font-face` in `tokens.css`, preload regular+semibold in `index.html`.
- Fallback: `system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif`. Mono per dati: `ui-monospace, SF Mono, Menlo, Consolas…`.
- Scala `--ct-*`: display 56 · h1 40 · h2 32 · h3 24 · body 17 · small 14 · caption 12 · meta 11. Leading: tight 1.2 / body 1.55. Tracking: display −0.02em, caps 0.07em.
- *(Instrument Sans resta su disco nel progetto OD ma NON è dichiarato: `@font-face` rimosso — legacy.)*

## 4. Posture / layout

- Radius canon **8px** (sm 6, lg 12, pill per filtri/barre); griglia base 4px con ritmo 8px; bordi **1px solid** `--ct-color-border`.
- **Ombre assenti o molto leggerissime**, riservate agli overlay (brief `context/source-context.md`).
- Motion: app `120/200/320ms`, ease-out `cubic-bezier(0.2, 0.65, 0.2, 1)` (canone app tokens); `prefers-reduced-motion` rispettato.
- Regole posture (brand.json `layout.postureRules`): 8px radius · 1px borders · 8px baseline grid · *warm neutral canvas, not beige* · **single accent used sparingly**. Vietati: gradienti dominanti, glassmorphism/vibrancy, card ovunque, dashboard aesthetics.

## 5. Marchio

- `logos/logo-mark.svg` (primario): ritratto minimale a contorni, stroke `#242629` **3.5/256**, round cap/join, sfondo trasparente, **un solo dettaglio sage `#829F68`** (il simbolo AI, stroke 2.5). Invisibile su dark → `header-inline.svg` è la variante chiara (demoted to alternates).
- **Scelta Marco (v1.6.0)**: il marchio di Osusume resta il **torii**, ricreato *nello stesso identico stile* del logo OD: line-art a stroke uniforme ink (`--mark-fg`), round cap/join, **kasagi = unico elemento sage** (`--mark-accent`), tile flat raised (niente gradiente), niente fill. Favicon e icone installer allineate (canvas paper bianco, hairline `#dbdbdb`).
- Imagery: solo screenshot reali e composizioni tipografiche; vietati stock, ritratti generati, AI-slop, decorazioni neurali.

## 6. Voice (brand.json, per copy e note di release)

Adjectives: *applied, measured, technical*. Tono diretto e professionale, capacità concrete invece di astrazioni. **Use:** LangGraph, Neo4j, RAG, PEFT, LoRA, Fine-tuning, ML Engineer, AI Delivery Center. **Avoid:** visionary, revolutionary, game-changing, AI enthusiast, building the future.

## 7. Mappatura sui token Osusume (mappa canone → app)

| Canone OD | Token Osusume | Note |
|---|---|---|
| `--paper` / `--bg` | `--bg` | #ffffff / #131311 |
| `--surface` / `--bg-subtle` | `--surface`, `--sidebar` | card E sidebar = surface; il bordo 1px delinea |
| — (terzo passo assente) | `--surface-warm` | derivato: `#ececec` light, `#22221e` dark (= ghost-hover antd) |
| `--surface-raised` | `--input-bg`, `--mark-bg` | input e tile marchio = raised |
| `--ink` / `--ink-secondary` | `--fg` / `--fg-2` | v. deviazioni: fg-2 schiarito in light |
| `--ink-muted` | `--muted`, `--meta` | meta = muted al 60% |
| `--hairline` / `--hairline-strong` | `--border` / `--border-hover` | `--border-soft` derivato |
| `--accent-a` / `-tint` / `-strong` | `--accent` / `--selected-bg` / `--selected-fg` | la selezione dell'app È la tinta accent del canone |
| `--accent-secondary` | `--accent-secondary` | link chat |
| `--btn-primary-*` | `--btn-primary-*` | **primario = ink**, non rosso (canone) |
| `--focus-ring: var(--accent)` | `--brand` + `--focus-ring` | focus = accent (box-shadow string) |
| status + `-text` | `--success/--warn/--danger` | Osusume usa direttamente le varianti contrast-safe |
| `--dur-*` + `--ease-out` | `--motion-*` + `--ease-standard` | fast 120 / base 200 |

## 8. Deviazioni dichiarate (adattamenti app, deliberate)

1. **`--fg-2` light = `#3d3d3d`**, non il muted canonico `#8c8c8c`: in Osusame il token porta testo secondario piccolo (hero-why, errori, firme) che a `#8c8c8c` scende sotto 4.5:1; il muted canonico resta su `--muted`/`--meta` (etichette). In dark `--fg-2` = `#c4c2b9` (canone, ink-secondary).
2. **Scala tipo delle testate**: gli step h1/h2 Osusume mappano su h2/h3 canonici (32/28) per la densità dell'app; display 56 e h1 40 restano disponibili (`--text-4xl`/`--text-3xl`).
3. **Ombre overlay conservate** (toast/dialog/dropdown) ma ridotte a leggerissime — il canone vieta ombre pesanti, non la profondità degli overlay.
4. **Semantici usati come testo**: i token `--success/--warn/--danger` dell'app valgono le varianti contrast-safe canoniche, perché nell'app compaiono anche come colore testo (badge, stati set-row).
5. **Spacing invariato** (4/8/12/16/20/24/32/48 — già su griglia base 4px): la sostituzione con la scala estesa del canone app (fino a 128px) gonfiava i layout densi senza beneficio.
6. **Nessuna vibrancy**: il canone vieta il glassmorphism; finestra desktop opaca su paper (lezione v1.5.1 sulla translucenza resta valida per qualunque eventuale tema futuro).
7. **Link dark = `#023b95`** (canone app tokens): contrasto ridotto in dark, compensato da underline; la variante `#1a4a8c` del layer derivato non è adottata.

## 9. Cosa NON è stato importato

- `system/` (seed antd completo): derivato, si rigenera — mai editato a mano.
- `imagery/hero-*.png` e `ui_kits/`: artefatti del sito portfolio, non dell'app.
- `og-image.png` / `favicon-*.png`: sostituiti dai corrispondenti Osusume (`public/favicon.svg`, `public/icon.svg`, `build/icon.*`).
- Voice vocabulary di dominio ML: non appare nella UI di Osusume (l'app parla anime, non portfolio).
