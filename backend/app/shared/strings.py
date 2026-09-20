"""Porting di ``src/shared/strings.ts`` — SOLO le chiavi consumate dal dominio (P2).

``tr`` replica la semantica TS: dict della lingua → fallback ``en`` → la chiave
stessa; placeholder ``{k}`` sostituiti con ``String(v)`` (replaceAll).
Le restanti chiavi del dict TS (UI) non hanno consumatori server-side: si
portano quando compare il primo chiamante.
"""

from __future__ import annotations

from app.domain.js_compat import js_num_str
from app.shared.models import Lang

# src/shared/strings.ts righe 45-56 (en) — subset usato da scoring.ts
_EN: dict[str, str] = {
    "whyBase": "Matches your taste for {dims}{studioPart}.{examplesPart}{gemPart}",
    "whyNeutral": "Rated {avg}/100 on AniList by {pop} members.{gemPart}",
    "whyExamples": " Seen in: {examples}.",
    "whyEntryPoint": "It is also the first chapter of its series — a clean entry point.",
    "whyGem": " Hidden gem: only {pop} members, {avg}/100 on AniList.",
    "whyNotBase": "Shares {dims} you dropped or rated low{examplesPart}{droppedPart}.",
    "whyNotExamples": " (e.g. {examples})",
    "whyNotDropped": ", and you dropped {title} in this series",
    "dimGenre": "genres",
}

# src/shared/strings.ts righe 211-222 (it) — subset usato da scoring.ts
_IT: dict[str, str] = {
    "whyBase": "Matcha il tuo gusto per {dims}{studioPart}.{examplesPart}{gemPart}",
    "whyNeutral": "Valutato {avg}/100 su AniList da {pop} membri.{gemPart}",
    "whyExamples": " Visto in: {examples}.",
    "whyEntryPoint": "È anche il primo capitolo della serie — un buon punto d'ingresso.",
    "whyGem": " Gemma nascosta: solo {pop} membri, {avg}/100 su AniList.",
    "whyNotBase": "Condivide {dims} che hai droppato o votato basso{examplesPart}{droppedPart}.",
    "whyNotExamples": " (es. {examples})",
    "whyNotDropped": ", e in questa serie hai droppato {title}",
    "dimGenre": "generi",
}

_DICTS: dict[str, dict[str, str]] = {"en": _EN, "it": _IT}


def tr(lang: Lang, key: str, params: dict[str, str | float | int] | None = None) -> str:
    """Format a template with {placeholders}."""
    s = _DICTS[lang].get(key)
    if s is None:
        s = _EN.get(key)
    if s is None:
        s = key
    if params:
        for k, v in params.items():
            s = s.replace("{" + k + "}", v if isinstance(v, str) else js_num_str(v))
    return s
