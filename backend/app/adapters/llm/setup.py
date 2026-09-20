"""Helper di processo condivisi — subset di ``src/server/setup.ts`` utile a P3.

Completamento (resolveLms/resolveOmlx/job) in P5; qui solo ciò che client ed
explain consumano: auth headers e llm.log.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.core import config


def read_omlx_key() -> str | None:
    """The oMLX API key never leaves the server: read in-memory, used as auth header only.

    ponytail: versione minima (env + ~/.omlx/settings.json) — la logica completa
    (resolve omlx bin/model) arriva in P5.
    """
    if os.environ.get("OMLX_API_KEY"):
        return os.environ["OMLX_API_KEY"]
    try:
        with open(os.path.join(os.path.expanduser("~"), ".omlx", "settings.json"), encoding="utf-8") as f:
            key = (json.load(f).get("auth") or {}).get("api_key")
        return key if isinstance(key, str) and len(key) > 0 else None
    except Exception:
        return None


def llm_auth_headers() -> dict[str, str]:
    """``llmAuthHeaders`` (setup.ts righe 202-210) — Auth headers for the configured
    backend. Keys never leave the server."""
    if os.environ.get("LLM_API_KEY"):
        return {"authorization": f"Bearer {os.environ['LLM_API_KEY']}"}
    if config.read_config_file().get("backend") == "omlx":
        key = read_omlx_key()
        if key:
            return {"authorization": f"Bearer {key}"}
    return {}


def log_llm(line: str) -> None:
    """``logLlm`` (setup.ts righe 179-188) — shared llm.log writer: LLM errors
    must be observable, never swallowed."""
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        now = datetime.now(timezone.utc)
        iso = now.strftime("%Y-%m-%dT%H:%M:%S") + f".{now.microsecond // 1000:03d}Z"
        with open(os.path.join(config.DATA_DIR, "llm.log"), "a", encoding="utf-8") as f:
            f.write(f"{iso} {line}\n")
    except Exception:
        pass  # logging must never crash the app
