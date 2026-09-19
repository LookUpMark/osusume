import { Hono, type Context } from "hono";
import type { Lang } from "../shared/types.ts";
import { AniListError } from "./anilist.ts";
import {
  autoFallbackOn,
  fixturesAvailable,
  localModeOn,
  llmModel,
  setAutoFallback,
  setLocalMode,
} from "./config.ts";
import { explainRecos, LlmError, llmHealth } from "./llm.ts";
import { chatReply } from "./chat.ts";
import { getProfile, getRecommendation, lookupMedia, scoreArbitrary } from "./recommend.ts";
import { ensureLlmServer, llmBackendState, logLlm, setupRoutes, shutdownBackend } from "./setup.ts";
import { appUpdateStatus } from "./update.ts";

const USERNAME_RE = /^[A-Za-z0-9_-]{1,32}$/;
const LANGS: ReadonlySet<string> = new Set(["en", "it"]);

export const api = new Hono();

// Loopback binding is not per-user: reject Host headers that don't match the
// local host so DNS-rebinding pages (browser same-origin) and other machines'
// processes can't reach privileged endpoints. First middleware, covers all /api.
api.use("*", async (c, next) => {
  const host = c.req.header("host") ?? "";
  const hostname = host.replace(/:\d+$/, "").replace(/^\[|\]$/g, "");
  if (!["127.0.0.1", "localhost", "::1"].includes(hostname)) {
    return c.json({ error: "forbidden" }, 403);
  }
  await next();
});

api.get("/health", async (c) => {
  ensureLlmServer(); // throttled no-op unless the backend should be up (or retried)
  return c.json({
    ok: true,
    llm: { model: llmModel(), enabled: await llmHealth(), state: llmBackendState() },
    local: { on: localModeOn(), available: fixturesAvailable(), auto: autoFallbackOn() },
  });
});

api.get("/app-update", async (c) => c.json(await appUpdateStatus(c.req.query("fresh") === "1")));

// UI toggle: auto-fallback on AniList failure. Switching it off also retries live.
// {local:false} forces a live retry without touching the auto preference (banner button).
api.post("/local-mode", async (c) => {
  const body = (await c.req.json().catch(() => null)) as { auto?: boolean; local?: boolean } | null;
  if (typeof body?.auto !== "boolean") return c.json({ error: "invalid_request" }, 400);
  setAutoFallback(body.auto);
  if (body.local === false) setLocalMode(false);
  return c.json({ ok: true, local: { on: localModeOn(), available: fixturesAvailable(), auto: autoFallbackOn() } });
});

// AniList down + auto on + fixtures on disk → flip to local mode and retry once.
// 404 is a genuine "user not found", not an outage — never masked.
async function withLocalFallback(c: Context, fn: () => Promise<Response>): Promise<Response> {
  try {
    return await fn();
  } catch (e) {
    if (
      e instanceof AniListError &&
      e.status !== 404 &&
      autoFallbackOn() &&
      !localModeOn() &&
      fixturesAvailable()
    ) {
      setLocalMode(true);
      try {
        return await fn();
      } catch {
        /* fixtures failed too — report the original AniList error */
      }
    }
    return errorResponse(c, e);
  }
}

// disclosure-minimal: the base URL can point anywhere after a custom finish — don't announce it
api.get("/config", (c) => c.json({ llm: { model: llmModel() } }));

api.route("/setup", setupRoutes);

api.get("/profile/:username", (c) => {
  const username = c.req.param("username");
  if (!USERNAME_RE.test(username)) return c.json({ error: "invalid_username" }, 400);
  return withLocalFallback(c, async () => c.json({ profile: await getProfile(username) }));
});

api.post("/recommend", async (c) => {
  const body = (await c.req.json().catch(() => null)) as
    | { username?: string; lang?: Lang }
    | null;
  const username = body?.username ?? "";
  const lang = LANGS.has(body?.lang ?? "") ? (body!.lang as Lang) : "en";
  if (!USERNAME_RE.test(username)) return c.json({ error: "invalid_username" }, 400);
  return withLocalFallback(c, async () => c.json(await getRecommendation(username, lang)));
});

