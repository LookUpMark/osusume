import type { Explanation, Lang, RecoResult, SetupStatus, TasteProfile } from "../lib/types.ts";

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

export type ChatMsg = { role: "user" | "assistant"; content: string };

export const postChat = (
  username: string,
  lang: Lang,
  messages: ChatMsg[],
  extra: number[] = [],
): Promise<{ reply: string }> =>
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
