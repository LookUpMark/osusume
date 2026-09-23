"""Client LLM — porting di ``llmChat``/``llmHealth``/``resolveServedModel``
(llm.ts righe 29-105).

Timeout TOTALE ``LLM_TIMEOUT_MS`` via ``wait_for``; ``LlmError`` tipizzata così
i chiamanti distinguono "model/backend problem" (503, log) da errori generici.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx

from app.adapters.llm.setup import llm_auth_headers
from app.core import config


class LlmError(Exception):
    """Typed LLM failure: callers distinguish "model/backend problem" (503, log)
    from generic errors."""


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


# thinking OFF makes a full explanation ~150 tokens: budget for a batch, not
# for reasoning (the old 4000/16000 let Bonsai burn minutes of reasoning at 23 tok/s)
LLM_MAX_TOKENS = _int_env("LLM_MAX_TOKENS", 1200)
LLM_RETRY_TOKENS = _int_env("LLM_RETRY_TOKENS", 4000)


def is_truncation(e: BaseException) -> bool:
    """True when the failure was a token-budget truncation: thinking models spend
    the whole budget reasoning before the JSON — one bigger-budget retry wins."""
    return isinstance(e, LlmError) and "truncated" in str(e)


async def _served_model_ids() -> list[str] | None:
    """Id serviti da ``GET {base}/models`` (timeout totale 2s), None se non raggiungibile.

    follow_redirects: il fetch TS segue i redirect, httpx di default no.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await asyncio.wait_for(
                client.get(f"{config.llm_base_url()}/models", headers=llm_auth_headers(), timeout=None),
                2.0,
            )
        if not (200 <= res.status_code < 300):
            return None
        # il TS tollera entry non-oggetto (`m.id ?? ""` su una stringa → undefined → ""):
        # una sola entry sporca non deve spegnere il chip né rompere il leaf-match
        return [m.get("id") or "" for m in res.json().get("data") or [] if isinstance(m, dict)]
    except Exception:
        return None


async def served_models() -> list[str] | None:
    """Public view of ``GET {base}/models`` for the settings UI; None = unreachable."""
    return await _served_model_ids()


async def llm_health() -> bool:
    ids = await _served_model_ids()
    if ids is None:
        return False
    # a 200 on /models says nothing about OUR model: a chip that goes green
    # while every chat 404s is worse than an honest "off"
    want = config.configured_llm_model()
    if not want:
        return True  # no explicit model configured — reachable is all we know
    leaf = want.split("/")[-1]
    return any(m == want or m == leaf for m in ids)


async def resolve_served_model() -> str:
    """Servers rename models: oMLX serves bare names while the config may hold an
    org/repo id (404 on every chat otherwise). Resolve once per call round."""
    want = config.llm_model()
    ids = await _served_model_ids()
    if ids is None:
        return want  # unreachable — keep the configured id, the chat error will surface
    leaf = want.split("/")[-1]
    if want in ids:
        return want
    if leaf and leaf in ids:
        return leaf
    return want


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


async def llm_chat(messages: list[dict[str, str]], model: str, max_tokens: int | None = None) -> str:
    """``llmChat`` — server down / socket error become LlmError so /api/chat can
    answer 503 llm_unavailable (honest, fast) instead of a generic 500."""
    if max_tokens is None:
        max_tokens = LLM_MAX_TOKENS
    try:
        # follow_redirects: il fetch TS segue i redirect, httpx di default no
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await asyncio.wait_for(
                client.post(
                    f"{config.llm_base_url()}/chat/completions",
                    headers={"content-type": "application/json", **llm_auth_headers()},
                    content=json.dumps(
                        {
                            "model": model,
                            "messages": messages,
                            "temperature": 0.3,
                            "max_tokens": max_tokens,
                            # mild anti-loop pressure — small quants fall into verbatim paragraph
                            # repetition; servers without the field just drop it
                            "repetition_penalty": 1.12,
                            # Qwen3-family hard switch (Bonsai included): unknown fields are dropped
                            # by servers that don't support it. Verified live: without it the model
                            # spends the whole budget in invisible reasoning (~3 min per call).
                            "chat_template_kwargs": {"enable_thinking": False},
                        },
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    timeout=None,  # il timeout totale è gestito da wait_for
                ),
                config.LLM_TIMEOUT_MS / 1000,
            )
    except (httpx.TransportError, asyncio.TimeoutError) as e:
        raise LlmError(f"LLM unreachable ({e})")
    if not (200 <= res.status_code < 300):
        raise LlmError(f"LLM HTTP {res.status_code}")
    body = res.json()
    choice = (body.get("choices") or [None])[0] if isinstance(body, dict) else None
    if choice and choice.get("finish_reason") == "length":
        raise LlmError("LLM output truncated (finish_reason=length)")
    # templates without the kwarg may still reason inline — strip what we can
    content = ((choice or {}).get("message") or {}).get("content") or ""
    content = _THINK_RE.sub("", content).strip()
    # lone surrogate (escape \ud800 dal JSON LLM): utf-8 non la codifica → 500 su
    # chat/explain e cache mai scritta; il TS la ri-escapava (well-formed stringify) —
    # qui il code point si scarta, il testo resta sempre encodabile
    content = "".join(ch for ch in content if not 0xD800 <= ord(ch) <= 0xDFFF)
    if not content:
        raise LlmError("LLM returned empty content")
    return content
