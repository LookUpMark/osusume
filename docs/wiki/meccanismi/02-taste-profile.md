# 02 — Taste profile

**Abstract.** Derives the viewer's loved/disliked dimensions (tags, genres, studios, eras) from the whole AniList list, with sentiment weighting, support shrinkage and a stable content hash used as cache key everywhere downstream.

## Purpose

Turn a raw list (COMPLETED/DROPPED/PLANNING… with scores) into a compact `TasteProfile` the scorer and the LLM prompts can both consume.

## How it works (`build_profile`, `backend/app/domain/profile.py:140-188`)

1. `mean_score_of` (`profile.py:49-54`): mean of positive scores; fallback 60 when fewer than 3 scored entries.
2. Per entry, `entry_sentiment` (`profile.py:57-69`): PLANNING → weight 0 (no signal); sentiment `s = clamp(statusBase + (score-mean)/40 + 0.1·min(repeat,3) + 0.2-if-completed-unrated, -1, 1)`; weight 1 if scored, 0.6 if DROPPED, else 0.4.
3. `_add_sentiment` (`profile.py:77-103`): accumulates per `dim:value` key, weighted by `rank_factor` (tags × rank/100); `support` counts only positive-weight observations; keeps up to 3 example titles with `s > 0.3`.
4. `_finalize_sides` (`profile.py:106-137`): drops dims with zero weight or `support < supportMin` (2); `aff = (sum/weight) · min(support, 10)/10` (support shrinkage); loved iff `aff > 0.05`, disliked iff `< -0.05`; caps by strength — tag 20 / genre 8 / studio 5 / era 4 loved, half that disliked (`backend/app/shared/weights.py:45-51`).
5. Profile hash (`profile.py:176-177`): sha256[:16] over lexicographically sorted `mediaId:status:score:repeat` lines — the sort is string-based on purpose so the hash changes exactly when the list meaningfully changes; it keys the explanation cache (see [06-llm-layer.md](meccanismi/06-llm-layer.md)).
6. `meanScore` serialized as `js_number(js_round(mean*10)/10)`; `confidence = "ok"` iff ≥3 scored entries (`profile.py:181-186`).

## Data & states

- `TasteProfile` (`backend/app/shared/models.py:105-114`): `userName, meanScore, scoredCount, confidence, loved[], disliked[], counts, hash`.
- `DimValue` (`models.py:95-102`): `dim, value, aff, support, examples[]`.
- Affinity map domain: `-1..1`, disliked overwrite loved on key collision (consumed by `affinity_of`, [03-recommendation-pipeline.md](meccanismi/03-recommendation-pipeline.md)).

## Edge cases

- Unrated completed entries get a small negative bias (they cost the viewer time with no endorsement).
- `< 3 scored` → confidence "low", surfaced in the UI (`App.tsx` profile view) and worth less in prompts.
- Empty/PLANNING-heavy lists produce a near-empty profile — the pipeline's cold-start path takes over.

## Dependencies

- Reads user lists from the AniList adapter ([01-anilist-adapter.md](meccanismi/01-anilist-adapter.md)).
- Consumed by scoring and prompts ([03](meccanismi/03-recommendation-pipeline.md), [06-llm-layer.md](meccanismi/06-llm-layer.md)).
- Number formatting via JS-parity helpers ([04-js-parity-golden.md](meccanismi/04-js-parity-golden.md)).

## Files covered

- `backend/app/domain/profile.py`
- `backend/app/queries/profile_query.py`

## Studio

1. Why does PLANNING carry weight 0 instead of a small positive value?
2. What is the effect of support shrinkage (`min(support,10)/10`) on a niche tag seen once?
3. Why is the profile hash built from sorted string lines rather than a JSON dump?
