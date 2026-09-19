# AUDIT 20260918-osusume-adversarial-followup

Audit avversariale follow-up (10 agent sonnet: evidence, repro-test, 4 finder, 3 verifier, sintesi). Baseline: `pnpm test` 29/29 verde. Dedup vs `AUDIT-20260907-193547.md` (81 findings).

**Risultato: 33 finding confermati — 3 HIGH, 14 MEDIUM, 16 LOW.** 46 finding in ingresso, 13 assorbiti in dedup; 56 verdetti avversariali.

Root cause dominante: il backend LLM non ha NESSUN proprietario unico — né dello spazio id del modello (wizard persiste id HF-repo, oMLX serve il basename, modelVisible confronta uguaglianza esatta → mai vero), né del job di download (run() auto-get fuori dal singleton, cancelJob senza child handle, jobFeed globale), né del processo backend (spawn senza handler error, rescan che uccide solo il wrapper).

Aggravi confermati di mitigazioni pregresse: logic-2.1 (cancel implementato ma senza kill/guardia), logic-2.2 (mitigazione "il wizard non chiama /setup/download" FALSA da 4433e2e — doppio lms get riprodotto a runtime), performance+logic-6.2 (throw fuori dal loop dei batch), security+performance-3.2 (guard ANILIST_FIXTURES bypassato dall auto-load .env).

## Finding (per severità)

### [HIGH] f1-1 — Lo spazio id del modello ha tre formati incompatibili e nessun punto di normalizzazione: il wizard persiste id HF-repo, oMLX serve il basename, modelVisible confronta uguaglianza esatta → backend permanently off + churn di rescan

- **File**: `src/server/setup.ts:717` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: setup.ts:717 `updateConfig({setupDone:true, backend:"omlx", model: body.model, baseUrl: OMLX_BASE})` persiste verbatim; setup.ts:522 `(j.data ?? []).some((m) => m.id === cfg.model)` è uguaglianza esatta; OMLX_DOWNLOADABLE (setup.ts:321-324) usa id repo. Sul sistema reale: data/config.json ha "Bonsai-27B-mlx-1bit" (inesistente ovunque), ~/.omlx/logs/server.log ripete "404: Model 'Bonsai-27B-mlx-1bit' not found" e "404: Model 'prism-ml/Ternary-Bonsai-27B-gguf' not found" (quest'ultimo è il literal di MODELS.b27 inviato all'endpoint), mentre il probe live di /v1/models (con key di ~/.omlx/settings.json) lista il modello scaricato SENZA prefisso org ("Ternary-Bonsai-27B-mlx-2bit"). Assorbe f3-1 (modelVisible mai vero) ed e1-2 (config reale → branch rescan di run() a setup.ts:536-551: kill+respawn+stato starting/off ~4,5 min per launch, re-kick da /api/health api.ts:35, riprodotto con il contenuto esatto di data/config.json in CONFIG_PATH isolato).
- **Repro**: `grep -h "not found" ~/.omlx/logs/server.log* | head; curl -s -H "authorization: Bearer <key>" http://127.0.0.1:<port>/v1/models → id senza org vs data/config.json .model`
- **Fix proposto**: Normalizzare in UN punto: (1) in POST /finish ramo omlx (setup.ts:714-719) interrogare la live /v1/models e persistere l'id COSÌ come riportato dal server, rifiutando 400 se non risolvibile; (2) in modelVisible (setup.ts:514-526) tollerare il prefisso org: `const leaf = cfg.model!.split("/").pop(); return (j.data ?? []).some(m => m.id === cfg.model || m.id === leaf)`; (3) in /status esporre modelMissing:true quando cfg.model non è tra i serviti, così App.tsx:228 riapre la wizard invece di girare a vuoto.

### [HIGH] f1-2 — Auto-finish invia {model} senza backend: qualunque job completato configura LM Studio anche nel flusso oMLX

- **File**: `src/ui/components/SetupWizard.tsx:98` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: SetupWizard.tsx:94-100 `const modelDone = status.job.state === "done" || ...; void finish({ model })` — body senza backend; il bottone manuale a :217 invece manda {backend:"omlx", model}. In /finish l'assenza di backend cade nel ramo lmstudio (setup.ts:721-733) che scrive backend lmstudio + LMSTUDIO_BASE + kicks ensureLlmServer → con un download oMLX appena finito (partito da :193) riscrive la config per LM Studio con una chiave omlx e run() lancia `lms get` fino a 1h (setup.ts:586), oppure /finish risponde 400 lms_missing e la wizard non completa mai. Stesso difetto su skipDownload a :292 (verificato `finish({ model })`).
- **Fix proposto**: In SetupWizard.tsx:98 `void finish(backend === "omlx" ? { backend: "omlx", model } : { model })` e idem a :292; in alternativa server-side, far decorrere il ramo lmstudio (setup.ts:721) solo da `backend === "lmstudio"` esplicito invece del fallthrough.

### [HIGH] f1-3 — modelDone non distingue il tipo di job: il completamento di install-cli segna il setup come fatto senza modello

- **File**: `src/ui/components/SetupWizard.tsx:94` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: `const modelDone = status.job.state === "done" || (downloaded && status.job.state === "idle")` (:94) + auto-finish :96-100. runInstall chiude con finish("done") e model:null (setup.ts:294,310) quando l'installer LM Studio esce 0 → macchina senza lms: utente clicca "Install CLI" (:255) → al poll successivo (1.5s, :41-48) setupDone=true con model = suggested mai scaricato, step 3 "Start using", e ensureLlmServer avvia in background `lms get` fino a 1h (setup.ts:586) con backend off.
- **Fix proposto**: `const modelDone = status.job.state === "done" && status.job.model != null && status.job.model === model` (SetupWizard.tsx:94); per install-cli mostrare il bottone Download appena status.lms.installed diventa true.

### [MEDIUM] e1-6 — cancelJob non uccide il figlio e il .then di startDownload riscrive job: un download cancellato torna "done" 9s dopo e la wizard auto-completa il setup con quel modello

