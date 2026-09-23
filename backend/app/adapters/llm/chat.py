"""Porting di ``src/server/chat.ts`` — chat lookup + risposta.

history è la conversazione client-side (già trimmata dal layer API, in P5);
extraRecos: titoli cercati fuori dalla lista raccomandati, comunque discussabili.
"""

from __future__ import annotations

import re
from typing import Any

from app.adapters.anilist.media import ReviewLite, gather_reviews
from app.adapters.llm.client import is_truncation, llm_chat, resolve_served_model
from app.adapters.llm.prompts import build_chat_system
from app.domain.js_compat import js_round
from app.shared.models import Lang, ScoredReco

# safety net — thinking is off at the source
_CHAT_RETRY_TOKENS = 4000

# titoli raccomandati dal modello = grassetto nel markdown (il prompt lo prescrive)
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
CARDS_MAX = 4


def _norm_title(s: str) -> str:
    return " ".join(s.split()).lower()


def recommended_cards(reply: str, pool: list[ScoredReco]) -> list[ScoredReco]:
    """Titoli in **bold** nella reply matchati contro il pool — lo STESSO elenco
    che il system prompt mostra (``[*recos[:12], *extras[:5]]``), quindi il modello
    può segnalare solo ciò che ha visto. Esatto case-insensitive, poi contains
    bidirezionale con guard >=4 (stesso standard di mentioned_titles). Dedup per
    id, ordine di apparizione, cap CARDS_MAX. Mai inventare: solo match reali."""
    out: list[ScoredReco] = []
    seen: set[int] = set()
    for bold in _BOLD_RE.findall(reply):
        text = _norm_title(bold)
        if len(text) < 4:
            continue
        for r in pool:
            title = _norm_title(r.media.title)
            if len(title) < 4:
                continue
            if text == title or ((text in title or title in text) and len(text) >= 4):
                if r.media.id not in seen:
                    seen.add(r.media.id)
                    out.append(r)
                break
        if len(out) >= CARDS_MAX:
            break
    return out


def card_payload(r: ScoredReco) -> dict:
    """Payload minimale per la card frontend (lo ScoredReco ricco lo ha già
    il client quando l'id è locale — questo è il fallback per id assenti)."""
    return {
        "id": r.media.id,
        "title": r.media.title,
        "coverImage": r.media.coverImage,
        "coverColor": r.media.coverColor,
        "seasonYear": r.media.seasonYear,
        "format": r.media.format,
        "score": js_round(r.final * 100),
        "siteUrl": r.media.siteUrl,
    }


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
