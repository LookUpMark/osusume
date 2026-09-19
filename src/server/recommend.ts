import type { Lang, MediaLite, RecoResult, ScoredReco, TasteProfile, WhyNot } from "../shared/types.ts";
import { fetchCandidates } from "./candidates.ts";
import { fetchMediaByIds, fetchMediaSearch, fetchRecommendations, fetchUserList } from "./anilist.ts";
import { buildProfile, entrySentiment } from "./profile.ts";
import { analyzeFranchises } from "./franchise.ts";
import { buildSeenCorpus, dedupeFranchises, deterministicWhyNot, diversify, scoreAll, textLinks, tokenize } from "./scoring.ts";
import { WEIGHTS, localModeOn } from "./config.ts";

// in-memory result cache: profile+pool are the expensive part; explain() reuses it
const resultCache = new Map<string, { at: number; result: RecoResult }>();
const RESULT_TTL_MS = 10 * 60 * 1000;
// identical concurrent requests share one computation instead of racing
const inflight = new Map<string, Promise<RecoResult>>();

/** Cheap: list fetch (disk-cached 1h) + profile build. No candidate pool. */
export async function getProfile(username: string) {
  const { entries, mediaById } = await fetchUserList(username);
  return buildProfile(entries, mediaById, username);
}

/** Plot-text corpus of positively-sentiment watched titles (shared by the main
 *  pipeline and the arbitrary-title lookup). */
function seenCorpusFor(
  entries: Awaited<ReturnType<typeof fetchUserList>>["entries"],
  mediaById: Map<number, MediaLite>,
  meanScore: number,
) {
  return buildSeenCorpus(
    entries.map((e) => ({
      title: mediaById.get(e.mediaId)?.title ?? "",
      description: mediaById.get(e.mediaId)?.description ?? null,
      sentiment: entrySentiment(e, meanScore).s,
    })),
  );
}

/** Score arbitrary titles (chat lookup / explain / chat extras) against the
 *  user's taste: same scoring core, empty franchise/community context. */
export async function scoreArbitrary(
  ids: number[],
  username: string,
  lang: Lang,
): Promise<{ profile: TasteProfile; recos: ScoredReco[] }> {
  const { entries, mediaById } = await fetchUserList(username);
  const profile = buildProfile(entries, mediaById, username);
  const media = await fetchMediaByIds(ids);
  const scored = scoreAll(media, profile, new Map(), new Map(), lang);
  const corpus = seenCorpusFor(entries, mediaById, profile.meanScore);
  if (corpus.length > 0) {
    for (const r of scored) {
      const links = textLinks(r.media, corpus);
      if (links.length > 0) r.links = links;
    }
  }
  return { profile, recos: scored };
}

/** Search AniList by title and score the matches against the user's taste. */
export async function lookupMedia(username: string, q: string, lang: Lang): Promise<ScoredReco[]> {
  const media = await fetchMediaSearch(q);
  if (media.length === 0) return [];
  const { recos } = await scoreArbitrary(media.map((m) => m.id), username, lang);
  const order = new Map(media.map((m, i) => [m.id, i]));
  return recos.sort((a, b) => (order.get(a.media.id) ?? 0) - (order.get(b.media.id) ?? 0));
}

export async function getRecommendation(
  username: string,
  lang: Lang,
  opts: { refresh?: boolean; staleOk?: boolean } = {},
): Promise<RecoResult> {
  // mode in the key: a cached local-mode result must never resurface after
  // the app switches back to live AniList data
  const cacheKey = `${username}:${lang}:${localModeOn() ? "local" : "live"}`;
  if (!opts.refresh) {
    const hit = resultCache.get(cacheKey);
    if (hit && Date.now() - hit.at < RESULT_TTL_MS) return hit.result;
    // staleOk (chat context): better an expired result than a 1-minute recompute
    // — and if the recompute fails anyway, the last good result still answers
    if (hit && opts.staleOk) return hit.result;
    const pending = inflight.get(cacheKey);
    if (pending) return pending;
  }
  const p = recommendFor(username, lang, opts).finally(() => inflight.delete(cacheKey));
  inflight.set(cacheKey, p);
  try {
    const result = await p;
    for (const [k, v] of resultCache) {
      if (Date.now() - v.at >= RESULT_TTL_MS) resultCache.delete(k); // prune on write
    }
    resultCache.set(cacheKey, { at: Date.now(), result });
    return result;
  } catch (e) {
    if (opts.staleOk) {
      const hit = resultCache.get(cacheKey);
      if (hit) return hit.result;
    }
    throw e;
  }
}