api.post("/explain", async (c) => {
  const body = (await c.req.json().catch(() => null)) as
    | { username?: string; ids?: number[]; lang?: Lang }
    | null;
  const username = body?.username ?? "";
  const ids = new Set((body?.ids ?? []).filter((x) => typeof x === "number"));
  const lang = LANGS.has(body?.lang ?? "") ? (body!.lang as Lang) : "en";
  if (!USERNAME_RE.test(username) || ids.size === 0) return c.json({ error: "invalid_request" }, 400);
  return withLocalFallback(c, async () => {
    // stale-tolerant like /chat: the dialog explains a result the UI already
    // shows — recomputing the whole list mid-open is seconds of dead wait
    const { recos, profile } = await getRecommendation(username, lang, { staleOk: true });
    const subset = recos.filter((r) => ids.has(r.media.id));
    // ids outside the recommendation list (chat lookup) are scored on demand
    const missing = [...ids].filter((id) => !subset.some((r) => r.media.id === id));
    if (missing.length > 0) {
      const extra = await scoreArbitrary(missing, username, lang);
      subset.push(...extra.recos.filter((r) => ids.has(r.media.id)));
    }
    const explanations = await explainRecos(subset, profile, lang, username);
    return c.json({
      explanations: [...explanations.entries()].map(([id, e]) => ({ id, ...e })),
    });
  });
});

// Search any title and score it against the user's taste — powers the chat
// lookup card, the detail dialog and the "ask about a non-recommended title" flow.
api.post("/lookup", async (c) => {
  const body = (await c.req.json().catch(() => null)) as
    | { username?: string; q?: string; lang?: Lang }
    | null;
  const username = body?.username ?? "";
  const q = (body?.q ?? "").trim();
  const lang = LANGS.has(body?.lang ?? "") ? (body!.lang as Lang) : "en";
  if (!USERNAME_RE.test(username) || q.length < 2 || q.length > 80) {
    return c.json({ error: "invalid_request" }, 400);
  }
  return withLocalFallback(c, async () => c.json({ recos: await lookupMedia(username, q, lang) }));
});

// Natural-language chat about the current result. The context (recommendations,
// profile, avoid list) is rebuilt server-side — the client only sends the conversation.
api.post("/chat", async (c) => {
  const body = (await c.req.json().catch(() => null)) as
    | {
        username?: string;
        lang?: Lang;
        extra?: number[];
        messages?: { role?: string; content?: string }[];
      }
    | null;
  const username = body?.username ?? "";
  const lang = LANGS.has(body?.lang ?? "") ? (body!.lang as Lang) : "en";
  if (!USERNAME_RE.test(username)) return c.json({ error: "invalid_username" }, 400);
  // normalize, never drop: an over-long turn is clamped so mid-conversation
  // context survives (dropping it made the model "forget" what it had said)
  const history = (body?.messages ?? [])
    .filter(
      (m): m is { role: "user" | "assistant"; content: string } =>
        (m.role === "user" || m.role === "assistant") &&
        typeof m.content === "string" &&
        m.content.trim().length > 0,
    )
    .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }))
    .slice(-12);
  if (history.length === 0 || history[history.length - 1]!.role !== "user") {
    return c.json({ error: "invalid_request" }, 400);
  }
  return withLocalFallback(c, async () => {
    try {
      // stale-tolerant: a 10-minute-old result beats a full recompute mid-chat
      const result = await getRecommendation(username, lang, { staleOk: true });
      // titles opened via the chat lookup join the context so the model can
      // answer questions about them too (bounded, never duplicates)
      const extraIds = (body?.extra ?? [])
        .filter((x) => typeof x === "number")
        .filter((id) => !result.recos.some((r) => r.media.id === id))
        .slice(0, 5);
      const extras = extraIds.length > 0 ? (await scoreArbitrary(extraIds, username, lang)).recos : [];
      const reply = await chatReply(result, lang, history, extras);
      return c.json({ reply });
    } catch (e) {
      if (e instanceof LlmError) {
        logLlm(`chat: LLM error (${e.message}) per model=${llmModel()}`);
        return c.json({ error: "llm_unavailable" }, 503);
      }
      return errorResponse(c, e);
    }
  });
});

// Signal-independent teardown (Windows path): Electron calls this on quit because
// SIGTERM kills the Node child without running its exit handlers.
api.post("/shutdown", (c) => {
  shutdownBackend();
  setTimeout(() => process.exit(0), 200); // let the response flush first
  return c.json({ ok: true });
});

function errorResponse(c: { json: (x: object, status: number) => Response }, e: unknown): Response {
  if (e instanceof AniListError) {
    if (e.status === 404) return c.json({ error: "user_not_found" }, 404);
    return c.json({ error: "anilist_error", message: e.message }, 502);
  }
  return c.json({ error: "internal_error" }, 500);
}
