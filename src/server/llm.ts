import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { Explanation, Lang, ScoredReco, TasteProfile } from "../shared/types.ts";
import { CACHE_DIR, CACHE_TTL_EXPL_MS, configuredLlmModel, llmBaseUrl, llmModel, LLM_TIMEOUT_MS } from "./config.ts";
import { lovedOverlap } from "./scoring.ts";
import { llmAuthHeaders, logLlm } from "./setup.ts";

const EXPL_DIR = join(CACHE_DIR, "expl");

/** Typed LLM failure: callers distinguish "model/backend problem" (503, log)
 *  from generic errors. */
export class LlmError extends Error {}

// bumped when the prompt voice changes — old cached explanations must not resurface
const PROMPT_VERSION = "v2-expert-1";
// thinking OFF makes a full explanation ~150 tokens: budget for a batch, not
// for reasoning (the old 4000/16000 let Bonsai burn minutes of reasoning at 23 tok/s)
const LLM_MAX_TOKENS = Number(process.env.LLM_MAX_TOKENS ?? 1200);
const LLM_RETRY_TOKENS = Number(process.env.LLM_RETRY_TOKENS ?? 4000);

/** True when the failure was a token-budget truncation: thinking models spend
 *  the whole budget reasoning before the JSON — one bigger-budget retry wins. */
export function isTruncation(e: unknown): boolean {
  return e instanceof LlmError && e.message.includes("truncated");
}

