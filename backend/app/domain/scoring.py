"""Porting 1:1 di ``src/server/scoring.ts`` — funzioni pure, zero I/O.

Ogni funzione cita il corrispondente simbolo TS. Deviazioni dichiarate:
``diversify`` e ``dedupeFranchises`` restituiscono NUOVI oggetti (in TS mutano
gli input) — spec §2.2.8.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Iterable, NamedTuple

import regex as re  # \p{L} non esiste nella stdlib re (spec §2.2.5)

from app.domain.franchise import is_spin_off
from app.shared.weights import WEIGHTS
from app.domain.js_compat import js_log10, js_num_str, to_locale_string
from app.domain.profile import clamp
from app.shared.models import (
    Badge,
    DimValue,
    FranchiseInfo,
    Lang,
    MediaLite,
    RecoBreakdown,
    RecoLink,
    ScoredReco,
    TasteProfile,
)
from app.shared.strings import tr


class Affinity(NamedTuple):
    """Ritorno di ``affinityOf``: ``{ affinity01, parts }``."""

    affinity01: float
    parts: dict[str, float]


class Overlap(NamedTuple):
    """Elemento del ritorno di ``lovedOverlap``: ``{ label, examples }``."""

    label: str
    examples: list[str]


class SeenItem(NamedTuple):
    """Tipo inline del parametro di ``buildSeenCorpus`` (scoring.ts riga 295)."""

    title: str
    description: str | None
    sentiment: float


class SeenText(NamedTuple):
    """Interfaccia ``SeenText`` (scoring.ts riga 288) — keywords in ordine di inserimento."""

    title: str
    keywords: dict[str, None]


def affinity_map(p: TasteProfile) -> dict[str, float]:
    """``affinityMap``: disliked dopo loved → la collisione vince disliked (come Map.set)."""
    return {f"{d.dim}:{d.value}": d.aff for d in [*p.loved, *p.disliked]}


def pop_norm(m: MediaLite) -> float:
    """``popNorm``: 0 (pop ~100) → 1 (pop ~100k+): gems and mainstream separate.

    ``Math.log10`` di V8, NON la libm di CPython: divergono fino a 1 ULP
    (js_compat ha il dettaglio) e i golden bloccano il bit.
    """
    return clamp((js_log10(m.popularity + 1) - 2) / 4, 0, 1)


def affinity_of(m: MediaLite, p: TasteProfile) -> Affinity:
    """``affinityOf``: affinità 0..1 del candidato contro il profilo.

    core = 0.5 tag (rank-weighted) + 0.3 genre + 0.12 studio + 0.08 era,
    neutralizzato con (core + 1) / 2.
    """
    am = affinity_map(p)

    def aff(dim: str, value: str | None) -> float:
        return 0 if value is None else am.get(f"{dim}:{value}", 0)

    tag_num = 0.0
    tag_den = 0.0
    for t in m.tags:
        tag_num += aff("tag", t.name) * (t.rank / 100)
        tag_den += t.rank / 100
    tag_score = tag_num / tag_den if tag_den > 0 else 0

    genre_score = sum(aff("genre", g) for g in m.genres) / len(m.genres) if len(m.genres) > 0 else 0
    studio_score = aff("studio", m.studio)
    era_score = aff("era", None if m.seasonYear is None else str(5 * (m.seasonYear // 5)))

    core = (
        WEIGHTS["tag"] * tag_score
        + WEIGHTS["genre"] * genre_score
        + WEIGHTS["studio"] * studio_score
        + WEIGHTS["era"] * era_score
    )
    return Affinity((core + 1) / 2, {"tag": tag_score, "genre": genre_score, "studio": studio_score, "era": era_score})


def quality_of(m: MediaLite) -> float:
    """``qualityOf``: 0.8 * (averageScore ?? 60)/100 + 0.2 * pop_norm."""
    return WEIGHTS["qualityScore"] * ((m.averageScore if m.averageScore is not None else 60) / 100) + WEIGHTS[
        "qualityPop"
    ] * pop_norm(m)


def gem_score_of(m: MediaLite, affinity01: float, quality: float) -> float:
    """``gemScoreOf``: 0.65 aff + 0.35 quality − 0.3 pop_norm."""
    return (
        WEIGHTS["gemAffinity"] * affinity01
        + WEIGHTS["gemQuality"] * quality
        - WEIGHTS["gemPopPenalty"] * pop_norm(m)
    )


def is_gem(m: MediaLite, gem: float) -> bool:
    """``isGem``: pop < 40_000 AND (averageScore ?? 0) >= 72 AND gem >= 0.45.

    averageScore null → mai gem (il ``?? 0`` TS).
    """
    return (
        m.popularity < WEIGHTS["gemMaxPopularity"]
        and (m.averageScore if m.averageScore is not None else 0) >= WEIGHTS["gemMinScore"]
        and gem >= WEIGHTS["gemMinGemScore"]
    )


# --- deterministic explanations -------------------------------------------------


def _hit(d: DimValue, tag_names: set[str], values: set[str]) -> bool:
    """Confronto condiviso di lovedOverlap/deterministicWhyNot: era MAI (scoring.ts 77-78, 135-137)."""
    return (d.value in tag_names) if d.dim == "tag" else (d.dim != "era" and d.value in values)


def loved_overlap(m: MediaLite, p: TasteProfile) -> list[Overlap]:
    """``lovedOverlap``: loved dims presenti sul candidato, più forti prima.

    Solo tag rank >= 60; genre/studio su {genres} ∪ {studio}; max 2, ordinate
    per aff desc; soglia dura aff > 0.05.
    """
    tag_names = {t.name for t in m.tags if t.rank >= 60}
    values = {*m.genres, *([m.studio] if m.studio else [])}
    out: list[Overlap] = []
    for d in sorted(p.loved, key=lambda d: -d.aff):
        if _hit(d, tag_names, values) and d.aff > 0.05:
            out.append(Overlap(f"{d.dim}:{d.value}", d.examples[:2]))
        if len(out) >= 2:
            break
    return out


def deterministic_why(
    m: MediaLite,
    p: TasteProfile,
    badges: list[Badge],
    lang: Lang,
    franchise: FranchiseInfo | None = None,
) -> str:
    """``deterministicWhy`` (scoring.ts righe 85-120)."""
    overlap = loved_overlap(m, p)
    examples = list(dict.fromkeys(ex for o in overlap for ex in o.examples))[:3]
    if len(overlap) == 0:
        # no taste overlap to cite — stay honest: quality + popularity only
        return tr(
            lang,
            "whyNeutral",
            {
                "avg": "?" if m.averageScore is None else js_num_str(m.averageScore),
                "pop": to_locale_string(m.popularity, lang),
                "gemPart": (
                    tr(
                        lang,
                        "whyGem",
                        {
                            "pop": to_locale_string(m.popularity, lang),
                            "avg": "?" if m.averageScore is None else js_num_str(m.averageScore),
                        },
                    )
                    if "HIDDEN_GEM" in badges
                    else ""
                ),
            },
        )
    dims = ", ".join(o.label.replace(":", " ") for o in overlap)  # split(':').join(' ')
    base = tr(
        lang,
        "whyBase",
        {
            "dims": dims or tr(lang, "dimGenre"),
            "studioPart": "",
            "examplesPart": tr(lang, "whyExamples", {"examples": ", ".join(examples)}) if len(examples) > 0 else "",
            "gemPart": (
                tr(
                    lang,
                    "whyGem",
                    {
                        "pop": to_locale_string(m.popularity, lang),
                        "avg": "?" if m.averageScore is None else js_num_str(m.averageScore),
                    },
                )
                if "HIDDEN_GEM" in badges
                else ""
            ),
        },
    )
    return f"{base} {tr(lang, 'whyEntryPoint')}" if franchise is not None and franchise.kind == "ENTRY_POINT" else base


def deterministic_why_not(
    m: MediaLite,
    p: TasteProfile,
    f: FranchiseInfo | None,
    dropped_title: str | None,
    lang: Lang,
) -> str | None:
    """``deterministicWhyNot``: null quando manca prova negativa onesta.

    Il ramo whyNot richiede aff < −0.3 (scoring.ts riga 138).
    """
    tag_names = {t.name for t in m.tags if t.rank >= 60}
    values = {*m.genres, *([m.studio] if m.studio else [])}
    bad: list[str] = []
    examples: list[str] = []
    for d in sorted(p.disliked, key=lambda d: d.aff):
        if _hit(d, tag_names, values) and d.aff < -0.3:
            bad.append(f"{d.dim} {d.value}")
            examples.extend(d.examples[:2])
        if len(bad) >= 2:
            break
    if len(bad) == 0 and not dropped_title:
        return None
    unique_examples = list(dict.fromkeys(examples))[:3]
    return tr(
        lang,
        "whyNotBase",
        {
            "dims": ", ".join(bad),
            "examplesPart": (
                tr(lang, "whyNotExamples", {"examples": ", ".join(unique_examples)}) if len(unique_examples) > 0 else ""
            ),
            "droppedPart": tr(lang, "whyNotDropped", {"title": dropped_title}) if dropped_title else "",
        },
    )


# --- scoring --------------------------------------------------------------------


def score_all(
    candidates: list[MediaLite],
    p: TasteProfile,
    community: dict[int, float],
    franchise: dict[int, FranchiseInfo],
    lang: Lang,
    mood: dict[int, float] | None = None,
    cf_scores: dict[int, float] | None = None,
) -> list[ScoredReco]:
    """``scoreAll`` (scoring.ts righe 158-201).

    final = clamp(0.6 aff + 0.28 quality + community (cap 0.1) + mood
                  + (NEXT_STEP ? 0.12 : 0) + cf (cap 0.1, solo col modello), 0, 1.1).
    Badge order push: NEXT_STEP, ENTRY_POINT, SPIN_OFF, HIDDEN_GEM;
    ENTRY_POINT prende il badge SENZA bonus; rootId null se STANDALONE.

    ``cf_scores`` è il segnale collaborativo (CF v2, 0..1 per candidato): None =
    segnale spento (nessun modello) → contributo 0 e risultato byte-identico al TS.
    Non entra nel breakdown serializzato: sposta il ranking, il dialog resta com'è.
    """
    mood = mood if mood is not None else {}
    cf = cf_scores if cf_scores is not None else {}
    out: list[ScoredReco] = []
    for m in candidates:
        a = affinity_of(m, p)
        quality = quality_of(m)
        comm = min(WEIGHTS["communityCap"], community.get(m.id, 0))
        mood_bonus = mood.get(m.id, 0)
        cf_bonus = min(WEIGHTS["cfCap"], WEIGHTS["cf"] * cf.get(m.id, 0))
        f = franchise.get(m.id)
        badges: list[Badge] = []
        if f is not None and f.kind == "NEXT_STEP":
            badges.append("NEXT_STEP")
        if f is not None and f.kind == "ENTRY_POINT":
            badges.append("ENTRY_POINT")
        if is_spin_off(m):
            badges.append("SPIN_OFF")
        gem = gem_score_of(m, a.affinity01, quality)
        if is_gem(m, gem):
            badges.append("HIDDEN_GEM")

        final = clamp(
            WEIGHTS["affinity"] * a.affinity01
            + WEIGHTS["quality"] * quality
            + comm
            + mood_bonus
            + cf_bonus
            + (WEIGHTS["franchiseBonus"] if "NEXT_STEP" in badges else 0),
            0,
            1.1,
        )
        out.append(
            ScoredReco(
                media=m,
                final=final,
                breakdown=RecoBreakdown(
                    affinity=a.affinity01,
                    quality=quality,
                    community=comm,
                    mood=mood_bonus,
                ),
                badges=badges,
                rootId=None if (f is None or f.kind == "STANDALONE") else f.rootId,
                groupSize=1,
                why=deterministic_why(m, p, badges, lang, f),
            )
        )
    out.sort(key=lambda r: -r.final)  # stabile, come Array.sort (tie → ordine di inserimento)
    return out


def _pair_sim(a: MediaLite, b: MediaLite) -> float:
    """``pairSim``: genre jaccard + same-studio — cosa significa "quasi gemello"."""
    ga = set(a.genres)
    gb = set(b.genres)
    inter = len(ga & gb)
    union = len(ga | gb) or 1
    return (inter / union) * 0.5 + (0.5 if a.studio is not None and a.studio == b.studio else 0)


def diversify(recos: list[ScoredReco], lambda_: float = 0.15) -> list[ScoredReco]:
    """``diversify``: MMR greedy — PURA (in TS muta gli input, spec §2.2.8).

    λ piccolo: si muovono solo i vicini forti. mmRank è la posizione
    diversificata (1-based). Tie → primo indice (confronto ``>`` stretto).
    """
    pool = list(recos)
    out: list[ScoredReco] = []
    while pool:
        best_idx = 0
        best_score = -math.inf
        for i, c in enumerate(pool):
            sim = max((_pair_sim(c.media, s.media) for s in out), default=0)
            score = c.final - lambda_ * sim
            if score > best_score:
                best_score = score
                best_idx = i
        out.append(pool.pop(best_idx))
    return [r.model_copy(update={"mmRank": i + 1}) for i, r in enumerate(out)]


def dedupe_franchises(recos: list[ScoredReco]) -> list[ScoredReco]:
    """``dedupeFranchises``: un rappresentante per franchise + groupSize.

    I ``rootId`` null sono sempre tenuti; per ogni root si conta TUTTO il
    gruppo e si tiene il ``final`` massimo; i non-tenuti sono copie con
    groupSize aggiornata (in TS spread ``{...r}``).
    """
    best_by_root: dict[int, ScoredReco] = {}
    size_by_root: dict[int, int] = {}
    for r in recos:
        if r.rootId is None:
            continue
        size_by_root[r.rootId] = size_by_root.get(r.rootId, 0) + 1
        best = best_by_root.get(r.rootId)
        if best is None or r.final > best.final:  # '>' stretto: tie → resta il primo
            best_by_root[r.rootId] = r
    kept = {id(r) for r in best_by_root.values()}  # identità, come new Set(values) in TS
    return [
        r if r.rootId is None else r.model_copy(update={"groupSize": size_by_root.get(r.rootId, 1)})
        for r in recos
        if r.rootId is None or id(r) in kept
    ]


# --- plot-text links (scoring v2): connect candidates to what the user watched ---

# STOP_WORDS copiata INTEGRALE da scoring.ts righe 261-274: duplicati e forme
# strappate ('perche'/'perché', 'pero'/'però', 'cioe'/'cioè') restano — un set
# li assorbe, la fedeltà conta più la pulizia.
STOP_WORDS: frozenset[str] = frozenset(
    {
        # EN
        "the", "and", "that", "with", "this", "from", "they", "their", "them", "have", "has", "had",
        "been", "were", "will", "would", "could", "into", "than", "then", "when", "what", "which",
        "while", "after", "before", "because", "about", "against", "between", "through", "there",
        "these", "those", "being", "under", "over", "more", "most", "some", "such", "only", "also",
        "very", "just", "your", "have", "each", "other", "both", "must", "make", "made", "their",
        # IT
        "della", "delle", "degli", "dallo", "nella", "nelle", "sullo", "sulla", "come", "dove",
        "quando", "perche", "perché", "anche", "sono", "essere", "hanno", "questo", "questa",
        "questi", "queste", "quella", "quello", "molto", "troppo", "ancora", "prima", "dopo",
        "durante", "senza", "tutte", "tutti", "tutto", "tutta", "contro", "verso", "fuori",
        "dentro", "solo", "fino", "nella", "come", "però", "pero", "cioè", "cioe",
    }
)


def tokenize(text: str) -> dict[str, None]:
    """``tokenize``: lowercase → NFKD → ``[^\\p{L}\\s]``→spazio → split → len>3 → no stopword.

    I combining mark di NFKD NON sono ``\\p{L}``: il sub li elimina (equivalente
    del replace ``/[^\\p{L}\\s]/gu`` TS — NON unicodedata.combining).

    Ritorna un dict-chiavi (NON un ``set``): il Set JS itera in ordine di
    INSERIMENTO, il set Python è hash-randomizzato — l'ordine determina quali
    4 parole sopravvivono al cap di ``text_links``.
    """
    return dict.fromkeys(
        w
        for w in re.split(r"\s+", re.sub(r"[^\p{L}\s]", " ", unicodedata.normalize("NFKD", text.lower())))
        # `String.length` è in unità UTF-16, non code point: un token di 2-3 code
        # point astrali (CJK ext-B) conta 4-6 e passa il filtro come nel TS
        if len(w.encode("utf-16-le")) // 2 > 3 and w not in STOP_WORDS
    )


def build_seen_corpus(items: Iterable[SeenItem]) -> list[SeenText]:
    """``buildSeenCorpus``: titoli visti a voto positivo con testo di trama utilile."""
    kept = [i for i in items if i.sentiment > 0 and i.description]
    mapped = [SeenText(i.title, tokenize(i.description)) for i in kept]
    return [i for i in mapped if len(i.keywords) >= 8]


def text_links(m: MediaLite, seen: list[SeenText], limit: int = 2) -> list[RecoLink]:
    """``textLinks``: titoli visti la cui trama condivide vocabolario col candidato.

    shared >= 3, cap 4 parole per link (le PRIME 4 in ordine di inserimento,
    come il Set JS), sort desc per shared, max ``limit``.
    """
    themes = " ".join(t.name for t in m.tags if t.rank >= 60 and not t.isSpoiler)
    cand = tokenize(f"{m.description if m.description is not None else ''} {themes}")
    if len(cand) == 0:
        return []
    out: list[RecoLink] = []
    for s in seen:
        shared = [w for w in cand if w in s.keywords]
        if len(shared) >= 3:
            out.append(RecoLink(title=s.title, shared=shared[:4]))
    return sorted(out, key=lambda l: -len(l.shared))[:limit]
