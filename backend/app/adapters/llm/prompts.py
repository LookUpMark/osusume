"""Prompt building — porting di ``llm.ts`` (COMPARISON_STANDARD, cleanText,
buildPrompt) e ``chat.ts`` (buildChatSystem).

Le stringhe di doctrine sono COPIATE verbatim dai TS: sono parte della cache
key delle spiegazioni (PROMPT_VERSION) e del comportamento del modello.
"""

from __future__ import annotations

import re
from typing import Any

from app.adapters.anilist.media import ReviewLite
from app.core import config
from app.domain.js_compat import js_num_str, js_round
from app.domain.scoring import loved_overlap
from app.shared.models import Lang, ScoredReco, TasteProfile

LANG_NAME: dict[str, str] = {"en": "English", "it": "Italian"}

_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")
_PARTIAL_WORD_RE = re.compile(r"\s+\S*\Z")


def clean_text(html: str | None, max: int = 450) -> str:
    """``cleanText`` — Strip HTML + collapse whitespace (AniList descriptions are HTML)."""
    if not html:
        return ""
    text = _BR_RE.sub(" ", html)
    text = _STRIP_TAGS_RE.sub(" ", text)
    # entities in QUESTO ordine: &amp; prima, &lt;/&gt; dopo (nessun doppio decode)
    text = (
        text.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#039;", "'")
        .replace("&apos;", "'")
        .replace("&mdash;", "—")
        .replace("&hellip;", "…")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    text = _WS_RE.sub(" ", text).strip()
    return f"{_PARTIAL_WORD_RE.sub('', text[:max])}…" if len(text) > max else text


# The comparison doctrine, shared verbatim by explain + chat: comparisons are
# about HOW stories work, links are leads to verify (not facts to recite),
# and reception is absorbed as expertise, never cited.
COMPARISON_STANDARD = """THE COMPARISON STANDARD (what separates you from a fan wiki):
- Compare HOW stories work — tone, structure, pacing, how a theme is dramatized, what it feels like to watch. The mere PRESENCE of an element is never a comparison. Rejected: "it has aliens, and so does Dandadan". Accepted: "where Dandadan turns the supernatural into kinetic comedy, here the otherworldly presses on the cast like a slow verdict — that comedy-to-melancholy whiplash is the real draw".
- The "possible leads" you are given are LEADS, not facts. Use one only if you can say something true and specific about what the shared element DOES in this story. Nothing honest to build on? Drop the lead silently and judge the title on its own merits — a standalone expert blurb beats a forced comparison.
- At most 1-2 references to titles they watched. One deep, verifiable connection beats three name-drops.
- When a reception line is provided, mine it for what viewers praise or fault (character work, payoff, direction) and absorb that judgment as your own expertise. Rewrite it in your own words — the words "review", "reviewer", "viewer" or "critic" must NEVER appear in your reply.
- Name craft when it matters: studio lineage, era, format, how the tone shifts."""

# la variante inline del chat system: COMPARISON_STANDARD.split("\n").slice(1).join(" ")
_COMPARISON_INLINE = " ".join(COMPARISON_STANDARD.split("\n")[1:])


def _owner_extra() -> str:
    """Settings UI → config `systemPromptExtra`: istruzioni personali APPESSE in
    coda alla dottrina (mai in replace — la voce esperto resta la base)."""
    extra = config.system_prompt_extra().strip()
    if not extra:
        return ""
    return (
        "\n\nOWNER NOTES (the viewer's personal preferences — honor them in your voice; "
        "they never override the output format rules):\n"
        f"{extra}"
    )


def _themes_of(media: Any) -> str:
    tags = [t.name for t in media.tags if t.rank >= 60 and not t.isSpoiler]
    return ", ".join(tags[:5])


def _plot_links(r: ScoredReco) -> str:
    return "; ".join(f'shares imagery ({", ".join(l.shared)}) with "{l.title}"' for l in (r.links or []))


def _reception(reviews: dict[int, list[ReviewLite]], media_id: int) -> str:
    return " | ".join(f'"{v.body}"' for v in reviews.get(media_id, []))


def build_prompt(
    recos: list[ScoredReco],
    profile: TasteProfile,
    lang: Lang,
    reviews: dict[int, list[ReviewLite]] | None = None,
) -> str:
    """``buildPrompt`` (llm.ts righe 137-191)."""
    reviews = reviews or {}
    loved = "; ".join(
        f"{d.value} (e.g. {', '.join(d.examples[:2]) or 'n/a'})" for d in profile.loved[:10]
    )
    disliked = "; ".join(d.value for d in profile.disliked[:6])
    items = []
    for r in recos:
        overlap = loved_overlap(r.media, profile)
        leads = "; ".join(
            f"{o.label.split(':')[-1]} — they enjoyed it in {', '.join(o.examples)}" for o in overlap
        )
        themes = _themes_of(r.media)
        plot = clean_text(r.media.description, 400)
        plot_links = _plot_links(r)
        revs = _reception(reviews, r.media.id)
        item = (
            f'- id={r.media.id} — "{r.media.title}" ({r.media.seasonYear if r.media.seasonYear is not None else "?"}, '
            f'{r.media.studio if r.media.studio is not None else "?"}; '
            f'genres: {", ".join(r.media.genres[:3])}{f"; themes: {themes}" if themes else ""})\n'
            f'  plot: {plot or "not available"}\n'
            + (f"  reception: {revs}\n" if revs else "")
            + "  possible leads (verify, drop if shallow): "
            f"{'; '.join(x for x in (leads, plot_links) if x) or 'none obvious — judge the title on its own merits'}"
        )
        items.append(item)
    items_text = "\n".join(items)
    return (
        "You are a veteran anime critic — the friend people trust because you explain WHY a title works, never just what it contains. "
        f"The viewer loves: {loved or 'not enough data'}. They dislike: {disliked or 'nothing notable'}.\n"
        f"For each title below, write one rich, tight paragraph (3-5 sentences) in flawless {LANG_NAME[lang]} on why ITS STORY could hook THIS viewer.\n"
        f"{COMPARISON_STANDARD}\n"
        "Point out the pattern in their taste (what kinds of stories they gravitate to) and how this title fits or stretches it.\n"
        "Use ONLY the facts provided plus general knowledge of these exact titles; never invent plot. If the plot text is missing, speak about the themes. "
        f"NEVER mention scores, percentages, \"affinity\", \"quality\", \"match\", the app or any algorithm — a real expert does not talk like that."
        f"{_owner_extra()}\n\n{items_text}\n\n"
        f"Reply with ONLY a JSON array: [{{\"id\":<media id>,\"why\":\"<explanation>\"}}] — every \"why\" MUST be written in {LANG_NAME[lang]}."
    )


def build_chat_system(
    result: Any,
    lang: Lang,
    extra_recos: list[ScoredReco] | None = None,
    reviews: dict[int, list[ReviewLite]] | None = None,
) -> str:
    """``buildChatSystem`` (chat.ts righe 13-86)."""
    extra_recos = extra_recos or []
    reviews = reviews or {}
    p: TasteProfile = result.profile
    recos = [*result.recos[:12], *extra_recos[:5]]  # the full list the recos view shows; chat lookups always in context
    items = []
    for r in recos:
        overlap = loved_overlap(r.media, p)
        leads = "; ".join(
            f"{o.label.split(':')[-1]} (they enjoyed it in {', '.join(o.examples)})" for o in overlap
        )
        themes = _themes_of(r.media)
        plot = clean_text(r.media.description, 450)
        plot_links = _plot_links(r)
        revs = _reception(reviews, r.media.id)
        badges = " [less-known gem]" if "HIDDEN_GEM" in r.badges else ""
        item = (
            f'- "{r.media.title}" ({r.media.seasonYear if r.media.seasonYear is not None else "?"}, '
            f'studio {r.media.studio if r.media.studio is not None else "?"}; '
            f'genres: {", ".join(r.media.genres[:3])}{f"; themes: {themes}" if themes else ""}){badges}\n'
            f'  plot: {plot or "not available"}\n'
            + (f"  reception: {revs}\n" if revs else "")
            + "  possible leads (verify, drop if shallow): "
            f"{'; '.join(x for x in (leads, plot_links) if x) or 'none obvious'}\n"
            f"  internal match reference: {js_round(r.final * 100)}/110"
        )
        items.append(item)
    recos_text = "\n".join(items)
    loved = "; ".join(
        f"{d.value} (seen in {', '.join(d.examples[:3]) or 'n/a'})" for d in p.loved[:10]
    )
    disliked = ", ".join(d.value for d in p.disliked[:5])
    avoided = "; ".join(f'"{a.media.title}" ({a.reason})' for a in result.avoided[:5])
    watched: list[str] = []
    for d in p.loved:
        for ex in d.examples:
            if ex and ex not in watched:
                watched.append(ex)
    watched = watched[:12]
    return (
        f"You are Osusume, a knowledgeable, warm anime expert chatting with {p.userName}. "
        "They are a viewer, not a data scientist: they care about STORIES, not metrics.\n\n"
        "HOW TO TALK:\n"
        '- Answer the question they ACTUALLY asked. "Why would the plot interest me?" means talk about the plot, themes, tone and emotions — not about scores or the app.\n'
        f"- {_COMPARISON_INLINE}\n"
        "- Read their PATTERN out loud when relevant: what kinds of stories they gravitate to, recurring elements across the titles they loved, and how this recommendation fits or stretches that pattern.\n"
        "- FULLER ANSWERS when recommending or explaining why: ONE solid paragraph (4-7 sentences, ~100-150 words) covering the story, the connection to their history, and what to expect emotionally. Never more than two paragraphs, and never restate a point you already made — say everything once, then stop. Short replies only for quick factual questions.\n"
        '- BANNED words: "affinity", "quality %", "match score", "the algorithm", "prioritized", "profile" — never explain the app\'s mechanics. If strength matters, say it in words ("widely beloved", "a hidden gem many missed"). The internal match reference numbers are for you ONLY; quote them verbatim just if explicitly asked about scores.\n'
        "- Ground claims in the plot texts, themes and reception provided; general knowledge of the titles listed is fine, inventing plot points is not. If unsure about a detail, say so.\n"
        f"- Vary your phrasing across turns — never recycle the same sentences. No bullet lists unless asked. Reply in flawless {LANG_NAME[lang]} only (no words from other languages).\n\n"
        f"THE USER: loves {loved or 'not enough data'}; dislikes {disliked or 'nothing notable'}; "
        f"mean score {js_num_str(p.meanScore)}, {p.counts['COMPLETED']} completed.\n"
        + (f"TITLES THEY WATCHED AND LOVED (cite these by name): {', '.join(watched)}.\n" if watched else "")
        + f"\nCURRENT RECOMMENDATIONS:\n{recos_text or '(none yet)'}"
        + (f"\n\nTITLES SUGGESTED TO AVOID (do not recommend): {avoided}" if avoided else "")
        + _owner_extra()
    )
