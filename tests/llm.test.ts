import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import type { MediaLite, ScoredReco, TasteProfile } from "../src/shared/types.ts";
import { explainRecos, llmChat, llmHealth, LlmError, parseExplanations } from "../src/server/llm.ts";
import { llmModel } from "../src/server/config.ts";

// explainRecos reads LLM_BASE_URL per call — each test points it at its fake server

const media = (id: number): MediaLite => ({
  id,
  title: `m${id}`,
  format: "TV",
  seasonYear: 2015,
  genres: ["Mystery"],
  tags: [{ name: "Psychological", rank: 90, isSpoiler: false }],
  studio: "Madhouse",
  averageScore: 80,
  popularity: 50000,
  coverImage: null,
  coverColor: null,
  siteUrl: null,
  description: null,
  relations: [],
});

const reco = (id: number): ScoredReco => ({
  media: media(id),
  final: 0.8,
  breakdown: { affinity: 0.7, quality: 0.7, community: 0 },
  badges: [],
  rootId: null,
  groupSize: 1,
  why: `deterministic why for ${id}`,
});

const profile: TasteProfile = {
  userName: "test",
  meanScore: 70,
  scoredCount: 10,
  confidence: "ok",
  counts: { CURRENT: 0, PLANNING: 0, COMPLETED: 10, DROPPED: 0, PAUSED: 0, REPEATING: 0 },
  loved: [{ dim: "tag", value: "Psychological", aff: 0.6, support: 5, examples: ["X"] }],
  disliked: [],
  hash: "h1",
};

async function withFakeLLM(
  handler: (body: any, hits: { count: number }) => string,
  fn: (url: string, hits: { count: number }) => Promise<void>,
): Promise<void> {
  const hits = { count: 0 };
  const server: Server = createServer((req, res) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      res.setHeader("content-type", "application/json");
      // model resolution probe — serve the configured model id as an OpenAI list
      if ((req.url ?? "").includes("/models")) {
        res.end(JSON.stringify({ data: [{ id: llmModel() }] }));
        return;
      }
      hits.count++;
      res.end(JSON.stringify({ choices: [{ message: { content: handler(JSON.parse(data), hits) } }] }));
    });
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
  try {
    await fn(url, hits);
  } finally {
    server.closeAllConnections(); // drop keep-alive sockets so the test process can exit
    server.close();
  }
}

test("explainRecos: LLM narrations cached, fallbacks never cached, request contract held", async () => {
  profile.hash = `h-${Math.random().toString(36).slice(2)}`;
  const prevBase = process.env.LLM_BASE_URL;
  const prevModel = process.env.LLM_MODEL;
  try {
    await withFakeLLM(
      (body) => {
        // request-contract asserts: model = whatever llmModel() resolves, profile + language present
        assert.equal(body.model, llmModel());
        const user = body.messages.at(-1).content as string;
        assert.ok(user.includes("Psychological"), "taste profile must reach the prompt");
        assert.ok(user.includes("English"), "language directive must be present");
        const ids = [...user.matchAll(/id=(\d+)/g)].map((m) => Number(m[1]));
        return JSON.stringify(ids.map((id) => (id === 2 ? { id, why: "" } : { id, why: `llm says ${id}` })));
      },
      async (url, hits) => {
        process.env.LLM_BASE_URL = url;
        const recos = [reco(1), reco(2)];
        const first = await explainRecos(recos, profile, "en", "testuser");
        assert.equal(first.get(1)?.source, "llm");
        assert.equal(first.get(1)?.text, "llm says 1");
        assert.equal(first.get(2)?.source, "fallback", "empty LLM answer falls back");
        assert.equal(first.get(2)?.text, "deterministic why for 2");
        assert.equal(hits.count, 1);

        const second = await explainRecos(recos, profile, "en", "testuser");
        assert.equal(second.get(1)?.source, "cache", "LLM text is cached");
        assert.equal(second.get(2)?.source, "fallback", "fallbacks are NOT cached — model retried");
        assert.equal(hits.count, 2, "second call retries the failed id with the LLM");
      },
    );
  } finally {
    if (prevBase === undefined) delete process.env.LLM_BASE_URL;
    else process.env.LLM_BASE_URL = prevBase;
    if (prevModel === undefined) delete process.env.LLM_MODEL;
    else process.env.LLM_MODEL = prevModel;
  }
});

