import type { RecoResult, ScoredReco } from "../types.ts";

export type SortKey = "final" | "gem" | "affinity";

export const gemRank = (r: ScoredReco): number =>
  r.badges.includes("HIDDEN_GEM")
    ? r.breakdown.affinity - r.media.popularity / 1_000_000
    : Number.NEGATIVE_INFINITY; // outside the value domain — no config coupling

export interface Filters {
  gemsOnly: boolean;
  format: string;
  genre: string;
  sort: SortKey;
}

/** Grid pipeline: gemsOnly → format → genre, in this order, then the sort.
 *  "final" keeps the server's diversified default order (mmRank). */
export const applyFilters = (recos: ScoredReco[], f: Filters): ScoredReco[] => {
  let list = recos;
  if (f.gemsOnly) list = list.filter((r) => r.badges.includes("HIDDEN_GEM"));
  if (f.format !== "all") list = list.filter((r) => r.media.format === f.format);
  if (f.genre !== "all") list = list.filter((r) => r.media.genres.includes(f.genre));
  const sorted = [...list];
  if (f.sort === "gem") sorted.sort((a, b) => gemRank(b) - gemRank(a));
  else if (f.sort === "affinity") sorted.sort((a, b) => b.breakdown.affinity - a.breakdown.affinity);
  else sorted.sort((a, b) => (a.mmRank ?? 1e6) - (b.mmRank ?? 1e6)); // server's diversified default order
  return sorted;
};

/** Home top picks by final score — hero is [0], the carousel is slice(0, 8). */
export const topPicksOf = (result: RecoResult | null): ScoredReco[] =>
  result ? [...result.recos].sort((a, b) => b.final - a.final) : [];
export const heroPick = (top: ScoredReco[]): ScoredReco | null => top[0] ?? null;
export const carouselPicks = (top: ScoredReco[]): ScoredReco[] => top.slice(0, 8);

/** Hidden gems, best taste affinity first. */
export const gemsOf = (result: RecoResult | null): ScoredReco[] =>
  result
    ? result.recos.filter((r) => r.badges.includes("HIDDEN_GEM")).sort((a, b) => b.breakdown.affinity - a.breakdown.affinity)
    : [];

/** Top-9 genres by frequency across the recommended list (home chips). */
export const topGenres = (result: RecoResult | null): string[] => {
  if (!result) return [];
  const freq = new Map<string, number>();
  for (const r of result.recos) for (const g of r.media.genres) freq.set(g, (freq.get(g) ?? 0) + 1);
  return [...freq].sort((a, b) => b[1] - a[1]).slice(0, 9).map(([g]) => g);
};

/** Formats present in the list (toolbar filter), first-seen order. */
export const formatsOf = (result: RecoResult | null): string[] =>
  [...new Set((result?.recos ?? []).map((r) => r.media.format).filter(Boolean))] as string[];
