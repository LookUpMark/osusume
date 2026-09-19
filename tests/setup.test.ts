import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";
import { readConfigFile, updateConfig, type AppConfig } from "../src/server/config.ts";
import { needsSetupVersion, suggestModel, type Hardware } from "../src/server/setup.ts";

const hw = (over: Partial<Hardware> = {}): Hardware => ({
  os: "mac",
  chip: "Apple M3 Pro",
  ramGb: 36,
  appleSilicon: true,
  ...over,
});

test("suggestModel: RAM thresholds pick 27B vs 8B", () => {
  assert.ok(suggestModel(hw({ ramGb: 16 })).model.includes("27B"));
  assert.ok(suggestModel(hw({ ramGb: 32 })).model.includes("27B"));
  assert.ok(suggestModel(hw({ ramGb: 15 })).model.includes("8B"));
  assert.ok(suggestModel(hw({ ramGb: 8 })).model.includes("8B"));
  assert.equal(suggestModel(hw({ ramGb: 36 })).sizeGb, 6.7);
  assert.equal(suggestModel(hw({ ramGb: 8 })).sizeGb, 2.03);
});

test("suggestModel: MLX variant only on Apple Silicon", () => {
  assert.ok(suggestModel(hw({ appleSilicon: true })).mlx?.model.includes("mlx"));
  assert.equal(suggestModel(hw({ appleSilicon: false })).mlx, null);
});

test("suggestModel: Bonsai-2 MLX is oMLX-only — no LM Studio MLX variant for 27B", () => {
  const hi = suggestModel(hw({ ramGb: 36, appleSilicon: true }));
  assert.equal(hi.mlx?.model, "prism-ml/Ternary-Bonsai-2-27B-mlx-2bit");
  assert.equal(hi.mlx?.sizeGb, 8.6);
  assert.equal(hi.mlxLms, null, "Bonsai-2 packings are not loadable by LM Studio — no lms MLX variant");
  const lo = suggestModel(hw({ ramGb: 8, appleSilicon: true }));
  assert.ok(lo.mlxLms?.model.includes("8B"), "8B v1 MLX stays available via lms");
  assert.ok(lo.mlxLms?.model.includes("mlx"));
});

test("needsSetupVersion: wizard reopens on app update, ack silences it", () => {
  assert.equal(needsSetupVersion({}, "0.5.4"), true, "no marker yet");
  assert.equal(needsSetupVersion({ setupVersion: "0.5.3" }, "0.5.4"), true, "older marker");
  assert.equal(needsSetupVersion({ setupVersion: "0.5.4" }, "0.5.4"), false, "acked");
  assert.equal(needsSetupVersion({ setupVersion: "0.5.3" }, undefined), false, "dev: no APP_VERSION");
});

