import type { Badge, Lang, MediaLite, ScoredReco, TasteProfile } from "../shared/types.ts";
import { WEIGHTS } from "./config.ts";
import { isSpinOff, type FranchiseInfo } from "./franchise.ts";
import { clamp } from "./profile.ts";
import { tr } from "../shared/strings.ts";

export function affinityMap(p: TasteProfile): Map<string, number> {
  const map = new Map<string, number>();
  for (const d of [...p.loved, ...p.disliked]) map.set(`${d.dim}:${d.value}`, d.aff);
  return map;
}

/** 0 (pop ~100) → 1 (pop ~100k+): gems and mainstream actually separate. */
export function popNorm(m: MediaLite): number {
  return clamp((Math.log10(m.popularity + 1) - 2) / 4, 0, 1);
}

/** 0..1 affinity of a candidate against the profile (disliked values pull down). */
export function affinityOf(m: MediaLite, p: TasteProfile): { affinity01: number; parts: Record<string, number> } {
  const am = affinityMap(p);
  const aff = (dim: string, value: string | null): number =>
    value == null ? 0 : (am.get(`${dim}:${value}`) ?? 0);

  let tagNum = 0;
  let tagDen = 0;
  for (const t of m.tags) {
    tagNum += aff("tag", t.name) * (t.rank / 100);
    tagDen += t.rank / 100;
  }
  const tagScore = tagDen > 0 ? tagNum / tagDen : 0;

  const genreScore =
    m.genres.length > 0
      ? m.genres.reduce((a, g) => a + aff("genre", g), 0) / m.genres.length
      : 0;
  const studioScore = aff("studio", m.studio);
  const eraScore = aff("era", m.seasonYear == null ? null : String(5 * Math.floor(m.seasonYear / 5)));

  const core =
    WEIGHTS.tag * tagScore +
    WEIGHTS.genre * genreScore +
    WEIGHTS.studio * studioScore +
    WEIGHTS.era * eraScore;
  return {
    affinity01: (core + 1) / 2,
    parts: { tag: tagScore, genre: genreScore, studio: studioScore, era: eraScore },
  };
}

export function qualityOf(m: MediaLite): number {
  return WEIGHTS.qualityScore * ((m.averageScore ?? 60) / 100) + WEIGHTS.qualityPop * popNorm(m);
}

export function gemScoreOf(m: MediaLite, affinity01: number, quality: number): number {
  return (
    WEIGHTS.gemAffinity * affinity01 + WEIGHTS.gemQuality * quality - WEIGHTS.gemPopPenalty * popNorm(m)
  );
}

export function isGem(m: MediaLite, gem: number): boolean {
  return (
    m.popularity < WEIGHTS.gemMaxPopularity &&
    (m.averageScore ?? 0) >= WEIGHTS.gemMinScore &&
    gem >= WEIGHTS.gemMinGemScore
  );
}

// --- deterministic explanations -------------------------------------------------

/** Shared loved dims present on the candidate, strongest first. */
export function lovedOverlap(m: MediaLite, p: TasteProfile): { label: string; examples: string[] }[] {
  const tagNames = new Set(m.tags.filter((t) => t.rank >= 60).map((t) => t.name));
  const values = new Set<string>([...m.genres, ...(m.studio ? [m.studio] : [])]);
  const out: { label: string; examples: string[] }[] = [];
  for (const d of [...p.loved].sort((a, b) => b.aff - a.aff)) {
    const hit =
      (d.dim === "tag" && tagNames.has(d.value)) ||
      (d.dim !== "tag" && d.dim !== "era" && values.has(d.value));
    if (hit && d.aff > 0.05) out.push({ label: `${d.dim}:${d.value}`, examples: d.examples.slice(0, 2) });
    if (out.length >= 2) break;
  }
  return out;
}

export function deterministicWhy(
  m: MediaLite,
  p: TasteProfile,
  badges: Badge[],
  lang: Lang,
): string {
  const overlap = lovedOverlap(m, p);
  const examples = [...new Set(overlap.flatMap((o) => o.examples))].slice(0, 3);
  if (overlap.length === 0) {
    // no taste overlap to cite — stay honest: quality + popularity only
    return tr(lang, "whyNeutral", {
      avg: String(m.averageScore ?? "?"),
      pop: m.popularity.toLocaleString(lang),
      gemPart:
        badges.includes("HIDDEN_GEM")
          ? tr(lang, "whyGem", { pop: m.popularity.toLocaleString(lang), avg: String(m.averageScore ?? "?") })
          : "",
    });
  }
  const dims = overlap.map((o) => o.label.split(":").join(" ")).join(", ");
  return tr(lang, "whyBase", {
    dims: dims || tr(lang, "dimGenre"),
    studioPart: "",
    examplesPart:
      examples.length > 0 ? tr(lang, "whyExamples", { examples: examples.join(", ") }) : "",
    gemPart:
      badges.includes("HIDDEN_GEM")
        ? tr(lang, "whyGem", {
            pop: m.popularity.toLocaleString(lang),
            avg: String(m.averageScore ?? "?"),
          })
        : "",
  });
}

