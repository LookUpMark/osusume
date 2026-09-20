# Piano d'esecuzione — Migrazione osusume a backend Python/FastAPI (CQRS-lite)

Spec: `docs/superpowers/specs/2026-09-20-python-migration-design.md` (approvata).
Branch di lavoro: `py-backend`. Il main resta inviolato fino a P9.
Ogni fase è autosufficiente: può essere eseguita in una sessione pulita leggendo spec + questa sezione.

---

## Fase 0 — Discovery (COMPLETATA 2026-09-20)

Consolidamento dei fatti verificati (4 ricerche con fonti, esecuzioni live incluse). Sono gli unici API-fatti su cui le fasi successive possono contare senza ri-verificarli.

**FastAPI/Starlette/uvicorn** (fastapi.tiangolo.com, starlette.dev, source uvicorn/server.py):
- Error shape custom: `@app.exception_handler(RequestValidationError)` (override default 422) e `@app.exception_handler(starlette.exceptions.HTTPException)` → `JSONResponse(status_code=…, content={"error": "code"})`. Handler FastAPI HTTPException ereditato da Starlette: registra quello Starlette.
- Host header: `@app.middleware("http")` (async def f(request, call_next)); `request.headers["host"]` case-insensitive. Strip porta: logica stdlib (`rsplit(":",1)` se un solo `:`, `[::1]:8000` → strip parentesi).
- SPA: `app.frontend("/", directory="dist", fallback="index.html")` — API nativa: "FastAPI checks path operations first… your API won't be affected" (fallback solo GET/HEAD con Accept: text/html). Alternativa manuale: `@app.get("/{file_path:path}")` DOPO le route /api (matching in ordine di dichiarazione).
- Payload controllo: `response_model=Model` filtra campi extra; `response_model_exclude_unset=True` (solo campi settati) vs `response_model_exclude_none=True` (mai chiavi None). Input: `model_config = ConfigDict(extra="forbid")` per rifiutare extra.
- Shutdown: uvicorn `Server.should_exit = True` → main_loop esce al tick successivo e la risposta corrente viene completata; SIGTERM = `handle_exit` → should_exit (secondo segnale → force_exit). Istanza Server va conservata in un modulo importabile (`uvicorn.Server(uvicorn.Config(...))`). `capture_signals` solo nel main thread.
- Test in-process: `fastapi.testclient.TestClient` (httpx), sync test, lifespan solo dentro `with TestClient(app)`.

**PyInstaller/electron-builder** (pyinstaller.org, hooks-contrib sorgenti, electron.build; build e2e di verifica eseguita):
- PyInstaller 6.22.3 + hooks-contrib: hook ufficiali coprono uvicorn (`collect_submodules('uvicorn')` — 39 submoduli incl. loops.auto/protocols/lifespan), pydantic v2, regex. **Build verificata e2e senza NESSUN hidden-import manuale**: server parte. Non usare `uvicorn.workers`; `workers=1`; niente multiprocessing.freeze_support necessario (solo se worker>1).
- Layout onedir 6.x: `dist/<name>/<name>` eseguibile + `_internal/`; `sys._MEIPASS` = path di `_internal`; cwd del parent NON richiesto (verificato da dir estraneo); risorse via `--add-data "fixtures:."` lette da `_MEIPASS` fallback `__file__`.
- macOS: PyInstaller ad-hoc firma di default output e binari (obbligatorio su Apple Silicon) — niente codesign manuale per uso locale. electron-builder `mac.identity: "-"` = ad-hoc, `null` = nessuna firma; `extraResources` from(project dir)/to(resource dir)/filter; `process.resourcesPath` per risolverlo nel main.
- Dimensione misurata: onedir fastapi+uvicorn+httpx+pydantic+regex = **22.4 MB** (~13-15 MB compressi sul DMG).
- Warning build accettabili: gunicorn/wsproto/a2wsgi mancanti.