test("config precedence: env > file > default; corrupt file tolerated", () => {
  const dir = mkdtempSync(join(tmpdir(), "alr-cfg-"));
  const path = join(dir, "config.json");
  try {
    assert.deepEqual(readConfigFile(path), {}, "missing file = empty config");
    writeFileSync(path, "{not json");
    assert.deepEqual(readConfigFile(path), {}, "corrupt file = empty config");
    writeFileSync(
      path,
      JSON.stringify({ setupDone: true, backend: "lmstudio", model: "prism-ml/Bonsai-8B-gguf", baseUrl: "http://127.0.0.1:1234/v1" }),
    );
    const cfg: AppConfig = readConfigFile(path);
    assert.equal(cfg.model, "prism-ml/Bonsai-8B-gguf");
    assert.equal(cfg.backend, "lmstudio");
    updateConfig({ model: "prism-ml/Bonsai-27B-gguf" }, path);
    assert.equal(readConfigFile(path).model, "prism-ml/Bonsai-27B-gguf", "update merges");
    assert.ok(readFileSync(path, "utf8").includes("setupDone"), "other keys preserved");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("setup flow with fake lms: status, finish writes config, ensure sequences lms commands", async () => {
  const dir = mkdtempSync(join(tmpdir(), "alr-setup-"));
  const cfgPath = join(dir, "config.json");
  const callsPath = join(dir, "lms-calls.log");
  // fake lms: logs "subcmd args…" per invocation, ls lists the model only after
  // it was "get"-ed, load fails (fast, no HTTP poll)
  const fakeLms = join(dir, "fake-lms.sh");
  writeFileSync(
    fakeLms,
    [
      "#!/bin/bash",
      `echo "$*" >> ${JSON.stringify(callsPath)}`,
      'if [ "$1" = "ls" ]; then',
      `  if grep -q "^get " ${JSON.stringify(callsPath)}; then`,
      `    echo '{"models":[{"key":"prism-ml/Bonsai-27B-gguf"}]}';`,
      "  else",
      "    echo '[]';",
      "  fi",
      "fi",
      'if [ "$1" = "load" ]; then exit 1; fi',
      "exit 0",
      "",
    ].join("\n"),
  );
  const { chmodSync } = await import("node:fs");
  chmodSync(fakeLms, 0o755);

  // closed port: bind ephemeral, release — deterministic "LM Studio down"
  const { createServer } = await import("node:http");
  const blocker = createServer();
  const closedPort = await new Promise<number>((r) => blocker.listen(0, "127.0.0.1", () => r((blocker.address() as any).port))).then((p) => {
    blocker.close();
    return p;
  });

  const PORT = 4791;
  const BASE = `http://127.0.0.1:${PORT}`;
  const child: ChildProcess = spawn(process.execPath, ["src/server/index.ts"], {
    cwd: join(import.meta.dirname, ".."),
    env: {
      ...process.env,
      ANILIST_FIXTURES: "fixtures",
      ALR_DATA_DIR: join(dir, "data"), // keep llm.log/cache out of the real repo data/
      CONFIG_PATH: cfgPath,
      LMS_PATH: fakeLms,
      LMSTUDIO_BASE_URL: `http://127.0.0.1:${closedPort}/v1`,
      PORT: String(PORT),
    },
    stdio: "ignore",
  });
  try {
    const deadline = Date.now() + 15000;
    for (;;) {
      try {
        if ((await fetch(`${BASE}/api/health`)).ok) break;
      } catch {
        /* not up yet */
      }
      if (Date.now() > deadline) throw new Error("server did not start");
      await new Promise((r) => setTimeout(r, 300));
    }

    const status = await (await fetch(`${BASE}/api/setup/status`)).json();
    assert.equal(status.setupDone, false);
    assert.ok(status.hardware.ramGb > 0);
    assert.ok(status.suggested.model.includes("Bonsai"));
    assert.equal(status.lms.installed, true, "fake LMS_PATH must be detected");
    assert.equal(status.job.state, "idle");

    const bad = await fetch(`${BASE}/api/setup/download`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: "bad name!" }),
    });
    assert.equal(bad.status, 400, "model key must be validated");

    const fin = await fetch(`${BASE}/api/setup/finish`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: "prism-ml/Bonsai-27B-gguf" }),
    });
    assert.equal(fin.status, 200);
    const cfg = readConfigFile(cfgPath);
    assert.equal(cfg.setupDone, true);
    assert.equal(cfg.backend, "lmstudio");
    assert.equal(cfg.baseUrl, `http://127.0.0.1:${closedPort}/v1`);

    // ensureLlmServer() was kicked by finish: wait for the documented sequence.
    // (Boot-time ensure is a no-op until setupDone — no pre-wizard probes.)
    // The auto-get of the missing model now runs through the download job
    // singleton: ensure#1 stops after "ls --json" (model absent → startDownload),
    // the job's "get" runs, and on completion ensure re-kicks itself and loads.
    // Anchor on the LAST "daemon up" (= ensure#2).
    const expected = [
      "daemon up",
      "server start",
      "ls --json",
      "load prism-ml/Bonsai-27B-gguf -y --gpu=max --context-length=8192",
    ];
    const deadline2 = Date.now() + 30000;
    let seq: string[] = [];
    while (Date.now() < deadline2) {
      try {
        seq = readFileSync(callsPath, "utf8").split("\n").filter((l) => l.trim().length > 0);
      } catch {
        /* not written yet */
      }
      if (seq.slice(-1)[0]?.startsWith("load")) break;
      await new Promise((r) => setTimeout(r, 300));
    }
    const start = seq.lastIndexOf("daemon up");
    assert.ok(start >= 0, "ensure must run the documented command sequence");
    assert.deepEqual(seq.slice(start, start + expected.length), expected, "ensure must run the documented command sequence");
    assert.equal(
      seq.filter((l) => l === "get prism-ml/Bonsai-27B-gguf --gguf").length,
      1,
      "exactly one download of the model, owned by the job singleton",
    );

    // load failed on the fake → backend deterministically off (never a phantom "up")
    const health = await (await fetch(`${BASE}/api/health`)).json();
    assert.equal(health.llm.state, "off");

    // wizard reappears after reset
    await fetch(`${BASE}/api/setup/reset`, { method: "POST" });
    assert.deepEqual(readConfigFile(cfgPath), {});
    const statusAfter = await (await fetch(`${BASE}/api/setup/status`)).json();
    assert.equal(statusAfter.setupDone, false);
  } finally {
    child.kill("SIGTERM");
    rmSync(dir, { recursive: true, force: true });
  }
});

