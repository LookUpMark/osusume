import type { Lang, RecoResult } from "../shared/types.ts";
import { llmChat, resolveServedModel } from "./llm.ts";

const LANG_NAME: Record<Lang, string> = { en: "English", it: "Italian" };

/** System prompt: the model can only discuss what the UI already shows — the
 *  current recommendations, the taste profile, the avoid list — grounded in the
 *  exact scores and reasons it can be asked about. */
export function buildChatSystem(result: RecoResult, lang: Lang): string {
  const p = result.profile;
  const recos = result.recos
    .slice(0, 10)
    .map(
      (r, i) =>
        `${i + 1}. "${r.media.title}" (${r.media.seasonYear ?? "?"}, ${r.media.studio ?? "?"}) — match ` +
        `${Math.round(r.final * 100)}/110 (affinity ${Math.round(r.breakdown.affinity * 100)}%, ` +
        `quality ${Math.round(r.breakdown.quality * 100)}%): ${r.why}`,
    )
    .join("\n");
  const loved = p.loved
    .slice(0, 5)
    .map((d) => `${d.value} (${Math.round(d.aff * 100)}%)`)
    .join(", ");
  const disliked = p.disliked.slice(0, 5).map((d) => d.value).join(", ");
  const avoided = result.avoided.slice(0, 5).map((a) => a.media.title).join(", ");
  return (
    `You are Osusume, an anime recommendation assistant, chatting with AniList user ${p.userName}. ` +
    `Reply in ${LANG_NAME[lang]}, naturally and concisely (2-5 sentences unless the question needs more). ` +
    `You can only discuss the data below (the current recommendations, the taste profile, the avoid list) plus general context about those titles. ` +
    `Ground every claim in the list: cite titles, match scores out of 110, affinity/quality percentages and the match reasons. ` +
    `Do not invent recommendations outside the list — if asked for more, say the list is what the app found.\n\n` +
    `USER TASTE — loves: ${loved || "not enough data"}. Dislikes: ${disliked || "nothing notable"}. ` +
    `Mean score ${p.meanScore}, ${p.counts.COMPLETED} completed.\n\n` +
    `CURRENT RECOMMENDATIONS:\n${recos || "(none yet)"}` +
    (avoided ? `\n\nSUGGESTED TO AVOID: ${avoided}` : "")
  );
}

/** history is the client-side conversation (already trimmed by the API layer). */
export async function chatReply(
  result: RecoResult,
  lang: Lang,
  history: { role: "user" | "assistant"; content: string }[],
): Promise<string> {
  const model = await resolveServedModel();
  return llmChat([{ role: "system", content: buildChatSystem(result, lang) }, ...history], model);
}
