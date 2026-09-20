#!/usr/bin/env node
// Golden master recorder (P0 migrazione Python/FastAPI).
//
//   node tests/golden/record.mjs fixtures          # fixture sintetiche (committate)
//   node tests/golden/record.mjs fixtures-real     # fixture reali (gitignored, solo locale)
//
// Spawna il server TS attuale contro la dir fixture data, con LLM/AniList-morti, HOME
// reindirizzata al tmpdir (niente ~/.omlx reale) e cache/config/dati freschi — poi cattura
// in sequenza gli endpoint e scrive in tests/golden/<dir>/: {"status": <n>, "body": <json>}
// pretty 2-space, con i path di tests/golden/volatile.json scrubbed a null (tratti macchina).
// Exit 0 solo se tutte le catture tornano (status atteso incluso); mai parallelismo:
// l'ordine sequenziale è parte della riproducibilità.
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer, request } from "node:http";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL("../..", import.meta.url)));
process.chdir(ROOT); // il server legge le fixture relative a cwd (come tests/api.test.ts)

/** Bind :0, read the port, release — no fixed-port collisions across runs (api.test.ts). */
async function freePort() {
  const s = createServer();
  await new Promise((r) => s.listen(0, "127.0.0.1", () => r()));
  const port = s.address().port;
  await new Promise((r) => s.close(() => r()));
  return port;
}

async function waitForServer(base, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/api/health`);
      if (res.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error("server did not start");
}

/** undici fetch risetta l'header host dall'URL — per testare la allowlist Host serve http. */
function getWithHost(base, path, host) {
  return new Promise((resolve, reject) => {
    const req = request(`${base}${path}`, { headers: { host } }, (res) => {
      let raw = "";
      res.on("data", (c) => (raw += c));
      res.on("end", () => resolve({ status: res.statusCode, text: raw }));
    });
    req.on("error", reject);
    req.end();
  });
}

/** Scrub dei tratti macchina (tests/golden/volatile.json, path "body.x.y") → null. */
function scrub(doc, paths) {
  for (const p of paths) {
    const keys = p.split(".");
    let cur = doc;
    let ok = true;
    for (const k of keys.slice(0, -1)) {
      if (cur != null && typeof cur === "object" && k in cur) cur = cur[k];
      else {
        ok = false;
        break;
      }
    }
    if (ok && cur != null && typeof cur === "object" && keys.at(-1) in cur) cur[keys.at(-1)] = null;
  }
  return doc;
}

const ALLOWED_FIXTURES = ["fixtures", "fixtures-real"];
const fixtureDir = process.argv[2];
if (!ALLOWED_FIXTURES.includes(fixtureDir) || !existsSync(join(ROOT, fixtureDir, "userlist.json"))) {
  console.error(
    `usage: node tests/golden/record.mjs <fixtures|fixtures-real>\n` +
      `  dir "${fixtureDir ?? ""}" non valida o senza userlist.json.\n` +
      `  fixtures-real è gitignored: esiste solo in locale (scripts/record-fixtures.mjs).`,
  );
  process.exit(1);
}

const goldenDir = join(ROOT, "tests", "golden", fixtureDir);
mkdirSync(goldenDir, { recursive: true });
const volatilePaths = JSON.parse(readFileSync(join(ROOT, "tests", "golden", "volatile.json"), "utf8"));

const PORT = await freePort();
const BASE = `http://127.0.0.1:${PORT}`;

// tmpdir fresco ogni run: cache/config/dati zeroed → nessuno stato tra catture e tra run
const tmp = mkdtempSync(join(tmpdir(), "osusume-golden-"));
const cacheDir = join(tmp, "cache");
mkdirSync(cacheDir, { recursive: true });

// fake lms (stesso pattern di tests/setup.test.ts): logga e esce 0 — mai un backend vero
const fakeLms = join(tmp, "fake-lms.sh");
writeFileSync(fakeLms, `#!/bin/bash\necho "lms-fake $*" >> ${JSON.stringify(join(tmp, "lms-calls.log"))}\nexit 0\n`);
chmodSync(fakeLms, 0o755);

// env esplicita: niente APP_VERSION (→ /api/app-update deterministico), niente .env
// (non esiste in repo), HOME reindirizzata (omlx.installed deterministicamente false) e
// le variabili critiche tutte iniettate qui → vincono comunque
const env = { ...process.env };
for (const k of [
  "APP_VERSION",
  "ANILIST_ENDPOINT",
  "LLM_API_KEY",
  "LLM_MODEL",
  "LLM_TIMEOUT_MS",
  "LMSTUDIO_BASE_URL",
  "OMLX_BASE_URL",
  "RATE_PER_MIN",
]) delete env[k];

const child = spawn(process.execPath, ["src/server/index.ts"], {
  cwd: ROOT,
  env: {
    ...env,
    HOME: tmp, // homedir() → tmpdir: ~/.omlx assente → omlx deterministicamente off
    ANILIST_FIXTURES: fixtureDir, // local mode bloccata on: fixture mode ignora lo username
    ALR_DATA_DIR: tmp,
    CACHE_DIR: cacheDir,
    CONFIG_PATH: join(tmp, "config.json"),
    LLM_BASE_URL: "http://127.0.0.1:1/v1", // dead → fallback deterministico + 503 su /chat
    LMS_PATH: fakeLms,
    LMSTUDIO_BASE_URL: "http://127.0.0.1:1/v1", // dead: /setup/status non dipende da un LM Studio locale
    OMLX_BASE_URL: "http://127.0.0.1:1/v1",
    PORT: String(PORT),
  },
  stdio: ["ignore", "pipe", "pipe"],
});
// attaccato PRIMA di qualunque kill: un child già morto non può lasciare la promise appesa
const exited = once(child, "exit").catch(() => undefined);
const childErr = [];
child.stderr.on("data", (c) => childErr.push(c.toString()));

const failures = [];
let captures = 0;

async function capture(name, path, init, expectStatus, send) {
  // send: richiesta già pronta {status, text} (per i casi dove fetch non basta, es. header Host)
  const res = send ? await send() : await fetch(`${BASE}${path}`, init);
  const status = res.status;
  const text = typeof res.text === "string" ? res.text : await res.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  scrub({ status, body }, volatilePaths); // muta in place i path volatili → null
  writeFileSync(join(goldenDir, `${name}.json`), `${JSON.stringify({ status, body }, null, 2)}\n`);
  captures += 1;
  const ok = expectStatus ? status === expectStatus : status >= 200 && status < 300;
  console.log(`  ${ok ? "ok" : "FAIL"} ${name} ${path} → ${status}${expectStatus ? ` (atteso ${expectStatus})` : ""}`);
  if (!ok) failures.push({ name, path, status, expectStatus, body });
  return body;
}

const post = (body) => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});
// fixture mode serve gli stessi dati per qualunque username valido — usiamo quello reale
const USER = "LookUpMark";

