import assert from "node:assert/strict";
import { test } from "node:test";
import type { ListEntry, MediaLite, TasteProfile } from "../src/shared/types.ts";
import { analyzeFranchises, type FranchiseInfo } from "../src/server/franchise.ts";
import { affinityOf, buildSeenCorpus, dedupeFranchises, deterministicWhy, deterministicWhyNot, gemScoreOf, isGem, popNorm, qualityOf, scoreAll, textLinks, tokenize } from "../src/server/scoring.ts";

const media = (id: number, over: Partial<MediaLite> = {}): MediaLite => ({
  id,
  title: `m${id}`,
  format: "TV",
  seasonYear: 2015,
  genres: [],
  tags: [],
  studio: null,
  averageScore: 70,
  popularity: 100000,
  coverImage: null,
  coverColor: null,
  siteUrl: null,
  description: null,
  relations: [],
  ...over,
});

const profile: TasteProfile = {
  userName: "test",
  meanScore: 70,
  scoredCount: 10,
  confidence: "ok",
  counts: { CURRENT: 0, PLANNING: 0, COMPLETED: 10, DROPPED: 2, PAUSED: 0, REPEATING: 0 },
  loved: [
    { dim: "tag", value: "Psychological", aff: 0.6, support: 8, examples: ["X"] },
    { dim: "genre", value: "Mystery", aff: 0.4, support: 8, examples: ["X"] },
  ],
  disliked: [{ dim: "genre", value: "Isekai", aff: -0.7, support: 4, examples: ["Y"] }],
  hash: "abc",
};

test("affinity: studio and era dims count (20% of the core weight)", () => {
  const p: TasteProfile = {
    ...profile,
    loved: [
      { dim: "studio", value: "Madhouse", aff: 0.6, support: 5, examples: ["X"] },
      { dim: "era", value: "2015", aff: 0.4, support: 5, examples: ["X"] },
    ],
  };
  const hit = media(1, { studio: "Madhouse", seasonYear: 2015 });
  const miss = media(2, { studio: "Toei", seasonYear: 1990 });
  const aHit = affinityOf(hit, p).affinity01;
  const aMiss = affinityOf(miss, p).affinity01;
  // core = 0.12·0.6 + 0.08·0.4 = 0.104 → affinity01 0.552; no match → neutral 0.5
  assert.ok(aHit > 0.55, `studio+era match must beat neutral, got ${aHit}`);
  assert.equal(aMiss, 0.5);
});

test("affinity: loved tags push up, disliked genres pull down", () => {
  const loved = media(1, {
    tags: [{ name: "Psychological", rank: 90, isSpoiler: false }],
    genres: ["Mystery"],
  });
  const hated = media(2, { genres: ["Isekai"] });
  const neutral = media(3);
  const aLoved = affinityOf(loved, profile).affinity01;
  const aHated = affinityOf(hated, profile).affinity01;
  const aNeutral = affinityOf(neutral, profile).affinity01;
  assert.ok(aLoved > 0.6, `loved should be high, got ${aLoved}`);
  assert.ok(aHated < 0.4, `hated should be low, got ${aHated}`);
  assert.equal(aNeutral, 0.5);
  assert.ok(aLoved > aNeutral && aNeutral > aHated);
});

test("popNorm separates gems from mainstream", () => {
  assert.ok(popNorm(media(1, { popularity: 1000 })) < 0.3);
  assert.ok(popNorm(media(1, { popularity: 5000 })) < 0.45);
  assert.ok(popNorm(media(1, { popularity: 40000 })) > 0.6);
  assert.ok(popNorm(media(1, { popularity: 500000 })) > 0.9);
});

test("hidden gem badge: low popularity + good score + good fit", () => {
  const tags = [{ name: "Psychological", rank: 95, isSpoiler: false }];
  const genres = ["Mystery"];
  const gem = media(1, { popularity: 5000, averageScore: 78, tags, genres });
  const aff = affinityOf(gem, profile).affinity01;
  const gemScore = gemScoreOf(gem, aff, qualityOf(gem));
  assert.ok(isGem(gem, gemScore), `expected gem, gemScore=${gemScore}`);
  // same fit but popular and mediocre → no gem
  const popular = media(2, { popularity: 500000, averageScore: 60, tags, genres });
  assert.ok(!isGem(popular, gemScoreOf(popular, aff, qualityOf(popular))));
  // thresholds are exact: popularity < 40_000 and averageScore ≥ 72 flip the flag
  const atLimit = (over: Partial<MediaLite>): MediaLite =>
    media(9, { popularity: 3000, averageScore: 78, tags, genres, ...over });
  assert.ok(!isGem(atLimit({ popularity: 40_000 }), gemScoreOf(atLimit({ popularity: 40_000 }), aff, qualityOf(atLimit({ popularity: 40_000 })))));
  assert.ok(isGem(atLimit({ popularity: 39_999 }), gemScoreOf(atLimit({ popularity: 39_999 }), aff, qualityOf(atLimit({ popularity: 39_999 })))));
  assert.ok(!isGem(atLimit({ averageScore: 71 }), gemScoreOf(atLimit({ averageScore: 71 }), aff, qualityOf(atLimit({ averageScore: 71 })))));
  assert.ok(isGem(atLimit({ averageScore: 72 }), gemScoreOf(atLimit({ averageScore: 72 }), aff, qualityOf(atLimit({ averageScore: 72 })))));
});

