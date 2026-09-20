/**
 * Display formulas — CONTRACT (see frontend/README.md): OpenDesign may
 * regenerate the markup around them, never the formulas themselves.
 */

/** Match score as shown to the user: Math.round(final * 100), always rendered "/110". */
export const score110 = (final: number): number => Math.round(final * 100);

/** Community 0..10 → 0..100 bar percentage (DetailDialog breakdown row). */
export const communityBar = (community: number): number => community / 0.1;

/** NEXT_STEP → "badgeNextStep" (i18n key, same scheme as the scoring server). */
export const badgeKey = (b: string): string =>
  `badge${b.split("_").map((w) => w[0] + w.slice(1).toLowerCase()).join("")}`;

/** Meta line under a title: drop the missing fields, join the rest with " · ". */
export const metaJoin = (parts: (string | number | null | undefined)[]): string =>
  parts.filter(Boolean).join(" · ");
