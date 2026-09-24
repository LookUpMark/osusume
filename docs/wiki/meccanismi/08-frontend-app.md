# 08 — Frontend app & views

**Abstract.** React 19 SPA: an app shell gating on setup status, a language that follows the OS, health polling, a fake login, the recommendation run, and seven views fed by pure list-logic helpers that `node --test` can exercise without a DOM.

## Purpose

Render the taste profile, recommendations, gems, chat, and settings — all state from the API, all pure logic isolated in `frontend/src/lib/logic/` (testable, OpenDesign-restylable).

## App shell (`frontend/src/App.tsx`)

- Boot: `lang` via `detectLang(localStorage["lang"], navigator.language)` (`App.tsx:44-46` — saved preference wins, OS locale `it-*` → Italian); `view` from `localStorage["alr-view"]` validated against `VIEW_ORDER` (`App.tsx:47-50`, `frontend/src/views/index.ts:1-15`).
- `fetchSetupStatus()` gates the render: null → splash, "error" → retry page, `needsSetup && !customEnv` → `<SetupWizard>` (`App.tsx:254-286`).
- Fake login: stored username auto-runs once (`App.tsx:81-88`); `login()` persists only on success.
- Health: `/api/health` on mount + every 60 s (`App.tsx:120-136`) — feeds the LLM chip and the chat lock.
- Two worlds: `media` state (`localStorage["alr-media"]`, validated) drives the ANIME/MANGA switch in the Rail (`media-seg`); switching resets the format/genre filters and re-runs `run()` — every request (stream, lookup, chat, explain) carries `mediaType`. Format chips use a per-type label map (`FORMAT_LABEL` in `App.tsx`).
- `run(username)` (`App.tsx`): reset state (closing any live stream via `esRef`) → `fetchProfile` (fast-fail JSON) → `streamRecommend(username, lang, setPhase, media)` — the SSE stream of [05-api-server.md](meccanismi/05-api-server.md) whose `done` resolves with the same `RecoResult`; `finally` closes the stream and `refreshHealth()` (the server may auto-switch to local mode mid-request). Language switch re-runs it — why/narrations are per-language.
- Progress UI: `phase` state holds the 9 stream phases; the loading branch renders `<Progress>` (label + `n/9` bar, `frontend/src/components/Progress.tsx`; keys `phaseKey`/`phaseStep` in `frontend/src/lib/logic/progress.ts`). Cache hit / local mode = single flush → renders as done, no artifacts.
- Chat extras: `onOpenChat(r)` adds looked-up titles to `extraRecos` (dedup) and opens the dialog; `onWhy` folds fetched explanations back into the lists.
- AniList OAuth: `auth` state (fetched on mount, polled 1500 ms while `flow === "pending"`), `startOauth` opens the authorize URL; the login modal grows a connect button ONLY when `auth.configured` (`LoginModal.tsx` — `oauthConfigured/oauthPending/onOauth`); settings hosts `<AniListAuthPanel>` (`frontend/src/components/AniListAuth.tsx`); the detail dialog gets `watchStatus/watchBusy/onAddToWatchlist` (fetched on dialog open, PLANNING after add) — the full flow is [11-anilist-oauth.md](meccanismi/11-anilist-oauth.md).

## Data flow (`frontend/src/lib/api.ts` + `lib/logic/`)

