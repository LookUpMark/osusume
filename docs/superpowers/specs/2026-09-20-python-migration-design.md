# Design — Migrazione osusume a backend Python/FastAPI (CQRS-lite) + frontend modulare

Data: 2026-09-20 · Stato: approvato (dialogo di brainstorming, 4 decisioni confermate da Marco)
Base fattuale: workflow di comprensione a 7 lettori paralleli sull'intero repo (645k token di mappa strutturata, sessione 2026-09-20).

## 0. Obiettivo e decisioni

Portare Osusume (oggi: server Hono/Node + UI React + shell Electron, tutto TypeScript) a:

- **Backend 100% Python** (FastAPI), struttura CQRS-lite in-process.
- **Frontend separato e modulare**, graficamente **identico**, rimodulato per ridisegno con OpenDesign.
- **Zero cambiamenti di funzionamento**, verificati con **golden master + diff automatici**.
- **Distribuzione desktop invariata** per l'utente finale: Electron resta come **shell minimale** (solo launcher), il figlio diventa un binario PyInstaller.
- **Storage invariato**: `config.json`, `data/cache/`, `llm.log`, `fixtures/` — zero migrazioni dati.
- **Strategia big-bang su branch** `py-backend`, cutover unico dopo i gate.

Decisioni registrate (brainstorming 2026-09-20):

| Decisione | Scelta |
|---|---|
| Distribuzione desktop | Electron shell minimale (Node solo launcher, nessuna logica) |
| Definizione di "porting perfetto" | Golden master + diff automatici in CI |
| Strategia di migrazione | Big-bang su branch + gate, niente proxy temporanei |
| Profondità CQRS | CQRS-lite in-process (commands/queries separati, niente event store/DB) |

## 1. Architettura target

```
backend/
  pyproject.toml            # uv, Python 3.12; deps runtime: fastapi, uvicorn, httpx, regex
  app/
    main.py                 # factory uvicorn: HOST/PORT, static dist/ + SPA fallback, lifecycle, ensure/shutdown
    api/                    # router 1:1 con Hono: stessi path, stessi payload, stessi errori
    core/                   # middleware Host-allowlist, error map canonica, .env loader custom,
                            #   fixture-mode state (localMode/autoFallback/fixturesAvailable), config accessors
    commands/               # setup wizard, config update, local-mode, chat send, shutdown
    queries/                # recommend, profile, explain, lookup, health, app-update, setup/status
                            #   + read-state in-memory (resultCache, update memo, lsCache)
    domain/                 # porting PURA senza I/O: profile, franchise, scoring, candidates (query building),
                            #   pipeline recommend (community, mood, dedupe/MMR/top50, avoided), textLinks, tokenizer
    adapters/anilist/       # client GraphQL (6 query esatte), token bucket, cache disco sha256+TTL,
                            #   retry/429 ladder, fixture mode, mapMedia
    adapters/llm/           # client OpenAI-compat, prompt builder explain/chat, parseExplanations,
                            #   expl cache, llmHealth/resolveServedModel, logLlm
    adapters/system/        # hardware detect, resolve/controllo lms+omlx, job download singleton, update check GitHub
    shared/                 # modelli pydantic specchio 1:1 di src/shared/types.ts, strings i18n en/it
frontend/                   # React 19 + Vite (stesso stack dell'attuale src/ui)
  src/design-system/        # tokens.css (estratto dal :root di styles.css), primitives, icone SVG
  src/components/           # gli 11 componenti esistenti, presentazione pura
  src/views/                # le 7 viste (home, recos, gems, chat, profile, avoid, settings)
  src/lib/                  # api client (da src/ui/api.ts), tr() i18n, formatters, sort/filtri
  src/App.tsx               # SOLO orchestrazione stato e gating
desktop/                    # electron/main.ts minimale: spawn sidecar PyInstaller + finestra (semantica invariata)
fixtures/                   # invariato (network di sicurezza offline, inclusa nei package desktop)
tests/                      # pytest (backend) + golden master + harness
```

