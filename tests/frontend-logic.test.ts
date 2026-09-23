import assert from "node:assert/strict";
import { test } from "node:test";
import type { MediaLite, RecoResult, ScoredReco } from "../frontend/src/lib/types.ts";
import { badgeKey, communityBar, metaJoin, score110 } from "../frontend/src/lib/logic/display.ts";
import { errorMessage } from "../frontend/src/lib/logic/errors.ts";
import { detectLang } from "../frontend/src/lib/logic/lang.ts";
import { applyFilters, gemRank, gemsOf, topGenres } from "../frontend/src/lib/logic/recos.ts";

const media = (over: Partial<MediaLite> = {}): MediaLite => ({
  id: 1,
  title: "t",
  format: "TV",
  seasonYear: 2015,
  genres: ["Drama"],
  tags: [],
  studio: null,
  averageScore: 70,
  popularity: 50_000,
  coverImage: null,
  coverColor: null,
  siteUrl: null,
  description: null,
  relations: [],
  ...over,
});

const reco = (over: {
  media?: Partial<MediaLite>;
  breakdown?: Partial<ScoredReco["breakdown"]>;
  badges?: string[];
} = {}): ScoredReco =>
  ({
    media: media(over.media),
    final: 1.049,
    breakdown: { affinity: 0.9, quality: 0.8, community: 8.2, ...over.breakdown },
    badges: over.badges ?? [],
    groupSize: 1,
  }) as ScoredReco;

const asResult = (recos: ScoredReco[]): RecoResult => ({ recos, avoided: [] }) as unknown as RecoResult;

test("score110 / communityBar: formule display del contratto", () => {
  assert.equal(score110(1.049), 105);
  assert.equal(score110(0), 0);
  assert.equal(communityBar(8.2), 8.2 / 0.1); // la barra arrotonda poi in BrkRow (Math.round(v * 100))
  assert.equal(Math.round(communityBar(8.2) * 100), 8200);
});

test("badgeKey: NEXT_STEP → badgeNextStep", () => {
  assert.equal(badgeKey("NEXT_STEP"), "badgeNextStep");
  assert.equal(badgeKey("HIDDEN_GEM"), "badgeHiddenGem");
});

test("metaJoin: scarta i campi vuoti e unisce con ' · '", () => {
  assert.equal(metaJoin([2015, "TV", null, undefined]), "2015 · TV");
  assert.equal(metaJoin([null, undefined]), "");
});

test("gemRank: solo le gem, popularity tie-break", () => {
  const gem = reco({ badges: ["HIDDEN_GEM"], breakdown: { affinity: 0.9 } });
  const plain = reco({});
  assert.equal(gemRank(plain), Number.NEGATIVE_INFINITY);
  assert.equal(gemRank(gem), 0.9 - 50_000 / 1_000_000);
});

test("applyFilters: gemsOnly → format → genre, poi sort", () => {
  const list = [
    reco({ media: { id: 1, title: "a" }, breakdown: { affinity: 0.5 } }),
    reco({ media: { id: 2, title: "b", format: "MOVIE" }, badges: ["HIDDEN_GEM"], breakdown: { affinity: 0.9 } }),
    reco({ media: { id: 3, title: "c", genres: ["Comedy"] }, breakdown: { affinity: 0.7 } }),
  ];
  const out = applyFilters(list, { gemsOnly: false, format: "TV", genre: "Drama", sort: "affinity" });
  assert.deepEqual(out.map((r) => r.media.id), [1]); // MOVIE e Comedy filtrati, in quell'ordine
  const gems = applyFilters(list, { gemsOnly: true, format: "all", genre: "all", sort: "final" });
  assert.deepEqual(gems.map((r) => r.media.id), [2]); // solo la gem
  // "final" non riordina oltre l'ordine diversificato del server (mmRank assente → stabile)
  assert.deepEqual(
    applyFilters(list, { gemsOnly: false, format: "all", genre: "all", sort: "final" }).map((r) => r.media.id),
    [1, 2, 3],
  );
});

test("gemsOf / topGenres: derivati home", () => {
  const r = asResult([
    reco({ media: { id: 1, title: "a", genres: ["Drama", "Comedy"] }, badges: ["HIDDEN_GEM"] }),
    reco({ media: { id: 2, title: "b" } }),
  ]);
  assert.deepEqual(gemsOf(r).map((x) => x.media.id), [1]);
  assert.deepEqual(topGenres(r), ["Drama", "Comedy"]);
  assert.deepEqual(topGenres(null), []);
});

test("errorMessage: user_not_found / anilist_error / generic", () => {
  assert.equal(errorMessage("en", new Error("user_not_found")), "User not found on AniList. Check the spelling.");
  assert.equal(errorMessage("it", new Error("anilist_error")), "AniList non raggiungibile al momento. Riprova tra poco.");
  assert.equal(errorMessage("en", new Error("qualunque")), "Something went wrong. Try again.");
  assert.equal(errorMessage("en", "not an error"), "Something went wrong. Try again.");
});

test("detectLang: saved wins, OS language fallback", () => {
  assert.equal(detectLang(null, "it-IT"), "it");
  assert.equal(detectLang(null, "en-US"), "en");
  assert.equal(detectLang(null, "fr-FR"), "en");
  assert.equal(detectLang("it", "en-US"), "it"); // saved preference wins
  assert.equal(detectLang("en", "it-IT"), "en");
  assert.equal(detectLang("crash", "it-IT"), "it"); // invalid saved → OS
  assert.equal(detectLang(null, ""), "en");
});