test("cancelled download cannot resurrect the job or outlive the cancel", async () => {
  const dir = mkdtempSync(join(tmpdir(), "alr-cancel-"));
  const cfgPath = join(dir, "config.json");
  const callsPath = join(dir, "lms-calls.log");
  // fake lms: "get" sleeps 2s (a real download takes a while), everything else instant
  const fakeLms = join(dir, "fake-lms.sh");
  writeFileSync(
    fakeLms,
    [
      "#!/bin/bash",
      `echo "$*" >> ${JSON.stringify(callsPath)}`,
      'if [ "$1" = "get" ]; then sleep 2; fi',
      'if [ "$1" = "ls" ]; then echo \'{"models":[]}\'; fi',
      "exit 0",
      "",
    ].join("\n"),
  );
  const { chmodSync } = await import("node:fs");
  chmodSync(fakeLms, 0o755);

  const PORT = 4797;
  const BASE = `http://127.0.0.1:${PORT}`;
  const child: ChildProcess = spawn(process.execPath, ["src/server/index.ts"], {
    cwd: join(import.meta.dirname, ".."),
    env: {
      ...process.env,
      ANILIST_FIXTURES: "fixtures",
      ALR_DATA_DIR: join(dir, "data"),
      CONFIG_PATH: cfgPath,
      LMS_PATH: fakeLms,
      LMSTUDIO_BASE_URL: "http://127.0.0.1:9/v1",
      PORT: String(PORT),
    },
    stdio: "ignore",
  });
  try {
    const deadline = Date.now() + 15000;
    for (;;) {
      try {
        if ((await fetch(`${BASE}/api/health`)).ok) break;
      } catch {
        /* not up yet */
      }
      if (Date.now() > deadline) throw new Error("server did not start");
      await new Promise((r) => setTimeout(r, 300));
    }

    const dl = await fetch(`${BASE}/api/setup/download`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model: "prism-ml/Bonsai-27B-gguf" }),
    });
    assert.equal(dl.status, 200);

    // cancel mid-download: job must go idle AND stay idle after the child exits
    await fetch(`${BASE}/api/setup/cancel`, { method: "POST" });
    const idle = (await (await fetch(`${BASE}/api/setup/status`)).json()).job;
    assert.equal(idle.state, "idle");
    await new Promise((r) => setTimeout(r, 3500)); // child would have exited by now
    const after = (await (await fetch(`${BASE}/api/setup/status`)).json()).job;
    assert.equal(after.state, "idle", "cancelled job must never resurrect to done/error");
    assert.equal(after.model, null);
  } finally {
    child.kill("SIGTERM");
    rmSync(dir, { recursive: true, force: true });
  }
});
