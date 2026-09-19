import assert from "node:assert/strict";
import { test } from "node:test";
import type { ListEntry, MediaLite } from "../src/shared/types.ts";
import { buildProfile, entrySentiment, eraBucket, meanScoreOf } from "../src/server/profile.ts";

const entry = (mediaId: number, status: ListEntry["status"], score: number, repeat = 0): ListEntry => ({
  mediaId,
  status,
  score,
  repeat,
  title: `m${mediaId}`,
});

const media = (id: number, over: Partial<MediaLite> = {}): MediaLite => ({
  id,
  title: `m${id}`,
  format: "TV",
  seasonYear: 2014,
  genres: ["Drama"],
  tags: [{ name: "Psychological", rank: 90, isSpoiler: false }],
  studio: "Madhouse",
  averageScore: 75,
  popularity: 100000,
  coverImage: null,
  coverColor: null,
  siteUrl: null,
  description: null,
  relations: [],
  ...over,
});

test("meanScoreOf ignores unscored and falls back to 60 below 3 scores", () => {
  assert.equal(meanScoreOf([entry(1, "COMPLETED", 80), entry(2, "COMPLETED", 90)]).mean, 60);
  const { mean, scoredCount } = meanScoreOf([
    entry(1, "COMPLETED", 80),
    entry(2, "COMPLETED", 90),
    entry(3, "COMPLETED", 100),
    entry(4, "DROPPED", 0),
  ]);
  assert.equal(mean, 90);
  assert.equal(scoredCount, 3);
});

test("unscored completion is a weak positive: zero-score lists get a taste profile", () => {
  const s = entrySentiment(entry(1, "COMPLETED", 0), 60).s;
  assert.ok(s > 0.1 && s < 0.3, `mild positive, got ${s}`);
  assert.equal(entrySentiment(entry(2, "REPEATING", 0), 60).s > 0, true, "rewatch too");
  assert.equal(entrySentiment(entry(3, "PAUSED", 0), 60).s < 0, true, "paused stays negative");
  // a list with zero scores still yields loved dims (the LookUpMark case)
  const mediaById = new Map([[1, media(0)]]);
  const p = buildProfile([entry(1, "COMPLETED", 0), entry(1, "COMPLETED", 0)], mediaById, "t");
  assert.ok(p.loved.length > 0, "Psychological lands in loved");
});

test("entrySentiment: above-mean scored, repeat bonus, planning excluded, dropped heavy negative", () => {
  const { mean } = meanScoreOf([
    entry(1, "COMPLETED", 60),
    entry(2, "COMPLETED", 80),
    entry(3, "COMPLETED", 100),
  ]);
  assert.equal(entrySentiment(entry(4, "PLANNING", 0), mean).w, 0);
  // 90 is +10 over mean 80 → 0.25 raw
  assert.equal(entrySentiment(entry(4, "COMPLETED", 90), mean).s, 0.25);
  // repeat adds 0.1 per rewatch (capped at 3)
  assert.equal(entrySentiment(entry(4, "COMPLETED", 90, 2), mean).s, 0.45);
  assert.equal(entrySentiment(entry(4, "COMPLETED", 90, 7), mean).s, 0.55);
  // dropped 0-score: statusBase −0.6
  assert.equal(entrySentiment(entry(4, "DROPPED", 0), mean).s, -0.6);
  // unscored completed still carries weight 0.4
  assert.equal(entrySentiment(entry(4, "COMPLETED", 0), mean).w, 0.4);
});

test("eraBucket floors to 5-year buckets", () => {
  assert.equal(eraBucket(2017), "2015");
  assert.equal(eraBucket(null), null);
});

test("entrySentiment: clamp bounds are exact", () => {
  const { mean } = meanScoreOf([entry(1, "COMPLETED", 60), entry(2, "COMPLETED", 80), entry(3, "COMPLETED", 100)]);
  // +40 over mean 80 → sRaw exactly +1
  assert.equal(entrySentiment(entry(4, "COMPLETED", 120), mean).s, 1);
  // far below mean + dropped status → clamps to -1, never below
  assert.equal(entrySentiment(entry(4, "DROPPED", 0), 60).s, -0.6);
  assert.equal(entrySentiment(entry(4, "PAUSED", 20), 80).s, -1);
  // repeat bonus can push over 1 → total clamps
  assert.equal(entrySentiment(entry(4, "CURRENT", 120, 3), mean).s, 1);
});

test("buildProfile: loved tag from high scores, disliked genre from drops, planning ignored", () => {
  const entries: ListEntry[] = [
    entry(1, "COMPLETED", 95),
    entry(2, "COMPLETED", 92),
    entry(3, "DROPPED", 0),
    entry(4, "DROPPED", 0),
    entry(5, "PLANNING", 0),
    entry(6, "COMPLETED", 40),
  ];
  const byId = new Map<number, MediaLite>([
    [1, media(1, { genres: ["Psychological"], tags: [{ name: "Psychological", rank: 95, isSpoiler: false }] })],
    [2, media(2, { genres: ["Psychological"], tags: [{ name: "Psychological", rank: 90, isSpoiler: false }] })],
    [3, media(3, { genres: ["Isekai"], tags: [{ name: "Isekai", rank: 85, isSpoiler: false }] })],
    [4, media(4, { genres: ["Isekai"], tags: [{ name: "Isekai", rank: 80, isSpoiler: false }] })],
    [5, media(5, { genres: ["Fantasy"], tags: [] })],
    [6, media(6, { genres: ["Slice of Life"], tags: [] })],
  ]);
  const p = buildProfile(entries, byId, "testuser");
  assert.equal(p.confidence, "ok");
  assert.equal(p.counts.DROPPED, 2);
  assert.ok(p.loved.some((d) => d.dim === "tag" && d.value === "Psychological"));
  assert.ok(p.loved.some((d) => d.dim === "genre" && d.value === "Psychological"));
  assert.ok(p.disliked.some((d) => d.value === "Isekai"), "dropped genre must be disliked");
  assert.ok(!p.loved.some((d) => d.value === "Fantasy"), "planning entries carry no signal");
  assert.ok(p.hash.length === 16);
});

test("buildProfile: low confidence when fewer than 3 scores", () => {
  const p = buildProfile([entry(1, "COMPLETED", 90), entry(2, "DROPPED", 0)], new Map(), "u");
  assert.equal(p.confidence, "low");
});
