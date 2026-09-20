#!/usr/bin/env node
// POSIX-only (mac/linux gate): spawns the bare binary name and derives the repo
// root from `new URL(..).pathname` — both break on Windows.
// P7 gate: sidecar standalone, run the way Electron runs it — health 200 within
// 15s, /api/shutdown → exit 0 within 5s. Fixtures fallback is proven with a dead
// ANILIST_ENDPOINT: `ANILIST_ENDPOINT=http://127.0.0.1:9 node scripts/check-pyserver.mjs`
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const PORT = await new Promise((resolve, reject) => {
  const s = createServer();
  s.listen(0, "127.0.0.1", () => {
    const p = s.address().port;
    s.close(() => resolve(p));
  });
  s.on("error", reject);
});
const data = mkdtempSync(join(tmpdir(), "p7-sidecar-"));
const child = spawn(join(root, "build/pyserver/dist/osusume-server/osusume-server"), [], {
  cwd: root, // fixtures/ resolve cwd-relative (what packaged maps to resourcesPath/app)
  env: { ...process.env, PORT: String(PORT), ALR_DATA_DIR: data, DIST_DIR: join(root, "dist") },
  stdio: ["ignore", "inherit", "inherit"],
});
const t0 = Date.now();
let up = false;
while (Date.now() - t0 < 15_000) {
  try {
    if ((await fetch(`http://127.0.0.1:${PORT}/api/health`)).ok) {
      up = true;
      break;
    }
  } catch {}
  await new Promise((r) => setTimeout(r, 300));
}
if (!up) {
  console.error("FAIL: health non raggiungibile entro 15s");
  child.kill("SIGKILL");
  process.exit(1);
}
console.log(`health 200 in ${Date.now() - t0}ms (port ${PORT})`);

// payload sanity: recos non-vuoti (auto-fallback sulle fixtures con AniList morto)
const rec = await fetch(`http://127.0.0.1:${PORT}/api/recommend`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ username: "LookUpMark", lang: "en" }),
});
const body = await rec.json().catch(() => null);
console.log(`recommend: ${rec.status}, recos: ${Array.isArray(body?.recos) ? body.recos.length : "n/a"}`);

const t1 = Date.now();
await fetch(`http://127.0.0.1:${PORT}/api/shutdown`, { method: "POST" });
const code = await new Promise((res) => child.on("exit", (c) => res(c)));
const dt = Date.now() - t1;
console.log(`exit code ${code} dopo ${dt}ms`);
rmSync(data, { recursive: true, force: true });
if (code !== 0 || dt > 5000 || !Array.isArray(body?.recos) || body.recos.length === 0) process.exit(1);
console.log("OK: health 200 + recos + shutdown exit 0 entro 5s");
