"""``GET /api/profile/:username`` (api.ts righe 85-89) → ``{profile}``.

La cache 1h è sulla LISTA AniList su disco (``fetchUserList`` → ``cacheWrap``
con ``CACHE_TTL_LIST_MS``), non sul profilo: il profilo si ricostruisce a ogni
chiamata, senza pool candidati.
"""

from __future__ import annotations

from app.domain import pipeline


async def get_profile(username: str) -> dict:
    profile = await pipeline.get_profile(username)
    return {"profile": profile.model_dump()}
