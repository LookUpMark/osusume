"""Porting 1:1 di ``tests/scoring.test.ts`` (374 righe, 17 scenari).

Stessi fixture (media/profile costruite a mano) e stessi valori pinned: il
titolo TS di ogni scenario è citato nella docstring.
"""

from __future__ import annotations

from app.domain.franchise import analyze_franchises
from app.domain.scoring import (
    SeenItem,
    affinity_of,
    build_seen_corpus,
    dedupe_franchises,
    deterministic_why,
    deterministic_why_not,
    diversify,
    gem_score_of,
    is_gem,
    pop_norm,
    quality_of,
    score_all,
    text_links,
    tokenize,
)
from app.shared.models import (
    DimValue,
    FranchiseInfo,
    ListEntry,
    MediaLite,
    RecoBreakdown,
    ScoredReco,
    TasteProfile,
)
from helpers import media


def make_profile(**over) -> TasteProfile:
    base = dict(
        userName="test",
        meanScore=70,
        scoredCount=10,
        confidence="ok",
        counts={"CURRENT": 0, "PLANNING": 0, "COMPLETED": 10, "DROPPED": 2, "PAUSED": 0, "REPEATING": 0},
        loved=[
            DimValue(dim="tag", value="Psychological", aff=0.6, support=8, examples=["X"]),
            DimValue(dim="genre", value="Mystery", aff=0.4, support=8, examples=["X"]),
        ],
        disliked=[DimValue(dim="genre", value="Isekai", aff=-0.7, support=4, examples=["Y"])],
        hash="abc",
    )
    base.update(over)
    return TasteProfile(**base)


profile = make_profile()


def test_affinita_studio_ed_era_contano():
    # "affinity: studio and era dims count (20% of the core weight)"
    p = profile.model_copy(
        update={
            "loved": [
                DimValue(dim="studio", value="Madhouse", aff=0.6, support=5, examples=["X"]),
                DimValue(dim="era", value="2015", aff=0.4, support=5, examples=["X"]),
            ]
        }
    )
    hit = media(1, studio="Madhouse", seasonYear=2015)
    miss = media(2, studio="Toei", seasonYear=1990)
    a_hit = affinity_of(hit, p).affinity01
    a_miss = affinity_of(miss, p).affinity01
    # core = 0.12·0.6 + 0.08·0.4 = 0.104 → affinity01 0.552; no match → neutral 0.5
    assert a_hit > 0.55, f"studio+era match must beat neutral, got {a_hit}"
    assert a_miss == 0.5


def test_affinita_tag_amosati_spingono_generi_odati_trascinano_giu():
    # "affinity: loved tags push up, disliked genres pull down"
    loved = media(1, tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}], genres=["Mystery"])
    hated = media(2, genres=["Isekai"])
    neutral = media(3)
    a_loved = affinity_of(loved, profile).affinity01
    a_hated = affinity_of(hated, profile).affinity01
    a_neutral = affinity_of(neutral, profile).affinity01
    assert a_loved > 0.6, f"loved should be high, got {a_loved}"
    assert a_hated < 0.4, f"hated should be low, got {a_hated}"
    assert a_neutral == 0.5
    assert a_loved > a_neutral > a_hated


def test_pop_norm_separa_gemme_da_mainstream():
    # "popNorm separates gems from mainstream"
    assert pop_norm(media(1, popularity=1000)) < 0.3
    assert pop_norm(media(1, popularity=5000)) < 0.45
    assert pop_norm(media(1, popularity=40000)) > 0.6
    assert pop_norm(media(1, popularity=500000)) > 0.9


