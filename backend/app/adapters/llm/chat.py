"""Porting di ``src/server/chat.ts`` — chat lookup + risposta.

history è la conversazione client-side (già trimmata dal layer API, in P5);
extraRecos: titoli cercati fuori dalla lista raccomandati, comunque discussabili.
"""

from __future__ import annotations

from typing import Any

from app.adapters.anilist.media import ReviewLite, gather_reviews
from app.adapters.llm.client import is_truncation, llm_chat, resolve_served_model
from app.adapters.llm.prompts import build_chat_system
from app.shared.models import Lang, ScoredReco

# safety net — thinking is off at the source
_CHAT_RETRY_TOKENS = 4000


def mentioned_titles(
    history: list[dict[str, str]],
    candidates: list[ScoredReco],
) -> list[ScoredReco]:
    """``mentionedTitles`` — Titles the user names in their latest message (cap 2):
    they earn review grounding so the chat can speak about them like an expert would."""
    if not history:
        return []
    last_user = history[-1]
    if last_user.get("role") != "user":
        return []
    text = last_user["content"].lower()
    return [r for r in candidates if len(r.media.title) >= 4 and r.media.title.lower() in text][:2]


async def chat_reply(
    result: Any,
    lang: Lang,
    history: list[dict[str, str]],
    extra_recos: list[ScoredReco] | None = None,
) -> str:
    """``chatReply`` (chat.ts righe 104-137) — altri errori PROPAGANO."""
    extra_recos = extra_recos or []
    model = await resolve_served_model()
    # review grounding only for titles actually in play (mentioned + looked-up):
    # fetching for all 12 listed recos would burn rate budget for nothing
    mentioned = mentioned_titles(history, [*result.recos, *extra_recos])
    focus_ids: list[int] = []
    for r in [*mentioned[:2], *extra_recos[:3]]:
        if r.media.id not in focus_ids:
            focus_ids.append(r.media.id)
    focus_ids = focus_ids[:4]
    reviews: dict[int, list[ReviewLite]] = await gather_reviews(focus_ids) if focus_ids else {}
    messages = [
        {"role": "system", "content": build_chat_system(result, lang, extra_recos, reviews)},
        *history,
    ]
    try:
        return await llm_chat(messages, model)
    except Exception as e:
        if not is_truncation(e):
            raise
        return await llm_chat(messages, model, _CHAT_RETRY_TOKENS)
