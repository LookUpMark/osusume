"""Modelli pydantic specchio campo-per-campo di ``src/shared/types.ts``
(+ ``FranchiseInfo``/``FranchiseKind`` da ``src/server/franchise.ts``).

I nomi dei campi restano camelCase: il JSON verso il client è identico per
costruzione (contract §1). Opzionalità replicata dal TS:

- ``X | null`` (obbligatorio, nullable) → ``X | None`` senza default;
- ``field?: number`` (assente o numero) → ``X | None = None``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_serializer

from app.domain.js_compat import js_number

Lang = Literal["en", "it"]


def _js_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _js_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_js_numbers(v) for v in value]
    return js_number(value)


class JsModel(BaseModel):
    """Base comune: serializza i float integrali come interi (``84``, non ``84.0``).

    ``JSON.stringify`` JS non distingue int/float (``84.0`` → ``84``) mentre
    pydantic emette ``84.0`` per un campo ``float`` — payload HTTP e confronto
    golden divergerebbero. Vale SOLO per la serializzazione (python e json):
    i tipi interni del dominio restano float.
    """

    @model_serializer(mode="wrap")
    def _serialize(self, handler) -> Any:
        return _js_numbers(handler(self))

ListStatus = Literal["CURRENT", "PLANNING", "COMPLETED", "DROPPED", "PAUSED", "REPEATING"]

Dim = Literal["tag", "genre", "studio", "era"]

Badge = Literal["NEXT_STEP", "ENTRY_POINT", "HIDDEN_GEM", "SPIN_OFF"]


class ListEntry(JsModel):
    mediaId: int
    status: ListStatus
    # Normalized 0-100 (0 = unscored).
    score: float
    repeat: int
    # Unix seconds of last list update (mood recency) — 0 in old fixtures.
    updatedAt: int | None = None
    title: str


class MediaTagLite(JsModel):
    name: str
    rank: float
    isSpoiler: bool


class MediaRelationLite(JsModel):
    id: int
    relationType: str


class MediaLite(JsModel):
    # 14 campi tutti obbligatori: nullable format/seasonYear/averageScore/studio/
    # coverImage/coverColor/siteUrl/description (types.ts righe 33-48).
    id: int
    title: str
    format: str | None
    seasonYear: int | None
    genres: list[str]
    tags: list[MediaTagLite]
    studio: str | None
    averageScore: float | None
    popularity: int
    coverImage: str | None
    coverColor: str | None
    siteUrl: str | None
    description: str | None
    relations: list[MediaRelationLite]


class DimValue(JsModel):
    dim: Dim
    value: str
    # -1..1, shrunk by support.
    aff: float
    support: int
    # Titles the user rated highly that contain this value.
    examples: list[str]


class TasteProfile(JsModel):
    userName: str
    meanScore: float | int
    scoredCount: int
    confidence: Literal["ok", "low"]
    counts: dict[ListStatus, int]
    loved: list[DimValue]
    disliked: list[DimValue]
    # Stable fingerprint of the list (ids+scores+statuses).
    hash: str


# --- franchise.ts ----------------------------------------------------------------

FranchiseKind = Literal["STANDALONE", "NEXT_STEP", "ENTRY_POINT", "EXCLUDED"]


class FranchiseInfo(JsModel):
    kind: FranchiseKind
    # First entry of the chain (prequel-most known id). Groups share this.
    rootId: int
    # Where the user should start watching (only for ENTRY_POINT).
    entryPointId: int | None
    # Prequel the user dropped (only for EXCLUDED).
    droppedId: int | None


# --- scoring.ts ------------------------------------------------------------------

class RecoBreakdown(JsModel):
    affinity: float
    quality: float
    community: float
    mood: float | None = None


class RecoLink(JsModel):
    title: str
    shared: list[str]


class ScoredReco(JsModel):
    media: MediaLite
    # 0..1.1, display x100.
    final: float
    breakdown: RecoBreakdown
    badges: list[Badge]
    rootId: int | None
    groupSize: int
    why: str
    # Plot-text links to positively-rated watched titles (scoring v2, set in recommend).
    links: list[RecoLink] | None = None
    # Default-order position (MMR-diversified, 1-based) — the recos list sorts by it.
    mmRank: int | None = None


class Explanation(JsModel):
    text: str
    source: Literal["llm", "cache", "fallback"]


class WhyNot(JsModel):
    media: MediaLite
    reason: str


class RecoResult(JsModel):
    profile: TasteProfile
    recos: list[ScoredReco]
    avoided: list[WhyNot]
