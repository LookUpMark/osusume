import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { appendFileSync, closeSync, createWriteStream, existsSync, mkdirSync, openSync, readdirSync, readFileSync, unlinkSync } from "node:fs";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";
import { homedir, platform, arch, totalmem, cpus } from "node:os";
import { join } from "node:path";
import { Hono } from "hono";
import {
  APP_VERSION,
  CONFIG_PATH,
  DATA_DIR,
  hasCustomEnv,
  readConfigFile,
  updateConfig,
  type AppConfig,
} from "./config.ts";
import type { SetupHardware, SetupStatus } from "../shared/types.ts";

const LLM_LOG = join(DATA_DIR, "llm.log");

// --- model catalogue (ternary variants, verified 2026-09-08, Apache 2.0, prism-ml on HF) ----------

export const MODELS = {
  b27: { model: "prism-ml/Ternary-Bonsai-27B-gguf", sizeGb: 6.7 },
  b8: { model: "prism-ml/Ternary-Bonsai-8B-gguf", sizeGb: 2.03 },
} as const;
const RAM_TRESHOLD_GB = 16; // ternary 27B ≈ 6.7 GB weights (8B-class footprint) @4K ctx — 16 GB machines are comfy
// overridable so tests (and port-conflicted setups) can point elsewhere
export const LMSTUDIO_BASE = process.env.LMSTUDIO_BASE_URL ?? "http://127.0.0.1:1234/v1";

// --- hardware -------------------------------------------------------------------

export type Hardware = SetupHardware;

export function detectHardware(): Hardware {
  const os = platform() === "darwin" ? "mac" : platform() === "win32" ? "win" : "linux";
  let appleSilicon = os === "mac" && arch() === "arm64";
  if (os === "mac" && !appleSilicon) {
    // Rosetta caveat: node may report x64 on Apple Silicon
    const { stdout } = spawnSync("sysctl", ["-n", "machdep.cpu.brand_string"], { encoding: "utf8", timeout: 3000 });
    appleSilicon = typeof stdout === "string" && stdout.includes("Apple");
  }
  const chip = cpus()[0]?.model?.trim() || "Unknown CPU";
  return { os, chip, ramGb: Math.round(totalmem() / 2 ** 30), appleSilicon };
}

export function suggestModel(hw: Hardware): {
  model: string;
  sizeGb: number;
  /** MLX pack for the oMLX backend (runs the Prism ternary runtime) */
  mlx: { model: string; sizeGb: number } | null;
  /** MLX variant downloadable via lms (v1 packings only — Bonsai-2 packs are
   *  not loadable by LM Studio/llama.cpp upstream, so 27B has none here) */
  mlxLms: { model: string; sizeGb: number } | null;
} {
  if (hw.ramGb >= RAM_TRESHOLD_GB) {
    return {
      model: MODELS.b27.model,
      sizeGb: MODELS.b27.sizeGb,
      mlx: hw.appleSilicon ? { model: "prism-ml/Ternary-Bonsai-2-27B-mlx-2bit", sizeGb: 8.6 } : null,
      mlxLms: null,
    };
  }
  return {
    model: MODELS.b8.model,
    sizeGb: MODELS.b8.sizeGb,
    mlx: hw.appleSilicon ? { model: "prism-ml/Ternary-Bonsai-8B-mlx-2bit", sizeGb: 2.16 } : null,
    mlxLms: hw.appleSilicon ? { model: "prism-ml/Ternary-Bonsai-8B-mlx-2bit", sizeGb: 2.16 } : null,
  };
}

/** Packaged app only (APP_VERSION set): a version mismatch reopens the wizard.
 *  In dev (no APP_VERSION) only setupDone decides — behavior unchanged. */
export function needsSetupVersion(cfg: { setupVersion?: string }, version = APP_VERSION): boolean {
  return Boolean(version) && cfg.setupVersion !== version;
}

// --- oMLX (Apple Silicon multi-model server) -------------------------------------

const omlxDefaultPath = (): string => join(homedir(), ".omlx", "bin", "omlx");
/** Port from ~/.omlx/settings.json — the oMLX CLI writes there; probing the wrong
 *  port costs a full HTTP timeout on every status/ensure round. */
