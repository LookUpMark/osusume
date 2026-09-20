"""Porting 1:1 di ``tests/profile.test.ts`` (119 righe, 7 scenari).

Stessi fixture (entry/media costruite a mano) e stessi valori pinned: il titolo
TS di ogni scenario è citato nella docstring.
"""

from __future__ import annotations

from app.domain.profile import build_profile, entry_sentiment, era_bucket, mean_score_of
from app.shared.models import ListEntry, ListStatus
from helpers import media

# base del fixture ``media`` di tests/profile.test.ts (diversa da quella di scoring);
# genres/tags restano espliciti per chiamata perché variano media per media
PROFILE_BASE = dict(seasonYear=2014, studio="Madhouse", averageScore=75)


def entry(media_id: int, status: ListStatus, score: float, repeat: int = 0) -> ListEntry:
    return ListEntry(mediaId=media_id, status=status, score=score, repeat=repeat, title=f"m{media_id}")


def test_mean_score_of_ignora_non_votati_e_fallback_60():
    # "meanScoreOf ignores unscored and falls back to 60 below 3 scores"
    assert mean_score_of([entry(1, "COMPLETED", 80), entry(2, "COMPLETED", 90)]).mean == 60
    ms = mean_score_of(
        [
            entry(1, "COMPLETED", 80),
            entry(2, "COMPLETED", 90),
            entry(3, "COMPLETED", 100),
            entry(4, "DROPPED", 0),
        ]
    )
    assert ms.mean == 90
    assert ms.scoredCount == 3


def test_completato_non_votato_positivo_debole():
    # "unscored completion is a weak positive: zero-score lists get a taste profile"
    s = entry_sentiment(entry(1, "COMPLETED", 0), 60).s
    assert 0.1 < s < 0.3, f"mild positive, got {s}"
    assert entry_sentiment(entry(2, "REPEATING", 0), 60).s > 0, "rewatch too"
    assert entry_sentiment(entry(3, "PAUSED", 0), 60).s < 0, "paused stays negative"
    # a list with zero scores still yields loved dims (the LookUpMark case)
    media_by_id = {
        1: media(
            0,
            **PROFILE_BASE,
            genres=["Drama"],
            tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}],
        )
    }
    p = build_profile([entry(1, "COMPLETED", 0), entry(1, "COMPLETED", 0)], media_by_id, "t")
    assert len(p.loved) > 0, "Psychological lands in loved"


def test_entry_sentiment_sopra_media_repeat_bonus_planning_dropped():
    # "entrySentiment: above-mean scored, repeat bonus, planning excluded, dropped heavy negative"
    mean = mean_score_of([entry(1, "COMPLETED", 60), entry(2, "COMPLETED", 80), entry(3, "COMPLETED", 100)]).mean
    assert entry_sentiment(entry(4, "PLANNING", 0), mean).w == 0
    # 90 is +10 over mean 80 → 0.25 raw
    assert entry_sentiment(entry(4, "COMPLETED", 90), mean).s == 0.25
    # repeat adds 0.1 per rewatch (capped at 3)
    assert entry_sentiment(entry(4, "COMPLETED", 90, 2), mean).s == 0.45
    assert entry_sentiment(entry(4, "COMPLETED", 90, 7), mean).s == 0.55
    # dropped 0-score: statusBase −0.6
    assert entry_sentiment(entry(4, "DROPPED", 0), mean).s == -0.6
    # unscored completed still carries weight 0.4
    assert entry_sentiment(entry(4, "COMPLETED", 0), mean).w == 0.4


def test_era_bucket_floor_a_bucket_di_5_anni():
    # "eraBucket floors to 5-year buckets"
    assert era_bucket(2017) == "2015"
    assert era_bucket(None) is None


def test_entry_sentiment_limiti_clamp_esatti():
    # "entrySentiment: clamp bounds are exact"
    mean = mean_score_of([entry(1, "COMPLETED", 60), entry(2, "COMPLETED", 80), entry(3, "COMPLETED", 100)]).mean
    # +40 over mean 80 → sRaw exactly +1
    assert entry_sentiment(entry(4, "COMPLETED", 120), mean).s == 1
    # far below mean + dropped status → clamps to -1, never below
    assert entry_sentiment(entry(4, "DROPPED", 0), 60).s == -0.6
    assert entry_sentiment(entry(4, "PAUSED", 20), 80).s == -1
    # repeat bonus can push over 1 → total clamps
    assert entry_sentiment(entry(4, "CURRENT", 120, 3), mean).s == 1


def test_build_profile_loved_da_voti_alti_disliked_da_drop_planning_ignorato():
    # "buildProfile: loved tag from high scores, disliked genre from drops, planning ignored"
    entries = [
        entry(1, "COMPLETED", 95),
        entry(2, "COMPLETED", 92),
        entry(3, "DROPPED", 0),
        entry(4, "DROPPED", 0),
        entry(5, "PLANNING", 0),
        entry(6, "COMPLETED", 40),
    ]
    by_id = {
        1: media(1, **PROFILE_BASE, genres=["Psychological"], tags=[{"name": "Psychological", "rank": 95, "isSpoiler": False}]),
        2: media(2, **PROFILE_BASE, genres=["Psychological"], tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}]),
        3: media(3, **PROFILE_BASE, genres=["Isekai"], tags=[{"name": "Isekai", "rank": 85, "isSpoiler": False}]),
        4: media(4, **PROFILE_BASE, genres=["Isekai"], tags=[{"name": "Isekai", "rank": 80, "isSpoiler": False}]),
        5: media(5, **PROFILE_BASE, genres=["Fantasy"], tags=[]),
        6: media(6, **PROFILE_BASE, genres=["Slice of Life"], tags=[]),
    }
    p = build_profile(entries, by_id, "testuser")
    assert p.confidence == "ok"
    assert p.counts["DROPPED"] == 2
    assert any(d.dim == "tag" and d.value == "Psychological" for d in p.loved)
    assert any(d.dim == "genre" and d.value == "Psychological" for d in p.loved)
    assert any(d.value == "Isekai" for d in p.disliked), "dropped genre must be disliked"
    assert not any(d.value == "Fantasy" for d in p.loved), "planning entries carry no signal"
    assert len(p.hash) == 16


def test_build_profile_confidence_bassa_sotto_3_voti():
    # "buildProfile: low confidence when fewer than 3 scores"
    p = build_profile([entry(1, "COMPLETED", 90), entry(2, "DROPPED", 0)], {}, "u")
    assert p.confidence == "low"