**Compat JSON JS↔Python + httpx + regex** (MDN, docs.python.org, python-httpx.org; verifiche live node+python):
- Cache key: `json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)` ≡ `JSON.stringify` per chiavi identificatore non numeriche. Divergenze note: float (soglie esponenziale diverse: JS plain <1e21, Python repr da 1e16), 0x7F escapeato da Python, NaN→null solo in JS, chiavi integer-like ordinate prima in JS. Le variables GraphQL di Osusume sono stringhe/interi → safe; test anti-drift con vettori sha256 generati da node obbligatorio (P1).
- Ordine chiavi: dict Python 3.7+ = inserimento (come JS per chiavi non integer-like); sort_keys default False.
- httpx: NESSUN retry nativo (solo HTTPTransport(retries=N) su ConnectError/ConnectTimeout — non basta: retry ladder manuale). Timeout per-fase (connect/read/write/pool) = inactivity, NON totale: replicare AbortSignal.timeout(15s) con `asyncio.wait_for`. Errori: rete = `httpx.TransportError`; status = resp.status_code; body non-JSON = json.JSONDecodeError. Streaming: `client.stream("GET", url)` + `aiter_bytes()`. In test/contesto con proxy env: `trust_env=False`.
- regex lib: `regex.sub(r"[^\p{L}\s]", " ", s)` — default UNICODE senza flag. NFKD: `unicodedata.normalize("NFKD", s)` + strip marks con `regex.sub(r"\p{M}", "", …)` (parità bit-a-bit con JS `\p{M}`; `unicodedata.combining` NON coincide al 100%).
- toLocaleString en/it: formattatore manuale su repr shortest round-trip; **CORREZIONE P2 (verificata su node + golden)**: il grouping NON è incondizionato — it segue CLDR minimumGroupingDigits=2: `(5000).toLocaleString('it')` → `"5000"` (4 cifre, no grouping), `90000` → `"90.000"`; en raggruppa sempre. Formatter hardcoded con regola it: grouping solo da ≥5 cifre nella parte intera. (La prescrizione iniziale "incondizionato" rompeva ogni gem con popularity a 4 cifre in it.)

**pytest e2e** (docs.pytest.org, docs.python.org asyncio/subprocess):
- `tmp_path_factory.mktemp(basename)` — API pytest è `mktemp`, NON `mkdtemp` (quello è tempfile). `monkeypatch.setenv` per env ereditata dal subprocess, teardown automatico.
- pytest-asyncio: `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`; NON mischiare con anyio auto (conflitto documentato). Test in-process sync con TestClient; async solo dove serve.
- Subprocess: `asyncio.create_subprocess_exec` (no shell), `start_new_session=True` → `os.killpg(os.getpgid(pid), sig)` per l'albero; leggere pipe con `communicate()` dentro `asyncio.wait_for` (wait() puro può deadlockare con PIPE); `returncode -N` = segnale N. Kill ladder: terminate() → wait_for(5s) → killpg(SIGTERM) → wait_for(5s) → killpg(SIGKILL) → wait().
- httpx nei test verso 127.0.0.1: `trust_env=False` (bypass HTTP_PROXY/HTTPS_PROXY ereditate).