function omlxPortFromSettings(): string | null {
  try {
    const s = JSON.parse(readFileSync(join(homedir(), ".omlx", "settings.json"), "utf8"));
    const p = s?.server?.port;
    return typeof p === "number" && p > 0 ? String(p) : null;
  } catch {
    return null;
  }
}
const OMLX_BASE = process.env.OMLX_BASE_URL ?? `http://127.0.0.1:${omlxPortFromSettings() ?? "8080"}/v1`;

export function resolveOmlx(): string | null {
  if (process.env.OMLX_BIN) return process.env.OMLX_BIN;
  const def = omlxDefaultPath();
  return existsSync(def) ? def : null;
}

/** The oMLX API key never leaves the server: read in-memory, used as auth header only. */
export function readOmlxKey(): string | null {
  if (process.env.OMLX_API_KEY) return process.env.OMLX_API_KEY;
  try {
    const s = JSON.parse(readFileSync(join(homedir(), ".omlx", "settings.json"), "utf8"));
    const key = s?.auth?.api_key;
    return typeof key === "string" && key.length > 0 ? key : null;
  } catch {
    return null;
  }
}

function localOmlxModels(): string[] {
  try {
    const modelsDir = join(homedir(), ".omlx", "models");
    // a real model dir has a config.json — skip stray files and containers
    return readdirSync(modelsDir, { withFileTypes: true })
      .filter((d) => d.isDirectory() && existsSync(join(modelsDir, d.name, "config.json")))
      .map((d) => d.name);
  } catch {
    return [];
  }
}

