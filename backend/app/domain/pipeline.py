"""Porting 1:1 di ``src/server/candidates.ts`` + ``src/server/recommend.ts``.

Ogni funzione cita il corrispondente simbolo TS. L'ORDINE delle operazioni di
``recommendFor`` NON è negoziabile (spec §2): lista → profilo → 1ª passata
franchise → epMap → pool ricostruito → 2ª passata → community → mood →
``scoreAll`` → ``dedupeFranchises`` → ``diversify`` → slice 50 → links →
anti-recommendazioni. Dedupe PRIMA di MMR.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from app.adapters.anilist.cache import now_ms
from app.adapters.anilist.media import (
    AniListError,
    fetch_media_by_ids,
    fetch_media_page,
    fetch_media_search,
    fetch_recommendations,
    fetch_user_list,
)
from app.domain.franchise import analyze_franchises
from app.domain.profile import build_profile, entry_sentiment
from app.domain.scoring import (
    SeenItem,
    build_seen_corpus,
    dedupe_franchises,
    deterministic_why_not,
    diversify,
    score_all,
    text_links,
    tokenize,
)
from app.shared.models import (
    Lang,
    ListEntry,
    MediaLite,
    RecoResult,
    ScoredReco,
    TasteProfile,
    WhyNot,
)
from app.shared.weights import WEIGHTS

# --- candidates.ts ---------------------------------------------------------------


def _top(p: TasteProfile, dim: str, n: int) -> list[str]:
    """``top`` (candidates.ts righe 4-9): strongest tastes first, not Map order."""
    return [d.value for d in sorted((d for d in p.loved if d.dim == dim), key=lambda d: -d.aff)[:n]]


async def fetch_candidates(profile: TasteProfile, exclude_ids: set[int]) -> list[MediaLite]:
    """``fetchCandidates`` (candidates.ts righe 16-58).

    Pool SOLO da query mirate (le ToS AniList vietano mirror del catalogo):
    top-3 generi amati × 2 pagine popularity, top-5 tag amati × 1 pagina
    (rank>=60), top-3 generi × 1 pagina per score (~14 richieste). Un fallimento
    singolo conta ``failed``; TUTTE fallite → AniListError 502. Dedup per id in
    ordine di inserimento (primo vince), fuori dalla lista utente.
    """
    genres = _top(profile, "genre", 3)
    tags = _top(profile, "tag", 5)
    queries: list[dict[str, Any]] = []
    for g in genres:
        queries.append({"sort": ["POPULARITY_DESC"], "page": 1, "genres": [g]})
        queries.append({"sort": ["POPULARITY_DESC"], "page": 2, "genres": [g]})
    for t in tags:
        queries.append({"sort": ["POPULARITY_DESC"], "page": 1, "tags": [t], "minimum_tag_rank": 60})
    for g in genres:
        queries.append({"sort": ["SCORE_DESC"], "page": 1, "genres": [g]})
    # cold-start fallback: global popularity pages
    if len(queries) == 0:
        queries.append({"sort": ["POPULARITY_DESC"], "page": 1})
        queries.append({"sort": ["POPULARITY_DESC"], "page": 2})

    pool: dict[int, MediaLite] = {}
    failed = 0

    async def run(q: dict[str, Any]) -> dict[str, Any]:
        nonlocal failed
        try:
            return await fetch_media_page(**q)
        except Exception:
            failed += 1  # il ``.catch(() => { failed++; return [] })`` del TS
            return {"media": [], "hasNextPage": False}

    results = await asyncio.gather(*(run(q) for q in queries))
    if failed == len(queries):
        raise AniListError("every candidate query failed", 502)
    for result in results:
        for m in result["media"]:
            if m.id not in exclude_ids and m.id not in pool:
                pool[m.id] = m
    return list(pool.values())


# --- recommend.ts ----------------------------------------------------------------

# in-memory result cache: profile+pool are the expensive part; explain() reuses it
_result_cache: dict[str, dict[str, Any]] = {}
_RESULT_TTL_MS = 10 * 60 * 1000
# identical concurrent requests share one computation instead of racing
_inflight: dict[str, asyncio.Task] = {}


def reset_result_cache_for_tests() -> None:
    """Azzera le state di processo (i test TS ricreano il modulo, qui serve un reset)."""
    _result_cache.clear()
    _inflight.clear()


async def get_profile(username: str) -> TasteProfile:
    """``getProfile`` (recommend.ts righe 16-19): lista (cache disco 1h) + profilo.

    Nessun pool candidati: la cache 1h è sulla LISTA AniList (``fetchUserList``),
    non sul profilo costruito.
    """
    ul = await fetch_user_list(username)
    return build_profile(ul.entries, ul.mediaById, username)


def _seen_corpus_for(entries: list[ListEntry], media_by_id: dict[int, MediaLite], mean_score: float) -> list:
    """``seenCorpusFor`` (recommend.ts righe 23-35): corpus di trama dei titoli visti."""
    return build_seen_corpus(
        SeenItem(
            title=media_by_id[e.mediaId].title if e.mediaId in media_by_id else "",
            description=media_by_id[e.mediaId].description if e.mediaId in media_by_id else None,
            sentiment=entry_sentiment(e, mean_score).s,
        )
        for e in entries
    )


async def score_arbitrary(ids: list[float | int], username: str, lang: Lang) -> tuple[TasteProfile, list[ScoredReco]]:
    """``scoreArbitrary`` (recommend.ts righe 39-56): scoring core, contesto vuoto."""
    ul = await fetch_user_list(username)
    profile = build_profile(ul.entries, ul.mediaById, username)
    media = await fetch_media_by_ids(ids)
    scored = score_all(media, profile, {}, {}, lang)
    corpus = _seen_corpus_for(ul.entries, ul.mediaById, profile.meanScore)
    if len(corpus) > 0:
        for r in scored:
            links = text_links(r.media, corpus)
            if len(links) > 0:
                r.links = links
    return profile, scored


async def lookup_media(username: str, q: str, lang: Lang) -> list[ScoredReco]:
    """``lookupMedia`` (recommend.ts righe 59-65): ricerca + scoring, ordine ricerca."""
    media = [m for m in await fetch_media_search(q) if m.format != "MUSIC"]
    if len(media) == 0:
        return []
    _, recos = await score_arbitrary([m.id for m in media], username, lang)
    order = {m.id: i for i, m in enumerate(media)}
    return sorted(recos, key=lambda r: order.get(r.media.id, 0))  # stabile, come Array.sort


def _local_mode() -> bool:
    """``localModeOn()`` indiretto: punto di patch dei test senza trascinare config qui."""
    from app.core import config

    return config.local_mode_on()


async def get_recommendation(
    username: str,
    lang: Lang,
    refresh: bool = False,
    stale_ok: bool = False,
) -> RecoResult:
    """``getRecommendation`` (recommend.ts righe 67-100).

    La modalità è nella chiave: un risultato in local mode non deve riaffiorare
    dopo il ritorno ai dati live. Ordine dei check con ``!refresh``: hit fresco →
    hit scaduto + staleOk → inflight. ``refresh`` bypassa le letture.
    """
    cache_key = f"{username}:{lang}:{'local' if _local_mode() else 'live'}"
    if not refresh:
        hit = _result_cache.get(cache_key)
        if hit is not None and now_ms() - hit["at"] < _RESULT_TTL_MS:
            return hit["result"]
        # staleOk (chat context): better an expired result than a recompute
        if hit is not None and stale_ok:
            return hit["result"]
        pending = _inflight.get(cache_key)
        if pending is not None:
            return await pending
    task = asyncio.ensure_future(recommend_for(username, lang))
    _inflight[cache_key] = task
    task.add_done_callback(lambda _t: _inflight.pop(cache_key, None))
    try:
        result = await task
    except Exception:
        if stale_ok:
            hit = _result_cache.get(cache_key)
            if hit is not None:
                return hit["result"]
        raise
    for key, value in list(_result_cache.items()):
        if now_ms() - value["at"] >= _RESULT_TTL_MS:
            _result_cache.pop(key, None)  # prune on write
    _result_cache[cache_key] = {"at": now_ms(), "result": result}
    return result


async def recommend_for(username: str, lang: Lang) -> RecoResult:
    """``recommendFor`` (recommend.ts righe 102-240)."""
    ul = await fetch_user_list(username)
    profile = build_profile(ul.entries, ul.mediaById, username)
    list_ids = {e.mediaId for e in ul.entries}
    list_map: dict[int, Any] = {e.mediaId: e for e in ul.entries}

    # 1st franchise pass: sequel chains collapse to their entry point.
    # epMap: entryPointId → superseded candidate (the sequel shown instead must go).
    candidates0 = await fetch_candidates(profile, list_ids)
    franchise0 = analyze_franchises(candidates0, list_map)
    ep_map: dict[int, int] = {}
    skipped: set[int] = set()
    for mid, f in franchise0.items():
        if f.kind != "ENTRY_POINT" or f.entryPointId is None or f.entryPointId == mid:
            continue
        entry = list_map.get(f.entryPointId)
        if entry is not None and entry.status == "PLANNING":
            skipped.add(mid)  # already planned the right entry — say nothing
            continue
        ep_map[f.entryPointId] = mid
    missing_entries = [
        i for i in ep_map if not any(c.id == i for c in candidates0) and i not in list_ids
    ]
    try:
        extra = await fetch_media_by_ids(missing_entries)
    except Exception:
        extra = []  # il ``.catch(() => [])`` del TS
    superseded = set(ep_map.values())
    candidates = [
        c for c in candidates0 if c.id not in superseded and c.id not in skipped
    ] + [m for m in extra if not any(c.id == m.id for c in candidates0)]
    # 2nd franchise pass: the pool is final now, classifications are stable
    franchise = analyze_franchises(candidates, list_map)
    # an entry point pulled in for a superseded sequel earns the badge unless
    # its own analysis already classified it (NEXT_STEP when its prequels are seen)
    for ep_id in ep_map:
        f = franchise.get(ep_id)
        if f is not None and f.kind == "STANDALONE":
            franchise[ep_id] = f.model_copy(update={"kind": "ENTRY_POINT", "entryPointId": ep_id})

    # community signal: recommendation graph of the user's top-5 positively-rated entries
    community: dict[int, float] = {}
    top5 = [e for e in ul.entries if entry_sentiment(e, profile.meanScore).s > 0]
    top5.sort(key=lambda e: -entry_sentiment(e, profile.meanScore).s)  # stabile, come Array.sort
    top5 = top5[:5]

    async def community_fetch(e) -> list[dict[str, Any]]:
        try:
            return await fetch_recommendations(e.mediaId)
        except Exception as err:
            print(f"community fetch failed for {e.mediaId}: {err}", file=sys.stderr)  # console.warn
            return []

    rec_lists = await asyncio.gather(*(community_fetch(e) for e in top5)) if top5 else []
    for recs in rec_lists:
        for rec in recs:
            target_id, rating = rec["targetId"], rec["rating"]
            if rating <= 0 or not any(c.id == target_id for c in candidates):
                continue
            community[target_id] = min(
                WEIGHTS["communityCap"], community.get(target_id, 0) + WEIGHTS["communityPerHit"]
            )

    # mood continuity (scoring v2): the last 5 completed titles shape what feels
    # like a natural "next watch" — small bonus on candidates sharing their vocabulary
    recent = [
        e
        for e in ul.entries
        if e.status == "COMPLETED" and (e.updatedAt if e.updatedAt is not None else 0) > 0
    ]
    recent.sort(key=lambda e: -(e.updatedAt if e.updatedAt is not None else 0))
    recent = recent[:5]
    mood: dict[int, float] = {}
    if len(recent) > 0:
        mood_texts = []
        for e in recent:
            m = ul.mediaById.get(e.mediaId)
            desc = m.description if m is not None and m.description is not None else ""
            title = m.title if m is not None else ""
            mood_texts.append(tokenize(f"{desc} {title}"))
        for c in candidates:
            f = franchise.get(c.id)
            if f is not None and f.kind == "EXCLUDED":
                continue
            themes = " ".join(t.name for t in c.tags if t.rank >= 60 and not t.isSpoiler)
            tok = tokenize(f"{c.description if c.description is not None else ''} {themes}")
            shared = sum(1 for w in tok if any(w in t for t in mood_texts))
            if shared >= 4:
                mood[c.id] = WEIGHTS["mood"]

    # scoreAll: the EXCLUDED candidates never enter scoring (they surface as avoided)
    scored = score_all(
        [c for c in candidates if (f := franchise.get(c.id)) is None or f.kind != "EXCLUDED"],
        profile,
        community,
        franchise,
        lang,
        mood,
    )
    # dedupe (canonical roots keep groups stable) then MMR-diversify: mmRank drives
    # the default order so near-duplicates don't stack at the top of the list
    with_groups = diversify(dedupe_franchises(scored))[:50]

    # plot-text links (scoring v2): connect each recommendation to positively-rated
    # watched titles through shared plot vocabulary — grounds LLM chat/explanations
    corpus = _seen_corpus_for(ul.entries, ul.mediaById, profile.meanScore)
    if len(corpus) > 0:
        for r in with_groups:
            links = text_links(r.media, corpus)
            if len(links) > 0:
                r.links = links

    # anti-recommendations: weakest affinity candidates + dropped-series sequels,
    # with honest negative evidence, never duplicating something already recommended
    shown_ids = {r.media.id for r in with_groups}
    bottom = [r for r in scored if r.media.id not in shown_ids]
    bottom.sort(key=lambda r: r.breakdown.affinity)  # crescente, stabile come Array.sort
    bottom = bottom[:12]
    avoided: list[WhyNot] = []

    def collect_why_not(media: MediaLite) -> None:
        if media.id in shown_ids or any(a.media.id == media.id for a in avoided):
            return
        f = franchise.get(media.id)
        dropped_title = None
        if f is not None and f.droppedId is not None:
            entry = list_map.get(f.droppedId)
            dropped_title = entry.title if entry is not None else None
        reason = deterministic_why_not(media, profile, f, dropped_title, lang)
        if reason is not None:
            avoided.append(WhyNot(media=media, reason=reason))

    for r in bottom:
        collect_why_not(r.media)
        if len(avoided) >= 3:
            break
    # excluded-by-dropped-prequel candidates are never in `scored` — surface them here
    for c in candidates:
        if len(avoided) >= 3:
            break
        f = franchise.get(c.id)
        if f is None or f.kind != "EXCLUDED":
            continue
        collect_why_not(c)

    return RecoResult(profile=profile, recos=with_groups, avoided=avoided)