test("explainRecos: unreachable LLM degrades to deterministic fallbacks without throwing", async () => {
  profile.hash = `h-${Math.random().toString(36).slice(2)}`;
  const prevBase = process.env.LLM_BASE_URL;
  try {
    process.env.LLM_BASE_URL = "http://127.0.0.1:59999/v1"; // nothing listens here
    const out = await explainRecos([reco(7)], profile, "it", "testuser");
    assert.equal(out.get(7)?.source, "fallback");
    assert.ok(out.get(7)?.text.includes("deterministic why for 7"));
  } finally {
    if (prevBase === undefined) delete process.env.LLM_BASE_URL;
    else process.env.LLM_BASE_URL = prevBase;
  }
});

test("llmChat: thinking disabled at the source, think blocks stripped, budget default", async () => {
  await withFakeLLM(
    () => "<think>let me reason at length…</think>[{\"id\":30,\"why\":\"ok\"}]",
    async (url) => {
      let body: any;
      const orig = globalThis.fetch;
      // capture the request body
      globalThis.fetch = (async (input: any, init?: any) => {
        body = JSON.parse(init.body);
        return orig(input, init);
      }) as typeof fetch;
      try {
        process.env.LLM_BASE_URL = url;
        const out = await llmChat([{ role: "user", content: "hi" }], "m");
        assert.equal(out, '[{"id":30,"why":"ok"}]');
        assert.equal(body.chat_template_kwargs?.enable_thinking, false);
        assert.equal(body.max_tokens, 1200); // explanation-sized, not reasoning-sized
      } finally {
        globalThis.fetch = orig;
        delete process.env.LLM_BASE_URL;
      }
    },
  );
});

test("llmChat: server down throws LlmError ('unreachable'), not a bare TypeError", async () => {
  process.env.LLM_BASE_URL = "http://127.0.0.1:59999/v1"; // nothing listens here
  try {
    await assert.rejects(
      llmChat([{ role: "user", content: "hi" }], "m"),
      (e: unknown) => e instanceof LlmError && e.message.includes("unreachable"),
    );
  } finally {
    delete process.env.LLM_BASE_URL;
  }
});

test("parseExplanations: prose-wrapped, fenced, truncated and garbage input", () => {
  assert.deepEqual(parseExplanations('bla [{"id":1,"why":"a"}] tra'), [{ id: 1, why: "a" }]);
  assert.deepEqual(parseExplanations('```json\n[{"id":2,"why":"b"}]\n```'), [{ id: 2, why: "b" }]);
  // prose containing multiple arrays: the LAST valid one wins (thinking models
  // write bracketed fragments first, the real answer last)
  assert.deepEqual(parseExplanations('[{"id":3,"why":"c"}] and [{"id":9,"why":"x"}]'), [{ id: 9, why: "x" }]);
  // a bracketed fragment inside reasoning is skipped when it doesn't parse as items
  assert.deepEqual(parseExplanations('think [0, 1] more [{"id":5,"why":"e"}]'), [{ id: 5, why: "e" }]);
  // string ids coerce when integer (small models), garbage ids drop
  assert.deepEqual(parseExplanations('[{"id":"4","why":"d"}]'), [{ id: 4, why: "d" }]);
  assert.deepEqual(parseExplanations('[{"id":"abc","why":"e"}]'), []);
  assert.deepEqual(parseExplanations("no array here at all"), []);
  assert.deepEqual(parseExplanations("[unclosed"), []);
});