async function omlxModels(serverUp: boolean): Promise<string[]> {
  if (!serverUp) return localOmlxModels();
  try {
    const key = readOmlxKey();
    const res = await fetch(`${OMLX_BASE}/models`, {
      headers: key ? { authorization: `Bearer ${key}` } : {},
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return localOmlxModels();
    const j = (await res.json()) as { data?: { id?: string }[] };
    return (j.data ?? []).map((m) => m.id ?? "").filter(Boolean);
  } catch {
    return localOmlxModels();
  }
}

// --- lms resolution -------------------------------------------------------------

const lmsDefaultPath = (): string =>
  platform() === "win32"
    ? join(homedir(), ".lmstudio", "bin", "lms.exe")
    : join(homedir(), ".lmstudio", "bin", "lms");

/** LMS_PATH env > config.json lmsPath > platform default if it exists > PATH lookup. */
export function resolveLms(): string | null {
  if (process.env.LMS_PATH) return process.env.LMS_PATH;
  const cfg = readConfigFile();
  if (cfg.lmsPath && existsSync(cfg.lmsPath)) return cfg.lmsPath;
  const def = lmsDefaultPath();
  if (existsSync(def)) return def;
  const probe = spawnSync("lms", ["--version"], { encoding: "utf8", timeout: 3000 });
  return probe.status === 0 ? "lms" : null;
}

// --- process helpers -------------------------------------------------------------

const log = (line: string): void => {
  try {
    mkdirSync(DATA_DIR, { recursive: true });
    appendFileSync(LLM_LOG, `${new Date().toISOString()} ${line}\n`);
  } catch {
    /* logging must never crash the app */
  }
};
/** Shared llm.log writer — LLM errors must be observable, never swallowed. */
export const logLlm = log;

const httpOk = async (url: string, timeoutMs: number, headers: Record<string, string> = {}): Promise<boolean> => {
  try {
    const res = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
    return res.ok;
  } catch {
    return false;
  }
};

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** Auth headers for the configured backend. Keys never leave the server. */
export function llmAuthHeaders(): Record<string, string> {
  if (process.env.LLM_API_KEY) return { authorization: `Bearer ${process.env.LLM_API_KEY}` };
  const cfg = readConfigFile();
  if (cfg.backend === "omlx") {
    const key = readOmlxKey();
    if (key) return { authorization: `Bearer ${key}` };
  }
  return {};
}

/** oMLX probes authenticate whenever a key exists — NOT only when the config
 *  already says backend "omlx": during the wizard the config is still empty and
 *  a keyless probe gets a 401, making a live server look unreachable. */
export function omlxAuthHeaders(): Record<string, string> {
  const key = readOmlxKey();
  return key ? { authorization: `Bearer ${key}` } : {};
}

interface RunResult {
  code: number | null;
  stdout: string;
  stderr: string;
}

/**
 * Spawn lms (array args, no shell), collect output, log it. Never throws on
 * nonzero exit — the caller decides via the returned code. Timeout: SIGTERM,
 * then SIGKILL after a grace window; the promise always settles.
 */
function runLms(lms: string, args: string[], timeoutMs = 60_000, onSpawn?: (child: ChildProcess) => void): Promise<RunResult> {
  log(`$ ${lms} ${args.join(" ")}`);
  return new Promise((resolve) => {
    const child = spawn(lms, args, { stdio: ["ignore", "pipe", "pipe"] });
    onSpawn?.(child);
    let stdout = "";
    let stderr = "";
    let done = false;
    const settle = (code: number | null) => {
      if (done) return;
      done = true;
      clearTimeout(killer);
      resolve({ code, stdout, stderr });
    };
    const timer = setTimeout(() => {
      if (!done) {
        log(`timeout dopo ${timeoutMs}ms — SIGTERM`);
        child.kill("SIGTERM");
      }
    }, timeoutMs);
    // SIGTERM ignored (or children keeping pipes open) → hard kill + settle anyway
    const killer = setTimeout(() => {
      if (!done) {
        log("SIGTERM ignorato — SIGKILL");
        child.kill("SIGKILL");
      }
    }, timeoutMs + 5000);
    setTimeout(() => settle(-1), timeoutMs + 15000); // last resort: promise must settle
    child.stdout.on("data", (c: Buffer) => {
      stdout += c;
      jobFeed(c.toString());
    });
    child.stderr.on("data", (c: Buffer) => {
      stderr += c;
      jobFeed(c.toString());
    });
    child.on("error", (e) => {
      log(`spawn error: ${e.message}`);
      stderr += e.message;
      settle(-1);
    });
    child.on("close", (code) => settle(code));
  });
}

// --- download / install job (singleton) ------------------------------------------

export type JobState = "idle" | "installing-cli" | "downloading" | "done" | "error";

export interface SetupJob {
  state: JobState;
  model: string | null;
  logTail: string;
  error?: string;
  bytesDone?: number;
  totalBytes?: number;
}

let job: SetupJob = { state: "idle", model: null, logTail: "" };
const jobActive = (): boolean => job.state === "downloading" || job.state === "installing-cli";

// generation token: every async writer captures its generation and no-ops if a
// newer job (or a cancel) has superseded it — no resurrected cancelled jobs
let jobGen = 0;
// child of the active lms download: cancelJob kills it for real
let dlChild: ChildProcess | null = null;

/** Feed the wizard's log view; ring buffer keeps the last ~2 KB. */
function jobFeed(text: string): void {
  if (!jobActive()) return;
  job.logTail = (job.logTail + text).slice(-2000);
}

// model keys are HF-style org/repo; require it to start alphanumeric (no ".."-leading tricks)
const MODEL_KEY_RE = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/;

export function startDownload(model: string): void {
  if (jobActive()) throw new Error("busy");
  if (!MODEL_KEY_RE.test(model)) throw new Error("invalid_model");
  const lms = resolveLms();
  if (!lms) throw new Error("lms_missing");
  const gen = ++jobGen;
  job = { state: "downloading", model, logTail: "" };
  // --gguf/--mlx flag: defensive disambiguation between repo variants
  const flag = model.includes("-mlx") ? "--mlx" : "--gguf";
  void runLms(lms, ["get", model, flag], 60 * 60 * 1000, (child) => {
    dlChild = child;
  }).then((r) => {
    dlChild = null;
    if (gen !== jobGen) return; // cancelled or superseded — never resurrect the job
    if (r.code === 0) {
      lsCache = null;
      job = { state: "done", model, logTail: job.logTail };
      ensureLlmServer(true); // auto-get path: pick up the new model now
    } else {
      log(`download fallito: ${r.stderr.slice(-500)}`);
      job = { state: "error", model, logTail: job.logTail, error: r.stderr.slice(-300) || `exit ${r.code}` };
    }
  });
}

/** SECURITY NOTE: fixed official install scripts, never interpolated — see plan. */
export function installCli(): void {
  if (jobActive()) throw new Error("busy");
  const os = detectHardware().os;
  const gen = ++jobGen;
  if (os === "win") {
    job = { state: "installing-cli", model: null, logTail: "" };
    // fixed string on purpose: official LM Studio PowerShell installer
    runInstall(gen, ["powershell", "-NoProfile", "-Command", "irm https://lmstudio.ai/install.ps1 | iex"]);
  } else if (os === "mac") {
    job = { state: "installing-cli", model: null, logTail: "" };
    // fixed string on purpose: official LM Studio bash installer
    runInstall(gen, ["bash", "-c", "curl -fsSL https://lmstudio.ai/install.sh | bash"]);
  } else {
    job = { state: "error", model: null, logTail: "", error: "unsupported OS — try: npx lmstudio install-cli" };
  }
}

function runInstall(gen: number, cmd: string[]): void {
  const child = spawn(cmd[0]!, cmd.slice(1), { stdio: ["ignore", "pipe", "pipe"] });
  let done = false;
  const finish = (state: JobState, error?: string): void => {
    if (done || gen !== jobGen) return; // superseded (cancel/reset) — never resurrect
    done = true;
    job = { state, model: null, logTail: job.logTail, ...(error ? { error } : {}) };
  };
  // installer must never wedge the job singleton: 10 min then hard stop
  const timer = setTimeout(() => {
    child.kill("SIGTERM");
    setTimeout(() => child.kill("SIGKILL"), 5000);
    setTimeout(() => finish("error", "installer timed out (10 min)"), 6500);
  }, 10 * 60 * 1000);
  child.stdout.on("data", (c: Buffer) => jobFeed(c.toString()));
  child.stderr.on("data", (c: Buffer) => jobFeed(c.toString()));
  child.on("error", (e) => {
    clearTimeout(timer);
    finish("error", e.message);
  });
  child.on("close", (code) => {
    clearTimeout(timer);
    if (code === 0) finish("done");
    else finish("error", `exit ${code}`);
  });
}

export function getJob(): SetupJob {
  return job;
}

// --- Bonsai MLX download into oMLX (streamed from Hugging Face) -------------------

const OMLX_DOWNLOADABLE = {
  "prism-ml/Ternary-Bonsai-2-27B-mlx-2bit": 8.6,
  "prism-ml/Ternary-Bonsai-27B-mlx-2bit": 7.9, // v1 — kept as an explicit alternative
  "prism-ml/Ternary-Bonsai-8B-mlx-2bit": 2.16,
} as const;
const GB = 2 ** 30;

let dlAbort: AbortController | null = null;

export function startOmlxDownload(repo: string): void {
  if (jobActive()) throw new Error("busy");
  if (!(repo in OMLX_DOWNLOADABLE)) throw new Error("unsupported_repo");
  const gen = ++jobGen;
  job = {
    state: "downloading",
    model: repo,
    logTail: `resolving ${repo} file list…\n`,
    bytesDone: 0,
    totalBytes: Math.round(OMLX_DOWNLOADABLE[repo as keyof typeof OMLX_DOWNLOADABLE] * GB),
  };
  dlAbort = new AbortController();
  void (async () => {
    const signal = dlAbort!.signal;
    try {
      const meta = await fetch(`https://huggingface.co/api/models/${repo}`, { signal });
      if (!meta.ok) throw new Error(`HF API ${meta.status}`);
      const j = (await meta.json()) as { siblings?: { rfilename: string }[] };
      const files = (j.siblings ?? [])
        .map((s) => s.rfilename)
        .filter((f) => !f.startsWith(".") && !f.includes("/"));
      // exact total from HEAD content-lengths → real progress percentage
      let totalBytes = 0;
      for (const file of files) {
        const head = await fetch(`https://huggingface.co/${repo}/resolve/main/${file}`, {
          method: "HEAD",
          signal,
        });
        totalBytes += Number(head.headers.get("content-length") ?? 0);
      }
      // oMLX discovery layout: models/<org>/<model>/ with config.json inside
      const dest = join(homedir(), ".omlx", "models", repo.split("/")[0]!, repo.split("/")[1]!);
      mkdirSync(dest, { recursive: true });
      for (const file of files) {
        job.logTail = (job.logTail + `↓ ${file}\n`).slice(-2000);
        const res = await fetch(`https://huggingface.co/${repo}/resolve/main/${file}`, { signal });
        if (!res.ok || !res.body) throw new Error(`${file}: HTTP ${res.status}`);
        const counter = new Transform({
          transform(chunk: Buffer, _enc, cb) {
            job.bytesDone = (job.bytesDone ?? 0) + chunk.length;
            cb(null, chunk);
          },
        });
        await pipeline(Readable.fromWeb(res.body as never), counter, createWriteStream(join(dest, file)));
      }
      if (gen !== jobGen) return; // cancelled or superseded
      lsCache = null;
      job = { state: "done", model: repo, logTail: job.logTail, bytesDone: totalBytes, totalBytes };
    } catch (e) {
      if (gen !== jobGen) return; // cancelled or superseded — never resurrect the job
      const aborted = (e as Error).name === "AbortError";
      job = {
        state: aborted ? "idle" : "error",
        model: repo,
        logTail: job.logTail,
        error: aborted ? undefined : String((e as Error).message).slice(0, 300),
        bytesDone: job.bytesDone,
        totalBytes: job.totalBytes,
      };
    }
  })();
}

export function cancelJob(): void {
  ++jobGen; // in-flight writers become stale: a finished child cannot resurrect the job
  dlAbort?.abort();
  dlAbort = null;
  if (dlChild) {
    const child = dlChild;
    child.kill("SIGTERM");
    setTimeout(() => child.kill("SIGKILL"), 5000);
    dlChild = null;
  }
  if (jobActive()) job = { state: "idle", model: null, logTail: "" };
}

// --- auto-config on every app start ---------------------------------------------

export type BackendState = "up" | "starting" | "off";
let backendState: BackendState = "off";
let ensureLock: Promise<void> | null = null;
// servers this app process started: torn down on app exit (open-with-app, close-with-app)
type OwnedBackend = { kind: "omlx"; child: ChildProcess } | { kind: "lmstudio" } | null;
let owned: OwnedBackend = null;

/** Kill the wrapper AND the omlx-server it spawned: the wrapper runs detached
 *  (own process group), so a negative pid reaches the whole tree — and only OUR
 *  instance, never the user's other oMLX processes. */
function killOmlxTree(child: ChildProcess): void {
  try {
    process.kill(-child.pid!, "SIGTERM");
  } catch {
    child.kill("SIGTERM");
  }
}

/** Stop the owned LLM backend. Signal-independent so it can also be invoked via
 *  POST /api/shutdown — on Windows SIGTERM kills Electron's Node child without
 *  running exit handlers, leaving the backend alive. */
export function shutdownBackend(): void {
  if (!owned) return;
  log(`app in chiusura — arresto backend ${owned.kind}`);
  if (owned.kind === "omlx") {
    killOmlxTree(owned.child);
  } else {
    const lms = resolveLms();
    if (lms) spawnSync(lms, ["server", "stop"], { timeout: 10_000 });
  }
  owned = null;
}

/** Register exit handlers: the LLM backend lives and dies with the app. */
export function cleanupOnExit(): void {
  const stop = shutdownBackend;
  process.on("exit", stop);
  for (const sig of ["SIGINT", "SIGTERM"] as const) {
    process.on(sig, () => {
      stop();
      process.exit(0);
    });
  }
}

export function llmBackendState(): BackendState {
  return backendState;
}

/** First run (or post-reset) with no backend configured: auto-resolve an engine
 *  that already exists on this machine, so the LLM comes up with the app.
 *  Only models already on disk are picked — fresh installs go through the wizard. */
async function autoPickBackend(): Promise<{ backend: "omlx" | "lmstudio"; model: string; baseUrl: string } | null> {
  if (resolveOmlx()) {
    const models = await omlxModels(false); // server not up yet → directory scan
    if (models.length) {
      return { backend: "omlx", model: models.find((m) => /bonsai/i.test(m)) ?? models[0], baseUrl: OMLX_BASE };
    }
  }
  const lms = resolveLms();
  if (lms) {
    const models = await downloadedModels(lms).catch(() => [] as string[]);
    if (models.length) {
      return { backend: "lmstudio", model: models.find((m) => /bonsai/i.test(m)) ?? models[0], baseUrl: LMSTUDIO_BASE };
    }
  }
  return null;
}

let lastEnsure = 0;

/** Fire-and-forget: bring the LLM backend up with the app, retry while it's off.
 *  Contract: the engine starts with the app and stops with the app (SIGTERM at
 *  quit) — the user never starts it by hand. */
export function ensureLlmServer(force = false): void {
  if (hasCustomEnv()) return; // env LLM_BASE_URL wins everywhere — hands off
  const cfg = readConfigFile();
  if (!cfg.setupDone) return; // wizard not finished — never probe/persist behind it
  if (cfg.backend === "skipped" || cfg.backend === "custom") return; // explicit user choice
  const configured = cfg.backend === "lmstudio" || cfg.backend === "omlx";
  if (configured && !cfg.model) return;
  const now = Date.now();
  // the lock wins over force: two concurrent run() calls spawn two backends and
  // leak one (owned points at the last child — the first survives app quit)
  if (ensureLock) return;
  if (!force && now - lastEnsure < (backendState === "up" ? 60_000 : 15_000)) return;
  lastEnsure = now; // ponytail: time-based retry throttle, no backoff table
  backendState = "starting";
  ensureLock = (async () => {
    if (!configured) {
      const pick = await autoPickBackend();
      if (!pick) {
        backendState = "off"; // no engine on this machine — wizard's job
        return;
      }
      updateConfig(pick); // persist so the next boot skips the probe
    }
    await run();
  })()
    .catch((e) => {
      log(`ensure fallito: ${e}`);
      backendState = "off";
    })
    .finally(() => {
      ensureLock = null;
    });
}

async function run(): Promise<void> {
  const cfg = readConfigFile();
  const base = cfg.baseUrl ?? LMSTUDIO_BASE;
  if (await httpOk(`${base}/models`, 2000, llmAuthHeaders())) {
    backendState = "up";
    return;
  }
  if (cfg.backend === "omlx") {
    const omlx = resolveOmlx();
    if (!omlx) {
      log("omlx non trovato — backend LLM non avviato");
      backendState = "off";
      return;
    }
    const port = new URL(base).port || "8080";
    const spawnServe = (): void => {
      log(`avvio omlx serve sulla porta ${port}`);
      const out = openSync(LLM_LOG, "a");
      // detached: own process group → killOmlxTree reaches wrapper + omlx-server
      const child = spawn(omlx, ["serve", "--host", "127.0.0.1", "--port", port], {
        stdio: ["ignore", out, out],
        detached: true,
      });
      child.on("error", (e) => {
        log(`omlx serve spawn error: ${e.message}`);
        backendState = "off";
        if (owned?.kind === "omlx" && owned.child === child) owned = null;
      });
      child.on("close", () => {
        try {
          closeSync(out);
        } catch {
          /* already closed */
        }
      });
      owned = { kind: "omlx", child };
    };
    const modelVisible = async (): Promise<boolean> => {
      try {
        const res = await fetch(`${base}/models`, {
          headers: omlxAuthHeaders(),
          signal: AbortSignal.timeout(3000),
        });
        if (!res.ok) return false;
        const j = (await res.json()) as { data?: { id?: string }[] };
        // oMLX serves bare names while the wizard may persist an org/repo id:
        // tolerate both spellings or the backend stays permanently "off"
        const leaf = cfg.model?.split("/").pop();
        return (j.data ?? []).some((m) => m.id === cfg.model || (leaf != null && m.id === leaf));
      } catch {
        return false;
      }
    };

    if (!(await httpOk(`${base}/models`, 2000, omlxAuthHeaders()))) {
      spawnServe();
      for (let i = 0; i < 60 && !(await httpOk(`${base}/models`, 2000, omlxAuthHeaders())); i++) {
        await sleep(2000);
      }
    }
    // oMLX scans models only at boot: a model downloaded while it was running
    // is invisible until a restart — rescan and restart when needed
    if (!(await modelVisible())) {
      log(`oMLX non vede ${cfg.model} — riavvio del server per rescan`);
      if (owned?.kind === "omlx") {
        killOmlxTree(owned.child); // whole group: the old server must free the port
        owned = null;
        for (let i = 0; i < 30 && (await httpOk(`${base}/models`, 1000, omlxAuthHeaders())); i++) {
          await sleep(1000);
        }
        spawnServe();
        for (let i = 0; i < 60 && !(await httpOk(`${base}/models`, 2000, omlxAuthHeaders())); i++) {
          await sleep(2000);
        }
      } else {
        log("server oMLX esterno all'app: serve un riavvio manuale per vedere i modelli nuovi");
      }
    }
    backendState = (await modelVisible()) ? "up" : "off";
    log(`backend omlx: ${backendState}`);
    return;
  }
  const lms = resolveLms();
  if (!lms) {
    log("lms non trovato — backend LLM non avviato");
    backendState = "off";
    return;
  }
  const daemon = await runLms(lms, ["daemon", "up"], 30_000);
  if (daemon.code !== 0) log(`daemon up: exit ${daemon.code} — ${daemon.stderr.slice(-200)}`);
  const server = await runLms(lms, ["server", "start"], 30_000);
  if (server.code !== 0) {
    log(`server start: exit ${server.code} — ${server.stderr.slice(-200)} (porta occupata?)`);
    backendState = "off";
    return;
  }
  owned = { kind: "lmstudio" }; // we started it → we stop it on app exit
  const ls = await runLms(lms, ["ls", "--json"], 30_000);
  let installed = false;
  try {
    const parsed = JSON.parse(ls.stdout) as { models?: { key?: string; path?: string }[] };
    installed = (parsed.models ?? []).some((m) => (m.key ?? m.path) === cfg.model);
  } catch {
    /* unparseable output — treat as absent */
  }
  if (!installed) {
    if (jobActive()) {
      log("un download del wizard è già in corso — salto l'auto-get");
      backendState = "off";
      return;
    }
    // route the auto-get through the download job singleton: one owner, the wizard
    // shows real progress, and completion re-kicks ensure (see startDownload)
    log(`modello ${cfg.model} assente — lo scarico (può volerci molto)`);
    try {
      startDownload(cfg.model!);
    } catch (e) {
      log(`auto-get non partito: ${(e as Error).message}`);
    }
    backendState = "off";
    return;
  }
  const load = await runLms(lms, ["load", cfg.model!, "-y", "--gpu=max", "--context-length=8192"], 180_000);
  if (load.code !== 0) {
    // a 200 on /v1/models means nothing if the model failed to load — stay off
    log(`load: exit ${load.code} — ${load.stderr.slice(-200)}`);
    backendState = "off";
    return;
  }
  for (let i = 0; i < 10 && !(await httpOk(`${base}/models`, 2000)); i++) {
    await new Promise((r) => setTimeout(r, 2000));
  }
  backendState = (await httpOk(`${base}/models`, 2000)) ? "up" : "off";
  log(`backend: ${backendState}`);
}

// --- downloaded models (memoized) --------------------------------------------------

let lsCache: { at: number; models: string[] } | null = null;

async function refreshLs(lms: string): Promise<void> {
  const ls = await runLms(lms, ["ls", "--json"], 15_000);
  if (ls.code !== 0) return; // keep serving whatever we had
  try {
    const parsed = JSON.parse(ls.stdout) as { models?: { path?: string; key?: string }[] };
    const models = (parsed.models ?? [])
      .map((m) => m.key ?? m.path ?? "")
      .filter((s) => s.length > 0);
    lsCache = { at: Date.now(), models };
  } catch {
    /* non-json output (older lms) — keep old cache */
  }
}

/** Stale-while-revalidate: /status must never block on `lms ls` (up to 15 s of
 *  spawn on a cold machine) — serve the last known list and refresh in background. */
async function downloadedModels(lms: string | null): Promise<string[]> {
  if (!lms) return [];
  const cached = lsCache;
  if (!cached) {
    await refreshLs(lms); // first call in this process: block once
    return lsCache?.models ?? [];
  }
  if (Date.now() - cached.at >= 10_000) void refreshLs(lms); // expired → revalidate
  return cached.models;
}

// --- routes -----------------------------------------------------------------------

export const setupRoutes = new Hono();

/** Backend state reconciled with a live probe at read time, so the two never disagree. */
function reportedLlmState(serverUp: boolean): BackendState {
  if (serverUp) return "up";
  return backendState === "starting" ? "starting" : "off";
}

setupRoutes.get("/status", async (c) => {
  const cfg = readConfigFile();
  const hw = detectHardware();
  const lms = resolveLms();
  const omlx = resolveOmlx();
  const omlxUp = omlx != null && (await httpOk(`${OMLX_BASE}/models`, 1000, omlxAuthHeaders()));
  const [models, omlxModelsList, serverUp] = await Promise.all([
    jobActive() ? [] : downloadedModels(lms),
    omlx != null ? omlxModels(omlxUp) : Promise.resolve([]),
    httpOk(`${cfg.baseUrl ?? LMSTUDIO_BASE}/models`, 1000, llmAuthHeaders()),
  ]);
  // "up" only if the configured model is actually among the served ones — a live
  // server that doesn't serve our model would show a green chip on a broken setup
  const leaf = cfg.model?.split("/").pop();
  const modelServed =
    cfg.model == null ||
    omlxModelsList.some((m) => m === cfg.model || m === leaf) ||
    models.some((m) => m === cfg.model || m === leaf);
  // disclosure-minimal: no absolute binary path, no raw env details beyond hw summary
  const status: SetupStatus = {
    setupDone: Boolean(cfg.setupDone),
    needsSetup: !cfg.setupDone || needsSetupVersion(cfg),
    customEnv: hasCustomEnv(),
    hardware: hw,
    suggested: suggestModel(hw),
    lms: { installed: lms != null, path: null, serverUp },
    omlx: {
      installed: omlx != null,
      serverUp: omlxUp,
      models: omlxModelsList,
      downloadable: Object.entries(OMLX_DOWNLOADABLE).map(([model, sizeGb]) => ({ model, sizeGb })),
    },
    downloadedModels: models,
    job,
    llm: { state: reportedLlmState(serverUp && modelServed) },
  };
  return c.json(status);
});

/** Wizard reopen after an app update (setupDone already true): persist only the
 *  version marker — backend/model choices stay untouched. */
setupRoutes.post("/ack", (c) => {
  updateConfig({ setupDone: true, setupVersion: APP_VERSION });
  return c.json({ ok: true });
});

setupRoutes.post("/install-cli", (c) => {
  try {
    installCli();
    return c.json({ ok: true });
  } catch (e) {
    return c.json({ error: String((e as Error).message) }, 409);
  }
});

setupRoutes.post("/download", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { model?: string } | null;
  if (!body?.model) return c.json({ error: "invalid_request" }, 400);
  try {
    startDownload(body.model);
    return c.json({ ok: true });
  } catch (e) {
    const msg = (e as Error).message;
    return c.json({ error: msg }, msg === "busy" ? 409 : 400);
  }
});

setupRoutes.post("/finish", async (c) => {
  const body = (await c.req.json().catch(() => null)) as
    | { model?: string; baseUrl?: string; backend?: "skipped" | "omlx" }
    | null;
  if (!body) return c.json({ error: "invalid_request" }, 400);
  if (body.backend === "skipped") {
    // explicit undefined keys erase leftovers: an LLM the user declined must not
    // keep receiving prompts through a stale model/baseUrl
    updateConfig({ setupDone: true, setupVersion: APP_VERSION, backend: "skipped", model: undefined, baseUrl: undefined });
    return c.json({ ok: true });
  }
  if (body.model != null && !MODEL_KEY_RE.test(body.model)) {
    return c.json({ error: "invalid_model" }, 400);
  }
  if (body.baseUrl != null) {
    if (!/^https?:\/\/[\w.:/-]+$/.test(body.baseUrl)) return c.json({ error: "invalid_url" }, 400);
    const patch: AppConfig = { setupDone: true, setupVersion: APP_VERSION, backend: "custom", baseUrl: body.baseUrl };
    if (body.model) patch.model = body.model;
    updateConfig(patch);
    return c.json({ ok: true });
  }
  if (body.backend === "omlx") {
    if (!body.model) return c.json({ error: "invalid_model" }, 400);
    if (!resolveOmlx()) return c.json({ error: "omlx_missing" }, 400);
    updateConfig({ setupDone: true, setupVersion: APP_VERSION, backend: "omlx", model: body.model, baseUrl: OMLX_BASE });
    ensureLlmServer(true);
    return c.json({ ok: true });
  }
  if (!body.model) return c.json({ error: "invalid_model" }, 400);
  const lms = resolveLms();
  if (!lms) return c.json({ error: "lms_missing" }, 400);
  updateConfig({
    setupDone: true,
    setupVersion: APP_VERSION,
    backend: "lmstudio",
    model: body.model,
    baseUrl: LMSTUDIO_BASE,
    lmsPath: lms,
  });
  ensureLlmServer(true);
  return c.json({ ok: true });
});

setupRoutes.post("/omlx-download", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { model?: string } | null;
  if (!body?.model) return c.json({ error: "invalid_request" }, 400);
  try {
    startOmlxDownload(body.model);
    return c.json({ ok: true });
  } catch (e) {
    const msg = (e as Error).message;
    return c.json({ error: msg }, msg === "busy" ? 409 : 400);
  }
});

setupRoutes.post("/cancel", (c) => {
  cancelJob();
  return c.json({ ok: true });
});

setupRoutes.post("/reset", (c) => {
  try {
    unlinkSync(CONFIG_PATH);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "ENOENT") {
      return c.json({ error: "reset_failed" }, 500);
    }
  }
  // reset shared state too, so the app truly returns to pre-setup
  updateConfig({});
  cancelJob(); // kills an in-flight download and bumps the generation
  return c.json({ ok: true });
});
