"""Collaborative signal (CF v2) — loader dell'artefatto + user-vector runtime.

L'artefatto (``osusume-cf-v1.bin``, costruito da ``scripts/cf/build.py``) parla
già ID AniList: il join MAL avviene offline. Attivo SOLO se scaricato e
abilitato — senza, il motore è byte-identico (golden incluso).

Formato binario: [u32 header_len][header JSON][anilist_ids i32×count][vectors f16 count×dim]
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from app.core import config

try:  # numpy NON è dipendenza dell'app: senza, il CF resta spento (degradazione onesta)
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    HAS_NUMPY = False

MIN_OVERLAP = 5  # titoli dell'utente presenti nel modello: sotto, segnale spento (cold start)

_state: dict[str, Any] = {
    "state": "absent",  # loaded | absent | downloading | disabled | error
    "error": None,
    "header": None,
    "ids": None,  # np.ndarray int32
    "vectors": None,  # np.ndarray f32 count×dim
    "norms": None,
    "last_attempt": 0.0,
}
_download_task: asyncio.Task | None = None

CF_MODEL_URL = os.environ.get("CF_MODEL_URL") or (
    "https://github.com/LookUpMark/osusume/releases/download/cf-v1/osusume-cf-v1.bin"
)
_DOWNLOAD_THROTTLE_S = 3600.0


def model_path() -> Path:
    return Path(config.DATA_DIR) / "cf" / "model.bin"


def cf_enabled() -> bool:
    env = os.environ.get("CF_ENABLED")
    if env is not None:
        return env not in ("0", "false", "no")
    value = config.read_config_file().get("cfEnabled")
    return True if value is None else bool(value)


def state() -> dict:
    header = _state["header"] or {}
    return {
        "state": "disabled" if not cf_enabled() else _state["state"],
        "enabled": cf_enabled(),
        "version": header.get("version"),
        "builtAt": header.get("builtAt"),
        "count": header.get("count"),
        "smoke": header.get("smoke", False),
        "error": _state["error"],
    }


def _parse(raw: bytes) -> None:
    if not HAS_NUMPY:
        raise ValueError("numpy non disponibile — segnale collaborativo spento")
    if len(raw) < 8:
        raise ValueError("file troppo corto")
    header_len = int.from_bytes(raw[:4], "little")
    header = json.loads(raw[4 : 4 + header_len])
    if header.get("magic") != "osusume-cf":
        raise ValueError("magic mancante")
    rest = raw[4 + header_len :]
    count, dim = int(header["count"]), int(header["dim"])
    ids = np.frombuffer(rest[: count * 4], dtype=np.int32)
    vectors = np.frombuffer(rest[count * 4 : count * 4 + count * dim * 2], dtype=np.float16)
    if len(ids) != count or vectors.size != count * dim:
        raise ValueError("artefatto troncato")
    vectors = vectors.astype(np.float32).reshape(count, dim)
    norms = np.linalg.norm(vectors, axis=1)
    norms[norms == 0] = 1e-9
    _state.update(state="loaded", error=None, header=header, ids=ids, vectors=vectors, norms=norms)


def load_local() -> bool:
    """Carica il modello dal disco se presente (lifespan/throttle-friendly)."""
    if not HAS_NUMPY:
        _state.update(state="error", error="numpy non disponibile")
        return False
    if not cf_enabled():
        _state["state"] = "disabled"
        return False
    path = model_path()
    if not path.exists():
        _state["state"] = "absent"
        return False
    try:
        _parse(path.read_bytes())
        return True
    except Exception as e:
        _state.update(state="error", error=str(e))
        return False


async def ensure_cf_model(force: bool = False) -> bool:
    """Scarica l'artefatto se assente (throttled) e lo carica. Fire-and-forget safe.
    In test/demo mode (ANILIST_FIXTURES pinato) niente rete: il CF resta spento."""
    global _download_task
    if os.environ.get("ANILIST_FIXTURES"):
        _state["state"] = "absent" if not _state["header"] else _state["state"]
        return _state["state"] == "loaded"
    if not cf_enabled():
        _state["state"] = "disabled"
        return False
    if _state["state"] == "loaded":
        return True
    if force is False and time.time() - _state["last_attempt"] < _DOWNLOAD_THROTTLE_S:
        return _state["state"] == "loaded"
    if _download_task is not None and not _download_task.done():
        return await _download_task
    _state["last_attempt"] = time.time()
    _download_task = asyncio.ensure_future(_download_and_load(force))
    return await _download_task


async def _download_and_load(force: bool) -> bool:
    import httpx

    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return load_local()
    _state["state"] = "downloading"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await client.get(CF_MODEL_URL, timeout=None)
        res.raise_for_status()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(res.content)
        os.replace(tmp, path)  # atomic swap — mai un modello parziale
        return load_local()
    except Exception as e:
        _state.update(state="error", error=str(e))
        return False


def set_enabled(on: bool) -> None:
    config.update_config({"cfEnabled": True if on else False})
    if on:
        if not load_local():
            asyncio.ensure_future(ensure_cf_model(force=False))
    else:
        _state["state"] = "disabled"


def cf_scores(candidate_ids: list[int], loved_titles_ids: set[int]) -> dict[int, float]:
    """Similarità coseno tra l'user-vector (media dei vettori dei titoli amati
    presenti nel modello) e i candidati, normalizzata min-max sui candidati.
    Segnale spento: modello non caricato/disabilitato o overlap < MIN_OVERLAP."""
    if not HAS_NUMPY or _state["state"] != "loaded" or not cf_enabled():
        return {}
    idx = _index()
    vectors: np.ndarray = _state["vectors"]
    norms: np.ndarray = _state["norms"]

    rows = [idx[i] for i in loved_titles_ids if i in idx]
    if len(rows) < MIN_OVERLAP:
        return {}
    user_vec = vectors[rows].mean(axis=0)
    un = float(np.linalg.norm(user_vec))
    if un == 0:
        return {}

    present = [c for c in candidate_ids if c in idx]
    if len(present) < 2:
        return {}
    cand_rows = np.fromiter((idx[c] for c in present), dtype=np.int64, count=len(present))
    sims = (vectors[cand_rows] @ user_vec) / norms[cand_rows] / un
    lo, hi = float(sims.min()), float(sims.max())
    if hi - lo < 1e-6:
        return {}
    normalized = (sims - lo) / (hi - lo)
    return {int(cid): float(nv) for cid, nv in zip(present, normalized)}


_index_cache: dict[int, int] | None = None


def _index() -> dict[int, int]:
    global _index_cache
    if _index_cache is None:
        _index_cache = {int(i): k for k, i in enumerate(_state["ids"])}
    return _index_cache