test("scoreAll: community bonus capped, next step bonus applied, sorted by final", () => {
  const candidates = [
    media(1, { tags: [{ name: "Psychological", rank: 90, isSpoiler: false }], genres: ["Mystery"] }),
    media(2, { genres: ["Isekai"] }),
    media(3),
  ];
  const community = new Map([
    [1, 0.5], // way over cap
    [3, 0.02],
  ]);
  const franchise = new Map<number, FranchiseInfo>([
    [1, { kind: "NEXT_STEP", rootId: 1, entryPointId: null, droppedId: null }],
    [2, { kind: "STANDALONE", rootId: 2, entryPointId: null, droppedId: null }],
    [3, { kind: "STANDALONE", rootId: 3, entryPointId: null, droppedId: null }],
  ]);
  const recos = scoreAll(candidates, profile, community, franchise, "en");
  assert.equal(recos[0].media.id, 1);
  const top = recos[0];
  assert.equal(top.breakdown.community, 0.1, "community bonus must be capped at 0.1");
  assert.ok(top.badges.includes("NEXT_STEP"));
  assert.ok(top.why.length > 10);
  assert.ok(recos[0].final >= recos[1].final);
});

test("dedupeFranchises: one representative per franchise, groupSize annotated", () => {
  // natural ranking: media(2) beats media(1) via higher score — no mutation
  const recos = scoreAll(
    [
      media(1, { averageScore: 60 }),
      media(2, { averageScore: 95 }),
      media(3, { averageScore: 70 }),
      media(4, { averageScore: 65 }),
      media(5, { averageScore: 68 }),
    ],
    profile,
    new Map(),
    new Map<number, FranchiseInfo>([
      [1, { kind: "NEXT_STEP", rootId: 100, entryPointId: null, droppedId: null }],
      [2, { kind: "NEXT_STEP", rootId: 100, entryPointId: null, droppedId: null }],
      [3, { kind: "STANDALONE", rootId: 3, entryPointId: null, droppedId: null }],
      [4, { kind: "NEXT_STEP", rootId: 200, entryPointId: null, droppedId: null }],
      [5, { kind: "NEXT_STEP", rootId: 200, entryPointId: null, droppedId: null }],
    ]),
    "en",
  );
  const deduped = dedupeFranchises(recos);
  assert.equal(deduped.length, 3, "5 candidates in 2 franchises + 1 standalone");
  const repA = deduped.find((r) => r.media.id === 2);
  assert.equal(repA?.groupSize, 2, "franchise 100 keeps its best member with groupSize 2");
  const repB = deduped.find((r) => r.media.id === 5);
  assert.equal(repB?.groupSize, 2);
  const standalone = deduped.find((r) => r.media.id === 3);
  assert.equal(standalone?.groupSize, 1);
  assert.ok(deduped.every((r) => deduped.indexOf(r) === deduped.length - 1 || deduped[deduped.indexOf(r)].final >= deduped[deduped.indexOf(r) + 1].final));
});

test("scoreAll: ENTRY_POINT gets the badge but no franchise bonus; spin-offs badge only", () => {
  const twin = (id: number, relations: MediaLite["relations"]): MediaLite =>
    media(id, {
      tags: [{ name: "Psychological", rank: 90, isSpoiler: false }],
      genres: ["Mystery"],
      relations,
    });
  const candidates = [
    twin(1, []), // next step
    twin(2, []), // entry point
    media(3, { relations: [{ id: 50, relationType: "SPIN_OFF" }], genres: ["Isekai"] }), // spin-off, disliked genre
  ];
  const franchise = new Map<number, FranchiseInfo>([
    [1, { kind: "NEXT_STEP", rootId: 1, entryPointId: null, droppedId: null }],
    [2, { kind: "ENTRY_POINT", rootId: 2, entryPointId: 2, droppedId: null }],
    [3, { kind: "STANDALONE", rootId: 3, entryPointId: null, droppedId: null }],
  ]);
  const recos = scoreAll(candidates, profile, new Map(), franchise, "en");
  const next = recos.find((r) => r.media.id === 1)!;
  const entry = recos.find((r) => r.media.id === 2)!;
  const spin = recos.find((r) => r.media.id === 3)!;
  assert.deepEqual(entry.badges, ["ENTRY_POINT"]);
  assert.deepEqual(next.badges, ["NEXT_STEP"]);
  assert.ok(entry.final < next.final, "ENTRY_POINT must not receive the +0.12 franchise bonus");
  assert.ok(spin.badges.includes("SPIN_OFF"));
  assert.ok(!spin.badges.includes("NEXT_STEP"));
});

