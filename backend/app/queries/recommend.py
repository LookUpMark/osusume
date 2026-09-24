"""Payload di ``recommend``/``lookup`` (porting di ``c.json(...)`` in api.ts righe 91-99, 129-140).

Chiavi ESATTAMENTE quelle del TS quando presenti: ``links``/``mmRank`` omessi se
assenti (``undefined``), ``rootId: null`` esplicito quando STANDALONE.
"""

from __future__ import annotations

from collections.abc import Callable

from app.domain import pipeline
from app.domain.js_compat import js_number
from app.shared.models import Lang, RecoResult, ScoredReco


def reco_payload(r: ScoredReco) -> dict:
    """``ScoredReco`` → dict (ordine chiavi = ordine di assegnazione del TS)."""
    out: dict = {
        "media": r.media.model_dump(),
        "final": js_number(r.final),
        "breakdown": {
            "affinity": js_number(r.breakdown.affinity),
            "quality": js_number(r.breakdown.quality),
            "community": js_number(r.breakdown.community),
            "mood": js_number(r.breakdown.mood),
        },
        "badges": list(r.badges),
        "rootId": r.rootId,
        "groupSize": r.groupSize,
        "why": r.why,
    }
    if r.mmRank is not None:  # assegnato da diversify prima dei links
        out["mmRank"] = r.mmRank
    if r.links is not None:
        out["links"] = [link.model_dump() for link in r.links]
    return out


def result_payload(result: RecoResult) -> dict:
    """``RecoResult`` → dict (NON wrapped: la risposta di /api/recommend è questa)."""
    return {
        "profile": result.profile.model_dump(),
        "recos": [reco_payload(r) for r in result.recos],
        "avoided": [{"media": a.media.model_dump(), "reason": a.reason} for a in result.avoided],
    }


async def get_recommendation(
    username: str,
    lang: Lang,
    refresh: bool = False,
    stale_ok: bool = False,
    on_phase: "Callable[[str], None] | None" = None,
) -> dict:
    """``getRecommendation`` + serializzazione (result cache in pipeline)."""
    result = await pipeline.get_recommendation(username, lang, refresh=refresh, stale_ok=stale_ok, on_phase=on_phase)
    return result_payload(result)


async def lookup(username: str, q: str, lang: Lang) -> dict:
    """``lookupMedia`` + serializzazione → ``{recos: [...]}``."""
    recos = await pipeline.lookup_media(username, q, lang)
    return {"recos": [reco_payload(r) for r in recos]}
