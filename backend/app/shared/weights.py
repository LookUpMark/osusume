"""Costanti pure del motore — porting 1:1 di ``WEIGHTS`` in ``src/server/config.ts``.

Modulo SENZA import (nemmeno lato app): è l'unico modo per far importare il
dominio i propri pesi senza trascinare l'I/O di ``app.core.config`` (che a
import time legge ``.env`` da disco e muta ``os.environ``).
``app.core.config`` re-importa questo dict ed lo esporta come ``WEIGHTS``:
i chiamanti di config non cambiano e i valori vivono in un punto solo.
"""

WEIGHTS = {
    # candidate affinity mix (sums to 1 over the -1..1 core)
    "tag": 0.5,
    "genre": 0.3,
    "studio": 0.12,
    "era": 0.08,
    # final score mix
    "affinity": 0.6,
    "quality": 0.28,
    "franchiseBonus": 0.12,
    "communityPerHit": 0.03,
    "communityCap": 0.1,
    "mood": 0.04,  # continuity bonus: shares themes/plot with the last 5 completed
    # collaborative signal (post-port): attivo SOLO col modello scaricato —
    # senza artefatto il contributo è 0 e il motore resta byte-identico
    "cf": 0.1,
    "cfCap": 0.1,
    # quality mix
    "qualityScore": 0.8,
    "qualityPop": 0.2,
    # gem score
    "gemAffinity": 0.65,
    "gemQuality": 0.35,
    "gemPopPenalty": 0.3,
    "gemMaxPopularity": 40_000,
    "gemMinScore": 72,
    "gemMinGemScore": 0.45,
    # sentiment
    "scoreSpread": 40,  # points from your mean = full ±1 weight
    "statusBase": {
        "COMPLETED": 0,
        "CURRENT": 0.1,
        "REPEATING": 0.15,
        "PAUSED": -0.25,
        "DROPPED": -0.6,
    },
    "repeatBonus": 0.1,
    "repeatCap": 3,
    # profile thresholds
    "lovedMin": 0.05,
    "supportMin": 2,
    "supportShrink": 10,
    "topTags": 20,
    "topGenres": 8,
    "topStudios": 5,
    "topDisliked": 10,
}
