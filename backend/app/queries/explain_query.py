"""``POST /api/explain`` (api.ts righe 101-125): subset del risultato corrente +
scoring on-demand per gli id fuori lista, poi ``explainRecos`` (P3)."""

from __future__ import annotations

from typing import Any

from app.adapters.llm.explain import explain_recos
from app.domain import pipeline
from app.shared.models import Lang


def normalize_ids(raw: list[Any]) -> list[float | int]:
    """``new Set((body?.ids ?? []).filter(x => typeof x === "number"))``.

    Dedup con ordine di PRIMA comparsa (il Set JS itera così). I bool NON sono
    ``typeof number``; ``5`` e ``5.0`` sono la stessa chiave del Set come del dict.
    """
    return list(dict.fromkeys(x for x in raw if isinstance(x, (int, float)) and not isinstance(x, bool)))


async def explain(username: str, ids: list[float | int], lang: Lang) -> dict:
    """Ordine risposta = ordine subset raccomandazioni (contract §7).

    ``staleOk: true`` come /chat: la dialog spiega un risultato che la UI mostra
    già — ricalcolare tutta la lista a dialog aperto sono secondi di attesa morta.
    """
    result = await pipeline.get_recommendation(username, lang, stale_ok=True)
    wanted = set(ids)
    subset = [r for r in result.recos if r.media.id in wanted]
    # ids outside the recommendation list (chat lookup) are scored on demand
    missing = [i for i in ids if not any(r.media.id == i for r in subset)]
    if len(missing) > 0:
        _, extra = await pipeline.score_arbitrary(missing, username, lang)
        subset.extend(r for r in extra if r.media.id in wanted)
    explanations = await explain_recos(subset, result.profile, lang, username)
    return {
        "explanations": [
            {"id": media_id, "text": e.text, "source": e.source} for media_id, e in explanations.items()
        ]
    }