test("llmHealth: 200 on /models is not 'up' unless the configured model is served", async () => {
  const prevBase = process.env.LLM_BASE_URL;
  const prevModel = process.env.LLM_MODEL;
  const server: Server = createServer((req, res) => {
    if ((req.url ?? "").includes("/models")) {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ data: [{ id: "altro-modello" }] }));
    } else {
      res.statusCode = 404;
      res.end("{}");
    }
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
  try {
    process.env.LLM_BASE_URL = url;
    process.env.LLM_MODEL = "prism-ml/Ternary-Bonsai-2-27B-gguf";
    assert.equal(await llmHealth(), false, "missing model → honest off (never a phantom green chip)");
    process.env.LLM_MODEL = "altro-modello";
    assert.equal(await llmHealth(), true, "model served → up");
    process.env.LLM_MODEL = "org/altro-modello";
    assert.equal(await llmHealth(), true, "org-prefixed config tolerated against bare server id");
  } finally {
    if (prevBase === undefined) delete process.env.LLM_BASE_URL;
    else process.env.LLM_BASE_URL = prevBase;
    if (prevModel === undefined) delete process.env.LLM_MODEL;
    else process.env.LLM_MODEL = prevModel;
    server.closeAllConnections();
    server.close();
  }
});

test("chat: system prompt is an expert grounded in the visible result, algorithm-speak banned", async () => {
  const { buildChatSystem } = await import("../src/server/chat.ts");
  const result = {
    profile,
    recos: [reco(1), reco(2)],
    avoided: [],
  } as unknown as Parameters<typeof buildChatSystem>[0];
  const sys = buildChatSystem(result, "en");
  assert.ok(sys.includes("m1") && sys.includes("m2"), "titles present");
  assert.ok(sys.includes("BANNED"), "explicit ban on algorithm-speak");
  assert.ok(sys.includes("Psychological (they enjoyed it in"), "taste links with seen titles");
  assert.ok(sys.includes("LEADS, not facts"), "comparison doctrine reaches chat");
  assert.ok(sys.includes("English"), "language directive present");
  const it = buildChatSystem(result, "it");
  assert.ok(it.includes("Italian"), "language follows the requested lang");
});

test("buildPrompt: comparison doctrine + reception line only when reviews exist", async () => {
  const { buildPrompt } = await import("../src/server/llm.ts");
  const base = buildPrompt([reco(1)], profile, "en");
  assert.ok(base.includes("veteran anime critic"), "critic voice, not friend-wiki");
  assert.ok(base.includes("LEADS, not facts"), "doctrine present");
  assert.ok(base.includes("possible leads (verify, drop if shallow)"), "leads are framed as unverified");
  assert.ok(!base.includes("reception:"), "no reception line without reviews");

  const grounded = buildPrompt([reco(1)], profile, "en", new Map([[1, [
    { summary: "A slow burn", body: "the payoff recontextualizes every early scene", score: 85, rating: 12 },
  ]]]));
  assert.ok(grounded.includes("reception:"), "reception reaches the prompt");
  assert.ok(grounded.includes("payoff recontextualizes"), "review body excerpt present");
  assert.ok(!grounded.includes("A slow burn"), "summary omitted — punchy lines get echoed verbatim");
});

test("mentionedTitles: last user message only, min title length, capped at 2", async () => {
  const { mentionedTitles } = await import("../src/server/chat.ts");
  const long = (id: number, title: string): ScoredReco => ({ ...reco(id), media: { ...media(id), title } });
  const cands = [long(1, "Monster"), long(2, "Vinland Saga"), long(3, "mx")];
  // titles below 4 chars ("mx") never match; case-insensitive
  assert.equal(mentionedTitles([{ role: "user", content: "tell me about MONSTER please" }], cands).length, 1);
  assert.equal(
    mentionedTitles([{ role: "user", content: "tell me about MONSTER please" }], cands)[0]?.media.id,
    1,
  );
  // last message is the assistant's → no match even if a title appears
  assert.equal(
    mentionedTitles(
      [
        { role: "user", content: "Monster?" },
        { role: "assistant", content: "Monster is great" },
      ],
      cands,
    ).length,
    0,
  );
  assert.equal(
    mentionedTitles([{ role: "user", content: "Monster or Vinland Saga first?" }], cands).length,
    2,
    "two mentions matched, cap enforced",
  );
});
