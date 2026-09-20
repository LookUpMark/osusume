"""Anti-drift della serializzazione JS-style dei modelli (spec §2.2, golden gate).

``JSON.stringify`` JS non distingue int/float: ``84.0`` → ``84``. Pydantic
emette ``84.0`` per un campo ``float`` → payload HTTP e confronto golden
divergerebbero. JsModel serializza i float integrali come interi lasciando i
tipi interni del dominio a float.
"""

from __future__ import annotations

from app.shared.models import MediaLite, RecoBreakdown, ScoredReco
from helpers import media


def media_js(averageScore: float | None) -> MediaLite:
    """Media con i valori pinned di questo file (rank 90 float, popularity 150000)."""
    return media(
        1,
        averageScore=averageScore,
        popularity=150_000,
        tags=[{"name": "Psychological", "rank": 90.0, "isSpoiler": False}],
    )


def test_float_integrali_serializzano_stile_js():
    dumped = media_js(84.0).model_dump()
    assert dumped["averageScore"] == 84
    assert isinstance(dumped["averageScore"], int)  # non 84.0
    assert isinstance(dumped["tags"][0]["rank"], int) and dumped["tags"][0]["rank"] == 90  # nested
    assert '"averageScore":84' in media_js(84.0).model_dump_json()  # anche in json mode


def test_float_non_integrali_e_null_restano_invariati():
    assert media_js(84.5).model_dump()["averageScore"] == 84.5
    assert media_js(None).model_dump()["averageScore"] is None
    assert media_js(None).model_dump_json().count('"averageScore":null') == 1


def test_breakdown_mood_zero_serializza_a_intero():
    r = ScoredReco(
        media=media_js(70.0),
        final=0.0,
        breakdown=RecoBreakdown(affinity=0.5, quality=0.71, community=0.0, mood=0.0),
        badges=[],
        rootId=None,
        groupSize=1,
        why="w",
    )
    b = r.model_dump()["breakdown"]
    assert b["mood"] == 0 and isinstance(b["mood"], int)
    assert b["community"] == 0 and isinstance(b["community"], int)
    # i tipi INTERNI restano float (solo la serializzazione cambia)
    assert isinstance(r.breakdown.mood, float) and isinstance(r.media.averageScore, float)
    assert r.model_dump_json().count('"mood":0') == 1
