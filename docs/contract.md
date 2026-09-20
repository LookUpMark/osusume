# Contratto HTTP congelato (P0 migrazione Python/FastAPI)

Fonte: `src/server/api.ts`, `src/server/index.ts`, `src/server/setup.ts`, `src/server/update.ts`,
`src/shared/types.ts`, `frontend/src/lib/api.ts`. Questo documento DESCRIVE il comportamento del backend
TypeScript attuale — non lo specifica ex novo. La porta Python deve produrre, a parità di input,
gli stessi status e gli stessi body JSON (golden master: `tests/golden/record.mjs`).

Convenzioni comuni a tutti gli endpoint `/api/*`:

- Tutte le risposte sono JSON (`application/json`). Il body di errore è `{"error": "<code>"}`
  (unico campo extra ammesso: `message` per `anilist_error`); eccezione: `install-cli`,
  `download` e `omlx-download` sotto `/api/setup/*` mettono in `error` messaggi arbitrari
  (es. `busy`, testo dell'errore installatore).
- **Middleware Host** (primo middleware, copre tutto `/api/*`): prende `host` dall'header
  `Host` (default `""`), strip della porta con `host.replace(/:\d+$/, "")` e strip delle
  parentesi `[`/`]`; se il risultato non è in `{127.0.0.1, localhost, ::1}` → `403 {"error":"forbidden"}`.
- **Lang**: body `lang` ammesso solo se in `{"en","it"}` (whitelist), altrimenti default `"en"`.
- **USERNAME_RE**: `^[A-Za-z0-9_-]{1,32}$`. Fallisce → `400 {"error":"invalid_username"}`.
- **Auto-fallback locale** (`withLocalFallback`, profile/recommend/explain/lookup/chat):
  su `AniListError` con `status !== 404`, se auto-fallback on E local-mode off E fixture su disco
  → attiva local mode e ritenta una volta; se il retry fallisce viene riportato l'errore AniList
  originale. Il 404 è "utente inesistente" e non viene mai mascherato.
- **Fixture mode** (`ANILIST_FIXTURES` settato): la lista utente è letta dai file fixture per
  QUALUNQUE username valido — lo username è ignorato e `user_not_found` è irraggiungibile.
  I golden di `tests/golden/` sono registrati in fixture mode: non contengono alcun 404
  (per esercitarlo serve AniList live).

## Mappa errori canonica

| code | status | quando |
|---|---|---|
| `invalid_request` | 400 | body JSON assente/non decodificabile, campi mancanti o di tipo errato, `q` fuori da 2..80, `ids` vuoto, history chat vuota o con ultima mossa non `user`, `auto` non booleano in `/local-mode`, setup senza `model` |
| `invalid_username` | 400 | username fuori da `^[A-Za-z0-9_-]{1,32}$` (profile, recommend, chat) |
| `forbidden` | 403 | header `Host` fuori allowlist loopback |
| `user_not_found` | 404 | AniList risponde 404 per la lista utente |
| `anilist_error` | 502 | errore AniList diverso da 404; body `{"error":"anilist_error","message":"..."}` |
| `llm_unavailable` | 503 | solo `/api/chat`: il backend LLM è irraggiungibile / errore LLM |
| `internal_error` | 500 | qualsiasi errore non classificato |

Setup (route `/api/setup/*`), errori specifici: `400 {"error":"invalid_model"}` (modello non
conforme a `^[A-Za-z0-9][A-Za-z0-9._/-]*$` o mancante), `400 {"error":"invalid_url"}`,
`400 {"error":"lms_missing"}`, `400 {"error":"omlx_missing"}`, `400 {"error":"unsupported_repo"}`,
`409 {"error":"busy"}` (job di download già attivo), `409 {"error":"<messaggio>"}` da
`install-cli`, `500 {"error":"reset_failed"}` (config.json non cancellabile).

## Tabella endpoint

| # | Metodo+Path | Request | Response 2xx | Errori |
|---|---|---|---|---|
| 1 | GET `/api/health` | — | `{ok:true, llm:{model:string, enabled:bool, state:"up"\|"starting"\|"off"}, local:{on:bool, available:bool, auto:bool}}` | — |
| 2 | GET `/api/app-update?fresh=1` | query `fresh` opzionale (`"1"` forza il check) | `AppUpdate` `{current:string\|null, latest:string\|null, url:string\|null, available:bool}` — senza `APP_VERSION` in env: tutti i campi `null`/`false` | — |
| 3 | POST `/api/local-mode` | `{auto:bool, local?:bool}` (`local===false` forza il retry live) | `{ok:true, local:{on,available,auto}}` | 400 `invalid_request` |
| 4 | GET `/api/config` | — | `{llm:{model:string}}` (mai baseUrl: disclosure-minimal) | — |
| 5 | GET `/api/profile/:username` | param path `username` | `{profile: TasteProfile}` | 400 `invalid_username`, 404 `user_not_found`, 502 `anilist_error`, 500 |
| 6 | POST `/api/recommend` | `{username:string, lang?:Lang}` | `RecoResult` | 400 `invalid_username`, 404/502/500 (fallback locale) |
| 7 | POST `/api/explain` | `{username:string, ids:number[], lang?:Lang}` | `{explanations: [{id:number, text:string, source:"llm"\|"cache"\|"fallback"}]}` (ordine = ordine subset raccomandazioni) | 400 `invalid_request`, 404/502/500 |
| 8 | POST `/api/lookup` | `{username:string, q:string, lang?:Lang}` (`q.trim()`, lunghezza 2..80) | `{recos: ScoredReco[]}` (ordine = ranking della ricerca) | 400 `invalid_request`, 404/502/500 |
| 9 | POST `/api/chat` | `{username:string, lang?:Lang, extra?:number[], messages:[{role:"user"\|"assistant", content:string}]}` (storia normalizzata: turni validi non vuoti, content clampato a 4000 char, ultime 12) | `{reply:string}` | 400 `invalid_request`/`invalid_username`, 503 `llm_unavailable`, 404/502/500 |
| 10 | POST `/api/shutdown` | — | `{ok:true}` e `process.exit(0)` dopo 200ms | — |
| 11 | GET `/api/setup/status` | — | `SetupStatus` (shape sotto) | — |
| 12 | POST `/api/setup/ack` | `{}` | `{ok:true}` (persistisce `setupDone:true` + `setupVersion`) | — |
| 13 | POST `/api/setup/install-cli` | `{}` | `{ok:true}` | 409 `{error}` |
| 14 | POST `/api/setup/download` | `{model:string}` | `{ok:true}` | 400 `invalid_request`/`invalid_model`, 409 `busy` |
| 15 | POST `/api/setup/finish` | `{model?, baseUrl?, backend?: "skipped"\|"omlx"}` | `{ok:true}` | 400 `invalid_request`/`invalid_model`/`invalid_url`/`omlx_missing`/`lms_missing` |
| 16 | POST `/api/setup/omlx-download` | `{model:string}` | `{ok:true}` | 400 `invalid_request`/`unsupported_repo`, 409 `busy` |
| 17 | POST `/api/setup/cancel` | `{}` | `{ok:true}` | — |
| 18 | POST `/api/setup/reset` | `{}` | `{ok:true}` (cancella config + stato job) | 500 `reset_failed` |

Chi non ha endpoint dedicati ma solo shape: `GET /api/profile/:username` applica
`encodeURIComponent` lato client (`frontend/src/lib/api.ts`); il server non decodifica nomi con caratteri
fuori whitelist (già rifiutati da `USERNAME_RE`).

## Static/SPA — deviazione del port Python (P1)

Il backend TypeScript in produzione serviva `dist/index.html` a prescindere dall'header `Accept`
(serveStatic + fallback). Il port Python/FastAPI (`app.frontend(fallback="index.html")`) negozia
sull'`Accept` per un `GET` su un path **non-API** non noto:

- `Accept: text/html` (browser) → `200 index.html` (SPA fallback, invariato);
- `Accept` non-HTML (es. `*/*`, client API) → `404 {"error":"not_found"}`.

`not_found` non esiste nella mappa errori TS: è un codice del solo port, deviazione
migliorativa (i client API ricevono un 404 JSON invece di HTML). Le richieste `/api/*`
sono sempre gestite prima del static.

## Shape congelati (`src/shared/types.ts`)

```ts
type Lang = "en" | "it";

interface ListEntry {
  mediaId: number;
  status: "CURRENT" | "PLANNING" | "COMPLETED" | "DROPPED" | "PAUSED" | "REPEATING";
  score: number;      // normalizzato 0-100 (0 = non votato)
  repeat: number;
  updatedAt?: number; // unix seconds
  title: string;
}

interface MediaTagLite { name: string; rank: number; isSpoiler: boolean }
interface MediaRelationLite { id: number; relationType: string }

interface MediaLite {
  id: number;
  title: string;
  format: string | null;
  seasonYear: number | null;
  genres: string[];
  tags: MediaTagLite[];
  studio: string | null;
  averageScore: number | null;
  popularity: number;
  coverImage: string | null;
  coverColor: string | null;
  siteUrl: string | null;
  description: string | null;   // troncata a 500 char
  relations: MediaRelationLite[];
}

type Dim = "tag" | "genre" | "studio" | "era";
interface DimValue { dim: Dim; value: string; aff: number; support: number; examples: string[] }

interface TasteProfile {
  userName: string;
  meanScore: number;
  scoredCount: number;
  confidence: "ok" | "low";
  counts: Record<ListStatus, number>;
  loved: DimValue[];
  disliked: DimValue[];
  hash: string;   // sha256 della lista (ids+scores+statuses)
}

type Badge = "NEXT_STEP" | "ENTRY_POINT" | "HIDDEN_GEM" | "SPIN_OFF";

interface ScoredReco {
  media: MediaLite;
  final: number;                 // 0..1.1 (UI x100)
  breakdown: { affinity: number; quality: number; community: number; mood?: number };
  badges: Badge[];
  rootId: number | null;
  groupSize: number;
  why: string;
  links?: { title: string; shared: string[] }[];
  mmRank?: number;               // posizione default (MMR), 1-based
}

interface WhyNot { media: MediaLite; reason: string }
interface RecoResult { profile: TasteProfile; recos: ScoredReco[]; avoided: WhyNot[] }
interface Explanation { text: string; source: "llm" | "cache" | "fallback" }
```

### SetupStatus (GET `/api/setup/status`)

```ts
interface SetupHardware { os: "mac" | "win" | "linux"; chip: string; ramGb: number; appleSilicon: boolean }

interface SetupStatus {
  setupDone: boolean;
  needsSetup: boolean;          // true anche dopo update (setupVersion mismatch)
  customEnv: boolean;           // true se LLM_BASE_URL è in env
  hardware: SetupHardware;
  suggested: {
    model: string; sizeGb: number;
    mlx: { model: string; sizeGb: number } | null;
    mlxLms: { model: string; sizeGb: number } | null;
  };
  lms: { installed: boolean; path: null; serverUp: boolean };  // `path` è SEMPRE null (disclosure-minimal)
  omlx: { installed: boolean; serverUp: boolean; models: string[];
          downloadable: { model: string; sizeGb: number }[] };
  downloadedModels: string[];
  job: { state: "idle" | "installing-cli" | "downloading" | "done" | "error";
         model: string | null; logTail: string; error?: string; bytesDone?: number; totalBytes?: number };
  llm: { state: "up" | "starting" | "off" };
}
```

## Server bootstrap, static e SPA (`src/server/index.ts`)

- `PORT` da env (default `3000`), `HOST` da env (default `127.0.0.1`; i container impostano `HOST=0.0.0.0`,
  la allowlist Host su `/api` resta il guard).
- `NODE_ENV !== "production"`: `/api/*` via Hono (`getRequestListener`), **tutto il resto** via
  middleware Vite in modalità `appType:"spa"` (stesso processo).
- `NODE_ENV === "production"`: `serveStatic({ root: "./dist" })` per ogni path, poi fallback
  `serveStatic({ path: "./dist/index.html" })` (**SPA fallback** su qualunque route non-static).
- Al bootstrap: `ensureLlmServer()` fire-and-forget (no-op se `LLM_BASE_URL` in env o wizard non
  completato) e `cleanupOnExit()` (SIGINT/SIGTERM fermano il backend LLM).
- Log di avvio su stdout, esattamente: ``osusume on http://127.0.0.1:${PORT}``.

## Ambienti letti all'avvio (contratto di configurazione)

`PORT`, `HOST`, `NODE_ENV`, `ANILIST_ENDPOINT` (default `https://graphql.anilist.co`),
`ANILIST_FIXTURES` (attiva e blocca la local mode), `RATE_PER_MIN` (default 25),
`APP_VERSION` (solo pacchetto Electron), `LLM_MODEL` / `LLM_BASE_URL` / `LLM_TIMEOUT_MS` /
`LLM_MAX_TOKENS` / `LLM_RETRY_TOKENS` / `LLM_API_KEY`, `LMSTUDIO_BASE_URL` (default
`http://127.0.0.1:1234/v1`), `OMLX_BASE_URL`, `OMLX_BIN`, `OMLX_API_KEY`, `LMS_PATH`,
`ALR_DATA_DIR` (default `<repo>/data/`), `CONFIG_PATH` (default `<ALR_DATA_DIR>/config.json`),
`CACHE_DIR` (default `<ALR_DATA_DIR>/cache`).

Costanti NON configurabili via env (`src/server/config.ts`): `CACHE_TTL_LIST_MS` = 1h,
`CACHE_TTL_MEDIA_MS` = 7d, `CACHE_TTL_EXPL_MS` = 7d (cache su disco AniList/spiegazioni).

`config.ts` carica un eventuale `.env` alla radice repo (chiavi `^[A-Z_]+$`,
env già presente vince) — il golden master (`tests/golden/record.mjs`) non lo tocca: nessun `.env`
presente e tutte le variabili critiche sono passate esplicite.