try {
  await waitForServer(BASE);
  console.log(`record golden → tests/golden/${fixtureDir}/ (port ${PORT}, tmp ${tmp})`);

  await capture("health-pre", "/api/health");
  const recosEn = await capture("recommend-en", "/api/recommend", post({ username: USER, lang: "en" }));
  await capture("recommend-it", "/api/recommend", post({ username: USER, lang: "it" }));
  await capture("profile", `/api/profile/${USER}`);
  await capture("lookup-1", "/api/lookup", post({ username: USER, q: "mecha", lang: "en" }));
  await capture("lookup-2", "/api/lookup", post({ username: USER, q: "slice of life", lang: "en" }));
  await capture("lookup-3", "/api/lookup", post({ username: USER, q: "violet", lang: "en" }));
  const ids = (recosEn?.recos ?? []).slice(0, 5).map((r) => r.media.id);
  if (ids.length === 0) failures.push({ name: "explain-fallback", path: "/api/explain", reason: "nessun id da recommend-en" });
  else await capture("explain-fallback", "/api/explain", post({ username: USER, ids, lang: "en" }));
  await capture("chat-503", "/api/chat", post({ username: USER, lang: "en", messages: [{ role: "user", content: "hi" }] }), 503);
  await capture("setup-status", "/api/setup/status");
  await capture("config", "/api/config");
  await capture("app-update", "/api/app-update");
  // mappa errori: ogni codice della contract con la sua rete (nessuna muta di stato)
  await capture("error-403", "/api/health", undefined, 403, () => getWithHost(BASE, "/api/health", "evil.com"));
  await capture("error-400-username", "/api/recommend", post({ username: "bad name!" }), 400);
  await capture("error-400-q", "/api/lookup", post({ username: USER, q: "m" }), 400);
  await capture("error-400-ids", "/api/explain", post({ username: USER, ids: [] }), 400);
  await capture(
    "error-400-chat",
    "/api/chat",
    post({ username: USER, lang: "en", messages: [{ role: "assistant", content: "hi" }] }),
    400,
  );
  await capture("localmode-off", "/api/local-mode", post({ auto: false }));
  await capture("health-post", "/api/health");
  await capture("localmode-retry-live", "/api/local-mode", post({ auto: true, local: false }));
} catch (e) {
  failures.push({
    name: "harness",
    path: "-",
    reason: `${String((e ?? {}).stack ?? e)}\nstderr: ${childErr.join("").slice(-800)}`,
  });
} finally {
  child.kill("SIGTERM");
  const hardKill = setTimeout(() => child.kill("SIGKILL"), 3000); // escalation (setup.ts)
  await exited;
  clearTimeout(hardKill);
  rmSync(tmp, { recursive: true, force: true });
}

if (failures.length > 0) {
  for (const f of failures) {
    console.error(`FAIL ${f.name} ${f.path}: ${JSON.stringify(f).slice(0, 1200)}`);
  }
  process.exit(1);
}
console.log(`golden OK: ${captures} catture in tests/golden/${fixtureDir}/`);
