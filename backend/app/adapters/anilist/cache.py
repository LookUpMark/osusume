"""Cache disco AniList — porting di ``cacheWrap`` (anilist.ts righe 121-140).

File ``{CACHE_DIR}/<sha256(key)>.json`` con ``{"exp": <epoch ms>, "data": ...}``;
hit solo se ``now < exp``; parse error = miss silenzioso; DEDUP in-flight per
path (una sola richiesta per chiave, gli altri chiamanti ne attendono il
risultato); scrittura DIRETTA non atomica (come il TS); i file scaduti non
vengono cancellati. Stati di processo module-level, come il TS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Awaitable, Callable, TypeVar

from app.core import config

T = TypeVar("T")

# path file → task in corso (la Map<string, Promise<unknown>> del TS)
_inflight: dict[str, asyncio.Future] = {}


def now_ms() -> int:
    """``Date.now()``: epoch in millisecondi."""
    return int(time.time() * 1000)


def cache_file(key: str) -> str:
    """``join(CACHE_DIR, sha256(key).json)`` — il TS hasha la key una seconda volta."""
    hex_ = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return os.path.join(config.CACHE_DIR, f"{hex_}.json")


async def cache_wrap(key: str, ttl_ms: int, fn: Callable[[], Awaitable[T]]) -> T:
    file = cache_file(key)
    try:
        # I/O file SYNC nel path async, come il TS (app monoutente): niente to_thread
        with open(file, encoding="utf-8") as f:
            hit = json.load(f)
        if now_ms() < hit["exp"]:
            return hit["data"]
    except Exception:
        pass  # miss
    # concurrent identical lookups share one in-flight request
    task = _inflight.get(file)
    if task is None:
        task = asyncio.ensure_future(fn())
        task.add_done_callback(lambda _t: _inflight.pop(file, None))
        _inflight[file] = task
    data = await task
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    with open(file, "w", encoding="utf-8") as f:
        json.dump(
            {"exp": now_ms() + ttl_ms, "data": data},
            f,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    return data
