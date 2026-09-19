import { createHash } from "node:crypto";
import type { Dim, DimValue, ListEntry, ListStatus, MediaLite, TasteProfile } from "../shared/types.ts";
import { WEIGHTS } from "./config.ts";

interface Acc {
  sum: number;
  weight: number;
  support: number;
  examples: { title: string; s: number }[];
}

export const clamp = (x: number, lo: number, hi: number): number =>
  Math.min(hi, Math.max(lo, x));

/** Mean of positive scores; falls back to 60 when fewer than 3 entries are scored. */
export function meanScoreOf(entries: ListEntry[]): { mean: number; scoredCount: number } {
  const scored = entries.filter((e) => e.score > 0);
  if (scored.length < 3) return { mean: 60, scoredCount: scored.length };
  return { mean: scored.reduce((a, e) => a + e.score, 0) / scored.length, scoredCount: scored.length };
}

export function entrySentiment(e: ListEntry, mean: number): { s: number; w: number } {
  if (e.status === "PLANNING") return { s: 0, w: 0 };
  const base = WEIGHTS.statusBase[e.status] ?? 0;
  const sRaw = e.score > 0 ? clamp((e.score - mean) / WEIGHTS.scoreSpread, -1, 1) : 0;
  const repeatBonus = WEIGHTS.repeatBonus * Math.min(e.repeat, WEIGHTS.repeatCap);
  // finishing (or rewatching) without rating is still a choice — mild positive,
  // otherwise a list with zero scores has an empty taste profile
  const completionBoost = e.score === 0 && (e.status === "COMPLETED" || e.status === "REPEATING") ? 0.2 : 0;
  const s = clamp(base + sRaw + repeatBonus + completionBoost, -1, 1);
  const w = e.score > 0 ? 1 : e.status === "DROPPED" ? 0.6 : 0.4;
  return { s, w };
}

export const eraBucket = (year: number | null): string | null =>
  year == null ? null : String(5 * Math.floor(year / 5));

function addSentiment(
  acc: Map<string, Acc>,
  dim: Dim,
  value: string | null,
  s: number,
  w: number,
  exampleTitle: string,
  rankFactor: number,
): void {
  if (value == null || value === "") return;
  const key = `${dim}:${value}`;
  const a = acc.get(key) ?? { sum: 0, weight: 0, support: 0, examples: [] };
  a.sum += s * rankFactor;
  a.weight += w * rankFactor;
  if (w * rankFactor > 0) a.support += 1; // zero-weight observations are not evidence
  if (s > 0.3 && !a.examples.some((x) => x.title === exampleTitle)) {
    a.examples.push({ title: exampleTitle, s });
    a.examples.sort((x, y) => y.s - x.s);
    if (a.examples.length > 3) a.examples.pop();
  }
  acc.set(key, a);
}

function finalizeSides(acc: Map<string, Acc>): { loved: DimValue[]; disliked: DimValue[] } {
  const loved: DimValue[] = [];
  const disliked: DimValue[] = [];
  for (const [key, a] of acc) {
    // indexOf split: values may contain ':' themselves (unlike split(':'))
    const colon = key.indexOf(":");
    const dim = key.slice(0, colon) as Dim;
    const value = key.slice(colon + 1);
    if (a.weight === 0 || a.support < WEIGHTS.supportMin) continue;
    const aff = (a.sum / a.weight) * (Math.min(a.support, WEIGHTS.supportShrink) / WEIGHTS.supportShrink);
    const dv: DimValue = { dim, value, aff, support: a.support, examples: a.examples.map((x) => x.title) };
    if (aff > WEIGHTS.lovedMin) loved.push(dv);
    else if (aff < -WEIGHTS.lovedMin) disliked.push(dv);
  }
  // cap by affinity strength, not Map insertion order — the strongest tastes must win
  const cap = (dim: Dim, n: number) =>
    loved.filter((d) => d.dim === dim).sort((a, b) => b.aff - a.aff).slice(0, n);
  const capNeg = (dim: Dim, n: number) =>
    disliked.filter((d) => d.dim === dim).sort((a, b) => a.aff - b.aff).slice(0, n);
  return {
    loved: [
      ...cap("tag", WEIGHTS.topTags),
      ...cap("genre", WEIGHTS.topGenres),
      ...cap("studio", WEIGHTS.topStudios),
      ...cap("era", 4),
    ],
    disliked: [
      ...capNeg("tag", WEIGHTS.topDisliked),
      ...capNeg("genre", 5),
      ...capNeg("studio", 3),
      ...capNeg("era", 2),
    ],
  };
}

/** Build the taste profile from the full AniList list + its media metadata. */
export function buildProfile(
  entries: ListEntry[],
  mediaById: Map<number, MediaLite>,
  userName = "",
): TasteProfile {
  const { mean, scoredCount } = meanScoreOf(entries);
  const acc = new Map<string, Acc>();
  const counts = {
    CURRENT: 0,
    PLANNING: 0,
    COMPLETED: 0,
    DROPPED: 0,
    PAUSED: 0,
    REPEATING: 0,
  } as Record<ListStatus, number>;

  for (const e of entries) {
    counts[e.status] = (counts[e.status] ?? 0) + 1;
    const { s, w } = entrySentiment(e, mean);
    if (w === 0) continue; // PLANNING carries no taste signal
    const m = mediaById.get(e.mediaId);
    addSentiment(acc, "era", eraBucket(m?.seasonYear ?? null), s, w, e.title, 1);
    if (!m) continue;
    for (const g of m.genres) addSentiment(acc, "genre", g, s, w, e.title, 1);
    for (const t of m.tags) addSentiment(acc, "tag", t.name, s, w, e.title, t.rank / 100);
    if (m.studio) addSentiment(acc, "studio", m.studio, s, w, e.title, 1);
  }

  const { loved, disliked } = finalizeSides(acc);
  const hash = createHash("sha256")
    .update(entries.map((e) => `${e.mediaId}:${e.status}:${e.score}:${e.repeat}`).sort().join("|"))
    .digest("hex")
    .slice(0, 16);

  return {
    userName,
    meanScore: Math.round(mean * 10) / 10,
    scoredCount,
    confidence: scoredCount >= 3 ? "ok" : "low",
    counts,
    loved,
    disliked,
    hash,
  };
}
