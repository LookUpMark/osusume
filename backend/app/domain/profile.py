"""Porting 1:1 di ``src/server/profile.ts`` — funzioni pure, zero I/O.

Ogni funzione cita il corrispondente simbolo TS.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple

from app.domain.js_compat import js_number, js_num_str, js_round
from app.shared.weights import WEIGHTS
from app.shared.models import Dim, DimValue, ListEntry, ListStatus, MediaLite, TasteProfile


class MeanScore(NamedTuple):
    """Ritorno di ``meanScoreOf``: ``{ mean, scoredCount }``."""

    mean: float
    scoredCount: int


class Sentiment(NamedTuple):
    """Ritorno di ``entrySentiment``: ``{ s, w }``."""

    s: float
    w: float


class _Example(NamedTuple):
    title: str
    s: float


class Acc(NamedTuple):
    """Accumulatore per ``dim:value`` (interfaccia ``Acc`` in profile.ts)."""

    sum: float
    weight: float
    support: int
    examples: list[_Example]


def clamp(x: float, lo: float, hi: float) -> float:
    """``clamp`` (profile.ts riga 12)."""
    return min(hi, max(lo, x))


def mean_score_of(entries: list[ListEntry]) -> MeanScore:
    """``meanScoreOf``: media dei soli score > 0; fallback 60 sotto i 3 votati."""
    scored = [e for e in entries if e.score > 0]
    if len(scored) < 3:
        return MeanScore(60, len(scored))
    return MeanScore(sum(e.score for e in scored) / len(scored), len(scored))


def entry_sentiment(e: ListEntry, mean: float) -> Sentiment:
    """``entrySentiment`` (profile.ts righe 22-33)."""
    if e.status == "PLANNING":
        return Sentiment(0, 0)
    base = WEIGHTS["statusBase"].get(e.status, 0)
    s_raw = clamp((e.score - mean) / WEIGHTS["scoreSpread"], -1, 1) if e.score > 0 else 0
    repeat_bonus = WEIGHTS["repeatBonus"] * min(e.repeat, WEIGHTS["repeatCap"])
    # finishing (or rewatching) without rating is still a choice — mild positive,
    # otherwise a list with zero scores has an empty taste profile
    completion_boost = 0.2 if e.score == 0 and e.status in ("COMPLETED", "REPEATING") else 0
    s = clamp(base + s_raw + repeat_bonus + completion_boost, -1, 1)
    w = 1 if e.score > 0 else (0.6 if e.status == "DROPPED" else 0.4)
    return Sentiment(s, w)


def era_bucket(year: int | None) -> str | None:
    """``eraBucket``: ``String(5 * Math.floor(year / 5))`` oppure ``null``."""
    return None if year is None else str(5 * (year // 5))


def _add_sentiment(
    acc: dict[str, Acc],
    dim: Dim,
    value: str | None,
    s: float,
    w: float,
    example_title: str,
    rank_factor: float,
) -> None:
    """``addSentiment`` (profile.ts righe 38-59)."""
    if value is None or value == "":
        return
    key = f"{dim}:{value}"
    a = acc.get(key)
    if a is None:
        a = Acc(0, 0, 0, [])
    _sum, _weight, support, examples = a
    _sum += s * rank_factor
    _weight += w * rank_factor
    if w * rank_factor > 0:
        support += 1  # zero-weight observations are not evidence
    if s > 0.3 and all(x.title != example_title for x in examples):
        examples.append(_Example(example_title, s))
        examples.sort(key=lambda x: x.s, reverse=True)  # stabile, come Array.sort
        if len(examples) > 3:
            examples.pop()
    acc[key] = Acc(_sum, _weight, support, examples)


def _finalize_sides(acc: dict[str, Acc]) -> tuple[list[DimValue], list[DimValue]]:
    """``finalizeSides`` (profile.ts righe 61-94)."""
    loved: list[DimValue] = []
    disliked: list[DimValue] = []
    for key, a in acc.items():
        # indexOf split: values may contain ':' themselves (unlike split(':'))
        colon = key.index(":")
        dim = key[:colon]
        value = key[colon + 1 :]
        if a.weight == 0 or a.support < WEIGHTS["supportMin"]:
            continue
        aff = (a.sum / a.weight) * (min(a.support, WEIGHTS["supportShrink"]) / WEIGHTS["supportShrink"])
        dv = DimValue(dim=dim, value=value, aff=aff, support=a.support, examples=[x.title for x in a.examples])
        if aff > WEIGHTS["lovedMin"]:
            loved.append(dv)
        elif aff < -WEIGHTS["lovedMin"]:
            disliked.append(dv)

    # cap by affinity strength, not Map insertion order — the strongest tastes must win
    def cap(dim: Dim, n: int) -> list[DimValue]:
        return sorted((d for d in loved if d.dim == dim), key=lambda d: -d.aff)[:n]

    def cap_neg(dim: Dim, n: int) -> list[DimValue]:
        return sorted((d for d in disliked if d.dim == dim), key=lambda d: d.aff)[:n]

    return (
        cap("tag", WEIGHTS["topTags"])
        + cap("genre", WEIGHTS["topGenres"])
        + cap("studio", WEIGHTS["topStudios"])
        + cap("era", 4),
        cap_neg("tag", WEIGHTS["topDisliked"]) + cap_neg("genre", 5) + cap_neg("studio", 3) + cap_neg("era", 2),
    )


def build_profile(
    entries: list[ListEntry],
    media_by_id: dict[int, MediaLite],
    user_name: str = "",
) -> TasteProfile:
    """``buildProfile``: gusto dall'intera lista AniList + metadati media."""
    mean, scored_count = mean_score_of(entries)
    acc: dict[str, Acc] = {}
    counts: dict[ListStatus, int] = {
        "CURRENT": 0,
        "PLANNING": 0,
        "COMPLETED": 0,
        "DROPPED": 0,
        "PAUSED": 0,
        "REPEATING": 0,
    }

    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
        s, w = entry_sentiment(e, mean)
        if w == 0:
            continue  # PLANNING carries no taste signal
        m = media_by_id.get(e.mediaId)
        _add_sentiment(acc, "era", era_bucket(m.seasonYear if m else None), s, w, e.title, 1)
        if m is None:
            continue
        for g in m.genres:
            _add_sentiment(acc, "genre", g, s, w, e.title, 1)
        for t in m.tags:
            _add_sentiment(acc, "tag", t.name, s, w, e.title, t.rank / 100)
        if m.studio:
            _add_sentiment(acc, "studio", m.studio, s, w, e.title, 1)

    loved, disliked = _finalize_sides(acc)
    # sort LESSICOGRAFICO (``Array.sort`` su stringhe, NON numerico) — un sort
    # numerico rompe l'invalidazione della cache spiegazioni (spec §2.2.4)
    payload = "|".join(sorted(f"{e.mediaId}:{e.status}:{js_num_str(e.score)}:{e.repeat}" for e in entries))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    return TasteProfile(
        userName=user_name,
        meanScore=js_number(js_round(mean * 10) / 10),  # Math.round(mean * 10) / 10
        scoredCount=scored_count,
        confidence="ok" if scored_count >= 3 else "low",
        counts=counts,
        loved=loved,
        disliked=disliked,
        hash=digest,
    )