- All fetchers share `json()`: non-ok → `Error(body.error)` (the snake_case code travels in the message) (`api.ts:3-7`).
- `postChat(username, lang, messages, extra)` → `{reply, cards?}`; `ChatMsg.cards` is client-only — `_normalize_history` strips it from the wire (`api.ts:63-77`).
- `patchSettings` — undefined fields dropped by `JSON.stringify`; `model: ""` reverts to the server default (`api.ts:117-136`).
- `frontend/src/lib/logic/recos.ts`: `applyFilters` (gemsOnly → format → genre; sorts: `gem` by `gemRank`, `affinity` desc, default `final` = server `mmRank` order) (`recos.ts:19-29`); `gemsOf`, `topGenres`, `heroPick`, `cardToReco` (`recos.ts:59-83` — pool hit returns the real object, miss builds a neutral shell whose empty `why` triggers on-demand explain in the dialog).
- `frontend/src/lib/logic/display.ts` — CONTRACT: OpenDesign may regenerate markup, never the formulas; `score110 = Math.round(final*100)` always "/110" (`display.ts:1-7`).
- `frontend/src/lib/logic/errors.ts`: `user_not_found` / `anilist_error` / generic mapping (`errors.ts:4-9`).
- `frontend/src/lib/logic/lang.ts`: `detectLang` (`lang.ts:5-6`).

## Components

- `SetupWizard.tsx`: server-truth step machine (done → 3, active job → 2, else 1), 1500 ms status polling with stale-drop (`SetupWizard.tsx:37-47`); oMLX radios + inline download %, LM Studio path with `install-cli`, auto-finish guarded by `finishedRef` so `install-cli` (model null) never completes setup (`SetupWizard.tsx:99-120`).
- `ChatPanel.tsx`: see [09-chat-ui.md](meccanismi/09-chat-ui.md).
- `DetailDialog.tsx`: on-demand explain (skips when already `llm`, `alive` cleanup flag), breakdown bars, "similar" → affinity sort (`DetailDialog.tsx:66-83,167-169`).
- `Topbar.tsx`: anime search ≥2 chars → `/api/lookup` → `listbox` dropdown (outside-click/Escape close) → `onOpen` (`Topbar.tsx:28-43,84-101`).
- `MediaCard` / `Hero` / `Carousel` / `Rail` / `ProfileView` / `AvoidList` / `LoginModal` / `LlmSettings` — presentational + settings form (presets LM Studio/Ollama/oMLX, live model picker, custom prompt textarea, `envOverride` warning) (`frontend/src/components/LlmSettings.tsx:34-121`).
- `main.tsx`: ErrorBoundary fallback; tokens.css → styles.css import order (`frontend/src/main.tsx:5-20`).

## Design tokens

`frontend/src/design-system/tokens.css` — "Seanime" dark theme: `--bg #121212`, `--surface/-2`, `--accent #9f92ff`, radii `--r-sm/md/lg`, Geist fonts, `.btn` primitives, `.chip-badge`, focus-visible ring, reduced-motion kill (`tokens.css:2-77`). Chat styles at `frontend/src/styles.css:549-576`.

## i18n

`frontend/src/lib/i18n.ts`: flat `en`/`it` dicts; `tr(lang, key, params)` falls back en → key, `{placeholder}` replaced (`i18n.ts:365-369`); badge labels computed via `badgeKey`.

## Edge cases

- Stale async responses dropped via request counters (wizard polling).
- `llmOn === false` disables chat input with an honest empty state (no silent dead button).
- `prefers-reduced-motion` skips the view cross-fade (`App.tsx:108-118`).

## Dependencies

- API endpoints ([05-api-server.md](meccanismi/05-api-server.md)); setup flows ([07-setup-wizard.md](meccanismi/07-setup-wizard.md)); chat mechanics ([09-chat-ui.md](meccanismi/09-chat-ui.md)); packaging of the whole shell ([10-desktop-packaging.md](meccanismi/10-desktop-packaging.md)).

## Files covered

- `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/src/views/index.ts`
- `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/i18n.ts`
- `frontend/src/lib/logic/recos.ts`, `display.ts`, `errors.ts`, `lang.ts`, `progress.ts`
- `frontend/src/components/*.tsx` (except ChatPanel/Markdown → [09], AniListAuth → [11])
- `frontend/src/design-system/tokens.css`, `frontend/src/styles.css`

## Studio

1. Why does a language switch re-run the whole recommendation request?
2. What does `cardToReco`'s neutral shell lose, and how does the dialog recover?
3. Why is `score110` marked as a contract?
