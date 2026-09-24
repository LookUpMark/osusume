"""``explainRecos`` (llm.ts righe 260-354) + cache spiegazioni.

Explain recos via the local LLM. Falls back to the deterministic why for any
id the model misses — all-or-nothing LLM failure still yields explanations.

Ordine operazioni NON negoziabile (spec §2): cache key → pre-riempimento
(cache/fallback) → resolve model + reviews → batch ≤10 → llm_chat (retry
truncation) → parse (retry correttivo) → break su errore LLM → solo testo LLM
vero in cache (merge atomico tmp+rename). Il wiring della query arriva in P4.
"""

from __future__ import annotations

import hashlib
import json
import os

from app.adapters.anilist.cache import now_ms
from app.adapters.anilist.media import gather_reviews
from app.adapters.llm.client import LLM_RETRY_TOKENS, is_truncation, llm_chat, resolve_served_model
from app.adapters.llm.parse import Explanation, parse_explanations
from app.adapters.llm.prompts import build_prompt
from app.adapters.llm.setup import log_llm
from app.core import config
from app.shared.models import Explanation as ExplanationModel
from app.shared.models import Lang, ScoredReco, TasteProfile

# bumped when the prompt voice changes — old cached explanations must not resurface
PROMPT_VERSION = "v5-media"

_SYSTEM_JSON = (
    "You output only valid JSON. Do not explain your reasoning — the reply must be ONLY the JSON array."
)

_CORRECTIVE = (
    'Your reply did not match the required format. Each item must be exactly {"id":<media id>,"why":"<explanation text>"}. Reply again with ONLY the JSON array.'
)


def _expl_dir() -> str:
    return os.path.join(config.CACHE_DIR, "expl")


def cache_key(recos: list[ScoredReco], profile: TasteProfile, lang: str, username: str, media_type: str = "ANIME") -> str:
    """``createHash().update(prefix).update(ids.join(","))`` del TS.

    `systemPromptExtra` entra nella key: cambiare le istruzioni personali deve
    invalidare le spiegazioni cachate, non servire la voce vecchia per 7 giorni.
    Il TIPO (anime/manga) pure: stessi id non possono travestirsi."""
    ids = ",".join(str(r.media.id) for r in sorted(recos, key=lambda r: r.media.id))
    extra_hash = hashlib.sha1(config.system_prompt_extra().strip().encode("utf-8")).hexdigest()[:12]
    return hashlib.sha256(
        f"{username}|{profile.hash}|{lang}|{media_type}|{config.llm_model()}|{config.llm_base_url()}|{PROMPT_VERSION}|{extra_hash}|{ids}".encode("utf-8")
    ).hexdigest()


async def _cache_get(key: str) -> dict[str, str] | None:
    try:
        with open(os.path.join(_expl_dir(), f"{key}.json"), encoding="utf-8") as f:
            hit = json.load(f)
        if now_ms() < hit["exp"]:
            items = hit["items"]
            return items if isinstance(items, dict) else None  # cache corrotta → miss
    except Exception:
        pass  # miss
    return None


async def _cache_set(key: str, items: dict[str, str]) -> None:
    os.makedirs(_expl_dir(), exist_ok=True)
    file = os.path.join(_expl_dir(), f"{key}.json")
    tmp = f"{file}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"exp": now_ms() + config.CACHE_TTL_EXPL_MS, "items": items}, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, file)  # atomic swap — no partial reads


def _collapse(text: str) -> str:
    return " ".join(text.split())


async def explain_recos(
    recos: list[ScoredReco],
    profile: TasteProfile,
    lang: Lang,
    username: str,
    media_type: str = "ANIME",
) -> dict[int, ExplanationModel]:
    out: dict[int, ExplanationModel] = {}
    pending: list[ScoredReco] = []
    fresh: dict[str, str] = {}

    key = cache_key(recos, profile, lang, username, media_type)
    cached = await _cache_get(key)
    for r in recos:
        hit = (cached or {}).get(str(r.media.id))
        out[r.media.id] = (
            ExplanationModel(text=hit, source="cache") if hit else ExplanationModel(text=r.why, source="fallback")
        )
        if not hit:
            pending.append(r)
    if not pending:
        return out

    try:
        model = await resolve_served_model()
        # real reception as critic grounding (never blocking — failures degrade silently)
        reviews = await gather_reviews([r.media.id for r in pending])
        # ponytail: batches of max 10 — small local models degrade past that
        for i in range(0, len(pending), 10):
            batch = pending[i : i + 10]
            items: list[Explanation] = []
            try:
                chat = [
                    {"role": "system", "content": _SYSTEM_JSON},
                    {"role": "user", "content": build_prompt(batch, profile, lang, reviews, media_type)},
                ]
                try:
                    raw = await llm_chat(chat, model)
                except Exception as e:
                    if not is_truncation(e):
                        raise
                    # thinking models burn the default budget reasoning: one retry with
                    # a big budget — the explanation is per-title and cached for a week
                    raw = await llm_chat(chat, model, LLM_RETRY_TOKENS)
                items = parse_explanations(raw)
                if not items:
                    # small models sometimes return valid JSON with a wrong key ("where"
                    # instead of "why"): one corrective retry beats a silent fallback
                    log_llm(f"explain: batch unparseabile ({_collapse(raw[:60])}…) — retry correttivo")
                    corrective = [*chat, {"role": "user", "content": _CORRECTIVE}]
                    try:
                        raw = await llm_chat(corrective, model)
                        items = parse_explanations(raw)
                    except Exception:
                        pass  # keep the deterministic fallbacks
            except Exception as e:
                # log the failure — silent fallbacks made "why is there no LLM text?" undebuggable
                log_llm(f"explain: LLM error ({e}) per model={config.llm_model()} — prose deterministiche in uso")
                break
            for item in items:
                reco = next((r for r in batch if r.media.id == item["id"]), None)
                text = item["why"].strip()
                # only genuine LLM output is cached — caching deterministic fallbacks would
                # mask model failures as source:"cache" for a week
                if reco and len(text) > 0:
                    out[item["id"]] = ExplanationModel(text=text, source="llm")
                    fresh[str(item["id"])] = text
        if fresh:
            await _cache_set(key, {**(cached or {}), **fresh})
    except Exception as e:
        # LLM unreachable/slow — deterministic fallbacks already in place, but leave a trace
        log_llm(f"explain: fallito ({e}) — prose deterministiche in uso")
    return out