def test_badge_hidden_gem_pop_bassa_voto_buono_fit_buono():
    # "hidden gem badge: low popularity + good score + good fit"
    tags = [{"name": "Psychological", "rank": 95, "isSpoiler": False}]
    genres = ["Mystery"]
    gem = media(1, popularity=5000, averageScore=78, tags=tags, genres=genres)
    aff = affinity_of(gem, profile).affinity01
    gem_score = gem_score_of(gem, aff, quality_of(gem))
    assert is_gem(gem, gem_score), f"expected gem, gemScore={gem_score}"
    # same fit but popular and mediocre → no gem
    popular = media(2, popularity=500000, averageScore=60, tags=tags, genres=genres)
    assert not is_gem(popular, gem_score_of(popular, aff, quality_of(popular)))
    # thresholds are exact: popularity < 40_000 and averageScore ≥ 72 flip the flag
    def at_limit(over) -> MediaLite:
        base = dict(popularity=3000, averageScore=78, tags=tags, genres=genres)
        base.update(over)
        return media(9, **base)

    m = at_limit({"popularity": 40_000})
    assert not is_gem(m, gem_score_of(m, aff, quality_of(m)))
    m = at_limit({"popularity": 39_999})
    assert is_gem(m, gem_score_of(m, aff, quality_of(m)))
    m = at_limit({"averageScore": 71})
    assert not is_gem(m, gem_score_of(m, aff, quality_of(m)))
    m = at_limit({"averageScore": 72})
    assert is_gem(m, gem_score_of(m, aff, quality_of(m)))


def test_score_all_bonus_community_cappato_next_step_ordinato():
    # "scoreAll: community bonus capped, next step bonus applied, sorted by final"
    candidates = [
        media(1, tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}], genres=["Mystery"]),
        media(2, genres=["Isekai"]),
        media(3),
    ]
    community = {
        1: 0.5,  # way over cap
        3: 0.02,
    }
    franchise = {
        1: FranchiseInfo(kind="NEXT_STEP", rootId=1, entryPointId=None, droppedId=None),
        2: FranchiseInfo(kind="STANDALONE", rootId=2, entryPointId=None, droppedId=None),
        3: FranchiseInfo(kind="STANDALONE", rootId=3, entryPointId=None, droppedId=None),
    }
    recos = score_all(candidates, profile, community, franchise, "en")
    assert recos[0].media.id == 1
    top = recos[0]
    assert top.breakdown.community == 0.1, "community bonus must be capped at 0.1"
    assert "NEXT_STEP" in top.badges
    assert len(top.why) > 10
    assert recos[0].final >= recos[1].final


def test_dedupe_franchises_un_rappresentante_per_franchise_group_size():
    # "dedupeFranchises: one representative per franchise, groupSize annotated"
    # natural ranking: media(2) beats media(1) via higher score — no mutation
    recos = score_all(
        [
            media(1, averageScore=60),
            media(2, averageScore=95),
            media(3, averageScore=70),
            media(4, averageScore=65),
            media(5, averageScore=68),
        ],
        profile,
        {},
        {
            1: FranchiseInfo(kind="NEXT_STEP", rootId=100, entryPointId=None, droppedId=None),
            2: FranchiseInfo(kind="NEXT_STEP", rootId=100, entryPointId=None, droppedId=None),
            3: FranchiseInfo(kind="STANDALONE", rootId=3, entryPointId=None, droppedId=None),
            4: FranchiseInfo(kind="NEXT_STEP", rootId=200, entryPointId=None, droppedId=None),
            5: FranchiseInfo(kind="NEXT_STEP", rootId=200, entryPointId=None, droppedId=None),
        },
        "en",
    )
    deduped = dedupe_franchises(recos)
    assert len(deduped) == 3, "5 candidates in 2 franchises + 1 standalone"
    rep_a = next((r for r in deduped if r.media.id == 2), None)
    assert rep_a is not None and rep_a.groupSize == 2, "franchise 100 keeps its best member with groupSize 2"
    rep_b = next((r for r in deduped if r.media.id == 5), None)
    assert rep_b is not None and rep_b.groupSize == 2
    standalone = next((r for r in deduped if r.media.id == 3), None)
    assert standalone is not None and standalone.groupSize == 1
    assert all(deduped[i].final >= deduped[i + 1].final for i in range(len(deduped) - 1))


