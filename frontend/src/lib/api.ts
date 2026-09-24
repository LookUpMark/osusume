import type { ChatCard, Explanation, Lang, RecoResult, SetupStatus, TasteProfile } from "../lib/types.ts";
import type { StreamHandle, StreamPhase } from "./logic/progress.ts";

const json = async (res: Response): Promise<any> => {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `HTTP ${res.status}`);
  return body;
};

export interface LocalMode {
  on: boolean;
  available: boolean;
  auto: boolean;
}

export const fetchHealth = (): Promise<{
  ok: boolean;
  llm: { enabled: boolean; model: string; state?: string };
  local: LocalMode;
}> => fetch("/api/health").then(json);

/** UI toggle for auto-fallback to local fixture data. */
export const postLocalMode = (
  auto: boolean,
  local?: boolean,
): Promise<{ ok: boolean; local: LocalMode }> =>
  fetch("/api/local-mode", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(local === undefined ? { auto } : { auto, local }),
  }).then(json);

export interface AppUpdate {
  current: string | null;
  latest: string | null;
  url: string | null;
  available: boolean;
}

export const fetchAppUpdate = (fresh = false): Promise<AppUpdate> =>
  fetch(`/api/app-update${fresh ? "?fresh=1" : ""}`).then(json);

export const fetchProfile = (username: string): Promise<{ profile: TasteProfile }> =>
  fetch(`/api/profile/${encodeURIComponent(username)}`).then(json);

export const fetchRecommend = (username: string, lang: Lang): Promise<RecoResult> =>
  fetch("/api/recommend", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, lang }),
  }).then(json);

/** Streaming generation progress (SSE). `done` resolves with the same payload
 *  POST /api/recommend returns; `close()` must be called on completion/error —
 *  EventSource would otherwise auto-reconnect into a fresh run. */
export const streamRecommend = (
  username: string,
  lang: Lang,
  onPhase: (phase: StreamPhase) => void,
): StreamHandle => {
  const es = new EventSource(`/api/recommend/stream?username=${encodeURIComponent(username)}&lang=${lang}`);
  let closed = false;
  let rejectFn!: (e: Error) => void;
  const done = new Promise<RecoResult>((resolve, reject) => {
    rejectFn = reject;
    es.addEventListener("phase", (ev) => {
      const phase = (ev as MessageEvent).data ? (JSON.parse((ev as MessageEvent).data as string).phase as StreamPhase) : "";
      if (phase) onPhase(phase);
    });
    es.addEventListener("done", (ev) => {
      closed = true;
      es.close();
      resolve(JSON.parse((ev as MessageEvent).data as string) as RecoResult);
    });
    es.addEventListener("error", (ev) => {
      // a named server event, NOT the connection failure (that fires plain "error" too)
      const code = (ev as MessageEvent).data ? (JSON.parse((ev as MessageEvent).data as string).error as string) : null;
      if (code) {
        closed = true;
        es.close();
        reject(new Error(code));
      }
    });
    es.onerror = () => {
      // connection-level failure (or server closed early); if we are already
      // finished this is the browser complaining after close() — ignore
      if (!closed && es.readyState === EventSource.CLOSED) {
        closed = true;
        reject(new Error("errGeneric"));
      }
    };
  });
  return {
    done,
    close: () => {
      if (!closed) {
        closed = true;
        es.close();
      }
    },
  };
};

export const fetchExplain = (
  username: string,
  ids: number[],
  lang: Lang,
): Promise<{ explanations: (Explanation & { id: number })[] }> =>
  fetch("/api/explain", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, ids, lang }),
  }).then(json);

// cards is client-only: _normalize_history (routes.py) strips it from the wire,
// so past assistant turns reach the model as plain role/content again
export type ChatMsg = { role: "user" | "assistant"; content: string; cards?: ChatCard[] };

export const postChat = (
  username: string,
  lang: Lang,
  messages: ChatMsg[],
  extra: number[] = [],
): Promise<{ reply: string; cards?: ChatCard[] }> =>
  fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, lang, messages, extra }),
  }).then(json);

/** Search any title, scored against the user's taste (chat lookup). */
export const lookupMedia = (
  username: string,
  q: string,
  lang: Lang,
): Promise<{ recos: import("../lib/types.ts").ScoredReco[] }> =>
  fetch("/api/lookup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, q, lang }),
  }).then(json);

const isSetupStatus = (b: unknown): b is SetupStatus =>
  !!b && typeof b === "object" &&
  typeof (b as SetupStatus).setupDone === "boolean" &&
  typeof (b as SetupStatus).needsSetup === "boolean" &&
  !!(b as SetupStatus).hardware && !!(b as SetupStatus).job &&
  Array.isArray((b as SetupStatus).downloadedModels);

export const fetchSetupStatus = (): Promise<SetupStatus> =>
  fetch("/api/setup/status")
    .then(json)
    .then((b) => {
      if (!isSetupStatus(b)) throw new Error("invalid /api/setup/status payload");
      return b;
    });

/** Errors arrive as thrown Error (server code in message) — {ok:true} on success. */
export const postSetup = (
  action: "install-cli" | "download" | "finish" | "reset" | "omlx-download" | "cancel" | "ack",
  body?: object,
): Promise<{ ok: boolean }> =>
  fetch(`/api/setup/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  }).then(json);

export interface Settings {
  baseUrl: string;
  model: string | null; // null = server fallback default
  defaultModel: string;
  systemPromptExtra: string;
  envOverride: boolean; // LLM_BASE_URL/LLM_MODEL env win over these settings
}

export const fetchSettings = (): Promise<Settings> => fetch("/api/settings").then(json);

/** Key present = change; key absent = untouched. model:"" reverts to the default,
 *  systemPromptExtra:"" clears. Undefined fields are dropped by JSON.stringify. */
export const patchSettings = (
  patch: Partial<Pick<Settings, "baseUrl" | "model" | "systemPromptExtra">>,
): Promise<Settings> =>
  fetch("/api/settings", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  }).then(json);

/** Live backend reachability + model ids (settings UI test button). 503 llm_unavailable. */
export const fetchLlmModels = (): Promise<{ models: string[]; configured: string | null }> =>
  fetch("/api/llm/models").then(json);

// --- AniList OAuth + watchlist -------------------------------------------------

export interface AniListAuth {
  configured: boolean;
  authenticated: boolean;
  username: string | null;
  flow: "idle" | "pending" | "ok" | "error";
  flowError: string | null;
  redirectUri: string;
  tokenExpiresAt: string | null;
}

export const fetchAniListAuth = (): Promise<AniListAuth> => fetch("/api/auth/anilist").then(json);

/** Key present = change; "" clears. The secret never round-trips. */
export const patchAniListAuth = (patch: { clientId?: string; clientSecret?: string }): Promise<AniListAuth> =>
  fetch("/api/auth/anilist", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(patch),
  }).then(json);

export const startAniListLogin = (): Promise<{ url: string }> =>
  fetch("/api/auth/anilist/start", { method: "POST" }).then(json);

export const disconnectAniList = (): Promise<{ ok: boolean }> =>
  fetch("/api/auth/anilist/disconnect", { method: "POST" }).then(json);

export const watchlistStatus = (username: string, mediaId: number): Promise<{ status: string | null }> =>
  fetch(`/api/watchlist/status?username=${encodeURIComponent(username)}&mediaId=${mediaId}`).then(json);

export const addToWatchlist = (mediaId: number): Promise<{ ok: boolean; status: string }> =>
  fetch("/api/watchlist", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ mediaId }),
  }).then(json);
