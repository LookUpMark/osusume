import type { Lang, RecoResult } from "../shared/types.ts";
import { cleanText, llmChat, resolveServedModel } from "./llm.ts";
import { lovedOverlap } from "./scoring.ts";

const LANG_NAME: Record<Lang, string> = { en: "English", it: "Italian" };

/** System prompt: the model is an anime expert friend, NOT a dashboard. It may
 *  only discuss what the UI already shows — but in terms a viewer cares about:
 *  plot, themes, atmosphere, connections with what they have already watched.
 *  Algorithm-speak (affinity, match %, "the algorithm") is explicitly banned:
 *  scores are internal reference material, quoted only if the user asks. */
export function buildChatSystem(result: RecoResult, lang: Lang): string {
  const p = result.profile;
  const recos = result.recos
    .slice(0, 10)
    .map((r) => {
      const overlap = lovedOverlap(r.media, p);
      const links = overlap
        .map((o) => {
          const theme = o.label.split(":").pop();
          return `${theme} (they enjoyed it in ${o.examples.join(", ")})`;
        })
        .join("; ");
      const themes = r.media.tags
        .filter((t) => t.rank >= 60 && !t.isSpoiler)
        .slice(0, 5)
        .map((t) => t.name)
        .join(", ");
      const plot = cleanText(r.media.description, 450);
      const badges = r.badges.includes("HIDDEN_GEM") ? " [less-known gem]" : "";
      return (
        `- "${r.media.title}" (${r.media.seasonYear ?? "?"}, studio ${r.media.studio ?? "?"}; ` +
        `genres: ${r.media.genres.slice(0, 3).join(", ")}${themes ? `; themes: ${themes}` : ""})${badges}\n` +
        `  plot: ${plot || "not available"}\n` +
        `  links to the user: ${links || "none obvious"}\n` +
        `  internal match reference: ${Math.round(r.final * 100)}/110`
      );
    })
    .join("\n");
  const loved = p.loved
    .slice(0, 8)
    .map((d) => `${d.value} (seen in ${d.examples.slice(0, 2).join(", ") || "n/a"})`)
    .join("; ");
  const disliked = p.disliked.slice(0, 5).map((d) => d.value).join(", ");
  const avoided = result.avoided
    .slice(0, 5)
    .map((a) => `"${a.media.title}" (${a.reason})`)
    .join("; ");
  return (
    `You are Osusume, a knowledgeable, warm anime expert chatting with ${p.userName}. ` +
    `They are a viewer, not a data scientist: they care about STORIES, not metrics.\n\n` +
    `HOW TO TALK:\n` +
    `- Answer the question they ACTUALLY asked. "Why would the plot interest me?" means talk about the plot, themes, tone and emotions — not about scores or the app.\n` +
    `- Connect titles to what they have already watched ("since you enjoyed X, which shares Y…"), using the links provided.\n` +
    `- BANNED words: "affinity", "quality %", "match score", "the algorithm", "prioritized", "profile" — never explain the app's mechanics. If strength matters, say it in words ("widely beloved", "a hidden gem many missed"). The internal match reference numbers are for you ONLY; quote them verbatim just if explicitly asked about scores.\n` +
    `- Ground claims in the plot texts and themes provided; general knowledge of the titles listed is fine, inventing plot points is not. If unsure about a detail, say so.\n` +
    `- Conversational: 2-5 sentences unless the question needs more. No bullet lists unless asked. Reply in ${LANG_NAME[lang]}.\n\n` +
    `THE USER: loves ${loved || "not enough data"}; dislikes ${disliked || "nothing notable"}; ` +
    `mean score ${p.meanScore}, ${p.counts.COMPLETED} completed.\n\n` +
    `CURRENT RECOMMENDATIONS:\n${recos || "(none yet)"}` +
    (avoided ? `\n\nTITLES SUGGESTED TO AVOID (do not recommend): ${avoided}` : "")
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