def test_score_all_entry_point_badge_senza_bonus_spin_off_solo_badge():
    # "scoreAll: ENTRY_POINT gets the badge but no franchise bonus; spin-offs badge only"
    def twin(id: int, relations) -> MediaLite:
        return media(
            id,
            tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}],
            genres=["Mystery"],
            relations=relations,
        )

    candidates = [
        twin(1, []),  # next step
        twin(2, []),  # entry point
        media(3, relations=[{"id": 50, "relationType": "SPIN_OFF"}], genres=["Isekai"]),  # spin-off, disliked genre
    ]
    franchise = {
        1: FranchiseInfo(kind="NEXT_STEP", rootId=1, entryPointId=None, droppedId=None),
        2: FranchiseInfo(kind="ENTRY_POINT", rootId=2, entryPointId=2, droppedId=None),
        3: FranchiseInfo(kind="STANDALONE", rootId=3, entryPointId=None, droppedId=None),
    }
    recos = score_all(candidates, profile, {}, franchise, "en")
    next_ = next(r for r in recos if r.media.id == 1)
    entry = next(r for r in recos if r.media.id == 2)
    spin = next(r for r in recos if r.media.id == 3)
    assert entry.badges == ["ENTRY_POINT"]
    assert next_.badges == ["NEXT_STEP"]
    assert entry.final < next_.final, "ENTRY_POINT must not receive the +0.12 franchise bonus"
    assert "SPIN_OFF" in spin.badges
    assert "NEXT_STEP" not in spin.badges


def test_franchise_prequel_droppato_esclude_sequel():
    # "franchise: dropped prequel excludes sequel (analyzeFranchises)"
    list_map = {201: ListEntry(mediaId=201, status="DROPPED", score=0, repeat=0, title="S1")}
    candidates = [
        media(201, relations=[{"id": 202, "relationType": "SEQUEL"}]),
        media(202, relations=[{"id": 201, "relationType": "PREQUEL"}]),
    ]
    info = analyze_franchises(candidates, list_map)
    assert info[202].kind == "EXCLUDED"
    assert info[202].droppedId == 201


def test_franchise_mai_s3_senza_s1_entry_point_e_s1():
    # "franchise: never show S3 without S1 → entry point is S1"
    candidates = [
        media(101, relations=[{"id": 102, "relationType": "SEQUEL"}]),
        media(102, relations=[{"id": 101, "relationType": "PREQUEL"}]),
        media(103, relations=[{"id": 102, "relationType": "PREQUEL"}]),
    ]
    # user completed S1 only
    list_map = {101: ListEntry(mediaId=101, status="COMPLETED", score=90, repeat=0, title="S1")}
    info = analyze_franchises(candidates, list_map)
    assert info[102].kind == "NEXT_STEP", "S1 completed → S2 is the next step"
    assert info[103].kind == "ENTRY_POINT"
    # first unseen node from the root side = S2 (the user's actual next watch)
    assert info[103].entryPointId == 102


def test_why_why_not_template_onesti_senza_autoreferenzze():
    # "deterministic why/whyNot: honest templates, no self-references"
    m = media(
        9,
        genres=["Isekai"],
        tags=[{"name": "Isekai", "rank": 80, "isSpoiler": False}],
        averageScore=60,
        popularity=90000,
    )
    # why: no loved overlap → neutral quality sentence, no invented claims
    why = deterministic_why(m, profile, [], "en")
    assert "m9" not in why, "why must not cite the candidate itself"
    assert "60/100" in why, why
    assert "90,000" in why, why  # pin: toLocaleString("en")
    # whyNot: shares disliked Isekai + the dropped prequel
    franchise = FranchiseInfo(kind="EXCLUDED", rootId=9, entryPointId=None, droppedId=3)
    why_not = deterministic_why_not(m, profile, franchise, "Dropped Series S1", "en")
    assert why_not is not None
    assert "Isekai" in why_not
    assert "Dropped Series S1" in why_not, why_not
    # no negative evidence at all → null (never invent a reason)
    neutral = media(10, genres=["Mystery"])
    assert deterministic_why_not(neutral, profile, None, None, "en") is None
    # why with real overlap cites the loved dim and its example titles
    loved = media(11, tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}], genres=["Mystery"])
    why_loved = deterministic_why(loved, profile, [], "en")
    assert "Psychological" in why_loved
    assert "X" in why_loved, why_loved