**Anti-pattern globali** (validi per tutte le fasi):
- NON usare python-dotenv (semantica diversa dal loader custom di config.ts: righe `^([A-Z_]+)=`, env esistente vince, strip quote, troncamento a ` #`).
- NON usare `round()` Python dove il TS usa `Math.round` (banker's) — helper `js_round(x) = math.floor(x + 0.5)`.
- NON convertire `updatedAt` (secondi) in ms; `exp` delle cache è ms epoch.
- NON fare retry con httpx native; ladder manuale 1s·2^attempt / 429 10 round.
- NON aggiungere campi ai payload di risposta (golden diff li becca).

---

## P0 — Contratto congelato + harness golden master

**Cosa fare**
1. `git checkout -b py-backend` dal main corrente.
2. Scrivere `docs/contract.md`: tabella endpoint della spec §2.1 + error map + shape payload (fonte: lettura diretta `src/server/api.ts`, `src/shared/types.ts`, `src/ui/api.ts` — copiare gli shape, non riformularli).
3. Scrivere `tests/golden/record.mjs` (record DAL backend Node attuale): spawn `node src/server/index.ts` con env blindata — `ANILIST_FIXTURES=fixtures|fixtures-real`, `CACHE_DIR`/`CONFIG_PATH`/`ALR_DATA_DIR` in tmpdir (`fs.mkdtemp`), `LLM_BASE_URL=http://127.0.0.1:1/v1` (dead), `LMS_PATH` fake bash, NO `APP_VERSION` — e catturare: health (pre), recommend en, recommend it, profile, lookup×3 query, explain batch (→ fallback), health (post), local-mode `{auto:false}` → `{auto:true,local:false}` → health, setup/status, config, app-update, chat (→ 503). Scrive `tests/golden/<case>.json` (body + status) e `tests/golden/manifest.json`.
4. Compare: `tests/golden/compare.py` — deep-diff JSON (chiavi ordine-insensibile, array ordine-sensibile, float shortest-repr) con exit code 0/1; scrub dei path in `tests/golden/volatile.json` su ENTRAMBI i lati.
   Ricetta env obbligatoria del lato "actual" (identica a record.mjs): `ANILIST_FIXTURES`, `LLM_BASE_URL`/`LMSTUDIO_BASE_URL`/`OMLX_BASE_URL` dead su 127.0.0.1:1, `LMS_PATH` fake bash, `ALR_DATA_DIR`/`CONFIG_PATH`/`CACHE_DIR` in tmpdir, `HOME` in tmpdir (→ `~/.omlx` vuoto, come il golden), delete-list env completa (APP_VERSION, LLM_MODEL, ANILIST_ENDPOINT, RATE_PER_MIN, LLM_TIMEOUT_MS, LLM_API_KEY inclusi), senza .env.

**Gate (exit 0 richiesto)**
- `node tests/golden/record.mjs fixtures && node tests/golden/record.mjs fixtures-real` (secondo solo se fixtures-real presente in locale) → golden committati (sintetici) e `git status` pulito dopo secondo record (stabilità: 2 record identici → `git diff --exit-code tests/golden`).

**Anti-pattern**: non avviare il record senza CACHE_DIR fresco (cache reale inquinerebbe: source:'cache'); non settare APP_VERSION.

## P1 — Skeleton backend

**Cosa fare**
1. `backend/pyproject.toml` (uv, py≥3.12: fastapi, uvicorn, httpx, regex; dev: pytest, pytest-asyncio, respx opzionale) + `backend/app/` skeleton dalla spec §1.
2. Porting `src/server/config.ts` → `app/core/config.py`: env surface completa (PORT, HOST, ANILIST_ENDPOINT, ANILIST_FIXTURES, RATE_PER_MIN, APP_VERSION, ALR_DATA_DIR, CONFIG_PATH, CACHE_DIR, LLM_*, LMSTUDIO_BASE_URL, LMS_PATH, OMLX_*), loader .env custom (regex `^([A-Z_]+)=(.*)$`, env esistente vince, strip quote, ` #`), readConfigFile tollerante, updateConfig merge tmp+rename, WEIGHTS literal (da config.ts).
3. `app/main.py`: factory uvicorn programmatica (`uvicorn.Server(uvicorn.Config(...))` con istanza conservata per shutdown), HOST/PORT, `app.frontend` per dist + route /api, middleware Host-allowlist (127.0.0.1/localhost/::1 → altrimenti 403 `{"error":"forbidden"}`), exception handlers (`RequestValidationError` → 400 `invalid_request`; Starlette HTTPException → shape {error}).
4. `GET /api/health` (stubs llm/local state) + `POST /api/shutdown` (schedule: `asyncio.create_task(sleep(0.2)); server.should_exit=True`).
5. `backend/tests/conftest.py`: fixture e2e subprocess (create_subprocess_exec + start_new_session + poll 15s/300ms + kill ladder; trust_env=False) e `test_contract.py` (Host 403, health shape, shutdown cycle, error shape 422→400).
6. Vettori anti-drift JSON: generare con node (`node -e "…createHash…JSON.stringify…"`) ≥5 vettori (unicode, newline/tab, slash, interi) → `backend/tests/test_json_compat.py`.

**Gate**
- `cd backend && uv run pytest tests/test_contract.py tests/test_json_compat.py` exit 0.
- `python tests/golden/compare.py golden-node golden-py --only health,config,app-update` exit 0 (sottogruppo coperto).
- `curl -s localhost:PORT/` serve dist/ e fallback SPA su route inventata.

**Anti-pattern**: python-dotenv; `os._exit` (usare should_exit); response_model che aggiunge campi; catch-all prima delle route /api (se non si usa app.frontend).

## P2 — Dominio puro

**Cosa fare** — porting 1:1, funzioni pure, zero I/O, in `app/domain/`:
- `profile.py` ← src/server/profile.ts (clamp, meanScoreOf, entrySentiment, eraBucket, buildProfile, hash **lessicografico** 16-char).
- `franchise.py` ← src/server/franchise.ts (catene PREQUEL, memo, anti-ciclo, SEEN set, rootId=min, classificazione in ordine).
- `scoring.py` ← src/server/scoring.ts (affinityMap, popNorm, affinityOf, qualityOf, gemScoreOf, isGem, lovedOverlap, deterministicWhy/WhyNot, scoreAll, diversify λ=0.15 PURA, dedupeFranchises, tokenize, STOP_WORDS integrale, buildSeenCorpus, textLinks).
- `js_compat.py`: js_round, to_locale (en/it), js_sort_key se serve.
- Test: `test_scoring.py` ← tests/scoring.test.ts e `test_profile.py` ← tests/profile.test.ts (valori pinned: 0.12/0.08 core, 0.5 neutro, 40000/72/0.45 gem, cap 0.1, +0.12 solo NEXT_STEP, -0.6 DROPPED, repeat 7→0.55, eraBucket 2017→"2015", hash 16, entrySentiment 0.25/0.55/±1, fallback 60, confidence low <3).

**Gate**: `uv run pytest backend/tests/test_scoring.py backend/tests/test_profile.py` exit 0, 100% dei casi del TS portati (contarli: stesso numero di assert di scenario).

**Anti-pattern**: `unicodedata.combining` invece di `regex.sub(r"\p{M}")`; sort numerico per l'hash; MMR mutante (portare puro); regex stdlib per `\p{L}` (non supportato — serve `regex`).

## P3 — Adapters

**Cosa fare**
- `app/adapters/anilist/`: 6 query GraphQL COPIATE verbatim da src/server/anilist.ts; token bucket asyncio (Lock+monotonic, capacità 3, refill RATE_PER_MIN/60); cache disco (sha256 di `json.dumps(ensure_ascii=False,separators=(',',':'),allow_nan=False)` di query+variables, file `{CACHE_DIR}/<hex>.json`, {exp,data}, TTL 1h/7d, dedup in-flight asyncio); gql ladder (15s totale con asyncio.wait_for, retry 3× 1s·2^a su TransportError/5xx/non-JSON, 429 ≤10 round sleep min(retry-after,60)|5s); mapMedia (500 char desc, relations filter, tag spoiler, title fallback); fixture mode (3 file, filtri ignorati, search substring case-insensitive ≤6, reviews sempre []).
- `app/adapters/llm/`: llmChat (httpx AsyncClient, temperature 0.3, repetition_penalty 1.12, chat_template_kwargs.enable_thinking false, max_tokens, Bearer da llmAuthHeaders, timeout totale LLM_TIMEOUT_MS con wait_for; LlmError 'unreachable'/'HTTP N'/'truncated'/empty; strip `<think>`); resolveServedModel + llmHealth (2s, leaf match); buildPrompt + COMPARISON_STANDARD verbatim; parseExplanations (scan bilanciato, span inverso, id float→int check); explainRecos (ordine operazioni spec §2: cache key sha256 con PROMPT_VERSION 'v4-critic-2', batch ≤10, retry truncation 4000, retry correttivo, BREAK su errore, solo LLM cachato, merge tmp+rename, llm.log); cleanText (entità in ordine, max default 450); chat.ts: buildChatSystem verbatim, mentionedTitles, chatReply (retry truncation 4000 HARDCODED, altri errori propagano).
- Test: `test_llm.py` ← tests/llm.test.ts (fake OpenAI server: server asyncio su porta efimera; vettori: cache solo-LLM, fallback mai cachato, parse variants, llmHealth onesto, prompt doctrine).

**Gate**: `uv run pytest backend/tests/test_llm.py` exit 0; golden compare `--only profile,lookup,explain-fallback` exit 0.

**Anti-pattern**: httpx retry native; timeout per-fase al posto del wait_for totale; `ensure_ascii=True` default nel serializzatore cache; cachare i fallback.

## P4 — Pipeline + queries

**Cosa fare**
- `app/domain/pipeline.py` ← src/server/candidates.ts + recommend.ts: fetchCandidates (14 query max, Promise.all→asyncio.gather, 'every candidate query failed' 502), pipeline recommendFor (ordine NON negoziabile spec §2: profile→candidates→franchise→epMap/skipped→missingEntries→seconda analisi→force ENTRY_POINT), community signal (top5 sentiment, cap 0.03/hit in accumulo), mood bonus (≥4 token condivisi), final clamp 0..1.1, badge order push, dedupe→MMR→slice50, textLinks sui 50, avoided (affinity crescente, ≤12→3, collectWhyNot), resultCache (chiave `user:lang:local|live`, TTL 10min, staleOk, inflight, refresh bypass).
- `app/queries/`: recommend, profile (cache lista 1h), explain (ids filter/dedup, staleOk, scoreArbitrary per missing), lookup (MUSIC escluso, riordino per indice ricerca), local-mode state (core/: pin env, auto-fallback ≠404 +1 retry, setAutoFallback(false)→setLocalMode(false)).
- Test: golden compare FULL `recommend en+it, lookup, explain-fallback, local-mode, health-post` su fixtures + fixtures-real.

**Gate**: `python tests/golden/compare.py --suite full` exit 0 su ENTRAMBI i dataset; `uv run pytest backend/tests` exit 0.

**Anti-pattern**: cambiare l'ordine delle fasi della pipeline; dedupe dopo MMR; applicare communityCap solo in scoreAll e non in accumulo (o viceversa).

**Payload** (da review P2): i campi optional `links`/`mmRank` vanno OMITTI dal JSON (semantica `undefined` TS), `rootId`/`droppedId`/`entryPointId` restano `null` esplicito — exclude_none selettivo campo per campo, il golden compare becca chiavi in più.

## P5 — Commands (setup/config/chat/app-update)

**Cosa fare** — portare `src/server/setup.ts` + `update.ts` + router setup di `api.ts` in `app/commands/`+`app/queries/setup_status.py`: detectHardware (sysctl su mac x64, ramGb round, os map), suggestModel + MODELS literal (RAM_TRESHOLD_GB typo conservato), needsSetupVersion, resolveLms/resolveOmlx, runLms kill-ladder, job singleton con jobGen, logTail ring 2000, install-cli stringhe fisse, startDownload (MODEL_KEY_RE, flag --mlx/--gguf case-insensitive, timeout 1h), omlx-download (whitelist, HEAD content-length, streaming aiter_bytes), cancel (jobGen++ + abort + SIGTERM→SIGKILL +5s), ensureLlmServer (short-circuit order spec §2.3, probe 4s, sequenza lms, run omlx detached process group), autoPickBackend, downloadedModels stale-while-revalidate 10s, /setup/finish ordine branch (skipped→invalid_model→baseUrl custom→omlx→lmstudio), /setup/reset (unlink ENOENT ok), config endpoints, /api/chat route (history normalize: trim content 4000, ultime 12, ultima user, extra slice 5 non-in-recos), app-update (memo 5min anche fallimenti, fresh=1, cmpVersion, senza APP_VERSION no rete).
- Test: `test_setup_e2e.py` ← tests/setup.test.ts (fake lms bash: sequenza daemon up→server start→ls --json→load; UNA `get --gguf`; cancel→idle exit 143; suggestModel per RAM; config corrotta {}; reset→{}) + `test_api_e2e.py` ← tests/api.test.ts (badge/esclusioni franchise "josh", auto-fallback outage, local-mode 400/200) + `test_update.py` ← tests/update.test.ts.

**Gate**: `uv run pytest backend/tests` exit 0; golden compare `--suite full --plus setup-status,chat-503` exit 0 su entrambi i dataset.

**Anti-pattern**: spawn con shell=True (array args sempre); job resuscitato dopo cancel (jobGen); probe LLM prima di !setupDone.

## P6 — Frontend restructure

**Cosa fare** — spostare `src/ui` → `frontend/src` SENZA cambiamenti visivi; smembramento: `design-system/tokens.css` (dal :root), `lib/` (api client da src/ui/api.ts, tr() da strings.ts — strings restano in shared usate dal build, o duplicate in lib/i18n.ts con test di parità), `lib/logic/` (sort/filtri/gemRank/run-order/polling/localStorage/error-map), `components/`, `views/`, `App.tsx` ridotto a orchestrazione. `frontend/README.md` con la lista logica non-ridisegnabile + contratto data-od-id. Vite config aggiornato; script `data-od-id check` (grep dei marker contro lista dal vecchio markup).
- Test: `pnpm typecheck` + `pnpm build` + screenshots.mjs smoke; script data-od-id exit 0.

**Gate**: build verde; `node scripts/check-od-ids.mjs` exit 0; screenshots.mjs completa (server nuovo dietro).

**Anti-pattern**: riscrivere componenti (solo spostare/estrarre); toccare formule display (community/0.1, /110); rinominare classi CSS.

## P7 — Desktop shell

**Cosa fare**: `desktop/main.ts` ← electron/main.ts cambiando SOLO il figlio spawnato → binario PyInstaller onedir (`resources/desktop-server/`), env identica (PORT/ALR_DATA_DIR/APP_VERSION), freePort/waitHealth 15s/300ms, testi showErrorBox identici, before-quit POST /api/shutdown + SIGTERM. Script `scripts/build-pyserver.mjs` (pyinstaller per piattaforma: `--onedir --name osusume-server --add-data "fixtures:fixtures" --collect-submodules uvicorn`; NOTA hooks coprono tutto il resto). electron-builder: extraResources from build/pyserver → to desktop-server, mac.identity "-" (ad-hoc — PyInstaller già ad-hoc firma).
- Gate: dmg macOS generato, app avvia, ciclo health/shutdown scripted (spawn → poll → POST shutdown → exit 0 within 5s), wizard→recos→chat e2e manuale su fixtures.

**Anti-pattern**: uvicorn.workers; workers>1; assumere cwd (verificato non richiesto); `mac.identity: null` (perde anche ad-hoc).

## P8 — Docker/CI/release

**Cosa fare**: Dockerfile (stage node: build frontend → dist; runtime python:3.12-slim + uv sync --frozen + dist + fixtures + backend, CMD uvicorn, HOST=0.0.0.0 healthcheck su 127.0.0.1 dentro container); compose INVARIATO (env/porte/volumi); ci.yml: job pytest (uv run pytest) + job docker smoke (20×1s /api/health); release.yml: 3 job OS con pyinstaller per-target + electron-builder, check tag==package.json version; README update.
- Gate: CI verde su branch; `docker compose up` smoke; release dry-run (workflow_dispatch) produce artefatti.

## P9 — Cutover

Merge `py-backend` → main (squash o merge commit — decidere in fase), cancellare `src/server` + `src/shared` + bundle server, tag `v2.0.0`, release. Golden archiviati in `tests/golden/`. Rollback post-cutover = revert del merge.

---

## Verifica finale (all phases)

1. `uv run pytest` (tutti i test portati: stesso numero di scenari dei 6 file node:test — 848 righe di specifica).
2. `python tests/golden/compare.py --suite full` exit 0 su fixtures + fixtures-real.
3. `grep -r "python-dotenv\|os._exit\|tmp_path_factory.mkdtemp\|round(" backend/app --include="*.py"` — audit anti-pattern (round( solo dentro js_round).
4. Desktop dmg avvia; docker smoke verde; release artifacts.
