"""Mini test di pipeline (P4): ciò che i golden NON isolano.

I golden end-to-end coprono ordine pipeline e payload (recommend-en/it, lookup,
explain): qui si testa lo stato di processo — result cache (TTL, stale_ok,
refresh, inflight, chiave local/live) — e i branch di ``recommendFor``/
``fetchCandidates`` che i fixture sintetici non toccano (entry point pianificato
soppresso, entry point fetched + badge forzato, tutte le query fallite).
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.anilist.client import AniListError
from app.domain import pipeline
from app.domain.franchise import analyze_franchises
from app.domain.js_compat import js_log10
from app.domain.scoring import pop_norm, quality_of
from app.shared.models import ListEntry
from helpers import media as base_media

USER = "u"
LANG = "en"
TTL = pipeline._RESULT_TTL_MS

# clock controllabile: getRecommendation usa Date.now() per TTL e prune
_CLOCK = {"now": 1_000_000}


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    pipeline.reset_result_cache_for_tests()
    _CLOCK["now"] = 1_000_000
    monkeypatch.setattr(pipeline, "now_ms", lambda: _CLOCK["now"])
    yield
    pipeline.reset_result_cache_for_tests()


def entry(mid: int, status: str) -> ListEntry:
    return ListEntry(mediaId=mid, status=status, score=0, repeat=0, updatedAt=0, title=f"e{mid}")


def rel(mid: int, kind: str) -> dict:
    return {"id": mid, "relationType": kind}


class _UL:
    def __init__(self, entries, media_by_id) -> None:
        self.entries = entries
        self.mediaById = media_by_id


def _stub_pipeline(monkeypatch, entries, pool):
    media_by_id = {m.id: m for m in pool}
    for e in entries:
        media_by_id.setdefault(e.mediaId, base_media(e.mediaId))

    async def fake_list(username, media_type="ANIME"):
        return _UL(entries, media_by_id)

    async def fake_pool(profile, exclude_ids, media_type="ANIME"):
        return [m for m in pool if m.id not in exclude_ids]

    async def no_extra(ids, media_type="ANIME"):
        return []

    async def no_recs(mid, media_type="ANIME"):
        return []

    monkeypatch.setattr(pipeline, "fetch_user_list", fake_list)
    monkeypatch.setattr(pipeline, "fetch_candidates", fake_pool)
    monkeypatch.setattr(pipeline, "fetch_media_by_ids", no_extra)
    monkeypatch.setattr(pipeline, "fetch_recommendations", no_recs)


def _install_counter(monkeypatch, fail: bool = False):
    calls = {"n": 0}

    async def fake_recommend_for(username, lang, on_phase=None, media_type="ANIME"):
        calls["n"] += 1
        if fail:
            raise AniListError("boom", 502)
        return f"result-{username}-{lang}"

    monkeypatch.setattr(pipeline, "recommend_for", fake_recommend_for)
    return calls


# --- result cache ----------------------------------------------------------------


async def test_cache_hit_entro_ttl_non_ricalcola(monkeypatch):
    calls = _install_counter(monkeypatch)
    first = await pipeline.get_recommendation(USER, LANG)
    second = await pipeline.get_recommendation(USER, LANG)
    assert calls["n"] == 1
    assert first == second


async def test_hit_scaduto_con_stale_ok_ritorna_il_vecchio(monkeypatch):
    calls = _install_counter(monkeypatch)
    await pipeline.get_recommendation(USER, LANG)
    _CLOCK["now"] += TTL + 1
    stale = await pipeline.get_recommendation(USER, LANG, stale_ok=True)
    assert calls["n"] == 1  # nessun ricalcolo
    assert stale == "result-u-en"


async def test_hit_scaduto_senza_stale_ok_ricalcola(monkeypatch):
    calls = _install_counter(monkeypatch)
    await pipeline.get_recommendation(USER, LANG)
    _CLOCK["now"] += TTL + 1
    await pipeline.get_recommendation(USER, LANG)
    assert calls["n"] == 2


async def test_refresh_bypassa_la_lettura_della_cache(monkeypatch):
    calls = _install_counter(monkeypatch)
    await pipeline.get_recommendation(USER, LANG)
    await pipeline.get_recommendation(USER, LANG, refresh=True)
    assert calls["n"] == 2  # cache fresca ma refresh → ricalcolo


async def test_concorrenza_stessa_chiave_un_solo_calcolo(monkeypatch):
    calls = {"n": 0}
    gate = asyncio.Event()

    async def slow(username, lang, on_phase=None, media_type="ANIME"):
        calls["n"] += 1
        await gate.wait()
        return f"result-{username}-{lang}"

    monkeypatch.setattr(pipeline, "recommend_for", slow)
    a = asyncio.ensure_future(pipeline.get_recommendation(USER, LANG))
    b = asyncio.ensure_future(pipeline.get_recommendation(USER, LANG))
    gate.set()
    assert await a == await b
    assert calls["n"] == 1  # inflight dedup


async def test_fallimento_con_stale_ok_ritorna_ultimo_buono(monkeypatch):
    _install_counter(monkeypatch)
    await pipeline.get_recommendation(USER, LANG)
    _CLOCK["now"] += TTL + 1  # il buono resta in cache ma scaduto
    _install_counter(monkeypatch, fail=True)
    stale = await pipeline.get_recommendation(USER, LANG, stale_ok=True)
    assert stale == "result-u-en"


async def test_fallimento_senza_risultato_in_cache_rilancia(monkeypatch):
    _install_counter(monkeypatch, fail=True)
    with pytest.raises(AniListError):
        await pipeline.get_recommendation(USER, LANG, stale_ok=True)


async def test_chiave_cache_distinta_per_local_e_live(monkeypatch):
    calls = _install_counter(monkeypatch)
    await pipeline.get_recommendation(USER, LANG)
    monkeypatch.setattr(pipeline, "_local_mode", lambda: True)
    await pipeline.get_recommendation(USER, LANG)
    assert calls["n"] == 2  # modalità diversa → chiave diversa → ricalcolo


# --- branch di recommendFor non coperti dai fixture sintetici --------------------


async def test_entry_point_pianificato_soppresso(monkeypatch):
    # 701 ha il prequel 700 in PLANNING: il candidato sparisce senza avoid né fetch
    pool = [base_media(701, relations=[rel(700, "PREQUEL")], popularity=200, averageScore=90)]
    _stub_pipeline(monkeypatch, [entry(700, "PLANNING")], pool)
    fetched = {"n": 0}

    async def no_extra(ids, media_type="ANIME"):
        fetched["n"] += 1
        fetched["ids"] = list(ids)
        return []

    monkeypatch.setattr(pipeline, "fetch_media_by_ids", no_extra)
    result = await pipeline.recommend_for(USER, LANG)
    assert result.recos == []
    assert result.avoided == []
    # l'entry point è già pianificato: la fetch extra parte (col TS è sempre chiamata)
    # ma NON deve chiedere il 700, che sta già nella lista utente
    assert fetched["ids"] == []


async def test_entry_point_fetched_prende_il_badge(monkeypatch):
    # pool con solo il sequel 701: l'entry point 700 viene fetchato e, da
    # STANDALONE, forzato a ENTRY_POINT col badge (il TS fa franchise.set)
    pool = [base_media(701, relations=[rel(700, "PREQUEL")], popularity=200, averageScore=90)]
    _stub_pipeline(monkeypatch, [], pool)

    async def extra(ids, media_type="ANIME"):
        return [base_media(700, popularity=200, averageScore=90)]

    monkeypatch.setattr(pipeline, "fetch_media_by_ids", extra)
    result = await pipeline.recommend_for(USER, LANG)
    assert [r.media.id for r in result.recos] == [700]  # il sequel sostituito sparisce
    assert "ENTRY_POINT" in result.recos[0].badges
    assert result.recos[0].rootId == 700


async def test_tutte_le_query_candidati_fallite_502(monkeypatch):
    profile = pipeline.build_profile([], {}, USER)

    async def dead(**q):
        raise AniListError("dead", 503)

    monkeypatch.setattr(pipeline, "fetch_media_page", dead)
    with pytest.raises(AniListError) as err:
        await pipeline.fetch_candidates(profile, set())
    assert err.value.status == 502


async def test_un_singolo_failure_non_butta_il_pool(monkeypatch):
    profile = pipeline.build_profile([], {}, USER)
    calls = {"n": 0}

    async def half_dead(**q):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AniListError("dead", 503)
        return {"media": [base_media(1, popularity=100)], "hasNextPage": False}

    monkeypatch.setattr(pipeline, "fetch_media_page", half_dead)
    pool = await pipeline.fetch_candidates(profile, set())
    assert [m.id for m in pool] == [1]
    assert calls["n"] == 2  # cold-start: due pagine globali


def test_analyze_franchises_non_muta_i_candidati():
    # il port replica il TS per valori: l'oggetto passato non viene toccato
    m = base_media(1)
    before = m.model_dump()
    assert analyze_franchises([m], {})[1].kind == "STANDALONE"
    assert m.model_dump() == before


def test_js_log10_bit_esatto_v8():
    # regressione del port V8 di Math.log10 (js_compat): la libm CPython sbaglia
    # 1 ULP e quality/final non tornano coi golden — il caso reale è popularity
    # 115775, cioè log10(115776) con pop+1
    assert js_log10(2) == 0.3010299956639812
    m = base_media(1, averageScore=85, popularity=115775)
    assert pop_norm(m) == 0.7659046352109251  # libm darebbe ...53
    assert quality_of(m) == 0.833180927042185  # il valore del golden fixtures-real
    assert pop_norm(base_media(1, popularity=100000)) == 0.7500010857307762
    assert pop_norm(base_media(1, popularity=0)) == 0  # clamp basso
    assert pop_norm(base_media(1, popularity=1)) == 0