Il frontend resta un bundle Vite (`dist/`) servito dal backend:SPA fallback `GET /* → index.html`.
Non esiste routing server-side: nessun framework router.

## 2. Backend — specifiche di fedeltà

### 2.1 Contratto HTTP (congelato in P0 su `docs/contract.md`)

| Endpoint | Semantica da preservare |
|---|---|
| `GET /api/health` | `{ok:true, llm:{enabled,model,state}, local:{on,available,auto}}`; chiama `ensureLlmServer()` throttled (60s se up, 15s altrimenti) |
| `POST /api/local-mode` | body `{auto:bool, local?:bool}` (local presente SOLO se passato); 400 `invalid_request` se auto non bool; `local:false` forza retry live; env pin `ANILIST_FIXTURES` vince su setLocalMode |
| `GET /api/app-update` | memo 5 min (fallimenti cachati come "nessuna info", mai errore), `?fresh=1` bypass; senza APP_VERSION → tutti null/false SENZA rete; GitHub timeout 5s |
| `GET /api/config` | `{llm:{model}}` SOLO (mai baseUrl/path) |
| `GET /api/profile/:user` | username URL-encoded; 400 `invalid_username` fuori da `^[A-Za-z0-9_-]{1,32}$` |
| `POST /api/recommend` | `{username, lang?}` → RecoResult non-wrapped; lang whitelist en/it default en (silenzioso) |
| `POST /api/explain` | ids filtrati `typeof number` + dedup Set; 400 se vuota/username invalido; staleOk; id fuori recos → scoreArbitrary; → `{explanations:[{id,text,source}]}` |
| `POST /api/chat` | history: solo user/assistant, content.trim()>0, slice 4000 char, ultime 12, ultima DEVE essere user; extra = id non in recos slice 5; LlmError → 503 `llm_unavailable` |
| `POST /api/lookup` | q trim 2..80; format MUSIC escluso; recos riordinate secondo ordine ricerca |
| `GET /api/setup/status` | SetupStatus completo; disclosure-minimal (path sempre null); modelServed gate su 'up' |
| `POST /api/setup/{action}` | 7 action: install-cli, download, finish, reset, omlx-download, cancel, ack; errori setup 400/409/500 con codici dedicati |
| `POST /api/shutdown` | shutdownBackend() + exit(0) dopo 200ms (contratto Windows: SIGTERM non esegue exit handler) |
| Static | `dist/` + SPA fallback; 403 `forbidden` su Host header non in {127.0.0.1, localhost, ::1} (anche con HOST=0.0.0.0) |

Error map canonica: AniListError 404→404 `user_not_found`; AniListError altro→502 `anilist_error`+message; LlmError chat→503 `llm_unavailable`; validazione→400; setup busy→409, lms_missing/omlx_missing/invalid_model/invalid_url/unsupported_repo→400, reset_failed→500; altro→500 `internal_error`. Il client mostra il codice grezzo: i codici SONO la UI di errore.

### 2.2 Fedeltà numerica e semantica (deviazioni silenziose da prevenire)

