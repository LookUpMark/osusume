# 11 — AniList OAuth & watchlist

**Abstract.** Authorization-code grant against AniList with a fixed-port loopback callback listener that lives only for the flow; the token stays server-side, quietly attaching to list fetches and powering a one-tap "add to plan" from the detail dialog.

## Purpose

Read private lists (the app currently shows only what AniList serves anonymously) and write back — adding a recommended title to the user's PLANNING list — without a cloud, an account system, or the token ever reaching the frontend.

## How it works (`backend/app/adapters/anilist/auth.py`)

1. **Setup (user action)**: register an app on anilist.co/settings/developer with redirect URI `http://127.0.0.1:47321/callback` (`auth.py:34-40`, port overridable via `ANILIST_OAUTH_CALLBACK_PORT` for tests). Client id/secret are stored in config via `PATCH /api/auth/anilist` (`routes.py`, validated: numeric id, 8..200 secret; the secret never round-trips in any response).
2. **Connect**: `POST /auth/anilist/start` → `start_flow()` (`auth.py:96-127`) binds a temporary listener on `127.0.0.1:47321` (busy port → 409 `oauth_port_busy`; already pending → 409 `oauth_busy`) and returns the authorize URL with a single-use `state` (`secrets.token_hex(16)`).
3. **Callback**: the system browser lands on the loopback listener (`_on_callback`, `auth.py:160-196`). Path/state validated with `hmac.compare_digest` (the listener is a raw socket OUTSIDE the Host-allowlist middleware — `state` is the CSRF defense; no Origin/Referer checks exist in the repo). Rejected callbacks answer 404 and the listener keeps waiting; only a terminal outcome closes it. The listener is timeout-guarded (600 s → flow error).
4. **Exchange**: `exchange_and_store` (`auth.py:198-243`) POSTs code+credentials to the token endpoint (`TOKEN_URL`, env-overridable for tests) → `{access_token, expires_in}`, then `gql_uncached(VIEWER_QUERY)` for the identity, then atomic `update_config({anilistToken, anilistUser, anilistTokenAt, anilistTokenExpires})`. The browser gets a minimal "you can close this window" page.
5. **Use**: `token_for(username)` (`auth.py:63-70`) returns the token only when the requested list belongs to the connected user; `fetch_user_list` attaches it (`media.py:98-106`) — private entries included, with the salted cache key `auth|<hash>|` (see [01-anilist-adapter.md](meccanismi/01-anilist-adapter.md)). AniList tokens last 1 year with NO refresh: an expiry surfaces as AniList 401 → `anilist_auth` ([05-api-server.md](meccanismi/05-api-server.md)) → "reconnect from Settings".
6. **Watchlist**: `POST /api/watchlist {mediaId}` runs `SAVE_PLANNING_MUTATION` through `gql_uncached` (never cached); `GET /watchlist/status` reads the current entry status for the dialog chip. The frontend only exposes these when `auth.authenticated` ([08-frontend-app.md](meccanismi/08-frontend-app.md)).
7. **Disconnect** clears token/user (credentials survive), resets the flow state.

## Data & states

- Flow state machine `idle | pending | ok | error` (module-level `_flow` + listener/task handles); `/api/auth/anilist` exposes `configured, authenticated, username, flow, flowError, redirectUri, tokenExpiresAt` — never the token or secret.
- config keys: `anilistClientId`, `anilistClientSecret`, `anilistToken`, `anilistUser`, `anilistTokenAt`, `anilistTokenExpires`. Env overrides: `ANILIST_TOKEN`, `ANILIST_CLIENT_ID/SECRET` (precedence like every other config).

## Edge cases

- Port busy / double start → 409 with distinct codes (`oauth_port_busy` / `oauth_busy`).
- Wrong `state` → 404, flow stays pending (a browser retry still works).
- Exchange failure (bad code, AniList down) → listener answers 502, flow `error`; generic exceptions are caught so the connection never hangs.
- Local (fixture) mode ignores the token entirely — fixtures branch first.
- Without credentials the whole feature is invisible: the login modal is byte-identical to the username-only one (documented degraded gate).

## Dependencies

- AniList client for authenticated GraphQL ([01-anilist-adapter.md](meccanismi/01-anilist-adapter.md)); config store ([05-api-server.md](meccanismi/05-api-server.md)); the pipeline's list phase inherits the token for free ([03-recommendation-pipeline.md](meccanismi/03-recommendation-pipeline.md)); settings UI + login modal + detail dialog ([08-frontend-app.md](meccanismi/08-frontend-app.md)).

## Files covered

- `backend/app/adapters/anilist/auth.py`
- `frontend/src/components/AniListAuth.tsx`

## Studio

1. Why is the callback a raw socket instead of a FastAPI route, and what protection replaces the Host allowlist?
2. Why does the cache key need the token hash if queries are identical?
3. What is the failure UX when the token expires after a year, and which code carries it?
