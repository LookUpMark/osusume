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

test("suggestModel: RAM threshold 32GB picks Qwen3.6 vs Gemma 4", () => {
  assert.ok(suggestModel(hw({ ramGb: 32 })).model.includes("Qwen3.6"));
  assert.ok(suggestModel(hw({ ramGb: 64 })).model.includes("Qwen3.6"));
  assert.ok(suggestModel(hw({ ramGb: 24 })).model.includes("gemma-4"));
  assert.ok(suggestModel(hw({ ramGb: 8 })).model.includes("gemma-4"));
  assert.equal(suggestModel(hw({ ramGb: 64 })).sizeGb, 21.5);
  assert.equal(suggestModel(hw({ ramGb: 16 })).sizeGb, 8.1);
});

test("suggestModel: MLX variants only on Apple Silicon", () => {
  assert.ok(suggestModel(hw({ appleSilicon: true })).mlx?.model.includes("mlx"));
  assert.equal(suggestModel(hw({ appleSilicon: false })).mlx, null);
  assert.equal(suggestModel(hw({ appleSilicon: false })).mlxLms, null);
});

test("suggestModel: per-engine MLX packs for both tiers on Apple Silicon", () => {
  const hi = suggestModel(hw({ ramGb: 64, appleSilicon: true }));
  assert.equal(hi.mlx?.model, "mlx-community/Qwen3.6-35B-A3B-4bit", "oMLX gets the mlx-community pack");
  assert.equal(hi.mlxLms?.model, "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit", "LM Studio gets its own pack");
  const lo = suggestModel(hw({ ramGb: 16, appleSilicon: true }));
  assert.equal(lo.mlx?.model, "mlx-community/gemma-4-12B-it-4bit");
  assert.equal(lo.mlxLms?.model, "lmstudio-community/gemma-4-12B-it-MLX-4bit");
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
    assert.ok(/Qwen3\.6|gemma-4/i.test(status.suggested.model), "suggestion comes from the live catalogue");
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
  // fake lms: "get" sleeps 2s (a real download takes a while), everything else
  // instant; a TERM trap records the kill so the test can pin fix e1-6
  const fakeLms = join(dir, "fake-lms.sh");
  writeFileSync(
    fakeLms,
    [
      "#!/bin/bash",
      `echo "$*" >> ${JSON.stringify(callsPath)}`,
      `trap "echo KILLED >> ${callsPath}; exit 143" TERM`,
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

    // wait until the download child actually started (first call logged):
    // a TERM sent before bash registers its trap kills it silently
    const startDeadline = Date.now() + 5000;
    let started = false;
    while (Date.now() < startDeadline) {
      try {
        if (readFileSync(callsPath, "utf8").includes("get ")) {
          started = true;
          break;
        }
      } catch {
        /* not written yet */
      }
      await new Promise((r) => setTimeout(r, 100));
    }
    assert.ok(started, "download child must start");

    // cancel mid-download: job must go idle AND stay idle after the child exits
    await fetch(`${BASE}/api/setup/cancel`, { method: "POST" });
    const idle = (await (await fetch(`${BASE}/api/setup/status`)).json()).job;
    assert.equal(idle.state, "idle");

    // the child must die for real (fix e1-6 pinned): the fake logs KILLED on TERM
    const killDeadline = Date.now() + 6000;
    let killedSeen = false;
    while (Date.now() < killDeadline) {
      try {
        if (readFileSync(callsPath, "utf8").includes("KILLED")) {
          killedSeen = true;
          break;
        }
      } catch {
        /* not written yet */
      }
      await new Promise((r) => setTimeout(r, 200));
    }
    assert.ok(killedSeen, "cancel must SIGTERM the download child");

    await new Promise((r) => setTimeout(r, 3500)); // child would have exited by now
    const after = (await (await fetch(`${BASE}/api/setup/status`)).json()).job;
    assert.equal(after.state, "idle", "cancelled job must never resurrect to done/error");
    assert.equal(after.model, null);
  } finally {
    child.kill("SIGTERM");
    rmSync(dir, { recursive: true, force: true });
  }
});