/** Null when there is no honest negative evidence. */
export function deterministicWhyNot(
  m: MediaLite,
  p: TasteProfile,
  f: FranchiseInfo | undefined,
  droppedTitle: string | null,
  lang: Lang,
): string | null {
  const tagNames = new Set(m.tags.filter((t) => t.rank >= 60).map((t) => t.name));
  const values = new Set<string>([...m.genres, ...(m.studio ? [m.studio] : [])]);
  const bad: string[] = [];
  const examples: string[] = [];
  for (const d of [...p.disliked].sort((a, b) => a.aff - b.aff)) {
    const hit =
      (d.dim === "tag" && tagNames.has(d.value)) ||
      (d.dim !== "tag" && d.dim !== "era" && values.has(d.value));
    if (hit && d.aff < -0.3) {
      bad.push(`${d.dim} ${d.value}`);
      examples.push(...d.examples.slice(0, 2));
    }
    if (bad.length >= 2) break;
  }
  if (bad.length === 0 && !droppedTitle) return null;
  const uniqueExamples = [...new Set(examples)].slice(0, 3);
  return tr(lang, "whyNotBase", {
    dims: bad.join(", "),
    examplesPart:
      uniqueExamples.length > 0
        ? tr(lang, "whyNotExamples", { examples: uniqueExamples.join(", ") })
        : "",
    droppedPart: droppedTitle ? tr(lang, "whyNotDropped", { title: droppedTitle }) : "",
  });
}

// --- scoring --------------------------------------------------------------------

export function scoreAll(
  candidates: MediaLite[],
  p: TasteProfile,
  community: Map<number, number>,
  franchise: Map<number, FranchiseInfo>,
  lang: Lang,
): ScoredReco[] {
  const out: ScoredReco[] = [];
  for (const m of candidates) {
    const { affinity01 } = affinityOf(m, p);
    const quality = qualityOf(m);
    const comm = Math.min(WEIGHTS.communityCap, community.get(m.id) ?? 0);
    const f = franchise.get(m.id);
    const badges: Badge[] = [];
    if (f?.kind === "NEXT_STEP") badges.push("NEXT_STEP");
    if (f?.kind === "ENTRY_POINT") badges.push("ENTRY_POINT");
    if (isSpinOff(m)) badges.push("SPIN_OFF");
    const gem = gemScoreOf(m, affinity01, quality);
    if (isGem(m, gem)) badges.push("HIDDEN_GEM");

    const final = clamp(
      WEIGHTS.affinity * affinity01 +
        WEIGHTS.quality * quality +
        comm +
        (badges.includes("NEXT_STEP") ? WEIGHTS.franchiseBonus : 0),
      0,
      1.1,
    );
    out.push({
      media: m,
      final,
      breakdown: { affinity: affinity01, quality, community: comm },
      badges,
      rootId: f?.kind === "STANDALONE" ? null : (f?.rootId ?? null),
      groupSize: 1,
      why: deterministicWhy(m, p, badges, lang),
    });
  }
  out.sort((a, b) => b.final - a.final);
  return out;
}

/** Keep one representative per franchise; annotate group sizes. */
export function dedupeFranchises(recos: ScoredReco[]): ScoredReco[] {
  const bestByRoot = new Map<number, ScoredReco>();
  const sizeByRoot = new Map<number, number>();
  for (const r of recos) {
    if (r.rootId == null) continue;
    sizeByRoot.set(r.rootId, (sizeByRoot.get(r.rootId) ?? 0) + 1);
    const best = bestByRoot.get(r.rootId);
    if (!best || r.final > best.final) bestByRoot.set(r.rootId, r);
  }
  const kept = new Set(bestByRoot.values());
  return recos
    .filter((r) => r.rootId == null || kept.has(r))
    .map((r) =>
      r.rootId == null
        ? r
        : { ...r, groupSize: sizeByRoot.get(r.rootId) ?? 1 },
    );
}