- **File**: `src/server/setup.ts:392` · **Sintomo**: S2 · **Aggravio di**: logic-2.1
- **Evidenza**: Verificato su HEAD: cancelJob (setup.ts:389-392) fa solo `dlAbort?.abort()` (path omlx) e resetta job — il child `lms get` spawanto da startDownload (:254-268) non ha riferimento salvato; il .then a :263/:266-267 riscrive `job = {state:"done"|"error", ...}` incondizionatamente. Misurato con fake lms (get dorme 8s): t+2s POST /setup/download → ok; t+2s POST /setup/cancel → job idle; t+11.3s GET /status → job {state:"done", model:X} (lms-calls.log: il child completa 8s dopo lo start). A valle: modelDone (SetupWizard.tsx:94) + auto-finish :96-100 → setup completato col modello appena cancellato. Assorbe f1-9 e f3-6 (stesso meccanismo, quest'ultimo nota che il bottone cancel wizard :209 compare solo per job omlx e che jobActive() false post-cancel ammette un secondo get concorrente). Aggravio di logic-2.1: la mitigazione («POST /setup/job/cancel») è stata implementata (setup.ts:748-751) ma senza kill né guardia — la corsa resta.
- **Repro**: `fake lms get=sleep 8; POST /setup/download {model:X}; sleep 2; POST /setup/cancel; sleep 9; GET /api/setup/status → job.state=done, job.model=X`
- **Fix proposto**: Module-level `let dlChild: ChildProcess|null` settato in startDownload (setup.ts:262); in cancelJob (setup.ts:389-392) SIGTERM→SIGKILL prima di azzerare job; nel .then catturare un token di generazione (`const gen = ++jobGen`) e riscrivere job solo se invariato.

### [MEDIUM] t1-2 — Doppio `lms get` concorrente: run() auto-scarica bypassando il job singleton e POST /download risponde 200 invece di 409 — raggiungibile via UI da commit 4433e2e

- **File**: `src/server/setup.ts:586` · **Sintomo**: S2 · **Aggravio di**: logic-2.2
- **Evidenza**: Verificato su HEAD: run() ha solo il guard d'istante `if (jobActive())` (setup.ts:580-584) e poi lancia `runLms(lms,["get",cfg.model,...], 60*60*1000)` a :586 senza toccare il singleton → startDownload (:255) passa il check. Riprodotto a runtime (/tmp/alr-t1-emeOGp/r2-double-get.mjs): POST /download mentre l'auto-get è in corso → HTTP 200 {ok:true}, 2 invocazioni `get`, 2 child exit. Variante UI (r2b-reset-then-download.mjs): config setupDone+model assente → auto-get invisibile (job idle) → POST /reset (App.tsx:544) non lo cancella → wizard POST /download → 2 `lms get` paralleli. Assorbe e1-7 (stessa misura, calls.log con 2 pid) e la parte auto-get di f1-8. Aggravio di logic-2.2: la sua verifica escludeva l'UI perché «la wizard non chiama mai /setup/download» — falso da 4433e2e (SetupWizard.tsx:81 chiama postSetup("download")).
- **Repro**: `node /tmp/alr-t1-emeOGp/r2-double-get.mjs && node /tmp/alr-t1-emeOGp/r2b-reset-then-download.mjs`
- **Fix proposto**: Unico proprietario: estrarre il corpo di startDownload in `beginDownload(model)` e chiamarlo da run() al posto del runLms diretto (setup.ts:586), così jobActive() copre entrambi i path e POST /download (setup.ts:687) risponde 409 durante l'auto-get.

### [MEDIUM] f3-5 — Download HF scritto direttamente nella destinazione finale: senza tmp+rename, senza pulizia su abort/errore e senza resume — un download interrotto lascia un modello parziale che oMLX vede come installato

- **File**: `src/server/setup.ts:371` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: setup.ts:359-360 mkdir dest = ~/.omlx/models/<org>/<name>/ e :371 pipeline su createWriteStream(join(dest,file)); il catch (:375-385) e cancelJob (:390-392) si limitano a riscrivere job senza rmdir. config.json precede i safetensors in ordine alfabetico → dopo pochi secondi di download annullato la directory contiene già config.json → oMLX (scoperta per presenza di config.json, dichiarata nel commento a :358) e la wizard vedono il modello PARZIALE come installato; il tentativo successivo riparte da byte 0. Su 7.9 GB cancel (SetupWizard.tsx:209), quit o rete sono path realistici.
- **Repro**: `POST /api/setup/omlx-download {model} poi POST /api/setup/cancel dopo pochi secondi → ls ~/.omlx/models/<org>/<name>/ contiene config.json + safetensors troncati`
- **Fix proposto**: Scrivere in `dest + ".tmp"` e `renameSync(tmp,dest)` solo dopo l'ultimo file; nel catch/abort (:375-385) `rmSync(tmpDir,{recursive:true,force:true})`; opzionale resume via content-length.

### [MEDIUM] f3-7 — Su Windows il teardown del backend LLM non gira mai: kill('SIGTERM') sul child Node = TerminateProcess → niente handler SIGTERM/exit, LM Studio/omlx restano su dopo il quit (target NSIS spedito)

- **File**: `electron/main.ts:115` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD: electron-builder.yml:25-31 target `win → nsis x64`; electron/main.ts:112-115 before-quit fa solo `server?.kill("SIGTERM")` (child = Electron in ELECTRON_RUN_AS_NODE, :51-55). Su Windows process.kill termina il processo immediatamente: né process.on("SIGTERM") (setup.ts:424-429) né on("exit") (:423) girano, quindi stop() — `lms server stop` a :418-419 e pkill omlx a :413 — non esegue MAI. Il server LM Studio con modello in GPU/RAM e gli omlx-server restano vivi; al lancio successivo run() li riusa (setup.ts:494) col modello scanato in un boot precedente. Su macOS/Linux il path funziona (log reale "app in chiusura — arresto backend").
- **Fix proposto**: Canale di shutdown indipendente dai segnali: route `POST /api/shutdown` che invoca la stessa stop() di cleanupOnExit (setup.ts:406-422) + process.exit(0); in electron/main.ts before-quit chiamarla via fetch su 127.0.0.1:port prima di server?.kill(), su tutte le piattaforme (il kill resta rete di sicurezza).

### [MEDIUM] t1-1 — GET /api/setup/status è bloccante: attende `lms ls --json` (budget 15s) e la probe omlx — wizard sospesa per secondi (misurato 3.3-3.4s con ls 3s, 0ms a cache calda)

- **File**: `src/server/setup.ts:614` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: la route fa `await Promise.all([jobActive()?[]:downloadedModels(lms), omlxModels(...), httpOk(...)])` (setup.ts:643-650) e downloadedModels esegue `await runLms(lms,["ls","--json"],15_000)` (:614, cache 10s a :613). Misurato (/tmp/alr-t1-emeOGp/r1-r6-status-latency.mjs, fake lms con ls 3s): primo GET 3415ms (e1-5: 3302ms), secondo 9ms; POST /setup/reset azzera lsCache (:764) → GET subito dopo 3018-3020ms. Client: App.tsx:43 setup=null, unico fetch al mount (:61), decisione wizard a :228 → onboarding rimandato di N secondi a ogni avvio (cache in-memory, sempre cold). Non è il pregresso logic+security-10.5 (lì fallimento→setup done; qui latenza con successo). Assorbe e1-5.
- **Repro**: `node /tmp/alr-t1-emeOGp/r1-r6-status-latency.mjs`
- **Fix proposto**: Stale-while-revalidate: separare `cachedModels()` (lettura immediata, [] se cold) da `refreshModels()` async; a :647 usare cachedModels() + void refreshModels() (la poll 1.5s della wizard raccoglie al giro dopo); spostare la probe omlx dentro la Promise.all.

### [MEDIUM] t1-7 — Fallimento LLM invisibile su due fronti: llmHealth dà enabled=true con un generico 200 su /models (mai verifica che cfg.model sia servito) e explainRecos ingoia ogni errore senza log — data/llm.log non conterrà mai un errore LLM

- **File**: `src/server/llm.ts:16` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: llm.ts:16 `return res.ok` (catch a :17); catch di explainRecos a :187-189 è l'unico handler di tutti i fallimenti (timeout :27, HTTP non-ok :29, truncation :34, JSON malformato) ed è vuoto; nessun import del logger (log() a setup.ts:143-150 non è esportato). Riprodotto (/tmp/alr-t1-emeOGp/r7-health-false-positive.mjs): stub con /v1/models 200 {data:[]} e /chat/completions 404 → /api/health enabled:true, /api/explain 3 fallback, e NESSUNA riga nel llm.log; f2-2 (assorbito): 12 spiegazioni fallback + 2 chiamate fallite → data/ resta VUOTA. Contraddizione con strings.ts:83/226 "Vedi data/llm.log"; il chip (App.tsx:88-97) mostra "LLM on". Pregressi non sovrapponibili: performance+logic-6.1 (caching fallback, ora fixato a llm.ts:180-186), logic-2.5 (backendState in run(), non llmHealth).
- **Repro**: `node /tmp/alr-t1-emeOGp/r7-health-false-positive.mjs`
- **Fix proposto**: (1) llmHealth (llm.ts:10-20): parse del body e `(j.data ?? []).some(m => m.id === llmModel())` (fallback su prefisso per alias). (2) Esportare log() da setup.ts:143 (o modulo shared) e loggare in llm.ts:29 (`llm chat HTTP ${res.status} model=${llmModel()}`) e nel catch :187.

### [MEDIUM] f3-4 — localOmlxModels scansiona un solo livello di ~/.omlx/models richiedendo config.json lì, ma startOmlxDownload scrive models/<org>/<model>/config.json: i download dell'app sono invisibili al proprio scanner

- **File**: `src/server/setup.ts:100` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: setup.ts:99-101 filtra `d.isDirectory() && existsSync(join(modelsDir, d.name, "config.json"))` mentre :359 scrive `join(homedir(),".omlx","models", repo.split("/")[0], repo.split("/")[1])` (commento a :358 dichiara il layout annidato). Evidenza filesystem reale: ~/.omlx/models ha 6 modelli, 4 annidati per org (incluso prism-ml/Ternary-Bonsai-27B-mlx-2bit scaricato dall'app), lo scanner ne restituisce solo i 2 piatti mentre oMLX live ne lista 7. Impatto: /status.omlx.models (:648,655) e la card wizard (SetupWizard.tsx:172-184, check `includes("Bonsai-27B")`) non vedono mai i download → ri-proposta del download da 7.9 GB e autoPickBackend (:441-444) non può mai scegliere un Bonsai. Assorbe e1-1 (che mostra anche il finish che persiste models[0] da SetupWizard.tsx:152).
- **Repro**: `node -e "const fs=require('fs'),p=process.env.HOME+'/.omlx/models';console.log(fs.readdirSync(p,{withFileTypes:true}).filter(d=>d.isDirectory()&&fs.existsSync(p+'/'+d.name+'/config.json')).map(d=>d.name))"`
- **Fix proposto**: Un helper condiviso che scenda 2 livelli e restituisca lo stesso id usato da oMLX (basename o org/name — ma allora coerente anche in modelVisible :522 e SetupWizard); usarlo in localOmlxModels (:95-105) e far scrivere a startOmlxDownload (:359) la stessa chiave.

### [MEDIUM] f2-4 — autoPickBackend persiste {backend,model} SENZA baseUrl e i consumatori hanno tre default diversi (11434 Ollama / 1234 LM Studio / 8080 oMLX): oMLX viene avviato sulla porta di LM Studio mentre llm.ts interroga la porta di Ollama

- **File**: `src/server/config.ts:100` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: updateConfig(pick) a setup.ts:478 con pick = {backend, model} (:441-451); llm.ts/config.ts:99-100 usa `fileConfig.baseUrl ?? "http://127.0.0.1:11434/v1"`; run()/status usano `cfg.baseUrl ?? LMSTUDIO_BASE` = 1234 (setup.ts:493, :649); il ramo omlx ne deriva la porta da bindare: `new URL(base).port || "8080"` (setup.ts:505) → `omlx serve --port 1234`. Riprodotto (f1-4, live su HEAD): LMSTUDIO_BASE_URL=http://127.0.0.1:4999/v1 → llm.log "avvio omlx serve sulla porta 4999"; f2-4 test-c: config esattamente come scritta da :478 → llmBaseUrl()=11434, spawn omlx su 1234. Catena: `lms server start` fallisce "porta occupata" (:563-568) se l'utente sceglie LM Studio, oppure httpOk(1234) vero senza modello caricato → "up" con explain in fallback.
- **Repro**: `TMP=$(mktemp -d); ALR_DATA_DIR=$TMP CONFIG_PATH=$TMP/config.json node --experimental-strip-types /tmp/f2-llm.l6cL/test-c.mjs → 11434 vs 1234`
- **Fix proposto**: Unica fonte di verità: (1) persistere il baseUrl nel pick a setup.ts:478 (`{...pick, baseUrl: pick.backend === "omlx" ? OMLX_BASE : LMSTUDIO_BASE}`); (2) in config.ts:99-100 sostituire il default 11434 con la risoluzione per backend importando la stessa costante condivisa con setup.ts:29/:75.

### [MEDIUM] f2-3 — Finish custom persiste un model che il server custom non ha (il wizard manda sempre la chiave Bonsai suggested): ogni /explain 404 per sempre, health verde

- **File**: `src/server/setup.ts:710` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: SetupWizard.tsx:328 `finish({ baseUrl: customUrl, model })` con model = stato di :23 inizializzato a suggested.model (chiave gguf del catalogo) — il pannello custom (:321-332) non offre un campo modello e il placeholder suggerisce Ollama (strings.ts:77) che non avrà mai quella chiave. Server: setup.ts:704 valida solo MODEL_KEY_RE e :710 `patch.model = body.model` senza verificare l'esistenza su body.baseUrl; llmChat (llm.ts:26) invia quel model e il 404 diventa throw ingoiato (llm.ts:187). Distinto da logic-2.10 (model regex-INVALID, ora 400): qui il model è valido ma assente sul target, caso prodotto sistematicamente dal wizard.
- **Fix proposto**: In setup.ts:704-713, prima di updateConfig: probe `${body.baseUrl}/models` (timeout 2s) e rifiutare 400 invalid_model se body.model non è nell'elenco (degradare a warning se la probe fallisce); aggiungere un input model nel pannello custom di SetupWizard.tsx:321-332.

### [MEDIUM] f2-5 — "Skip setup (no LLM explanations)" non cancella model/baseUrl né ferma il backend: l'LLM declinato continua a ricevere i prompt e a produrre spiegazioni

- **File**: `src/server/setup.ts:701` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: il branch skipped fa solo `updateConfig({setupDone:true, setupVersion, backend:"skipped"})` (setup.ts:700-702); il merge di updateConfig (config.ts:91 spread) non può cancellare chiavi → model e baseUrl sopravvivono. Riprodotto (/tmp/f2-llm.l6cL/test-d.mjs): config omlx + finish skipped → config risultante con model/baseUrl intatti e llmModel()/llmBaseUrl() ancora sul backend declinato; ensureLlmServer rispetta lo skip (:464) ma non esiste stop del backend già avviato (cleanupOnExit solo all'exit, :423-429) e /api/explain non ha guard sul backend. UI promette il contrario (strings.ts:79/222) e il chip resta verde perché /api/health sonda il baseUrl stantio.
- **Repro**: `node --experimental-strip-types /tmp/f2-llm.l6cL/test-d.mjs`
- **Fix proposto**: Supportare la cancellazione esplicita in updateConfig (config.ts:91: dopo il merge `for (const k of Object.keys(patch)) if (patch[k] === null) delete merged[k]`) e passare `{backend:"skipped", model:null, baseUrl:null}`; esportare da setup.ts una stopBackend() (corpo stop di cleanupOnExit :406-422) chiamata nel branch skipped.

### [MEDIUM] f1-6 — spawnServe senza handler 'error': un binario omlx non avviabile (ENOENT/EACCES) crasha l'intero server — dialogo di crash all'avvio e wizard mai visibile

- **File**: `src/server/setup.ts:509` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: spawnServe (setup.ts:506-513) registra solo stdio su LLM_LOG, nessun `child.on("error")` — a differenza di runLms (:220) e runInstall (:304); in Node un evento 'error' senza listener rilancia. Riprodotto live: OMLX_BIN inesistente + config {setupDone:true, backend:"omlx", ...} → `throw er; // Unhandled 'error' event ... spawn ... ENOENT`, exit != 0. Confezionato: electron/main.ts exit → fail("The local server stopped unexpectedly.") → dialogo + quit, ripetuto a ogni rilancio. Trigger realistici: OMLX_BIN stantio, ~/.omlx/bin/omlx senza exec (EACCES), symlink rotto dopo update.
- **Repro**: `CONFIG_PATH={setupDone:true,backend:"omlx",model:"x",baseUrl:"http://127.0.0.1:1/v1"} + OMLX_BIN=<inesistente> node --experimental-strip-types src/server/index.ts → exit != 0`
- **Fix proposto**: In spawnServe (setup.ts:506-513): `child.on("error", (e) => { log(`omlx spawn error: ${e.message}`); owned = null; backendState = "off"; })`.

### [MEDIUM] e1-4 — 401 su /models è conflate con "server giù": 343 probe rifiutate in 8m32s (cadenza 1,49s = poll wizard) mentre il server oMLX era vivo e serviva, senza una sola riga applicativa che spieghi il motivo

- **File**: `src/server/setup.ts:647` · **Sintomo**: S4
- **Evidenza**: data/llm.log, finestra 2026-09-08 16:47:02,422 → 16:55:34,130: 343 righe "omlx.server - WARNING - GET /v1/models → 401: API key required" a intervallo medio 1,49s = il setInterval di 1500ms del polling /api/setup/status (SetupWizard.tsx:41-48) che prova omlx con timeout 1s; 407 righe 401 totali nel file. Nella stessa finestra zero righe applicative: httpOk (setup.ts:152-159) trasforma il 401 in false e reportedLlmState riporta "off" → server attivo e servente ma wizard/settings lo dichiarano giù, senza traccia del perché. (Causa prima della key mancante all'epoca non attribuibile: ~/.omlx/settings.json ora ha auth.api_key, mtimes successivi al flood.)
- **Repro**: `grep -c "401: API key required" data/llm.log → 407; awk per finestre → FLOOD 16:47:02,422 -> 16:55:34,130`
- **Fix proposto**: In httpOk (setup.ts:152-159) distinguere i codici: loggare lo status non-2xx della probe (es. "probe omlx → 401 auth mancante/errata") ed esporre uno stato distinto da "off" (es. auth_error) in reportedLlmState, così il flood diventa una riga di diagnosi.

### [MEDIUM] f3-2 — Il rescan-restart di oMLX uccide solo il wrapper CLI, non omlx-server: il vecchio server resta sulla porta, il nuovo `omlx serve` muore di EADDRINUSE e il rescan non può mai riuscire; il loop uccide anche server ancora in boot

- **File**: `src/server/setup.ts:539` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: setup.ts:539 `owned.child.kill("SIGTERM")` uccide il wrapper (`~/.omlx/bin/omlx` è un exec verso omlx-cli che spawna omlx-server SEPARATO — lo ammette cleanupOnExit a :410-416 con il suo pkill); il ramo rescan (:536-551) NON ha il pkill → (1) il vecchio server resta bindato e il loop :541 brucia sempre 30×1s; (2) spawnServe (:544) riparte sulla stessa porta e muore di EADDRINUSE (stdio→llm.log, invisibile); (3) il loop :530 non distingue "in boot" da "bootato senza modello" e uccide boot a metà. Evidenza di sistema: 2 processi omlx-server vivi via pgrep senza listener sulla 8080, e 0 righe "riavvio del server per rescan" riuscite in data/llm.log nonostante 9 spawn.
- **Fix proposto**: In setup.ts:538-544 fare teardown come cleanupOnExit: spawnare il child con detached:true e `process.kill(-owned.child.pid,"SIGTERM")` (process group), procedere a spawnServe solo quando httpOk resta falso; al :530 considerare il server "bootato" solo dopo un primo 200 su /models.

### [MEDIUM] f3-8 — Il guard ANILIST_FIXTURES controlla solo process.env e viene bypassato dall'auto-load .env di config.ts: il record riscrive i fixture partendo dai fixture stessi come da finding pregresso

- **File**: `scripts/record-fixtures.mjs:8` · **Sintomo**: none · **Aggravio di**: security+performance-3.2
- **Evidenza**: Verificato su HEAD: scripts/record-fixtures.mjs:8-11 controlla process.env ANILIST_FIXTURES PRIMA dell'import dinamico (:13-15); config.ts:9 carica ../../.env e setta process.env per chiavi non presenti, e config.ts:18 legge ANILIST_FIXTURES DOPO quell'auto-load. .env.example documenta la chiave → con `ANILIST_FIXTURES=fixtures` nel .env (uso documentato per pnpm dev) il guard passa, l'import attiva la replay e lo script stampa "N entries" dai fixture sintetici riscrivendoli con exit 0 — identico al difetto originario. AGGRAVIO di security+performance-3.2 (mitigazione aggiunta ma incompleta).
- **Repro**: `in .env: ANILIST_FIXTURES=fixtures → node scripts/record-fixtures.mjs <utente-inesistente> → riscrive i JSON dai fixture con exit 0, zero chiamate API`
- **Fix proposto**: Verificare il valore EFFETTIVO visto dai moduli: spostare il check dopo l'import dinamico — `const { ANILIST_FIXTURES } = await import("../src/server/config.ts"); if (ANILIST_FIXTURES) { console.error(...); process.exit(1); }` — ed eliminare il check su process.env.

### [LOW] t1-4 — jobFeed globale: l'output di OGNI runLms finisce nel logTail del download attivo — la wizard mostra ls/load di un altro modello come log del proprio download

- **File**: `src/server/setup.ts:214` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: runLms appende ogni chunk a jobFeed (setup.ts:214,218) e jobFeed (setup.ts:246-249) filtra solo su jobActive() senza verificare la sorgente; stesso accoppiamento in runInstall (:302-303). Riprodotto (/tmp/alr-t1-emeOGp/r4-logtail-contamination.mjs): durante POST /download {wizard/Download-Model} un re-kick di ensure produce in /status `job.logTail = {"models":[{"key":"lmstudio/Big-Model"}]} LOADING-BACKEND-MODEL-OUTPUT` — output di `ls --json` e `load` di run() per un ALTRO modello, mostrato in SetupWizard.tsx:290. Caso e1-8: logTail="[]\n" da una `ls --json` durante il download.
- **Repro**: `node /tmp/alr-t1-emeOGp/r4-logtail-contamination.mjs`
- **Fix proposto**: Rendere il feed esplicito per-spawn: parametro `onChunk: (s:string)=>void = () => {}` in runLms (setup.ts:185) usato al posto di jobFeed a :214/:218; passare jobFeed solo da startDownload (:262) e runInstall (:302-303).

### [LOW] t1-5 — lsCache non invalidata dopo un `lms get` riuscito (e invalidata nel path sbagliato): /status riporta il modello assente per ~10s e la wizard rimbalza a step 1

- **File**: `src/server/setup.ts:263` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: startDownload non tocca lsCache nel .then (:263-267); l'unico invalidate per path lms non esiste, mentre `lsCache = null` a :373 è dentro startOmlxDownload (download oMLX) — cioè azzera la cache del `lms ls` di LM Studio che quel download non tocca. Riprodotto (/tmp/alr-t1-emeOGp/r5-lscache-stale.mjs): pre-download downloadedModels=[] → job done → /status a t+5ms = [] → /status a 10.1s = [modello]. Effetto UI: `downloaded` (SetupWizard.tsx:53-55, substring) resta false e con job done la formula di step (:56-62) ricade a 1 per fino a 10s. Assorbe f1-11.
- **Repro**: `node /tmp/alr-t1-emeOGp/r5-lscache-stale.mjs`
- **Fix proposto**: In startDownload settare `lsCache = null` all'avvio e nei rami di chiusura del .then (setup.ts:259/263/266); rimuovere l'invalidazione a :373 (o sostituirla con una cache omlx dedicata).

### [LOW] t1-6 — "Rerun setup" = reset (che azzera lsCache) + window.location.reload: reboot completo e probe da zero per riaprire la wizard (misurato 3018ms post-reset contro 4ms)

- **File**: `src/server/setup.ts:764` · **Sintomo**: S3
- **Evidenza**: Verificato su HEAD: App.tsx:544 `postSetup("reset").then(() => window.location.reload())`; /reset (setup.ts:753-766) unlinka la config, svuota job e `lsCache = null` (:764) → il primo /status post-reboot rifà `lms ls` (fino a 15s) + probe omlx 1s + httpOk 1s, e /api/health re-kicka ensureLlmServer (api.ts:35; probe duplicati ammessi in tests/setup.test.ts:139-141). Misurato (r1-r6-status-latency.mjs): /status pre-reset 4ms → POST /reset 4ms → /status 3018-3020ms. Assorbe f1-14.
- **Repro**: `node /tmp/alr-t1-emeOGp/r1-r6-status-latency.mjs`
- **Fix proposto**: Togliere `lsCache = null` da /reset (setup.ts:764): un reset di config.json non cambia i modelli su disco; far restituire a /reset lo status fresco e in App.tsx:544 fare setSetup(await ...) senza location.reload().

### [LOW] f1-10 — La shell principale è renderizzata e interattiva mentre setup è null (niente splash): la wizard "salta addosso" dopo secondi; fetch fallito = pagina errore permanente senza wizard

- **File**: `src/ui/App.tsx:61` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: App.tsx:43 `useState<SetupStatus | null | "error">(null)` e nessun guard ferma il render → Rail/Topbar/search interattivi finché l'unico fetchSetupStatus del mount (:61, nessun polling finché setup è null) risponde; mentre /status blocca su `lms ls` (3.3s misurati, fino a ~15s). Se il fetch fallisce: setup="error" → pagina errore con solo retry (:216-226), wizard mai mostrata. Ipotesi ack-on-mount REFUTATA come causa S1: SetupWizard.tsx:33-37 invia /ack solo se initial.setupDone è già true.
- **Fix proposto**: Bloccare il render su uno splash finché setup è null (`if (setup === null) return <splash/>`) o renderizzare subito la wizard con dati parziali; retry con backoff nell'effetto di :61 e ripartenza automatica della wizard quando il prossimo /status ha successo.

### [LOW] f1-15 — resolveLms esegue spawnSync("lms --version") senza timeout nel percorso critico di /api/setup/status: un `lms` lento sul PATH congela tutte le route

- **File**: `src/server/setup.ts:137` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: setup.ts:137 `spawnSync("lms", ["--version"], { encoding: "utf8" })` — nessuna option timeout — chiamato da /status (:643) e da run()/autoPickBackend. spawnSync blocca l'event loop: bootstrap del daemon CLI al primo uso o antivirus su Windows congelano health, recommend, explain per la stessa durata, con la wizard che non appare. Il default path (:135-136) evita il caso comune, ma il fallback PATH lookup resta nel percorso critico.
- **Fix proposto**: `{ timeout: 3000 }` in spawnSync (setup.ts:137) trattando status!==0/timeout come "lms assente"; in alternativa risolvere il percorso una volta all'avvio e memoizzarlo.

### [LOW] t1-9 — Il boot auto-pick PERSISTE backend+model in config.json prima della wizard e lascia backendState bloccato su "starting"

- **File**: `src/server/setup.ts:478` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: run() esce presto a :466 (`configured && (!cfg.setupDone || !cfg.model)`) DOPO aver settato `backendState = "starting"` (:470) e aver fatto `updateConfig(pick)` (:478, commento "persist so the next boot skips the probe"). Riprodotto (/tmp/alr-t1-emeOGp/r1b-boot-autopick-customenv.mjs, fake lms con un modello su disco, nessuna config): config.json scritta dal solo server con setupDone assente; /status needsSetup=true e llm.state="starting" che non si risolve mai (solo /finish con force aggiorna). /api/health e /status riportano uno stato non veritiero finché la wizard non è completata, e la config pre-esiste alla scelta dell'utente.
- **Repro**: `node /tmp/alr-t1-emeOGp/r1b-boot-autopick-customenv.mjs`
- **Fix proposto**: (1) a setup.ts:466 aggiungere `backendState = "off";` prima del return; (2) non persistere prima del consenso: tenere pick in memoria e fare updateConfig solo a setupDone (o persistere con setupDone esplicitamente false + chiave dedicata).

### [LOW] f3-3 — Porta oMLX supposta fissa (8080) mentre oMLX reale binda porte effimere in settings.json: l'app non può mai parlare col server esistente e spawna un secondo server; l'fd di log aperto per spawn non viene mai chiuso

- **File**: `src/server/setup.ts:505` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: setup.ts:75 `OMLX_BASE = "http://127.0.0.1:8080/v1"`, :505 `new URL(base).port || "8080"`, :717 persiste baseUrl: OMLX_BASE; :508 `openSync(LLM_LOG,"a")` per ogni spawnServe senza close. Sul sistema reale ~/.omlx/settings.json ha server.port che cambia ad ogni avvio (51037 → 51403, poi ECONNREFUSED su entrambe) e lsof: nessun listener sulla 8080 → l'app non raggiunge mai il server dell'utente e ne spawna un secondo (RAM doppia). La parte 401-vs-down è coperta da e1-4; qui resta la sorgente porta e il leak fd.
- **Repro**: `node -e "const s=JSON.parse(require('fs').readFileSync(process.env.HOME+'/.omlx/settings.json'));console.log(s.server.port)" → porta diversa da 8080; curl http://127.0.0.1:8080/v1/models → ECONNREFUSED`
- **Fix proposto**: Leggere la porta dalla STESSA settings.json già parsata da readOmlxKey() (setup.ts:84-93): OMLX_BASE = 'http://127.0.0.1:'+(s.server?.port ?? 8080)+'/v1', usata sia in `omlx serve --port` (:509) sia nel baseUrl persistito (:717); chiudere l'fd di :508 (o aprirlo una volta sola).

### [LOW] f3-9 — cleanupOnExit fa `pkill -f omlx-server` globale: alla chiusura muoiono anche le istanze oMLX dell'utente non avviate dall'app

- **File**: `src/server/setup.ts:413` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD: setup.ts:412-416 `spawnSync("pkill", ["-f", "omlx-server"], {timeout:5000})` senza filtro di proprietà/PID; `-f` matcha l'intera command line. Basta che l'app abbia spawnato UN wrapper (owned settato a :512) perché il quit uccida tutti gli omlx-server della macchina (sistema reale: 2 processi utente osservati, e il codice stesso riconosce il caso "server esterno" a :549), troncando richieste in flight di altre app. LOW perché richiede owned settato.
- **Fix proposto**: Spawnare il wrapper con detached:true (setup.ts:509) e in cleanupOnExit `process.kill(-owned.child.pid, "SIGTERM")` sul process group invece di pkill -f.

### [LOW] f3-10 — freePort rilascia la porta prima che il child la bindi (TOCTOU): se un altro processo la prende, nessun retry e l'utente vede solo il dialogo "The local server did not start"

- **File**: `electron/main.ts:24` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD: electron/main.ts:19-28 chiude il listener effimero (`s.close(() => resolve(port))` a :24) PRIMA dello spawn del child (:50-51) che riceve PORT nell'env. Se il bind fallisce, l'errore di serve() non è gestito → waitHealth brucia 15s → fail + quit: nessun retry, nessuna diagnosi. Finestra di millisecondi (debito latente), fallback però totale.
- **Fix proposto**: Ritentare il ciclo freePort→spawn 2-3 volte se waitHealth fallisce (minimale), oppure passare il socket già bindato al child (listen({fd})).

### [LOW] f3-11 — L'immagine docker non contiene fixtures/ (escluse da .dockerignore): l'auto-fallback offline venduto per il bundle non esiste nel deploy compose — un'outage AniList è 502 senza rete di sicurezza

- **File**: `Dockerfile:19` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD: .dockerignore esclude fixtures/ e lo stage runtime del Dockerfile copia solo dist, src/server, src/shared; electron-builder.yml bundla invece fixtures/** con commento "powers the auto-fallback when AniList is down". Nel container fixturesAvailable() (config.ts:44-54) è falso → api.ts:61-67 non attiva mai la modalità locale: con AniList irraggiungibile /recommend e /profile rispondono 502 anilist_error invece del fallback documentato in compose.yaml.
- **Repro**: `docker compose up -d app ollama; bloccare graphql.anilist.co dal container → POST /api/recommend → 502, nessun fallback`
- **Fix proposto**: Aggiungere `COPY fixtures ./fixtures` nello stage runtime del Dockerfile, oppure documentare in compose.yaml/README che la modalità full non ha fallback offline.

### [LOW] f3-12 — APP_VERSION iniettato anche in dev-electron contro la premessa di needsSetupVersion: la wizard riapre a ogni bump in `pnpm app`, e /setup/ack al mount riscrive setupVersion senza domanda

- **File**: `electron/main.ts:61` · **Sintomo**: S1
- **Evidenza**: Verificato su HEAD: electron/main.ts:61 `APP_VERSION: app.getVersion()` è passato SEMPRE al child (non solo app.isPackaged), mentre setup.ts:66-70 documenta "Packaged app only"; in dev dopo ogni bump needsSetupVersion() è true → /status needsSetup:true → wizard riaperta, e il mount chiama POST /setup/ack (SetupWizard.tsx:33-37, useEffect) che scrive setupDone:true + setupVersion (setup.ts:669-672) PRIMA di qualsiasi scelta — quindi anche la reopen post-update in produzione viene confermata al mount.
- **Repro**: `pnpm build && pnpm build:electron; bump version in package.json; electron . → wizard riaperta nonostante setupDone:true`
- **Fix proposto**: In electron/main.ts:61 iniettare APP_VERSION solo se app.isPackaged (spread condizionale); separare l'ack di versione dal mount (POST /setup/ack solo a completamento/scelta esplicita).

### [LOW] f2-6 — Il throw su finish_reason=length (mitigazione 6.2) è fuori dal loop dei batch: un batch troncato abortisce anche tutti i successivi

- **File**: `src/server/llm.ts:165` · **Sintomo**: S4 · **Aggravio di**: performance+logic-6.2
- **Evidenza**: Verificato su HEAD: llm.ts:34 throw su finish_reason=length e il try/catch (:163-189) avvolge l'INTERO `for (let i = 0; i < pending.length; i += 10)` (:165). Riprodotto (/tmp/f2-llm.l6cL/test-b.mjs): 12 spiegazioni (2 batch), server che risponde sempre JSON valido con finish_reason=length → 1 sola chiamata HTTP, 0 spiegazioni llm, 12/12 fallback. LOW: il path UI invia al massimo 10 id (App.tsx:150) = 1 batch; multi-batch solo via /api/explain diretto. Aggravio della mitigazione di performance+logic-6.2 (che suggeriva log/skip, non abort del resto).
- **Repro**: `node --experimental-strip-types /tmp/f2-llm.l6cL/test-b.mjs → "HTTP chat calls made: 1" con pending=12`
- **Fix proposto**: Spostare il try/catch dentro il loop (llm.ts:165-185): avvolgere solo la await llmChat di ogni batch con log (vedi t1-7) e continue, così un batch degrada solo i propri 10 item.

### [LOW] f2-7 — Il loader .env non stripa quoting né commenti inline: LLM_BASE_URL quotato diventa un URL invalido, LLM_MODEL con commento diventa un model inesistente

- **File**: `src/server/config.ts:9` · **Sintomo**: S4
- **Evidenza**: Verificato su HEAD: config.ts:9 `process.env[m[1]] = m[2].trim()` — solo trim. Riprodotto eseguendo il loader reale (/tmp/f2-llm.l6cL/test-e.mjs): LLM_BASE_URL="http://..." → llmBaseUrl() con virgolette incluse → new URL lancia "Invalid URL" (ogni fetch fallisce → fallback sempre); LLM_MODEL="qwen3:8b # my model" → inviato verbatim a /chat/completions. Path documentato in README.md:72 dove il quoting è convenzione standard. LOW: opt-in, e qui llmHealth è onesto (false → chip spento); il degrado resta silenzioso perché il catch non logga (t1-7).
- **Repro**: `TMP=$(mktemp -d); mkdir -p $TMP/src/server; cp src/server/config.ts $TMP/src/server/; printf 'LLM_BASE_URL="http://127.0.0.1:11434/v1"\nLLM_MODEL=qwen3:8b # my model\n' > $TMP/.env; node --experimental-strip-types -e 'import(process.env.T+"/src/server/config.ts").then(m=>console.log(JSON.stringify(m.llmBaseUrl()),JSON.stringify(m.llmModel())))'`
- **Fix proposto**: In config.ts:9 normalizzare il valore: strip di virgolette singole/doppie matched e troncamento al primo " #" prima dell'assegnazione.

### [LOW] f4-1 — chainOf memo splice inietta il nodo di partenza nella catena su cicli PREQUEL: kind e entryPointId sbagliati (NEXT_STEP diventa ENTRY_POINT che punta a se stesso)

- **File**: `src/server/franchise.ts:46` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD (franchise.ts:45-50): se il prequel p ha una catena memoizzata essa viene concatenata (`chain.push(p, ...[...upstream].reverse())`) senza verificare che non contenga già il nodo corrente — su un ciclo PREQUEL la catena composta contiene il candidato stesso. Repro minimo su HEAD: candidati [media(1,PREQUEL 2), media(2,PREQUEL 3), media(3,PREQUEL 1)], listMap {1:COMPLETED, 2:COMPLETED} → analyzeFranchises per id 3: {kind:"ENTRY_POINT", entryPointId:3} (atteso NEXT_STEP). Impatto: badge "Start here" su un sequel proseguibile, perdita del franchiseBonus +0.12 (scoring.ts:170,180), entry point indicato = S2 invece di S1 (invariante pinanto in tests/scoring.test.ts:195-210 resta verde perché 239-250 non pinna entryPointId di 502). Fuzz differenziale del finder su 19.133 classificazioni: 434 kind sbagliati (2,3%), 403 entryPointId=self; con la guardia → 0. Bug NUOVO introdotto dal fix post-audit (66c40cd); logic-4.6 (root merging) risulta risolto.
- **Repro**: `node --experimental-strip-types con candidates=[media(1,PREQUEL 2),media(2,PREQUEL 3),media(3,PREQUEL 1)], listMap={1:COMPLETED,2:COMPLETED} → info.get(3).kind==="ENTRY_POINT" && entryPointId===3 (script: /var/folders/.../tmp.bftvPSpWm1/probe/cycle-min.mjs)`
- **Fix proposto**: (1) franchise.ts:46 `if (upstream && !upstream.includes(id))` (il ramo normale produce già la catena corretta troncando su visited) — verificato su copia tmp: repro torna NEXT_STEP e fuzz 19k → 0 mismatch kind/entryPointId/root; (2) src/server/recommend.ts:62-67 guardia anti-mutua-soppressione (una coppia ciclica mutua con epMap={502:501,501:502} fa sparire l'intera serie): saltare epMap.set quando epMap.has(id), tenendo la scheda con entry point a id minore.

### [LOW] f4-2 — attempt++ manuale nel catch di res.json() si somma all'incremento del for: il path body non-JSON ha un retry in meno rispetto a 5xx/rete

- **File**: `src/server/anilist.ts:161` · **Sintomo**: none
- **Evidenza**: Verificato su HEAD: anilist.ts:127 `for (let attempt = 0; ; attempt++)` incrementa già; il ramo non-JSON fa anche `attempt++` (:161) prima del continue → attempt avanza di 2 per tentativo: simulazione = 3 fetch prima del throw sul path non-JSON contro 4 sui path 5xx (:151) e network (:138). Nessun impatto di correttezza, solo budget di retry dimezzato su un path già degradato (error page Cloudflare/proxy).
- **Repro**: `for(let attempt=0;;attempt++){fetches++; if(branch==="5xx"){if(attempt<3)continue;return fetches;} if(branch==="nonjson"){if(attempt<3){attempt++;continue;} return fetches;}} → 5xx=4, nonjson=3`
- **Fix proposto**: Cancellare `attempt++;` a anilist.ts:161 (il continue è già seguito dall'incremento del for), allineando il budget a 5xx/rete.

### [LOW] f4-4 — Nessun test sui flussi setup che i fix S1/S2 toccheranno: auto-pick che persiste la config, job lifecycle (download/cancel/logTail), ramo "modello già presente", path omlx

- **File**: `tests/setup.test.ts:72` · **Sintomo**: S2
- **Evidenza**: Verificato su HEAD: l'unico test d'integrazione setup (tests/setup.test.ts:61-178) usa un fake lms che risponde sempre [] a `ls` (:72) → né il ramo "modello già scaricato" (setup.ts:579-592) né autoPickBackend (:441-478, che richiede un ls non vuoto) sono mai esercitati: una regressione che scrivesse setupDone:true al boot lascerebbe la suite verde. `grep -rn 'cancel\|jobFeed\|logTail\|autoPick' tests/` → 0 hit. Il backend omlx (setup.ts:498-554, incluso rescan) non ha alcun test. I fix pianificati toccano proprio ensureLlmServer/autoPickBackend/run/job: oggi nessuna rete.
- **Repro**: `grep -rn 'autoPick\|cancel\|logTail\|omlx' tests/ → nessun match`
- **Fix proposto**: Secondo scenario in tests/setup.test.ts con fake lms che a `ls --json` risponde un modello: assert post-boot setupDone ancora false e config senza setupDone (auto-pick non chiude mai la wizard); più sequenza POST /setup/download → poll job.state/logTail → POST /setup/cancel → assert job non-busy e nessun nuovo `get` nel calls log.

## Fix plan (per root cause)

1. **Un solo proprietario del download: child handle + generation token nel singleton, auto-get instradato via startDownload, jobFeed per-spawn, path atomico e lsCache invalidata** (certo) — src/server/setup.ts — finding: e1-6, t1-2, t1-4, f3-5, t1-5
2. **Teardown dei processi backend affidabile: process group (detached + kill(-pid)) al posto di pkill -f, route POST /api/shutdown per Windows, retry freePort→spawn** (condizionato) — src/server/setup.ts, electron/main.ts — finding: f3-2, f3-7, f3-9, f3-10
3. **/status non bloccante (stale-while-revalidate su lsCache + probe in Promise.all), reset senza invalidate né location.reload, splash finché setup è null, spawnSync con timeout** (certo) — src/server/setup.ts, src/ui/App.tsx — finding: t1-1, t1-6, f1-10, f1-15
4. **Normalizzare lo spazio id del modello in un punto solo: persistere l'id servito dal backend al finish, modelVisible tollerante al prefisso org, scanner omlx a 2 livelli, validazione del model anche sul target custom** (certo) — src/server/setup.ts, src/server/config.ts — finding: f1-1, f3-4, f2-3
5. **Auto-finish della wizard corretto: modelDone solo per il job di download del modello corrente e backend esplicito nel body di finish (2 HIGH, ~10 righe — candidato al primo commit nonostante il posto)** (certo) — src/ui/components/SetupWizard.tsx — finding: f1-2, f1-3
6. **Stato onesto del backend: handler 'error' su spawnServe, 401 distinto da "off" nella probe, porta omlx letta da settings.json, fd di log gestito** (certo) — src/server/setup.ts — finding: f1-6, e1-4, f3-3
7. **autoPickBackend completo e non invasivo: persistere anche baseUrl nel pick, default per-backend condiviso, backendState=off all'early-return, nessuna persistenza prima del consenso** (certo) — src/server/setup.ts, src/server/config.ts — finding: f2-4, t1-9
8. **Osservabilità LLM: log() esportato e chiamato su ogni fallimento, llmHealth che verifica il modello servito** (certo) — src/server/llm.ts, src/server/setup.ts — finding: t1-7
9. **Semantica di updateConfig per lo skip: supportare la cancellazione esplicita delle chiavi e fermare il backend posseduto** (certo) — src/server/config.ts, src/server/setup.ts — finding: f2-5
10. **Debito minore a root cause autonome (batch LLM, parser .env, guard fixtures, Docker fallback, ACK versione, ciclo franchise, retry AniList)** (certo) — src/server/llm.ts, src/server/config.ts, scripts/record-fixtures.mjs, Dockerfile, electron/main.ts, src/server/franchise.ts, src/server/recommend.ts, src/server/anilist.ts — finding: f2-6, f2-7, f3-8, f3-11, f3-12, f4-1, f4-2
11. **Rete di test per i flussi setup (chiusura del finding f4-4): secondo scenario fake-lms e asserzioni su config.json** (certo) — tests/setup.test.ts — finding: f4-4

## Non coperto

- Finding scartati in pre-verifica SENZA sopravvissuto tra i CONFIRMED (gap da ricoprire in un prossimo giro): t1-10 (LLM_BASE_URL/customEnv sopprime la wizard anche su installazione fresca — f2-7 copre solo il parsing .env, non la semantica customEnv di App.tsx:228) e f1-12 (match "già scaricato" per substring bidirezionale lato client, SetupWizard.tsx:53-55/172-184 — il fix di f1-3 restringe modelDone ma il substring match resta e va riverificato dopo).
- Cluster igiene dei test scartato senza finding confermato: e1-9, t1-8, f1-13, f4-3 (test setup/llm scrivono nella data dir reale del repo — data/llm.log con centinaia di righe di output fake-lms mescolate ai log reali, cache spiegazioni inquinata). Fix banale (ALR_DATA_DIR/CACHE_DIR isolati nei test) ma nessuno dei 33 finding lo porta: da rimettere in coda.
- Context (non difetto): e1-10 — baseline `pnpm test` 29/29 verde, nessuna regressione di partenza.
- Aree non coperte da questo audit: (a) nessuna audit security dedicata — le route Hono /api/setup/*, /api/explain, /api/setup/cancel sono raggiungibili da qualunque processo locale senza auth (toccato solo di passaggio in f3-6); (b) nessuna verifica runtime Windows (f3-7 è ragionamento su TerminateProcess, nessuna VM; idem packaging NSIS); (c) nessun test end-to-end della wizard nell'app Electron pacchettizzata — tutti i repro sono a livello server/HTTP; (d) comportamento di oMLX verificato solo contro la versione installata localmente (niente matrice versioni); (e) nessun soak test: crescita di llm.log e leak fd di setup.ts:508 osservati ma non misurati nel tempo; (f) niente audit UI/a11y/i18n delle viste; (g) niente audit dipendenze/supply-chain; (h) performance del path /api/recommend (rate-limit AniList, cache profili) non misurata in questo giro.
- Tipi di verifica non eseguiti: (a) nessun repro per f3-2, f3-7, f3-9, f3-10 (campo repro vuoto — esistenza supportata da evidenza di sistema o ragionamento, da cui certain=false dello step 2); (b) il fuzz differenziale di f4-1 è del finder ed è stato ri-eseguito su copia in tmp ma non re-verificato indipendentemente in questa fase di sintesi; (c) confutazioni mancanti su t1-10 e f1-12 (vedi sopra) prima di poterli dichiarare difetti o non-difetti.
- Linee corrette in sintesi rispetto ai finding in ingresso (nessun cambio di sostanza): e1-4 setup.ts:645→647, f4-2 anilist.ts:162→161, f1-10 App.tsx:60→61, f1-6 ancorato a :506-513 (spawn a :509).
