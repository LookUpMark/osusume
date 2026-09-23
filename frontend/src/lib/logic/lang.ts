import type { Lang } from "../types.ts";

/** Saved preference wins (validate, never cast); otherwise follow the OS
 *  language — any it-* locale starts in Italian, everything else English. */
export const detectLang = (saved: string | null, nav: string): Lang =>
  saved === "it" || saved === "en" ? saved : nav.toLowerCase().startsWith("it") ? "it" : "en";