export async function llmHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${llmBaseUrl()}/models`, {
      headers: llmAuthHeaders(),
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return false;
    // a 200 on /models says nothing about OUR model: a chip that goes green
    // while every chat 404s is worse than an honest "off"
    const want = configuredLlmModel();
    if (!want) return true; // no explicit model configured — reachable is all we know
    const j = (await res.json()) as { data?: { id?: string }[] };
    const leaf = want.split("/").pop();
    return (j.data ?? []).some((m) => m.id === want || m.id === leaf);
  } catch {
    return false;
  }
}

/** Servers rename models: oMLX serves bare names while the config may hold an
 *  org/repo id (404 on every chat otherwise). Resolve once per call round. */
export async function resolveServedModel(): Promise<string> {
  const want = llmModel();
  try {
    const res = await fetch(`${llmBaseUrl()}/models`, {
      headers: llmAuthHeaders(),
      signal: AbortSignal.timeout(2000),
    });
    if (!res.ok) return want;
    const j = (await res.json()) as { data?: { id?: string }[] };
    const ids = (j.data ?? []).map((m) => m.id ?? "");
    const leaf = want.split("/").pop();
    if (ids.includes(want)) return want;
    if (leaf != null && ids.includes(leaf)) return leaf;
  } catch {
    /* unreachable — keep the configured id, the chat error will surface */
  }
  return want;
}

/** Server down / socket error are plain TypeErrors — type them so /api/chat
 *  answers 503 llm_unavailable (honest, fast) instead of a generic 500. */
export async function llmChat(messages: { role: string; content: string }[], model: string, maxTokens = LLM_MAX_TOKENS): Promise<string> {
  let res: Response;
  try {
    res = await fetch(`${llmBaseUrl()}/chat/completions`, {
      method: "POST",
      headers: { "content-type": "application/json", ...llmAuthHeaders() },
      body: JSON.stringify({
        model,
        messages,
        temperature: 0.3,
        max_tokens: maxTokens,
        // Qwen3-family hard switch (Bonsai included): unknown fields are dropped
        // by servers that don't support it. Verified live: without it the model
        // spends the whole budget in invisible reasoning (~3 min per call).
        chat_template_kwargs: { enable_thinking: false },
      }),
      signal: AbortSignal.timeout(LLM_TIMEOUT_MS),
    });
  } catch (e) {
    throw new LlmError(`LLM unreachable (${(e as Error).message})`);
  }
  if (!res.ok) throw new LlmError(`LLM HTTP ${res.status}`);
  const json = (await res.json()) as {
    choices?: { message?: { content?: string }; finish_reason?: string }[];
  };
  const choice = json.choices?.[0];
  if (choice?.finish_reason === "length") throw new LlmError("LLM output truncated (finish_reason=length)");
  // templates without the kwarg may still reason inline — strip what we can
  const content = (choice?.message?.content ?? "").replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  if (content.length === 0) throw new LlmError("LLM returned empty content");
  return content;
}

const LANG_NAME: Record<Lang, string> = { en: "English", it: "Italian" };

/** Strip HTML + collapse whitespace (AniList descriptions are HTML). */
export function cleanText(html: string | null, max = 450): string {
  if (!html) return "";
  const text = html
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#039;|&apos;/g, "'")
    .replace(/&mdash;/g, "—")
    .replace(/&hellip;/g, "…")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > max ? `${text.slice(0, max).replace(/\s+\S*$/, "")}…` : text;
}

function buildPrompt(recos: ScoredReco[], profile: TasteProfile, lang: Lang): string {
  const loved = profile.loved
    .slice(0, 10)
    .map((d) => `${d.value} (e.g. ${d.examples.slice(0, 2).join(", ") || "n/a"})`)
    .join("; ");
  const disliked = profile.disliked
    .slice(0, 6)
    .map((d) => d.value)
    .join("; ");
  const items = recos
    .map((r) => {
      const overlap = lovedOverlap(r.media, profile);
      const links = overlap
        .map((o) => {
          const theme = o.label.split(":").pop();
          return `${theme} — they enjoyed it in ${o.examples.join(", ")}`;
        })
        .join("; ");
      const themes = r.media.tags
        .filter((t) => t.rank >= 60 && !t.isSpoiler)
        .slice(0, 5)
        .map((t) => t.name)
        .join(", ");
      const plot = cleanText(r.media.description, 400);
      const plotLinks = (r.links ?? [])
        .map((l) => `shares plot elements (${l.shared.join(", ")}) with "${l.title}"`)
        .join("; ");
      return (
        `- id=${r.media.id} — "${r.media.title}" (${r.media.seasonYear ?? "?"}, ${r.media.studio ?? "?"}; ` +
        `genres: ${r.media.genres.slice(0, 3).join(", ")}${themes ? `; themes: ${themes}` : ""})\n` +
        `  plot: ${plot || "not available"}\n` +
        `  links to their taste: ${[links, plotLinks].filter(Boolean).join("; ") || "none obvious — lean on the plot"}`
      );
    })
    .join("\n");
  return (
    `You are a knowledgeable anime friend. The user loves: ${loved || "not enough data"}. ` +
    `They dislike: ${disliked || "nothing notable"}.\n` +
    `For each title below, write 2-3 sentences in ${LANG_NAME[lang]} on why ITS STORY could hook THIS user: ` +
    `talk about the plot, themes and atmosphere (draw on the plot text), and connect them to titles they already enjoyed. ` +
    `NEVER mention scores, percentages, "affinity", "quality", "match", the app or any algorithm — a real expert does not talk like that. ` +
    `Use ONLY the facts provided; if the plot text is missing, speak about the themes. Never invent plot details.\n\n${items}\n\n` +
    `Reply with ONLY a JSON array: [{"id":<media id>,"why":"<explanation>"}]`
  );
}

/** Extract a valid JSON array even when a thinking model wraps it in prose.
 *  Scans balanced arrays last→first: reasoning text often contains bracketed
 *  fragments, and the real answer comes after it. */
export function parseExplanations(raw: string): { id: number; why: string }[] {
  const tryParse = (slice: string): { id: number; why: string }[] | null => {
    try {
      const arr = JSON.parse(slice) as { id?: unknown; why?: unknown }[];
      if (!Array.isArray(arr)) return null;
      const items = arr
        .map((x) => ({ id: typeof x?.id === "number" ? x.id : Number(x?.id), why: x?.why }))
        .filter(
          (x): x is { id: number; why: string } =>
            x.id !== null && Number.isInteger(x.id) && typeof x.why === "string",
        );
      return items.length > 0 ? items : null;
    } catch {
      return null;
    }
  };

  // collect candidate [ ... ] spans (string-aware depth scan)
  const spans: [number, number][] = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i];
    if (inString) {
      if (ch === "\\") i++;
      else if (ch === '"') inString = false;
    } else if (ch === '"') inString = true;
    else if (ch === "[") {
      if (depth === 0) start = i;
      depth++;
    } else if (ch === "]") {
      depth--;
      if (depth === 0 && start >= 0) {
        spans.push([start, i]);
        start = -1;
      }
    }
  }
  for (const [s, e] of spans.reverse()) {
    const items = tryParse(raw.slice(s, e + 1));
    if (items) return items;
  }
  return [];
}

async function cacheGet(key: string): Promise<Record<string, string> | null> {
  try {
    const hit = JSON.parse(await readFile(join(EXPL_DIR, `${key}.json`), "utf8"));
    if (Date.now() < hit.exp) return hit.items as Record<string, string>;
  } catch {
    /* miss */
  }
  return null;
}

async function cacheSet(key: string, items: Record<string, string>): Promise<void> {
  await mkdir(EXPL_DIR, { recursive: true });
  const file = join(EXPL_DIR, `${key}.json`);
  const tmp = `${file}.tmp`;
  await writeFile(tmp, JSON.stringify({ exp: Date.now() + CACHE_TTL_EXPL_MS, items }));
  await rename(tmp, file); // atomic swap — no partial reads
}

/**
 * Explain recos via the local LLM. Falls back to the deterministic why for any
 * id the model misses — all-or-nothing LLM failure still yields explanations.
 */
export async function explainRecos(
  recos: ScoredReco[],
  profile: TasteProfile,
  lang: Lang,
  username: string,
): Promise<Map<number, Explanation>> {
  const out = new Map<number, Explanation>();
  const pending: ScoredReco[] = [];
  const fresh = new Map<string, string>();

  const key = createHash("sha256")
    .update(`${username}|${profile.hash}|${lang}|${llmModel()}|${llmBaseUrl()}|${PROMPT_VERSION}|`)
    .update(recos.map((r) => r.media.id).sort((a, b) => a - b).join(","))
    .digest("hex");
  const cached = await cacheGet(key);
  for (const r of recos) {
    const hit = cached?.[String(r.media.id)];
    out.set(r.media.id, hit ? { text: hit, source: "cache" } : { text: r.why, source: "fallback" });
    if (!hit) pending.push(r);
  }
  if (pending.length === 0) return out;

  try {
    const model = await resolveServedModel();
    // ponytail: batches of max 10 — small local models degrade past that
    for (let i = 0; i < pending.length; i += 10) {
      const batch = pending.slice(i, i + 10);
      let raw: string;
      try {
        const chat = [
          {
            role: "system" as const,
            content:
              "You output only valid JSON. Do not explain your reasoning — the reply must be ONLY the JSON array.",
          },
          { role: "user" as const, content: buildPrompt(batch, profile, lang) },
        ];
        try {
          raw = await llmChat(chat, model);
        } catch (e) {
          if (!isTruncation(e)) throw e;
          // thinking models burn the default budget reasoning: one retry with
          // a big budget — the explanation is per-title and cached for a week
          raw = await llmChat(chat, model, LLM_RETRY_TOKENS);
        }
      } catch (e) {
        // log the failure — silent fallbacks made "why is there no LLM text?" undebuggable
        logLlm(`explain: LLM error (${(e as Error).message}) per model=${llmModel()} — prose deterministiche in uso`);
        break;
      }
      for (const e of parseExplanations(raw)) {
        const reco = batch.find((r) => r.media.id === e.id);
        const text = e.why.trim();
        // only genuine LLM output is cached — caching deterministic fallbacks would
        // mask model failures as source:"cache" for a week
        if (reco && text.length > 0) {
          out.set(e.id, { text, source: "llm" });
          fresh.set(String(e.id), text);
        }
      }
    }
    if (fresh.size > 0) await cacheSet(key, { ...(cached ?? {}), ...Object.fromEntries(fresh) });
  } catch (e) {
    // LLM unreachable/slow — deterministic fallbacks already in place, but leave a trace
    logLlm(`explain: fallito (${(e as Error).message}) — prose deterministiche in uso`);
  }
  return out;
}