1. **`Math.round` ≠ `round()` Python** (banker's): usare `floor(x+0.5)` (helper `js_round`). Punti toccati: meanScore arrotondato a 1 decimale, altrimenti i round sono lato UI (invariato).
2. **`toLocaleString(lang)`** nei template why (`whyNeutral`, `whyGem`): separatori **hardcoded** en=`,` it=`.` — MAI locale di sistema.
3. **Sort stabili** ovunque (tie → ordine di inserimento): `sorted()` Python è stabile; attenzione ai tie-break espliciti di MMR (`>` stretto → primo indice).
4. **profile.hash**: sha256 di `entries.map("${mediaId}:${status}:${score}:${repeat}").sort()` — sort **lessicografico** (stringhe), join `|`, primi 16 hex. Un sort numerico rompe l'invalidazione cache spiegazioni.
5. **Tokenizer**: lowercase → NFKD → strip combining marks → `[^\p{L}\s]`→spazio (richiede lib `regex` per `\p{L}`) → filtra len>3 e STOP_WORDS. STOP_WORDS copiata integrale da scoring.ts (include forme strappate `perche`/`perché` e duplicati).
6. **Cache keys**: AniList = sha256(query + JSON.stringify(variables)) — JSON.stringify Python-equivalente: separatori `", "`/`": "` e ordine inserimento chiavi uguali a JS (usare serializzatore dedicato, verificato sui golden). Expl = sha256 di `` `${username}|${profile.hash}|${lang}|${llmModel()}|${llmBaseUrl()}|${PROMPT_VERSION}|` + id ordinati numerici join(",") ``.
7. **Tutti i pesi/soglie** portati in un modulo `weights.py` unico specchio di WEIGHTS (valori in §5 — la vera fonte sono i test portati).
8. **MMR/diversify**: portare come funzione PURA (in TS muta gli oggetti).
9. **Timestamp**: `updatedAt` è in **secondi** unix (non ms) — mai convertire; `exp` nei file cache è in **ms** epoch.
10. **`.env` loader custom**: righe `^([A-Z_]+)=(.*)$`, env pre-esistente vince, strip quote matched, troncamento a ` #`. NON usare python-dotenv default (semantica diversa).
11. **`hasCustomEnv()`** = sola PRESENZA di `LLM_BASE_URL` (non verità) → wizard bypassato. Il compose conta su questo.
12. **Config precedence**: env > config.json > default; lettura tollerante (corrotto → `{}`); updateConfig = merge-patch, chiave `undefined`/assente-nella-patch-but-explicit cancella (replicare la semantica dei branch /finish skipped), write atomica tmp+rename.

### 2.3 Stato, processi, concorrenza

- Token bucket asyncio: capacità 3, refill RATE_PER_MIN/60 (default 25/min, min 1) — OGNI richiesta GraphQL lo attraversa.
- Retry AniList: rete/5xx/non-JSON → 3 retry backoff 1s·2^attempt → `AniListError('AniList unreachable: …', 502)`; 429 → max 10 round, sleep min(retry-after,60)|5s; timeout per-request 15s.
- resultCache in-memory: chiave `user:lang:{local|live}`, TTL 10 min, prune-on-write, inflight dedup, staleOk (explain/chat), refresh bypass.
- Job download singleton con jobGen (no-op se superata — un child finito non resuscita un job cancellato), logTail ring 2000 char.
- runlms: SIGTERM → SIGKILL a +5s → settle forzato a +15s; array-args senza shell.
- ensureLlmServer: short-circuit nell'ordine documentato (hasCustomEnv → !setupDone → skipped/custom → no model → ensureLock → throttle), probe /models 4s, sequenza lms `daemon up → server start → ls --json → load <m> -y --gpu=max --context-length=8192`.
- Auto-fallback locale: AniListError status≠404 + autoFallback + fixtures available → setLocalMode(true) + UN retry; errore secondario inghiottito.
- Update check: memo 5 min anche sui fallimenti; senza APP_VERSION mai rete; cmpVersion 3 parti, strip `v`, taglio a `-`.

## 3. Frontend — rimodulazione (zero cambiamento visivo)

Stack invariato (React 19 + Vite). Lavoro di sola riorganizzazione:

- `App.tsx` (693 righe) smembrato: logica in `lib/` (boot/run order, sort/filtri/gemRank, polling 60s health, localStorage 3 chiavi, error mapping, chat slice(-12), explain on-demand + fold), presentazione in `components/`+`views/`, token CSS in `design-system/tokens.css`.
- **Contratto di redesign OD**: i marker `data-od-id` esistenti sono i punti di aggancio dichiarati; `frontend/README.md` elenca la logica NON toccabile dal redesign (gemRank, community/0.1, `Math.round(final*100)+"/110"`, gate splash/wizard/login, ordine run(), ownership stretta auto-finish wizard, regex login, maxLength 80/4000/32, slice(0,8) carousel, top-9 generi).
- Grafica identica **per costruzione**: stessi componenti, stessi CSS (spostati), stesse stringhe. Gate: build verde + script che verifica la presenza/integrità di tutti i `data-od-id` + smoke visivo (screenshots.mjs esistente).

## 4. Desktop — Electron shell minimale

- `desktop/main.ts` = attuale `electron/main.ts` con un cambiamento: il figlio spawnato è il **binario PyInstaller (onedir)** del backend (`resources/desktop-server/<piattaforma>/osusume-server/…`) invece di `server.mjs` con ELECTRON_RUN_AS_NODE.
- Env figlio invariata: `PORT` (freePort), `ALR_DATA_DIR` (userData), `APP_VERSION` (solo packaged), `NODE_ENV=production`. waitHealth 15s/300ms su `/api/health`.
- Finestra/navigazione/shutdown/errori fatali invariati (testi esatti `showErrorBox`, will-navigate, `POST /api/shutdown` prima di SIGTERM).
- `electron-builder`: `extraResources` aggiunge il sidecar; `files` = dist/** + desktop/** + fixtures/** + package.json; asar può restare false (sidecar come risorsa piatta).
- Dev: `pnpm dev` = uvicorn (reload) + Vite middleware, come oggi; packaging testato solo su macOS in P7 (dmg), win/linux in P8 via CI.

## 5. Gate di verifica

### 5.1 Golden master (livello endpoint)

- **Record** (P0): harness `tests/golden/record.mjs` — server Node attuale con env blindata: `ANILIST_FIXTURES` (fixtures sintetiche e `fixtures-real`), `CACHE_DIR`/`CONFIG_PATH`/`ALR_DATA_DIR` in tmpdir freschi, `LLM_BASE_URL` su porta morta (fallback deterministico), `LMS_PATH` fake bash, senza `APP_VERSION`.
- Copertura: recommend en+it, explain batch (fonte fallback), profile, lookup (3 query), health prima/dopo, local-mode transizioni (auto f/t, local f), setup/status (fake lms), config, app-update (null, no rete), chat (503), shutdown.
- **Compare** (P2–P5, ripetuto a ogni fase): `tests/golden/compare.py` — stessa env contro FastAPI, deep-diff JSON normalizzato (chiavi ordine-insensibile, array ordine-SENSIBILE, numeri confrontati per identità esatta dopo normalizzazione float shortest-repr). Uguaglianza = gate.
- `fixtures-real/` (2.1 MB, LookUpMark) è gitignored: il gate lo usa da disco locale; in CI gira sulle fixture sintetiche committate.

### 5.2 Test portati (livello unit/e2e — i veri file di specifica)

| Oggi (node:test) | Diventa (pytest) |
|---|---|
| tests/scoring.test.ts (374 r) | backend/tests/test_scoring.py — pesi, soglie (40000/72/0.45), franchise, MMR, badge order, why/whyNot template |
| tests/profile.test.ts (119 r) | backend/tests/test_profile.py — sentiment (0.25/0.55/-0.6/±1 clamp), meanScore fallback 60, eraBucket, hash 16 char |
| tests/llm.test.ts (274 r) | backend/tests/test_llm.py — contratto OpenAI (enable_thinking=false, max_tokens 1200), cache solo-LLM, parseExplanations, llmHealth onesto, doctrine prompt |
| tests/api.test.ts (190 r) | backend/tests/test_api_e2e.py — spawn server reale, badge/ESCLUSIONI franchise su "josh", auto-fallback, local-mode |
| tests/setup.test.ts (307 r) | backend/tests/test_setup_e2e.py — fake lms bash (sequenza comandi, singleton, cancel→idle, exit 143), suggestModel per RAM, config tollerante |
| tests/update.test.ts (11 r) | backend/tests/test_update.py — cmpVersion |
| — (non esiste) | backend/tests/test_contract.py — Host middleware, error map, lang whitelist (nuovo, da contract.md) |

Fake OpenAI server e fake AniList: http-server minimali (attualmente node:http → FastAPI TestClient + server thread uvicorn, o respx per httpx).

### 5.3 Criterio di fine

Tutti e tre i livelli verdi + (P8) CI verde su pytest + docker smoke + release dry-run. La vecchia codebase (`src/server`, `src/shared`, server bundle) si cancella SOLO dopo il merge.

## 6. Fasi e gate

| Fase | Contenuto | Gate d'uscita |
|---|---|---|
| P0 | Branch `py-backend`; `docs/contract.md`; harness golden record; golden committati (fixture sintetiche) | golden/*.json presenti e stabili (record 2× identico) |
| P1 | Skeleton: uv, FastAPI factory, config/env loader, Host middleware, health/shutdown, static+SPA | e2e smoke verde; golden health/config/app-update identici |
| P2 | Dominio puro: profile, franchise, scoring, tokenizer, textLinks | test_scoring+test_profile 100% verdi (valori pinned) |
| P3 | Adapters: anilist client+cache+retry+fixtures; llm client+prompts+parse+expl-cache | test_llm verdi; golden profile/lookup/explain-fallback identici |
| P4 | Pipeline recommend + queries (resultCache, staleOk) + stato local-mode (core/, esposto via comando e health) | golden recommend/lookup/explain en+it (fixture + real) identici |
| P5 | Commands: setup wizard completo (lms/omlx, job singleton), config, chat, app-update | test_setup_e2e+test_api_e2e verdi; golden setup/status e chat-503 identici |
| P6 | Frontend restructure in frontend/ (stessi componenti) | pnpm build verde; script data-od-id completo; screenshots.mjs OK |
| P7 | Desktop: sidecar PyInstaller onedir, main.ts, electron-builder | dmg macOS avvia; ciclo health/shutdown scripted; wizard→recos→chat e2e manuale |
| P8 | Docker (stage node build → runtime python:3.12-slim), compose invariato, CI (pytest + smoke), release.yml (3 job + sidecar), README | CI verde; docker smoke verde; release dry-run produce artefatti |
| P9 | Cutover: merge main, cancellazione src/server+src/shared, tag v2.0.0 | release v2.0.0 pubblicata; golden archiviati |

Rollback: il main resta inviolato fino a P9; il branch si abbandona senza costi. Dopo il cutover, rollback = revert del merge (i dati utente JSON non cambiano formato).

## 7. Rischi e mitigazioni (registro)

| Rischio | Mitigazione |
|---|---|
| Deviazioni numeriche silenziose (round, locale, sort, hash) | §2.2 esplicita; golden + test pinned li acciuffano al primo diff |
| Serializzazione JSON diversa (chiavi/float) nelle cache sha256 | Serializzatore dedicato `js_json_dumps` verificato contro golden del record |
| `/api/shutdown` perso → backend LLM orfano su Windows | Gate e2e shutdown in P1 e P7 |
| Host-header check perso → design sicurezza rotto | test_contract.py + golden 403 |
|Wizard riaperto a ogni avvio (APP_VERSION/setupVersion) | Canale env replicato; test needsSetupVersion portato |
| FastAPI/piccolo: error handler default diversi | Exception handlers custom dal giorno P1, coperti da test_contract |
| PyInstaller AV/SmartScreen false positive su Windows | onedir (non one-file); accettato come oggi per unsigned |
| Doppia version (package.json vs pyproject) | package.json unica fonte; pyproject legge da build script |
| toLocaleString dipende da ICU | separatori hardcoded (§2.2) |
| ml/mlx path solo testabili su Apple Silicon | P7 su macOS reale di Marco; win/linux smoke via CI |

## 8. Fuori scope

Pixel-diff UI (identità per costruzione + smoke visivo); event store/DB; router server-side; autenticazione; rotazione llm.log; riscrittura della logica di scoring (è portata, non riprogettata); nuovo modello nel catalogo.
