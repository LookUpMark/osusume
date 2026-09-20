"""Client AniList — porting di rate limiter + ``gql`` (anilist.ts righe 100-192).

Token bucket asyncio (Lock + monotonic): capacità 3, refill ``RATE_PER_MIN/60``
al secondo, OGNI richiesta passa dal bucket. ``gql`` incapsula la cache: timeout
TOTALE 15s (``wait_for`` attorno alla chiamata httpx — il timeout per-fase httpx
NON equivale ad ``AbortSignal.timeout``), retry ladder con UN solo contatore
``attempt`` condiviso fra i rami (nel TS è l'``attempt++`` del ``for``).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

import httpx

from app.adapters.anilist import cache
from app.core import config, js_json


class AniListError(Exception):
    """``AniListError`` TS: messaggio + status HTTP della risposta."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


# --- rate limiting -------------------------------------------------------------

_tokens = 3.0
_last_refill = time.monotonic()
_refill_per_sec = max(0.1, config.RATE_PER_MIN / 60)
_lock = asyncio.Lock()


async def take_token() -> None:
    global _tokens, _last_refill
    while True:
        async with _lock:
            now = time.monotonic()
            _tokens = min(3, _tokens + (now - _last_refill) * _refill_per_sec)
            _last_refill = now
            if _tokens >= 1:
                _tokens -= 1
                return
        await asyncio.sleep(1 / _refill_per_sec)  # attesa reale del bucket


def reset_bucket_for_tests() -> None:
    """Riporta il bucket allo stato di partenza del processo TS (3 token)."""
    global _tokens, _last_refill
    _tokens = 3.0
    _last_refill = time.monotonic()


async def sleep_ms(ms: float) -> None:
    """Sleep del retry ladder: punto unico sostituibile dai test (backoff istantanei)."""
    await asyncio.sleep(ms / 1000)


def _js_header_number(raw: str | None) -> float:
    """``Number(header)`` JS: NaN se assente/non numerico."""
    if raw is None:
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


# --- network -------------------------------------------------------------------

_TIMEOUT_TOTAL_S = 15.0
_MAX_RETRIES = 3
_MAX_429_ROUNDS = 10


async def _post(query: str, variables: dict[str, Any]) -> httpx.Response:
    # follow_redirects: il fetch TS segue i redirect, httpx di default no
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return await asyncio.wait_for(
            client.post(
                config.ANILIST_ENDPOINT,
                headers={"content-type": "application/json", "accept": "application/json"},
                content=json.dumps({"query": query, "variables": variables}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                timeout=None,  # il timeout totale è gestito da wait_for
            ),
            _TIMEOUT_TOTAL_S,
        )


async def _gql_fetch(query: str, variables: dict[str, Any]) -> Any:
    attempt = -1  # il for TS incrementa a ogni giro: qui l'incremento apre il giro
    while True:
        attempt += 1
        await take_token()
        try:
            res = await _post(query, variables)
        except (httpx.TransportError, asyncio.TimeoutError) as e:
            if attempt < _MAX_RETRIES:
                await sleep_ms(1000 * 2**attempt)
                continue
            raise AniListError(f"AniList unreachable: {e}", 502)
        if res.status_code == 429:
            if attempt >= _MAX_429_ROUNDS:
                raise AniListError("AniList rate-limited for too long", 429)
            raw = _js_header_number(res.headers.get("retry-after"))
            # bounded: never hammer AniList (ToS) — cap 10 rounds, sanitized delay
            delay = min(raw, 60) if math.isfinite(raw) and raw > 0 else 5
            await sleep_ms(delay * 1000)
            continue
        if res.status_code >= 500 and attempt < _MAX_RETRIES:
            await sleep_ms(1000 * 2**attempt)
            continue
        try:
            json_body = res.json()
        except ValueError:
            if attempt < _MAX_RETRIES:
                await sleep_ms(1000 * 2**attempt)
                continue
            raise AniListError(f"AniList HTTP {res.status_code} (non-JSON body)", res.status_code)
        errors = json_body.get("errors") if isinstance(json_body, dict) else None
        if errors:
            e0 = errors[0]
            status = e0.get("status")
            raise AniListError(e0.get("message"), status if status is not None else res.status_code)
        data = json_body.get("data") if isinstance(json_body, dict) else None
        # ``!json.data`` del TS: dict/list sono SEMPRE truthy, contano null/""/0/false
        if data is None or data is False or data == 0 or data == "":
            raise AniListError(f"AniList HTTP {res.status_code}", res.status_code)
        return data


async def gql(query: str, variables: dict[str, Any], ttl_ms: int) -> Any:
    """``gql`` TS: chiave = ``sha256(query + JSON.stringify(variables))``."""
    return await cache.cache_wrap(js_json.sha256_key(query, variables), ttl_ms, lambda: _gql_fetch(query, variables))