test("franchise: dropped prequel excludes sequel (analyzeFranchises)", () => {
  const listMap = new Map<number, ListEntry>([
    [201, { mediaId: 201, status: "DROPPED", score: 0, repeat: 0, title: "S1" }],
  ]);
  const candidates = [
    media(201, { relations: [{ id: 202, relationType: "SEQUEL" }] }),
    media(202, { relations: [{ id: 201, relationType: "PREQUEL" }] }),
  ];
  const info = analyzeFranchises(candidates, listMap);
  assert.equal(info.get(202)?.kind, "EXCLUDED");
  assert.equal(info.get(202)?.droppedId, 201);
});

test("franchise: never show S3 without S1 → entry point is S1", () => {
  const candidates = [
    media(101, { relations: [{ id: 102, relationType: "SEQUEL" }] }),
    media(102, { relations: [{ id: 101, relationType: "PREQUEL" }] }),
    media(103, { relations: [{ id: 102, relationType: "PREQUEL" }] }),
  ];
  // user completed S1 only
  const listMap = new Map<number, ListEntry>([
    [101, { mediaId: 101, status: "COMPLETED", score: 90, repeat: 0, title: "S1" }],
  ]);
  const info = analyzeFranchises(candidates, listMap);
  assert.equal(info.get(102)?.kind, "NEXT_STEP", "S1 completed → S2 is the next step");
  assert.equal(info.get(103)?.kind, "ENTRY_POINT");
  // first unseen node from the root side = S2 (the user's actual next watch)
  assert.equal(info.get(103)?.entryPointId, 102);
});

test("deterministic why/whyNot: honest templates, no self-references", () => {
  const m = media(9, {
    genres: ["Isekai"],
    tags: [{ name: "Isekai", rank: 80, isSpoiler: false }],
    averageScore: 60,
    popularity: 90000,
  });
  // why: no loved overlap → neutral quality sentence, no invented claims
  const why = deterministicWhy(m, profile, [], "en");
  assert.ok(!why.includes("m9"), "why must not cite the candidate itself");
  assert.ok(why.includes("60/100"), why);
  // whyNot: shares disliked Isekai + the dropped prequel
  const franchise: FranchiseInfo = { kind: "EXCLUDED", rootId: 9, entryPointId: null, droppedId: 3 };
  const whyNot = deterministicWhyNot(m, profile, franchise, "Dropped Series S1", "en");
  assert.ok(whyNot !== null);
  assert.ok(whyNot.includes("Isekai"));
  assert.ok(whyNot.includes("Dropped Series S1"), whyNot);
  // no negative evidence at all → null (never invent a reason)
  const neutral = media(10, { genres: ["Mystery"] });
  assert.equal(deterministicWhyNot(neutral, profile, undefined, null, "en"), null);
  // why with real overlap cites the loved dim and its example titles
  const loved = media(11, { tags: [{ name: "Psychological", rank: 90, isSpoiler: false }], genres: ["Mystery"] });
  const whyLoved = deterministicWhy(loved, profile, [], "en");
  assert.ok(whyLoved.includes("Psychological"));
  assert.ok(whyLoved.includes("X"), whyLoved);
});

test("franchise: relation cycle does not hang", () => {
  const candidates = [
    media(501, { relations: [{ id: 502, relationType: "PREQUEL" }] }),
    media(502, { relations: [{ id: 501, relationType: "PREQUEL" }] }),
  ];
  const info = analyzeFranchises(candidates, new Map());
  assert.equal(info.size, 2);
  // both members share one canonical root → dedupeFranchises collapses them
  assert.equal(info.get(501)?.rootId, info.get(502)?.rootId);
  assert.equal(info.get(501)?.kind, "ENTRY_POINT");
  assert.equal(info.get(501)?.entryPointId, 502);
});

