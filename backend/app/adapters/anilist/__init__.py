"""Adapter AniList (P3): porting di src/server/anilist.ts (418 righe).

Query verbatim (queries.py), token bucket + retry ladder (client.py), cache
disco con dedup in-flight (cache.py), mappatura + API pubbliche + fixture mode
(media.py, fixtures.py).
"""

from __future__ import annotations

from .media import (
    ReviewLite,
    UserList,
    fetch_media_by_ids,
    fetch_media_page,
    fetch_media_reviews,
    fetch_media_search,
    fetch_recommendations,
    fetch_user_list,
    gather_reviews,
    map_media,
)

__all__ = [
    "ReviewLite",
    "UserList",
    "fetch_media_by_ids",
    "fetch_media_page",
    "fetch_media_reviews",
    "fetch_media_search",
    "fetch_recommendations",
    "fetch_user_list",
    "gather_reviews",
    "map_media",
]
