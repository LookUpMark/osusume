"""Adapter LLM (P3): porting di src/server/llm.ts + src/server/chat.ts.

client.py (llmChat/health/resolve), prompts.py (doctrine verbatim), parse.py
(scan bilanciato), explain.py (batch + cache spiegazioni), setup.py (subset di
setup.ts: auth headers + llm.log).
"""

from __future__ import annotations

from .chat import chat_reply, mentioned_titles
from .client import LlmError, is_truncation, llm_chat, llm_health, resolve_served_model
from .explain import explain_recos
from .parse import parse_explanations
from .prompts import COMPARISON_STANDARD, build_chat_system, build_prompt, clean_text

__all__ = [
    "COMPARISON_STANDARD",
    "LlmError",
    "build_chat_system",
    "build_prompt",
    "chat_reply",
    "clean_text",
    "explain_recos",
    "is_truncation",
    "llm_chat",
    "llm_health",
    "mentioned_titles",
    "parse_explanations",
    "resolve_served_model",
]
