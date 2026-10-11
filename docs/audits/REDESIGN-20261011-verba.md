# REDESIGN 20261011 — Osusume nello stile di Verba (design system Claude/Anthropic)

Ristrutturazione completa della UI: da "Seanime" (dark viola #121212/#9f92ff, Geist, rail icone 76px, glow/glass) al design system di **Verba** — warm minimal-editorial, replicato token-per-token dal suo `index.html` (che dichiara: *"Design System Claude (Anthropic) — tokens pasted verbatim"*). Nessuna funzionalità toccata.

**Vincoli rispettati**: stack Electron+React+FastAPI invariato; `lib/logic/` intatto; 35 marker `data-od-id` preservati (`check-od-ids` 35/35); parità i18n en/it (217=217); chiavi localStorage esistenti invariate (nuova `osusume-theme`); timing/polling/formati `/110` invariati.

## Mappatura prima → dopo

| Aspetto | Seanime (prima) | Claude/Verba (dopo) |
| --- | --- | --- |
| Palette | #121212 / #1c1c1c / viola #9f92ff | crema #f5f4ed / surface #faf9f5 / warm #e8e6dc; dark #1f1e1b/#262521/#30302e; accento terracotta #c96442 (light) / coral #d97757 (dark) |
| Tema | dark-only | **light default (prefers-color-scheme) + dark toggle persistente** `osusume-theme` |
| Font | Geist/Geist Mono self-hosted | stack Verba: `"Anthropic Serif", Georgia` (titoli) / `"Anthropic Sans", Arial, system-ui` / `"Anthropic Mono", …` — **zero webfont** |
| Navigazione | rail icone 76px + tooltip | **sidebar testuale 240px** (brand serif + tag, nav icona+label 44px, footer card stato) + bottombar mobile ≤900px |
| Intestazione viste | topbar con page-title | **utility header** (search + theme toggle + user) + **screen-head serif per vista** |
| Hero | full-bleed blur + scrim viola | card surface radius 12, copertina a lato, eyebrow accent, titolo serif, CTA primary/secondary |
| Card media | overlay gradiente scuro sul poster | poster sopra + corpo su surface (titolo, meta mono, barra affinità pill coral, badge pill) |
| Punteggi | mono /110 ovunque | mono nelle pill; **numero grande in serif coral** nel dialog (pattern XP hero di Verba) |
| Bottoni | viola con glow ombra | primary coral + ring self 1px; secondary surface-warm + ring; ghost; sm 32px |
| Badge/chip | mono uppercase su surface-2 | pill `color-mix` tinte (gem=accent, entry=muted, success/danger per stato) |
| Chat | bubbles surface-2/viola | **tutor pattern**: assistant surface-warm (coda 4px), user coral/accent-on, chat-head con avatar torii, typing dots blink scaglionati |
| Progress SSE | barra 3px + label | **lesson-progress**: pill 10px coral + contatore mono; skeleton shimmer |
| Errori/banner | testo viola/bianco | card a tinta danger/warn (`color-mix` 92–94%) con icona |
| Feedback transienti | inline only | **toast invertito fg/bg** (watchlist aggiunto, impostazioni salvate) |
| Wizard | card con bottoni "btn-primary" incompleti (pre-audit), rem | onboarding Verba: scenario-card selezionabili (aria-pressed → border coral + ring), barra download pill coral, joblog mono, wordmark serif |
| Impostazioni | righe full-width poi centrate 760px | role-row Verba (label fg-2 / controlli a destra), input surface+border-soft focus #3898ec |
| Icone | stroke 1.6 | stroke **1.75**, taglie 18/22px (`.icon`/`.icon-lg`), sun/moon da Verba |
| Focus | outline 2px ring viola | `box-shadow` ring blu 3px (pattern Verba), input focus border #3898ec |
| Electron | backgroundColor #121212 | backgroundColor **#f5f4ed** (flash d'avvio light) |
| Marchio | torii viola su accent | torii **stroke coral su squircle charcoal in gradiente** (trattamento logo Verba); icone installer invariate |

## File toccati

- `frontend/src/design-system/tokens.css` — riscritto: token Verba verbatim (light+dark) + base + primitive btn/badge/card
- `frontend/src/styles.css` — riscritto integralmente nel linguaggio Verba
- `frontend/src/components/Sidebar.tsx` — nuovo (sostituisce Rail.tsx); esporta NavIcon/VIEW_ORDER per la bottombar
- `frontend/src/components/Rail.tsx` — eliminato; `fonts.css` + `public/fonts/` — eliminati (zero webfont)
- `App.tsx` — shell .app + main-wrap, tema (state+effect+toggle), model da health, toast, screen-head per vista, toolbar pill, bottombar
- `Topbar.tsx` (utility header + theme toggle), `Hero.tsx` (card), `MediaCard.tsx` (poster+corpo), `ChatPanel.tsx` (chat-head + prop model), `SetupWizard.tsx` (scenario aria-pressed), `LoginModal.tsx`/`DetailDialog.tsx`/`LlmSettings.tsx`/`AniListAuth.tsx`/`CfSettings.tsx` (classi Verba)
- `i18n.ts` — +4 chiavi per lingua: `brandTag`, `themeDark`, `themeLight`, `toastWatchAdded` (217=217)
- `desktop/main.ts` — backgroundColor crema
- `DESIGN.md` — riscritto come spec del sistema Claude/Verba; wiki `08-frontend-app.md` aggiornato

## Esito

**Verifiche verdi**: `pnpm typecheck` · `pnpm test` 16/16 · `pnpm build` · `check-od-ids` **35/35** · parità i18n **217=217** (+4 chiavi/lingua: `brandTag`, `themeDark`, `themeLight`, `toastWatchAdded`).

**Pass visivo**: matrice Playwright 1280×832@2x — **EN+IT × light+dark** su tutte le 7 viste + detail dialog + login modal (switch-user) + chat con LLM reale (oMLX, EN light + IT dark) + wizard step 1 (light+dark) + dropdown ricerca = **41 screenshot**, zero errori console nelle viste. Controlli specifici: card allineate per riga (fix flex column mantenuto), etichette IT più lunghe gestite (nav "Gemme nascoste" wraps a 2 linee entro il min-height 44; wizard-steps ellipsis), contrasti semantici ≥4.5:1 in entrambi i temi (token dark auditati di Verba), focus ring blu su interattivi, `prefers-reduced-motion` esteso a shimmer/blink/slide.

**Note operative**: il tema persiste su `osusume-theme` e si applica via `data-theme` su `<html>`; l'auto-login OAuth reale (token in `data/config.json`) salta il modal nelle sessioni di test — il modal è stato verificato via switch-user. Gli screenshot del README (`docs/screenshots/`) sono stati rigenerati dalla matrice (home/login/search/detail/chat/profile/settings/setup-wizard/gems, tema light EN). Il bundle di produzione è quello validato via build; `desktop/main.ts` porta `backgroundColor: #f5f4ed` (flash d'avvio light) — il fumo completo dell'installer è demandato alla prossima release.
