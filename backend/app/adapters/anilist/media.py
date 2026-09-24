"""Porting di mappatura e API pubbliche (anilist.ts righe 194-417).

Ogni funzione cita il corrispondente simbolo TS. Gli adapters sono l'unico
luogo con I/O (rete, cache, fixture): il dominio resta puro.
"""

from __future__ import annotations

import asyncio
from typing import Any, NamedTuple

from app.adapters.anilist import queries
from app.adapters.anilist.client import AniListError, gql
from app.adapters.anilist.fixtures import read_fixture
from app.core import config
from app.shared.models import (
    ListEntry,
    MediaLite,
    MediaRelationLite,
    MediaTagLite,
)


def _nz(value, default):
    """``?? `` TS: solo null/undefined prendono il default (``or`` prenderebbe anche 0/"")."""
    return value if value is not None else default


class ReviewLite(NamedTuple):
    """``interface ReviewLite`` (anilist.ts righe 381-386)."""

    summary: str
    body: str
    score: float | None
    rating: float


class UserList(NamedTuple):
    """``interface UserList`` (anilist.ts righe 249-252)."""

    entries: list[ListEntry]
    mediaById: dict[int, MediaLite]


# --- mapping -------------------------------------------------------------------


def map_media(m: dict[str, Any]) -> MediaLite:
    """``mapMedia`` (anilist.ts righe 212-237)."""
    title = m.get("title") or {}
    romaji, english = title.get("romaji"), title.get("english")
    cover = m.get("coverImage") or {}
    nodes = _nz((m.get("studios") or {}).get("nodes"), []) or []
    description = m.get("description")
    edges = _nz((m.get("relations") or {}).get("edges"), []) or []
    return MediaLite(
        id=m["id"],
        title=_nz(romaji, _nz(english, f"(id {m['id']})")),
        format=m.get("format"),
        seasonYear=m.get("seasonYear"),
        genres=_nz(m.get("genres"), []),
        tags=[
            MediaTagLite(name=t["name"], rank=t["rank"], isSpoiler=False)
            for t in (_nz(m.get("tags"), []) or [])
            if not t.get("isGeneralSpoiler") and not t.get("isMediaSpoiler")
        ],
        studio=nodes[0].get("name") if nodes else None,
        averageScore=m.get("averageScore"),
        popularity=_nz(m.get("popularity"), 0),
        coverImage=cover.get("large"),
        coverColor=cover.get("color"),
        siteUrl=m.get("siteUrl"),
        # ponytail: truncate description to 500 chars — enough for LLM context
        description=description[:500] if description else None,
        relations=[
            MediaRelationLite(id=e["node"]["id"], relationType=e["relationType"])
            for e in edges
            # il filter TS fa includes(e.relationType): senza chiave → drop, non errore
            if e.get("relationType") in ("PREQUEL", "SEQUEL", "SIDE_STORY", "SPIN_OFF", "PARENT")
        ],
        # ponytail: relations perPage defaults to 25 — giant franchises (Fate) may truncate
    )


# --- public API ----------------------------------------------------------------


async def fetch_user_list(user_name: str) -> UserList:
    """``fetchUserList`` (anilist.ts righe 254-297)."""
    if config.local_mode_on():
        f = await read_fixture("userlist.json")
        return UserList(
            entries=[ListEntry.model_validate(e) for e in f["entries"]],
            mediaById={m["id"]: MediaLite.model_validate(m) for m in f["media"]},
        )
    entries: dict[int, dict[str, Any]] = {}
    media: dict[int, MediaLite] = {}
    # OAuth: quando il token dell'utente c'è, la lista arriva private inclusa
    from app.adapters.anilist import auth

    token = auth.token_for(user_name)
    # ponytail: API ceiling is 11k entries (22 chunks of 500) — beyond that we miss tail entries
    for chunk in range(22):
        data = await gql(
            queries.LIST_LIST_QUERY, {"userName": user_name, "chunk": chunk}, config.CACHE_TTL_LIST_MS, token=token
        )
        for list_ in data["MediaListCollection"]["lists"]:
            for e in list_.get("entries") or []:
                mid = e["media"]["id"]
                prev = entries.get(mid)
                raw_title = e["media"].get("title") or {}
                # status lists win over custom-list copies of the same entry
                if prev and prev["custom"] and not list_["isCustomList"]:
                    del entries[mid]
                if not prev or (prev["custom"] and not list_["isCustomList"]):
                    entries[mid] = {
                        "mediaId": mid,
                        "status": e["status"],
                        "score": _nz(e.get("score"), 0),
                        "repeat": _nz(e.get("repeat"), 0),
                        "updatedAt": _nz(e.get("updatedAt"), 0),
                        "title": _nz(raw_title.get("romaji"), _nz(raw_title.get("english"), f"({mid})")),
                        "custom": list_["isCustomList"],
                    }
                    media[mid] = map_media(e["media"])
        if not data["MediaListCollection"]["hasNextChunk"]:
            break
    return UserList(
        entries=[ListEntry(**{k: v for k, v in e.items() if k != "custom"}) for e in entries.values()],
        mediaById=media,
    )


