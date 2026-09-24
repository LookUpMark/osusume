import type { RecoResult } from "../types.ts";

/** Pipeline phases as streamed by GET /api/recommend/stream — the order is the
 *  engine's documented (non-negotiable) operation order, mirrored for the UI. */
export type StreamPhase =
  | "list"
  | "profile"
  | "candidates"
  | "franchise"
  | "community"
  | "mood"
  | "scoring"
  | "links"
  | "whynot";

export const PHASES: readonly StreamPhase[] = [
  "list",
  "profile",
  "candidates",
  "franchise",
  "community",
  "mood",
  "scoring",
  "links",
  "whynot",
];

/** i18n key for a phase (phaseList, phaseProfile, …); unknown → generic copy. */
export const phaseKey = (phase: string): string => {
  const hit = PHASES.find((p) => p === phase);
  return hit ? `phase${hit[0].toUpperCase()}${hit.slice(1)}` : "loadingRecos";
};

/** 1-based step of a phase; 0 when unknown (never shown). */
export const phaseStep = (phase: string): number =>
  PHASES.findIndex((p) => p === phase) + 1;

export interface StreamHandle {
  done: Promise<RecoResult>;
  close: () => void;
}
