"""``parseExplanations`` (llm.ts righe 196-240).

Extract a valid JSON array even when a thinking model wraps it in prose.
Scans balanced arrays last→first: reasoning text often contains bracketed
fragments, and the real answer comes after it. Mai throw: zero item = [].
"""

from __future__ import annotations

import json
import math
from typing import Any

Explanation = dict[str, Any]  # { id: int, why: str }

_MISSING = object()  # distingue "chiave assente" (undefined JS) da JSON null


def _js_number(value: Any) -> float:
    """``Number(x)`` JS sul campo id: str/bool/oggetto → numero o NaN."""
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:  # Number(null) === 0
        return 0.0
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return float("nan")
    return float("nan")  # Number(undefined) / Number({}) === NaN


def _js_id(x: Any) -> float:
    """``typeof x?.id === "number" ? x.id : Number(x?.id)`` — undefined ≠ null."""
    if not isinstance(x, dict):
        return float("nan")  # x?.id è undefined
    raw_id = x.get("id", _MISSING)
    if raw_id is _MISSING:
        return float("nan")
    if isinstance(raw_id, bool):  # True è int in Python, non in JS
        return 1.0 if raw_id else 0.0
    if isinstance(raw_id, (int, float)):
        return float(raw_id)
    return _js_number(raw_id)


def _reject_constant(token: str) -> float:
    """``JSON.parse`` rifiuta NaN/Infinity/-Infinity, ``json.loads`` li accetta:
    rilancio per scartare l'intero span (il TS passerebbe al precedente)."""
    raise ValueError(f"invalid JSON constant: {token}")


def _try_parse(slice_str: str) -> list[Explanation] | None:
    try:
        arr = json.loads(slice_str, parse_constant=_reject_constant)
    except ValueError:
        return None
    if not isinstance(arr, list):
        return None
    items: list[Explanation] = []
    for x in arr:
        num = _js_id(x)
        why = x.get("why") if isinstance(x, dict) else None
        # Number.isInteger: NaN/Infinity non lo passano mai
        if math.isnan(num) or math.isinf(num) or not num.is_integer() or not isinstance(why, str):
            continue
        items.append({"id": int(num), "why": why})
    return items if items else None


def parse_explanations(raw: str) -> list[Explanation]:
    # collect candidate [ ... ] spans (string-aware depth scan)
    spans: list[tuple[int, int]] = []
    depth = 0
    start = -1
    in_string = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if in_string:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append((start, i))
                start = -1
        i += 1
    for s, e in reversed(spans):
        items = _try_parse(raw[s : e + 1])
        if items:
            return items
    return []