test("franchise: long chain (13 prequels) keeps one canonical root", () => {
  const candidates: MediaLite[] = [];
  for (let id = 1; id <= 13; id++) {
    candidates.push(
      media(id, { relations: id > 1 ? [{ id: id - 1, relationType: "PREQUEL" }] : [] }),
    );
  }
  const listMap = new Map<number, ListEntry>();
  for (let id = 3; id <= 13; id++) {
    listMap.set(id, { mediaId: id, status: "COMPLETED", score: 80, repeat: 0, title: `s${id}` });
  }
  const info = analyzeFranchises(candidates, listMap);
  const roots = new Set([...info.values()].map((f) => f.rootId));
  assert.equal(roots.size, 1, `all 13 members must share one root, got ${[...roots]}`);
  assert.equal(info.get(1)?.rootId, 1);
  assert.equal(info.get(13)?.kind, "ENTRY_POINT");
  assert.equal(info.get(13)?.entryPointId, 1, "first unseen from root side");
  // even mid-chain members collapse to the same entry point
  assert.equal(info.get(12)?.kind, "ENTRY_POINT");
  assert.equal(info.get(12)?.entryPointId, 1);
});

test("scoring v2: plot-text links + entry-point why", () => {
    const a = tokenize("Heroes train at the academy to master their quirk powers");
  assert.ok(a.has("heroes") && a.has("academy"), "meaningful words kept");
  assert.ok(!a.has("their") && !a.has("the"), "stopwords and short words dropped");

  const corpus = buildSeenCorpus([
    { title: "My Hero Academia", description: "Heroes training at the academy master quirk powers in class battles", sentiment: 0.8 },
    { title: "Short desc", description: "too short", sentiment: 0.9 },
    { title: "Dropped one", description: "Heroes academy quirk training again but dropped", sentiment: -0.5 },
  ]);
  assert.equal(corpus.length, 1, "only positive-sentiment with enough text");

  const cand = {
    id: 5, title: "cand", format: "TV", seasonYear: 2020, genres: [], studio: null,
    tags: [], popularity: 50000, coverImage: null, coverColor: null, siteUrl: null,
    description: "A school for heroes where students train their quirk in class",
    relations: [],
  } as any;
  const links = textLinks(cand, corpus);
  assert.equal(links.length, 1);
  assert.equal(links[0].title, "My Hero Academia");
  assert.ok(links[0].shared.length >= 3, "shared plot vocabulary extracted");

  const noLinks = textLinks({ ...cand, description: null }, corpus);
  assert.equal(noLinks.length, 0, "no description — no fabricated links");
});

test("scoring v2: entry-point franchise adds the entry hint to the why", () => {
  // deterministicWhy with an ENTRY_POINT franchise appends the hint
  const m = {
    id: 9, title: "t", format: "TV", seasonYear: 2020, genres: [], studio: null,
    tags: [{ name: "Psychological", rank: 90, isSpoiler: false }],
    popularity: 50000, coverImage: null, coverColor: null, siteUrl: null,
    description: null, relations: [],
  } as any;
  const profile = {
    userName: "u", meanScore: 70, scoredCount: 5, confidence: "ok",
    counts: { CURRENT: 0, PLANNING: 0, COMPLETED: 5, DROPPED: 0, PAUSED: 0, REPEATING: 0 },
    loved: [{ dim: "tag", value: "Psychological", aff: 0.6, support: 5, examples: ["Serial Experiments Lain"] }],
    disliked: [], hash: "h",
  } as any;
  const base = deterministicWhy(m, profile, [], "en");
  const withEp = deterministicWhy(m, profile, [], "en", { kind: "ENTRY_POINT", entryPointId: 9, rootId: 9, droppedId: null });
  assert.ok(!base.includes("entry point"), "no hint without franchise info");
  assert.ok(withEp.includes("entry point"), "hint appended for ENTRY_POINT");
});

test("scoring v2: PREQUEL cycle never self-references (pin f4-1)", () => {
  // 1 and 2 claim each other as prequel: chainOf(1) must not contain 1 itself
  const listMap = new Map<number, any>([
    [1, { mediaId: 1, status: "COMPLETED", score: 80, title: "t1" }],
    [2, { mediaId: 2, status: "COMPLETED", score: 80, title: "t2" }],
  ]);
  const cands = [
    media(1, { relations: [{ id: 2, relationType: "PREQUEL" }] }),
    media(2, { relations: [{ id: 1, relationType: "PREQUEL" }] }),
  ];
  const info = analyzeFranchises(cands, listMap);
  for (const [id, f] of info) {
    assert.notEqual(f.entryPointId, id, `franchise ${id} must not be its own entry point`);
    assert.notEqual(f.kind, "EXCLUDED", "a two-node seen cycle is not dropped material");
  }
});
