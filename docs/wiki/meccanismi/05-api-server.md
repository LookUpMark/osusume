# 05 — API server & configuration

**Abstract.** The FastAPI surface: contract-locked endpoints with JS parsing semantics, a canonical error-code map, DNS-rebinding Host allowlist, SPA fallback, graceful shutdown, the settings/config store, and the local-mode fixtures switch.

## Purpose

Serve the React UI and any API client exactly like the original Hono server did: same paths, same bodies, same error codes, same static/SPA behavior.

## Endpoints (`backend/app/api/routes.py`, all under `/api`)

- `GET /health` (`routes.py:119-130`) — throttled `ensure_llm_server()` re-kick + llm/local state.
- `GET /app-update`, `POST /local-mode` (`routes.py:133-145`), `GET /config` (disclosure-minimal, no baseUrl) (`routes.py:149-151`).
- `GET|PATCH /settings`, `GET /llm/models` (`routes.py:182-218`) — settings UI backend (see below).
- `GET /profile/{username}` (`routes.py:241-248`), `POST /recommend` (`routes.py:251-263`), `POST /explain` (`routes.py:266-280`), `POST /lookup` (`routes.py:283-296`), `POST /chat` (`routes.py:351-366`, details in [06-llm-layer.md](meccanismi/06-llm-layer.md)), `POST /shutdown` (`routes.py:369-383`).

## Request parsing parity

- `_js_body` (`routes.py:43-53`): strict `json.loads` with `parse_constant` rejecting NaN/Infinity; empty/invalid → `None`; a non-dict body flows to the endpoint's TS-shaped navigation (null body → `username ""` → `invalid_username`).
- `USERNAME_RE = \A[A-Za-z0-9_-]{1,32}\Z` (`routes.py:32-34`) — `\A\Z` because Python `$` accepts a trailing `\n`.
- `_lang` (`routes.py:56-58`): anything not in `{en, it}` (including non-strings) silently defaults to `"en"`.
- `/lookup` q bounds use `js_trim` + `js_length` (2..80 UTF-16 units) (`routes.py:290-291`).
- `/chat` history: `_normalize_history` clamps each turn to 4000 chars (never drops mid-conversation context), keeps valid user/assistant turns, last 12 (`routes.py:310-319`); `chat_extra_ids` takes numeric ids not in the recos, first 5, order preserved (`routes.py:322-330`).

## Errors (`backend/app/core/errors.py`)

- `ApiError(status, code, message)` (`errors.py:25-32`) — the snake_case codes ARE the error UI.
- `RequestValidationError` → 400 `invalid_request`, never FastAPI's 422 detail (`errors.py:57-60`).
- 405 → TS-shaped fallback: GET/HEAD on a known API path serve the SPA index (`_spa_index()`, DIST_DIR-aware, `errors.py:18-22,62-73`); other methods → plain-text 404.
- Route-level `AniListError` 404 → `user_not_found`, else `anilist_error` 502 (`routes.py:69-75`).

## Middleware & app shell

- `HostAllowlistMiddleware` (`backend/app/core/middleware.py:20-43`): guards `/api*` against DNS rebinding; allowlist `{127.0.0.1, localhost, ::1}`; port stripped with the same two-pass regex as the TS (quirk preserved: bare `::1` is out, `::1:3000` is in); violation → 403.
- `create_app` (`backend/app/main.py:43-60`): lifespan runs `cleanup_on_exit()` + `ensure_llm_server()`; docs/openapi disabled; `app.frontend("/", directory=dist, fallback="index.html")` mounted AFTER `/api` (Accept-negotiated: browser → index.html, API client → 404 `not_found`).
- Shutdown: `/api/shutdown` answers `{"ok":true}` first, then sets `SERVER.should_exit` after 0.2 s; `run_dev.py` sets `timeout_graceful_shutdown=3` so the process exits ~3 s even with a hung LLM call (`backend/run_dev.py:16-29`).
- Local fallback: `with_local_fallback` (`routes.py:78-99`) — AniList failure (≠404) + auto on + fixtures present → flip to local mode, retry once; a 404 is never masked.

## Configuration (`backend/app/core/config.py`)

- Precedence everywhere: **env > data/config.json > hardcoded default** (`config.py:1-4`); minimal `.env` loader at import, existing env wins (`config.py:17-31`).
- Paths: `DATA_DIR` (`ALR_DATA_DIR` or repo `data/`), `CONFIG_PATH`, `CACHE_DIR` (`config.py:101-103,182`).
- `update_config` (`config.py:119-140`): atomic merge-patch (`.tmp` + `os.replace`); a `None` value DELETES the key.
- Readers: `configured_llm_model` (env `LLM_MODEL` → file), `llm_model()` default `"qwen3:8b"`, `llm_base_url()` (env → file → `http://127.0.0.1:11434/v1`, read per call), `system_prompt_extra()` (settings UI custom prompt), `has_custom_env()` (mere presence of `LLM_BASE_URL`) (`config.py:143-176`).

## Settings endpoints (`routes.py:154-218`)

- `GET /settings`: values from the FILE (what the form edits) with `envOverride` flag when env vars win at runtime.
- `PATCH /settings`: absent key = untouched (`model_fields_set`); baseUrl trimmed + `https?://` + ≤200; model ≤120, `""` → back to server default; `systemPromptExtra` ≤4000, blank → deleted; violations → 400 `invalid_request`; one atomic write.
- `GET /llm/models`: live `GET {baseUrl}/models` proxied; unreachable → 503 `llm_unavailable`.

## Dependencies

- Domain pipeline for data ([03](meccanismi/03-recommendation-pipeline.md)), LLM layer ([06](meccanismi/06-llm-layer.md)), setup wizard ([07-setup-wizard.md](meccanismi/07-setup-wizard.md)).
- JS-parity helpers for parsing/validation ([04-js-parity-golden.md](meccanismi/04-js-parity-golden.md)).
- AniList adapter error types ([01-anilist-adapter.md](meccanismi/01-anilist-adapter.md)); frontend consumers in [08-frontend-app.md](meccanismi/08-frontend-app.md).

## Files covered

- `backend/app/api/routes.py`
- `backend/app/core/errors.py`
- `backend/app/core/middleware.py`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `backend/run_dev.py`
- `backend/pyserver_main.py`

## Studio

1. Why does a junk JSON body on `/recommend` return `invalid_username` and not `invalid_request`?
2. What contract does `/api/shutdown` have with the Electron host, and what breaks without `timeout_graceful_shutdown`?
3. Why does `GET /settings` return file values while `GET /config` returns the effective model?