def test_franchise_ciclo_di_relations_non_si_blocca():
    # "franchise: relation cycle does not hang"
    candidates = [
        media(501, relations=[{"id": 502, "relationType": "PREQUEL"}]),
        media(502, relations=[{"id": 501, "relationType": "PREQUEL"}]),
    ]
    info = analyze_franchises(candidates, {})
    assert len(info) == 2
    # both members share one canonical root → dedupeFranchises collapses them
    assert info[501].rootId == info[502].rootId
    assert info[501].kind == "ENTRY_POINT"
    assert info[501].entryPointId == 502


def test_franchise_catena_lunga_13_prequel_root_canonico_unico():
    # "franchise: long chain (13 prequels) keeps one canonical root"
    candidates = [
        media(id, relations=[{"id": id - 1, "relationType": "PREQUEL"}] if id > 1 else []) for id in range(1, 14)
    ]
    list_map = {
        id: ListEntry(mediaId=id, status="COMPLETED", score=80, repeat=0, title=f"s{id}") for id in range(3, 14)
    }
    info = analyze_franchises(candidates, list_map)
    roots = {f.rootId for f in info.values()}
    assert len(roots) == 1, f"all 13 members must share one root, got {roots}"
    assert info[1].rootId == 1
    assert info[13].kind == "ENTRY_POINT"
    assert info[13].entryPointId == 1, "first unseen from root side"
    # even mid-chain members collapse to the same entry point
    assert info[12].kind == "ENTRY_POINT"
    assert info[12].entryPointId == 1


def test_plot_text_links_e_tokenizer():
    # "scoring v2: plot-text links + entry-point why"
    a = tokenize("Heroes train at the academy to master their quirk powers")
    assert "heroes" in a and "academy" in a, "meaningful words kept"
    assert "their" not in a and "the" not in a, "stopwords and short words dropped"

    corpus = build_seen_corpus(
        [
            SeenItem("My Hero Academia", "Heroes training at the academy master quirk powers in class battles", 0.8),
            SeenItem("Short desc", "too short", 0.9),
            SeenItem("Dropped one", "Heroes academy quirk training again but dropped", -0.5),
        ]
    )
    assert len(corpus) == 1, "only positive-sentiment with enough text"

    cand = media(
        5,
        popularity=50_000,
        description="A school for heroes where students train their quirk in class",
    )
    links = text_links(cand, corpus)
    assert len(links) == 1
    assert links[0].title == "My Hero Academia"
    assert len(links[0].shared) >= 3, "shared plot vocabulary extracted"

    no_links = text_links(media(5, popularity=50_000, description=None), corpus)
    assert len(no_links) == 0, "no description — no fabricated links"

    # pin regression: con 5+ parole condivise il cap 4 deve tenere le PRIME 4 in
    # ordine di inserimento (Set JS) — un set Python sarebbe hash-randomizzato
    many = media(
        6,
        popularity=50_000,
        description="Heroes train at the academy to master their quirk powers in class battles",
    )
    assert text_links(many, corpus)[0].shared == ["heroes", "academy", "master", "quirk"]

    # pin extra (golden recommend-it): CLDR it raggruppa da 5 cifre in su
    it_why = deterministic_why(media(9, popularity=90000, averageScore=60), profile, [], "it")
    assert "90.000 membri" in it_why, it_why
    it_small = deterministic_why(media(9, popularity=5000, averageScore=78), profile, [], "it")
    assert "5000 membri" in it_small, it_small