async def fetch_media_page(
    sort: list[str],
    page: int,
    genres: list[str] | None = None,
    tags: list[str] | None = None,
    minimum_tag_rank: int | None = None,
) -> dict[str, Any]:
    """``fetchMediaPage`` (anilist.ts righe 299-325) → ``{ media, hasNextPage }``."""
    if config.local_mode_on():
        # fixture mode ignores filters: the recorded pool is served whole
        all_ = await read_fixture("candidates.json")
        return {"media": [MediaLite.model_validate(m) for m in all_], "hasNextPage": False}
    data = await gql(
        queries.MEDIA_PAGE_QUERY,
        {
            "page": page,
            "genre_in": genres,
            "tag_in": tags,
            "sort": sort,
            "minimumTagRank": minimum_tag_rank,
        },
        config.CACHE_TTL_MEDIA_MS,
    )
    return {
        "media": [map_media(m) for m in data["Page"]["media"]],
        "hasNextPage": data["Page"]["pageInfo"]["hasNextPage"],
    }


async def fetch_media_by_ids(ids: list[int]) -> list[MediaLite]:
    """``fetchMediaByIds`` (anilist.ts righe 327-344)."""
    if len(ids) == 0:
        return []
    if config.local_mode_on():
        all_ = await read_fixture("candidates.json")
        return [MediaLite.model_validate(m) for m in all_ if m["id"] in ids]
    # GraphQL Page depth cap is 5000, perPage max 50 → chunk the input
    out: list[MediaLite] = []
    for i in range(0, len(ids), 50):
        data = await gql(queries.MEDIA_BY_IDS_QUERY, {"id_in": ids[i : i + 50]}, config.CACHE_TTL_MEDIA_MS)
        out.extend(map_media(m) for m in data["Page"]["media"])
    return out


async def fetch_media_search(q: str) -> list[MediaLite]:
    """``fetchMediaSearch`` — title search for the chat lookup (top matches, adult excluded)."""
    if config.local_mode_on():
        all_ = await read_fixture("candidates.json")
        n = q.lower()
        return [MediaLite.model_validate(m) for m in all_ if n in m["title"].lower()][:6]
    data = await gql(queries.MEDIA_SEARCH_QUERY, {"q": q}, config.CACHE_TTL_MEDIA_MS)
    return [map_media(m) for m in data["Page"]["media"]]


async def fetch_recommendations(media_id: int) -> list[dict[str, Any]]:
    """``fetchRecommendations`` (anilist.ts righe 361-377) → ``{ targetId, rating }[]``."""
    if config.local_mode_on():
        map_ = await read_fixture("recommendations.json")
        return map_.get(str(media_id), [])
    data = await gql(queries.RECOMMENDATIONS_QUERY, {"id": media_id}, config.CACHE_TTL_MEDIA_MS)
    return [
        {"targetId": n["mediaRecommendation"]["id"], "rating": n["rating"]}
        for n in data["Media"]["recommendations"]["nodes"]
    ]


# --- reviews (LLM grounding) ----------------------------------------------------


async def fetch_media_reviews(media_id: int) -> list[ReviewLite]:
    """``fetchMediaReviews`` — top-rated user reviews, LLM context only, never blocking:
    fixtures have none (silent degradation) and a fetch failure must not fail
    explain/chat nor trip the AniList auto-fallback."""
    if config.local_mode_on():
        return []
    try:
        data = await gql(queries.MEDIA_REVIEWS_QUERY, {"id": media_id}, config.CACHE_TTL_MEDIA_MS)
    except Exception:
        data = None  # il ``.catch(() => null)`` del TS
    nodes: list = []
    if isinstance(data, dict):  # il ``data?.Media?.reviews?.nodes ?? []`` del TS
        nodes = (((data.get("Media") or {}).get("reviews") or {}).get("nodes")) or []
    out: list[ReviewLite] = []
    for n in nodes:
        if not ((n.get("summary") or "") + (n.get("body") or "")).strip():
            continue
        out.append(
            ReviewLite(
                summary=" ".join((n.get("summary") or "").split())[:120],
                body=" ".join((n.get("body") or "").split())[:260],
                score=n.get("score"),
                rating=n.get("rating"),
            )
        )
        if len(out) >= 2:  # SLICE(0,2) del TS: solo 2 nonostante perPage 3
            break
    return out


async def gather_reviews(ids: list[int]) -> dict[int, list[ReviewLite]]:
    """``gatherReviews`` — reviews for a handful of ids at once (explain batch / chat mentions)."""
    unique = list(dict.fromkeys(ids))
    lists = await asyncio.gather(*(fetch_media_reviews(i) for i in unique))
    return {mid: lst for mid, lst in zip(unique, lists) if len(lst) > 0}


__all__ = [
    "AniListError",
    "ReviewLite",
    "UserList",
    "map_media",
    "fetch_user_list",
    "fetch_media_page",
    "fetch_media_by_ids",
    "fetch_media_search",
    "fetch_recommendations",
    "fetch_media_reviews",
    "gather_reviews",
]


async def fetch_media_list_status(user_name: str, media_id: int) -> str | None:
    """Stato dell'entry `media_id` nella lista dell'utente (per la watchlist UI).
    None = non in lista. Token usato quando disponibile (liste private)."""
    from app.adapters.anilist import auth

    try:
        data = await gql(
            queries.MEDIA_LIST_STATUS_QUERY,
            {"userName": user_name, "mediaId": media_id},
            config.CACHE_TTL_LIST_MS,
            token=auth.token_for(user_name),
        )
    except AniListError:
        return None  # entry assente = 404/404-graphql: per la UI è "non in lista"
    entry = data.get("MediaList") if isinstance(data, dict) else None
    status = entry.get("status") if isinstance(entry, dict) else None
    return status if isinstance(status, str) else None