async function recommendFor(
  username: string,
  lang: Lang,
  opts: { refresh?: boolean },
): Promise<RecoResult> {
  const { entries, mediaById } = await fetchUserList(username);
  const profile = buildProfile(entries, mediaById, username);
  const listIds = new Set(entries.map((e) => e.mediaId));
  const listMap = new Map(entries.map((e) => [e.mediaId, e]));

  // 1st franchise pass: sequel chains collapse to their entry point.
  // epMap: entryPointId → superseded candidate (the sequel shown instead must go).
  const candidates0 = await fetchCandidates(profile, listIds);
  const franchise0 = analyzeFranchises(candidates0, listMap);
  const epMap = new Map<number, number>();
  const skipped = new Set<number>();
  for (const [id, f] of franchise0) {
    if (f.kind !== "ENTRY_POINT" || f.entryPointId == null || f.entryPointId === id) continue;
    if (listMap.get(f.entryPointId)?.status === "PLANNING") {
      skipped.add(id); // already planned the right entry — say nothing
      continue;
    }
    epMap.set(f.entryPointId, id);
  }
  const missingEntries = [...epMap.keys()].filter(
    (id) => !candidates0.some((c) => c.id === id) && !listIds.has(id),
  );
  const extra = await fetchMediaByIds(missingEntries).catch(() => []);
  const superseded = new Set(epMap.values());
  const candidates = [
    ...candidates0.filter((c) => !superseded.has(c.id) && !skipped.has(c.id)),
    ...extra.filter((m) => !candidates0.some((c) => c.id === m.id)),
  ];
  const franchise = analyzeFranchises(candidates, listMap);
  // an entry point pulled in for a superseded sequel earns the badge unless
  // its own analysis already classified it (NEXT_STEP when its prequels are seen)
  for (const [epId] of epMap) {
    const f = franchise.get(epId);
    if (f?.kind === "STANDALONE") {
      franchise.set(epId, { ...f, kind: "ENTRY_POINT", entryPointId: epId });
    }
  }

  // community signal: recommendation graph of the user's top-5 positively-rated entries
  const community = new Map<number, number>();
  const top5 = [...entries]
    .map((e) => ({ e, s: entrySentiment(e, profile.meanScore).s }))
    .filter(({ s }) => s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, 5);
  const recLists = await Promise.all(
    top5.map(({ e }) =>
      fetchRecommendations(e.mediaId).catch((err) => {
        console.warn(`community fetch failed for ${e.mediaId}:`, (err as Error).message);
        return [];
      }),
    ),
  );
  for (const recs of recLists) {
    for (const { targetId, rating } of recs) {
      if (rating <= 0 || !candidates.some((c) => c.id === targetId)) continue;
      community.set(
        targetId,
        Math.min(WEIGHTS.communityCap, (community.get(targetId) ?? 0) + WEIGHTS.communityPerHit),
      );
    }
  }

  // mood continuity (scoring v2): the last 5 completed titles shape what feels
  // like a natural "next watch" — small bonus on candidates sharing their vocabulary
  const recent = [...entries]
    .filter((e) => e.status === "COMPLETED" && (e.updatedAt ?? 0) > 0)
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
    .slice(0, 5);
  const mood = new Map<number, number>();
  if (recent.length > 0) {
    const moodTexts = recent.map((e) => {
      const m = mediaById.get(e.mediaId);
      return tokenize(`${m?.description ?? ""} ${m?.title ?? ""}`);
    });
    for (const c of candidates) {
      if (franchise.get(c.id)?.kind === "EXCLUDED") continue;
      const themes = c.tags.filter((t) => t.rank >= 60 && !t.isSpoiler).map((t) => t.name).join(" ");
      const tok = tokenize(`${c.description ?? ""} ${themes}`);
      const shared = [...tok].filter((w) => moodTexts.some((t) => t.has(w))).length;
      if (shared >= 4) mood.set(c.id, WEIGHTS.mood);
    }
  }

  const scored = scoreAll(
    candidates.filter((c) => franchise.get(c.id)?.kind !== "EXCLUDED"),
    profile,
    community,
    franchise,
    lang,
    mood,
  );
  // dedupe (canonical roots keep groups stable) then MMR-diversify: mmRank drives
  // the default order so near-duplicates don't stack at the top of the list
  const withGroups = diversify(dedupeFranchises(scored)).slice(0, 50);

  // plot-text links (scoring v2): connect each recommendation to positively-rated
  // watched titles through shared plot vocabulary — grounds LLM chat/explanations
  const corpus = seenCorpusFor(entries, mediaById, profile.meanScore);
  if (corpus.length > 0) {
    for (const r of withGroups) {
      const links = textLinks(r.media, corpus);
      if (links.length > 0) r.links = links;
    }
  }

  // anti-recommendations: weakest affinity candidates + dropped-series sequels,
  // with honest negative evidence, never duplicating something already recommended
  const shownIds = new Set(withGroups.map((r) => r.media.id));
  const bottom = [...scored]
    .filter((r) => !shownIds.has(r.media.id))
    .sort((a, b) => a.breakdown.affinity - b.breakdown.affinity)
    .slice(0, 12);
  const avoided: WhyNot[] = [];
  const collectWhyNot = (media: WhyNot["media"]): void => {
    if (shownIds.has(media.id) || avoided.some((a) => a.media.id === media.id)) return;
    const f = franchise.get(media.id);
    const droppedTitle = f?.droppedId != null ? (listMap.get(f.droppedId)?.title ?? null) : null;
    const reason = deterministicWhyNot(media, profile, f, droppedTitle, lang);
    if (reason) avoided.push({ media, reason });
  };
  for (const r of bottom) {
    collectWhyNot(r.media);
    if (avoided.length >= 3) break;
  }
  // excluded-by-dropped-prequel candidates are never in `scored` — surface them here
  for (const c of candidates) {
    if (avoided.length >= 3) break;
    if (franchise.get(c.id)?.kind !== "EXCLUDED") continue;
    collectWhyNot(c);
  }

  return { profile, recos: withGroups, avoided };
}
