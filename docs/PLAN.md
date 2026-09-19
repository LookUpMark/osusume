# Piano di implementazione e stato

Riprendere il progetto: leggere `docs/README.md` → `decisions.md` → `architecture.md`, poi la tabella qui sotto. Ogni milestone ha DoD verificabile.

## Milestone

| M | Contenuto | DoD | Stato |
|---|---|---|---|
| M0 | Scaffold: pnpm+TS+Vite+Hono, /api/health, CI, LICENSE, README | `pnpm dev` → pagina + health 200; CI verde | ✅ |
| M1 | Profilo gusti: `record-fixtures.mjs`, `anilist.ts`, `profile.ts`, GET /api/profile, UsernameForm+ProfilePanel, test profilo | Profilo generato offline da fixture; UI mostra amati/odiati; `pnpm test` verde | ✅ |
| M2 | Motore deterministico: `candidates.ts`, `scoring.ts`, `franchise.ts`, `recommend.ts`, POST /api/recommend, RecoCard/griglia/filtri, test scoring+franchise | Recos complete SENZA LLM con why deterministico; test: S3 senza S1 → entry point; dropped S1 esclude S2; badge gem sotto 40k pop | ✅ |
| M3 | Layer LLM: `llm.ts`, POST /api/explain, cache spiegazioni, whyNot | Con Ollama attivo: spiegazioni su top-10; LLM irraggiungibile → fallback senza errori (test automatico); seconda richiesta identica → cache | ✅ |
| M4 | Rifinitura: toggle lingua EN (default)/IT, gems view, dedupe franchise espandibile, stati vuoto/errore, CSS, ui-ux-audit, README quickstart | Audit senza P0; quickstart clone → rec in ≤5 comandi | ✅ (audit statico 0 FAIL; verifica visiva browser da fare con API reale) |
| M5 | Hardening: e2e vs API reale, liste >1k, utente senza score, 429 reale, edge fixture (lista vuota, 1 entry, zero score), tag v1.0.0 | Checklist e2e documentata; nessun crash su edge | ⬜ bloccata su API AniList stabile / username reale per fixtures |
| M6 | Setup wizard LLM: hw detect → suggerimento Bonsai-27B/8B → download via LM Studio headless (`lms`) → auto-config backend a ogni avvio (`ensureLlmServer`) | Wizard e2e su mac reale; suite verde; degrado a LLM spento intatto | ✅ logica+test (21/21); e2e con download reale e LM Studio: vedi checklist sotto |

## Come verificare

```bash
pnpm install
pnpm typecheck && pnpm test     # unit + smoke API su fixture
ANILIST_FIXTURES=fixtures pnpm dev   # app offline su fixture sintetiche
# API reale (quando AniList è su): pnpm dev, poi inserire uno username
```

## Aperti

- **M5**: username AniList di Marco = **LookUpMark** (2026-09-07). Registrare fixtures reali e provare il flusso e2e: `pnpm record-fixtures LookUpMark` poi `pnpm dev`. Il 2026-09-07 l'API rispondeva 403 "temporarily disabled due to severe stability issues" — riprovare quando torna su.
- Release v1.0.0 dopo M5 (commit solo a nome Marco, push su richiesta)

## Esito audit avversariale (20260907-193547)

Report: `docs/audits/AUDIT-20260907-193547.md` (81 findings validi: 0 CRITICAL, 5 HIGH, 16 MEDIUM, 56 LOW, 4 INFO; patch proposte in `docs/audits/patches/`, MAI applicate lì).

**Fix applicati in follow-up (79/81 pieni + 2 parziali)**: Host/Origin allowlist su /api (DNS rebinding chiuso), disclosure minimale (lms.path e baseUrl non più esposti), profilo gusti ordinato per affinità (profile.ts + candidates.ts), wizard download collegato al job reale, form non più bloccato dopo la prima ricerca, retry 429 limitato (max 10, delay sanitizzato), runLms escalation SIGKILL + promise sempre settled, runInstall con timeout 10min, catene franchise illimitate con root canonica min-id (memoizzate), avoided include le serie droppate, fallback LLM non più cachati, parse JSON quote-aware, write cache atomiche, contract UI/server allineati su SetupStatus, test estesi con boundary e mutation-tested (26/26 verdi).

Differiti dichiarati: ci.yml actions ancora tag-based (@v4, mitigato con `permissions: contents: read` — SHA pin da fare con lookup online); CACHE_DIR iniettabile via env ma i test llm in-process scrivono ancora in data/cache (gitignored).

## Docker (2026-09-08)

- `docker compose up -d` = full mode (app + Ollama + Bonsai auto-pull, wizard bypassato via env). App-only per macOS + LM Studio host: header di compose.yaml.
- Docker assente sul mac di Marco: il build + smoke container girano in CI (job docker). Runtime ollama pull di Bonsai Q1_0 via HF da validare su host docker reale; fallback documentato `qwen3:8b`.

## Checklist e2e manuale M6 (mac di Marco, LM Studio reale)

- [ ] `rm -f data/config.json && pnpm dev` → wizard mostrato all'avvio
- [ ] Status mostra M-chip + RAM giuste; ≥16 GB → Bonsai-27B consigliato
- [ ] Tasto download → barra indeterminata + logTail; alla fine step 3 automatico
- [ ] Finish → `lms daemon up` + `server start` + `load --context-length=8192` in data/llm.log; health passa a `state:"up"`, `enabled:true`
- [ ] Consigli con username reale → spiegazioni LLM (source "llm"/"cache")
- [ ] Kill del server LM Studio → restart app → recupero automatico
- [ ] Porta 1234 occupata da altro processo → solo log, app integra
- [ ] `rm data/config.json` → wizard riappare
- [ ] `.env` con `LLM_BASE_URL` custom → wizard mai mostrato, ensure no-op

## Scoring v2 — expert-first (2026-09-19)

Requisito Marco: la chat e le spiegazioni parlano al *telespettatore* (trama, temi, collegamenti con ciò che ha visto), mai di algoritmi. Fatto subito (v0.7.4):

- descrizioni AniList (HTML-strippate, spoiler-tag esclusi) nel contesto chat e nel prompt explain
- `lovedOverlap` esposto: per ogni titolo consigliato il modello riceve i collegamenti reali col gusto (tema → titoli visti in cui è apparso)
- system prompt chat = esperto amico: gergo dell'app bannato (affinity/match/algoritmo), numeri solo su richiesta esplicita, risposta alla domanda effettiva

Tranche successiva (da validare su fixture reali):

- [ ] similarity semantica su description (embedding locali) per catchare collegamenti tematici che i tag si perdono
- [ ] peso "mood/continuità": premi titoli che condividono tone-setting con le ultime N sessioni viste
- [ ] franchise-aware: spiegare il punto di ingresso (cosa devi aver visto prima) dentro il why, non solo nei badge
- [ ] diversità: MMR sul pool finale per non mandare 5 shonen dello stesso studio in top 10
