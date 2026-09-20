"""Helper di processo condivisi — subset di ``src/server/setup.ts`` (completo da P5).

Qui solo la famiglia di chiavi: auth headers e lettura in-memory di ~/.omlx/settings.json
(porta server + api_key, MAI persistite né loggate). Il resto del porting (hardware,
catalogo, job singleton, ensure) vive in ``app/adapters/system/setup.py``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from app.core import config


def _omlx_settings() -> dict:
    """Contenuto di ~/.omlx/settings.json o ``{}`` (file assente/corrotto → silenzio)."""
    try:
        with open(os.path.join(os.path.expanduser("~"), ".omlx", "settings.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def read_omlx_key() -> str | None:
    """The oMLX API key never leaves the server: read in-memory, used as auth header only.

    ``readOmlxKey`` (setup.ts righe 108-117): env OMLX_API_KEY > settings.json auth.api_key.
    """
    if os.environ.get("OMLX_API_KEY"):
        return os.environ["OMLX_API_KEY"]
    key = (_omlx_settings().get("auth") or {}).get("api_key")
    return key if isinstance(key, str) and len(key) > 0 else None


def read_omlx_port() -> str | None:
    """Port from ~/.omlx/settings.json — the oMLX CLI writes there; probing the wrong
    port costs a full HTTP timeout on every status/ensure round (setup.ts righe 90-98)."""
    p = (_omlx_settings().get("server") or {}).get("port")
    if isinstance(p, (int, float)) and not isinstance(p, bool) and p > 0:
        return str(p)
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


def omlx_auth_headers() -> dict[str, str]:
    """``omlxAuthHeaders`` (setup.ts righe 215-218) — oMLX probes authenticate whenever
    a key exists — NOT only when the config already says backend "omlx": during the
    wizard the config is still empty and a keyless probe gets a 401, making a live
    server look unreachable."""
    key = read_omlx_key()
    return {"authorization": f"Bearer {key}"} if key else {}


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
