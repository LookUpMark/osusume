# 10 — Desktop packaging & CI/CD

**Abstract.** The Electron shell that owns the Python sidecar lifecycle, the PyInstaller build that freezes the backend, electron-builder targets for three OSes, and the two GitHub Actions workflows (CI and tag-triggered release).

## Purpose

Ship one installer per OS where the app starts its own backend, owns its lifecycle, and survives quarantine/translocation quirks — with releases published by pushing a tag.

## Electron shell (`desktop/main.ts`)

- Single-instance lock — a second instance would race the LLM backend and the port (`main.ts:14-17`).
- `serverCommand()` (`main.ts:22-41`): dev = `backend/.venv/{bin|Scripts}/python run_dev.py` (not `uv run` — uv may be off the app PATH); packaged = `resourcesPath/desktop-server/osusume-server[.exe]` (PyInstaller onedir copied by electron-builder).
- Env: `PORT` (free port from bind :0), `ALR_DATA_DIR = userData` (bundle is read-only under App Translocation), packaged-only `APP_VERSION` + `DIST_DIR` (`main.ts:43-92`).
- Crash handling: `server.on("exit")` → error box + quit; `server.on("error")` exists because a spawn ENOENT/EACCES (missing binary, Gatekeeper quarantine) emits only "error", never "exit" — without the handler the app hangs as a windowless zombie (`main.ts:93-101`).
- Navigation guards: `setWindowOpenHandler` → `shell.openExternal` + deny; `will-navigate` only to `http://127.0.0.1:{port}` (`main.ts:122-131`); loads http, not file://, because the API rejects foreign Host headers.
- Shutdown contract: best-effort `POST /api/shutdown` (SIGTERM skips Python exit handlers, always on Windows), then SIGTERM + 2 s SIGKILL; explicit SIGTERM/SIGINT handlers bypass `before-quit` and `app.exit(0)` (`main.ts:147-188`).

## Sidecar build (`scripts/build-pyserver.mjs`)

PyInstaller onedir → `build/pyserver/dist/osusume-server/`: fresh venv via `uv sync --frozen --no-dev --python 3.12` with `UV_PROJECT_ENVIRONMENT` redirected, pinned `pyinstaller==6.22.3`; no `--add-data` — fixtures ship as electron-builder extraResources and the sidecar resolves them cwd-relative (`build-pyserver.mjs:20-62`).

## electron-builder (`electron-builder.yml`)

`appId com.lookupmark.osusume`, output `release/`; `files: dist/**, dist-electron/**, fixtures/**`, `asar: false`; extraResources maps the sidecar → `desktop-server`. Targets: mac dmg arm64 unsigned (`identity: null` — right-click → Open), win NSIS x64 unsigned (SmartScreen warning), linux AppImage x64. Artifact names carry `${version}` — which must match the tag (see CI gate).

## Workflows

- `ci.yml` — 3 jobs on push/PR, `contents: read`: node (typecheck, vite build, `node --test tests/*.test.ts`), python (`uv sync --frozen --dev`, pytest `backend/tests -q`), docker (buildx no-push + `/api/health` smoke) (`.github/workflows/ci.yml:8-51`).
- `release.yml` — on tags `v*` (+ `workflow_dispatch` build-only dry run); `contents: write` is the only write permission. Jobs `dmg`/`nsis`/`appimage` each: **tag ↔ package.json version gate** (mismatch → hard error), build + pyserver + electron-builder `--publish never`, then tag-only upload: `gh release view` → `gh release upload --clobber`, else `gh release create --generate-notes --latest` (`.github/workflows/release.yml:10-182`).

## Release runbook (verified 2026-09-23)

1. Align versions in `backend/pyproject.toml`, `backend/uv.lock`, `package.json`; commit `chore: release vX.Y.Z`; push main.
2. `git tag vX.Y.Z && git push origin vX.Y.Z` — the workflow builds and creates the release; the detailed body is set afterwards with `gh release edit vX.Y.Z --notes-file` (only ONE channel creates the release — never also `gh release create`).
3. Verify assets via `gh api repos/:owner/:repo/releases/ID/assets` — the `/releases` collection can list `assets: []` for minutes (eventual consistency); never re-upload based on that view.
4. Versioning = impact-based semver: additive refinements (settings panel, chat markdown) are PATCH; new capability areas are MINOR.

## Edge cases

- `dev` script needs `uv` on PATH and `backend/.venv` present (created by `uv sync`).
- Windows always kills via `/api/shutdown` + SIGKILL timer (no graceful SIGTERM semantics).
- The release gate makes a wrong version bump fail fast on all three runners.

## Dependencies

- Serves the frontend ([08-frontend-app.md](meccanismi/08-frontend-app.md)); sidecar exposes the API ([05-api-server.md](meccanismi/05-api-server.md)) and owns the LLM backend ([07-setup-wizard.md](meccanismi/07-setup-wizard.md)).

## Files covered

- `desktop/main.ts`
- `scripts/build-pyserver.mjs`
- `electron-builder.yml`, `vite.config.ts`, `package.json`
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`

## Studio

1. Why does a spawn failure need a separate `error` handler from `exit`?
2. Why are fixtures extraResources instead of PyInstaller `--add-data`?
3. What happens if you push a tag whose version doesn't match package.json — on which job does it fail?