def test_franchise_entry_point_aggiunge_hint_al_why():
    # "scoring v2: entry-point franchise adds the entry hint to the why"
    m = media(
        9,
        seasonYear=2020,
        tags=[{"name": "Psychological", "rank": 90, "isSpoiler": False}],
        popularity=50_000,
    )
    p = make_profile(
        userName="u",
        meanScore=70,
        scoredCount=5,
        counts={"CURRENT": 0, "PLANNING": 0, "COMPLETED": 5, "DROPPED": 0, "PAUSED": 0, "REPEATING": 0},
        loved=[DimValue(dim="tag", value="Psychological", aff=0.6, support=5, examples=["Serial Experiments Lain"])],
        disliked=[],
        hash="h",
    )
    base = deterministic_why(m, p, [], "en")
    with_ep = deterministic_why(
        m, p, [], "en", FranchiseInfo(kind="ENTRY_POINT", rootId=9, entryPointId=9, droppedId=None)
    )
    assert "entry point" not in base, "no hint without franchise info"
    assert "entry point" in with_ep, "hint appended for ENTRY_POINT"


def test_ciclo_prequel_mai_autoreferenziale():
    # "scoring v2: PREQUEL cycle never self-references (pin f4-1)"
    list_map = {
        1: ListEntry(mediaId=1, status="COMPLETED", score=80, repeat=0, title="t1"),
        2: ListEntry(mediaId=2, status="COMPLETED", score=80, repeat=0, title="t2"),
    }
    cands = [
        media(1, relations=[{"id": 2, "relationType": "PREQUEL"}]),
        media(2, relations=[{"id": 1, "relationType": "PREQUEL"}]),
    ]
    info = analyze_franchises(cands, list_map)
    for id_, f in info.items():
        assert f.entryPointId != id_, f"franchise {id_} must not be its own entry point"
        assert f.kind != "EXCLUDED", "a two-node seen cycle is not dropped material"


def test_mmr_diversita_allontana_i_gemelli_e_assegna_mm_rank():
    # "scoring v2: MMR diversity pushes twins apart and assigns mmRank"
    def twin(id: int, final: float) -> ScoredReco:
        return ScoredReco(
            media=media(id, studio="Bones", genres=["Action", "Comedy"]),
            final=final,
            breakdown=RecoBreakdown(affinity=final * 0.6, quality=final * 0.3, community=0),
            badges=[],
            rootId=None,
            groupSize=1,
            why=f"why {id}",
        )

    def other(id: int, final: float) -> ScoredReco:
        return ScoredReco(
            media=media(id, studio="Kyoto Animation", genres=["Slice of Life"]),
            final=final,
            breakdown=RecoBreakdown(affinity=final * 0.6, quality=final * 0.3, community=0),
            badges=[],
            rootId=None,
            groupSize=1,
            why=f"why {id}",
        )

    out = diversify([twin(1, 0.90), twin(2, 0.88), other(3, 0.87)])
    assert [r.media.id for r in out] == [1, 3, 2], "twin #2 moves below the dissimilar title"
    assert [r.mmRank for r in out] == [1, 2, 3], "mmRank is the diversified position"


def test_bonus_mood_alza_il_finale_e_compare_nel_breakdown():
    # "scoring v2: mood bonus lifts the final score and lands in the breakdown"
    p = make_profile(
        userName="u",
        meanScore=70,
        scoredCount=5,
        counts={"CURRENT": 0, "PLANNING": 0, "COMPLETED": 5, "DROPPED": 0, "PAUSED": 0, "REPEATING": 0},
        loved=[],
        disliked=[],
        hash="h",
    )
    cands = [media(7)]
    plain = score_all(cands, p, {}, {}, "en")
    boosted = score_all(cands, p, {}, {}, "en", {7: 0.04})
    assert boosted[0].final > plain[0].final, "mood bonus lifts final"
    assert boosted[0].breakdown.mood == 0.04
    plain_mood = plain[0].breakdown.mood
    assert (plain_mood if plain_mood is not None else 0) == 0
