#!/usr/bin/env node
// Build the Python sidecar (PyInstaller onedir) for the current platform.
// Output: build/pyserver/dist/osusume-server/<osusume-server|osusume-server.exe> + _internal/
// Reproducible: dedicated venv built from backend/uv.lock (--frozen) + pinned pyinstaller.
// Requirements: uv on PATH or $UV (default ~/.local/bin/uv) — it provisions CPython 3.12.
import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const out = join(root, "build", "pyserver");
const venv = join(out, ".venv");
const uv = process.env.UV || join(process.env.HOME || "", ".local", "bin", "uv");
const PYINSTALLER = "6.22.3";
const win = process.platform === "win32";
const vbin = join(venv, win ? "Scripts" : "bin");
const exe = win ? "osusume-server.exe" : "osusume-server";

function run(cmd, args, env = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", cwd: root, env: { ...process.env, ...env } });
  if (r.status !== 0) process.exit(r.status ?? 1);
}

// fresh venv from the backend lockfile (uv ignores it unless UV_PROJECT_ENVIRONMENT points elsewhere)
rmSync(venv, { recursive: true, force: true });
run(
  uv,
  ["sync", "--project", join(root, "backend"), "--frozen", "--no-dev", "--python", "3.12"],
  { UV_PROJECT_ENVIRONMENT: venv },
);
run(uv, ["pip", "install", "--python", join(vbin, win ? "python.exe" : "python"), `pyinstaller==${PYINSTALLER}`]);

// no --add-data: fixtures ship via electron-builder extraResources and the sidecar
// resolves them cwd-relative (resourcesPath/app); hooks-contrib covers uvicorn/pydantic
run(join(vbin, win ? "python.exe" : "python"), [
  "-m",
  "PyInstaller",
  "--noconfirm",
  "--onedir",
  "--name",
  "osusume-server",
  "--paths",
  join(root, "backend"),
  "--distpath",
  join(out, "dist"),
  "--workpath",
  join(out, "work"),
  "--specpath",
  out,
  join(root, "backend", "pyserver_main.py"),
]);

const bin = join(out, "dist", "osusume-server", exe);
if (!existsSync(bin)) {
  console.error(`build-pyserver: missing ${bin}`);
  process.exit(1);
}
const mb = (p) => {
  const st = statSync(p);
  if (!st.isDirectory()) return (st.size / 1024 / 1024).toFixed(1);
  let n = 0;
  for (const e of readdirSync(p, { recursive: true })) {
    const f = join(p, e);
    if (statSync(f).isFile()) n += statSync(f).size;
  }
  return (n / 1024 / 1024).toFixed(1);
};
const internal = join(out, "dist", "osusume-server", "_internal");
console.log(`build-pyserver: ${bin} (${mb(bin)} MB, _internal ${mb(internal)} MB)`);
