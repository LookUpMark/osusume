#!/usr/bin/env node
// Record AniList fixtures for offline dev/tests: node scripts/record-fixtures.mjs <username>
// Requires the AniList API to be reachable. Writes fixtures/{userlist,candidates,recommendations}.json
import { writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";

const { fetchUserList, fetchRecommendations } = await import("../src/server/anilist.ts");
const { fetchCandidates } = await import("../src/server/candidates.ts");
const { buildProfile, entrySentiment } = await import("../src/server/profile.ts");
// check AFTER the imports: config.ts auto-loads .env, so process.env alone lies
// about what the server modules will actually see
const { ANILIST_FIXTURES } = await import("../src/server/config.ts");
if (ANILIST_FIXTURES) {
  console.error("ANILIST_FIXTURES must be unset to record real fixtures");
  process.exit(1);
}

const username = process.argv[2];
if (!username) {
  console.error("usage: node scripts/record-fixtures.mjs <anilist-username>");
  process.exit(1);
}

console.log(`fetching list of ${username}…`);
const { entries, mediaById } = await fetchUserList(username);
console.log(`${entries.length} entries`);

const profile = buildProfile(entries, mediaById, username);
const listIds = new Set(entries.map((e) => e.mediaId));
console.log("fetching candidate pool (~13 requests, rate-limited)…");
const candidates = await fetchCandidates(profile, listIds);
console.log(`${candidates.length} candidates`);

console.log("fetching community recommendations (top 5)…");
const top5 = [...entries]
  .map((e) => ({ e, s: entrySentiment(e, profile.meanScore).s }))
  .sort((a, b) => b.s - a.s)
  .slice(0, 5);
const recMap = {};
let recFails = 0;
for (const { e } of top5) {
  const recs = await fetchRecommendations(e.mediaId).catch(() => {
    recFails++;
    return [];
  });
  if (recs.length > 0) recMap[String(e.mediaId)] = recs;
}
if (recFails > 0) {
  console.error(`${recFails}/${top5.length} recommendation fetches failed — fixtures are partial`);
  process.exitCode = 1;
}

await mkdir("fixtures", { recursive: true });
await writeFile(
  join("fixtures", "userlist.json"),
  JSON.stringify({ entries, media: [...mediaById.values()] }, null, 2),
);
await writeFile(join("fixtures", "candidates.json"), JSON.stringify(candidates, null, 2));
await writeFile(join("fixtures", "recommendations.json"), JSON.stringify(recMap, null, 2));
console.log("fixtures written: userlist.json, candidates.json, recommendations.json");
