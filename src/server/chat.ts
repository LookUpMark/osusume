import type { Lang, RecoResult, ScoredReco } from "../shared/types.ts";
import { gatherReviews, type ReviewLite } from "./anilist.ts";
import { cleanText, isTruncation, llmChat, resolveServedModel, COMPARISON_STANDARD } from "./llm.ts";
import { lovedOverlap } from "./scoring.ts";

const LANG_NAME: Record<Lang, string> = { en: "English", it: "Italian" };

/** System prompt: the model is an anime expert friend, NOT a dashboard. It may
 *  only discuss what the UI already shows — but in terms a viewer cares about:
 *  plot, themes, atmosphere, connections with what they have already watched.
 *  Algorithm-speak (affinity, match %, "the algorithm") is explicitly banned:
 *  scores are internal reference material, quoted only if the user asks. */
export function buildChatSystem(
  result: RecoResult,
  lang: Lang,
  extraRecos: ScoredReco[] = [],
  reviews: Map<number, ReviewLite[]> = new Map(),
): string {
  const p = result.profile;
  const recos = [
    ...result.recos.slice(0, 12), // the full list the recos view shows — nothing on screen is off-limits
    ...extraRecos.slice(0, 5), // titles the user looked up in chat — always in context
  ]
    .map((r) => {
      const overlap = lovedOverlap(r.media, p);
      const leads = overlap
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
      const plotLinks = (r.links ?? [])
        .map((l) => `shares imagery (${l.shared.join(", ")}) with "${l.title}"`)
        .join("; ");
      const revs = (reviews.get(r.media.id) ?? [])
        .map((v) => `"${v.body}"`)
        .join(" | ");
      const badges = r.badges.includes("HIDDEN_GEM") ? " [less-known gem]" : "";
      return (
        `- "${r.media.title}" (${r.media.seasonYear ?? "?"}, studio ${r.media.studio ?? "?"}; ` +
        `genres: ${r.media.genres.slice(0, 3).join(", ")}${themes ? `; themes: ${themes}` : ""})${badges}\n` +
        `  plot: ${plot || "not available"}\n` +
        (revs ? `  reception: ${revs}\n` : "") +
        `  possible leads (verify, drop if shallow): ${[leads, plotLinks].filter(Boolean).join("; ") || "none obvious"}\n` +
        `  internal match reference: ${Math.round(r.final * 100)}/110`
      );
    })
    .join("\n");
  const loved = p.loved
    .slice(0, 10)
    .map((d) => `${d.value} (seen in ${d.examples.slice(0, 3).join(", ") || "n/a"})`)
    .join("; ");
  const disliked = p.disliked.slice(0, 5).map((d) => d.value).join(", ");
  const avoided = result.avoided
    .slice(0, 5)
    .map((a) => `"${a.media.title}" (${a.reason})`)
    .join("; ");
  const watched = [
    ...new Set(
      p.loved.flatMap((d) => d.examples).filter(Boolean),
    ),
  ].slice(0, 12);
  return (
    `You are Osusume, a knowledgeable, warm anime expert chatting with ${p.userName}. ` +
    `They are a viewer, not a data scientist: they care about STORIES, not metrics.\n\n` +
    `HOW TO TALK:\n` +
    `- Answer the question they ACTUALLY asked. "Why would the plot interest me?" means talk about the plot, themes, tone and emotions — not about scores or the app.\n` +
    `- ${COMPARISON_STANDARD.split("\n").slice(1).join(" ")}\n` +
    `- Read their PATTERN out loud when relevant: what kinds of stories they gravitate to, recurring elements across the titles they loved, and how this recommendation fits or stretches that pattern.\n` +
    `- FULLER ANSWERS when recommending or explaining why: ONE solid paragraph (4-7 sentences, ~100-150 words) covering the story, the connection to their history, and what to expect emotionally. Never more than two paragraphs, and never restate a point you already made — say everything once, then stop. Short replies only for quick factual questions.\n` +
    `- BANNED words: "affinity", "quality %", "match score", "the algorithm", "prioritized", "profile" — never explain the app's mechanics. If strength matters, say it in words ("widely beloved", "a hidden gem many missed"). The internal match reference numbers are for you ONLY; quote them verbatim just if explicitly asked about scores.\n` +
    `- Ground claims in the plot texts, themes and reception provided; general knowledge of the titles listed is fine, inventing plot points is not. If unsure about a detail, say so.\n` +
    `- Vary your phrasing across turns — never recycle the same sentences. No bullet lists unless asked. Reply in flawless ${LANG_NAME[lang]} only (no words from other languages).\n\n` +
    `THE USER: loves ${loved || "not enough data"}; dislikes ${disliked || "nothing notable"}; ` +
    `mean score ${p.meanScore}, ${p.counts.COMPLETED} completed.\n` +
    (watched.length ? `TITLES THEY WATCHED AND LOVED (cite these by name): ${watched.join(", ")}.\n` : "") +
    `\nCURRENT RECOMMENDATIONS:\n${recos || "(none yet)"}` +
    (avoided ? `\n\nTITLES SUGGESTED TO AVOID (do not recommend): ${avoided}` : "")
  );
}

/** Titles the user names in their latest message (cap 2) — they earn review
 *  grounding so the chat can speak about them like an expert would. */
export function mentionedTitles(
  history: { role: "user" | "assistant"; content: string }[],
  candidates: ScoredReco[],
): ScoredReco[] {
  const lastUser = history[history.length - 1];
  if (!lastUser || lastUser.role !== "user") return [];
  const text = lastUser.content.toLowerCase();
  return candidates
    .filter((r) => r.media.title.length >= 4 && text.includes(r.media.title.toLowerCase()))
    .slice(0, 2);
}

/** history is the client-side conversation (already trimmed by the API layer).
 *  extraRecos: looked-up titles outside the recommendation list, still discussable. */
export async function chatReply(
  result: RecoResult,
  lang: Lang,
  history: { role: "user" | "assistant"; content: string }[],
  extraRecos: ScoredReco[] = [],
): Promise<string> {
  const model = await resolveServedModel();
  // review grounding only for titles actually in play (mentioned + looked-up):
  // fetching for all 12 listed recos would burn rate budget for nothing
  const mentioned = mentionedTitles(history, [...result.recos, ...extraRecos]);
  const focusIds = [...new Set([
    ...mentioned.slice(0, 2).map((r) => r.media.id),
    ...extraRecos.slice(0, 3).map((r) => r.media.id),
  ])].slice(0, 4);
  const reviews = focusIds.length > 0 ? await gatherReviews(focusIds) : new Map();
  const messages = [
    {
      role: "system" as const,
      content: buildChatSystem(
        result,
        lang,
        extraRecos,
        reviews,
      ),
    },
    ...history,
  ];
  try {
    return await llmChat(messages, model);
  } catch (e) {
    if (!isTruncation(e)) throw e;
    return llmChat(messages, model, 4000); // safety net — thinking is off at the source
  }
}
