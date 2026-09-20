"""Porting fedele di ``src/server/config.ts``.

Precedenza ovunque: env > data/config.json > default hardcoded.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

# --- Minimal .env loader (no dependency): KEY=VALUE lines, existing env wins. ---
# Values: matched quotes stripped, inline ` # comment` truncated.
try:
    for _line in (_REPO_ROOT / ".env").read_text(encoding="utf-8").split("\n"):
        _m = re.match(r"^([A-Z_]+)=(.*)$", _line)
        if _m and _m.group(1) not in os.environ:
            _v = _m.group(2).strip()
            if len(_v) > 1 and (
                (_v.startswith('"') and _v.endswith('"')) or (_v.startswith("'") and _v.endswith("'"))
            ):
                _v = _v[1:-1]
            _hash = _v.find(" #")
            if _hash >= 0:
                _v = _v[:_hash].strip()
            os.environ[_m.group(1)] = _v
except Exception:
    pass  # no .env — fine


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


PORT = _int_env("PORT", 3000)
# overridable so tests can point at a dead port and exercise the local fallback
ANILIST_ENDPOINT = os.environ.get("ANILIST_ENDPOINT") or "https://graphql.anilist.co"
ANILIST_FIXTURES = os.environ.get("ANILIST_FIXTURES") or ""
RATE_PER_MIN = max(1, _int_env("RATE_PER_MIN", 25))
# packaged app version, injected by the Electron main — absent in dev/docker
APP_VERSION: str | None = os.environ.get("APP_VERSION")

# --- local (fixture) mode: auto-fallback when AniList is unreachable -------------
# env ANILIST_FIXTURES pins the mode on for the whole process (tests, demos).

FIXTURES_DIR = ANILIST_FIXTURES or "fixtures"
_local_mode = bool(ANILIST_FIXTURES)
_auto_fallback = True  # default on: switch to fixtures on the first AniList failure


def fixtures_dir() -> str:
    return FIXTURES_DIR


def local_mode_on() -> bool:
    return _local_mode


def auto_fallback_on() -> bool:
    return _auto_fallback


def set_local_mode(on: bool) -> None:
    global _local_mode
    if not ANILIST_FIXTURES:
        _local_mode = on  # env pin wins


def set_auto_fallback(on: bool) -> None:
    global _auto_fallback
    _auto_fallback = on
    if not on:
        set_local_mode(False)  # disabling auto = try live again right away


_fixtures_present: bool | None = None


def fixtures_available() -> bool:
    global _fixtures_present
    if ANILIST_FIXTURES:
        return True
    if _fixtures_present is None:
        try:
            _fixtures_present = (Path(os.getcwd()) / FIXTURES_DIR / "userlist.json").exists()
        except Exception:
            _fixtures_present = False
    return _fixtures_present


# --- persisted app config (written by the setup wizard) -------------------------
# All runtime data (config, cache, logs) lives in one directory: the repo's data/
# in dev, ~/Library/Application Support/… when packaged (env from electron main —
# the .app bundle is read-only under App Translocation).
DATA_DIR = os.environ.get("ALR_DATA_DIR") or str(_REPO_ROOT / "data")

CONFIG_PATH = os.environ.get("CONFIG_PATH") or os.path.join(DATA_DIR, "config.json")


def read_config_file(path: str | None = None) -> dict:
    """Tolerant read: any error (missing, corrupt) yields an empty config."""
    try:
        with open(path or CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_file_config = read_config_file()


def update_config(patch: dict, path: str | None = None) -> dict:
    """Atomic write (tmp + rename) + in-memory refresh; merge-patch.

    Una chiave della patch con valore ``None`` CANCELLA la chiave (in TS il branch
    ``skipped`` scrive ``key: undefined`` e ``JSON.stringify`` la dropa).
    """
    global _file_config
    target = path or CONFIG_PATH
    parent = os.path.dirname(target)
    os.makedirs(parent, exist_ok=True)  # packaged data dir may not exist yet
    merged = read_config_file(target)
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    with open(f"{target}.tmp", "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    os.replace(f"{target}.tmp", target)
    if target == CONFIG_PATH:
        _file_config = merged
    return merged


def configured_llm_model() -> str | None:
    """Explicitly configured model, or None when the app would fall back to the default."""
    env = os.environ.get("LLM_MODEL")
    if env is not None:
        return env
    return _file_config.get("model")


def llm_model() -> str:
    model = configured_llm_model()
    return model if model is not None else "qwen3:8b"


def llm_base_url() -> str:
    """Read per call (tests repoint the env at a fake server)."""
    env = os.environ.get("LLM_BASE_URL")
    if env is not None:
        return env
    base = _file_config.get("baseUrl")
    if base is not None:
        return base
    return "http://127.0.0.1:11434/v1"


def has_custom_env() -> bool:
    """Sola PRESENZA di LLM_BASE_URL (il compose conta su questo, non sulla verità)."""
    return "LLM_BASE_URL" in os.environ


# explain runs async in the UI: generous timeout covers cold model loads + reasoning models
LLM_TIMEOUT_MS = _int_env("LLM_TIMEOUT_MS", 300_000)

CACHE_DIR = os.environ.get("CACHE_DIR") or os.path.join(DATA_DIR, "cache")
CACHE_TTL_LIST_MS = 60 * 60 * 1000  # 1h — lists change while you watch
CACHE_TTL_MEDIA_MS = 7 * 24 * 60 * 60 * 1000  # 7d — metadata is stable
CACHE_TTL_EXPL_MS = 7 * 24 * 60 * 60 * 1000

WEIGHTS = {
    # candidate affinity mix (sums to 1 over the -1..1 core)
    "tag": 0.5,
    "genre": 0.3,
    "studio": 0.12,
    "era": 0.08,
    # final score mix
    "affinity": 0.6,
    "quality": 0.28,
    "franchiseBonus": 0.12,
    "communityPerHit": 0.03,
    "communityCap": 0.1,
    "mood": 0.04,  # continuity bonus: shares themes/plot with the last 5 completed
    # quality mix
    "qualityScore": 0.8,
    "qualityPop": 0.2,
    # gem score
    "gemAffinity": 0.65,
    "gemQuality": 0.35,
    "gemPopPenalty": 0.3,
    "gemMaxPopularity": 40_000,
    "gemMinScore": 72,
    "gemMinGemScore": 0.45,
    # sentiment
    "scoreSpread": 40,  # points from your mean = full ±1 weight
    "statusBase": {
        "COMPLETED": 0,
        "CURRENT": 0.1,
        "REPEATING": 0.15,
        "PAUSED": -0.25,
        "DROPPED": -0.6,
    },
    "repeatBonus": 0.1,
    "repeatCap": 3,
    # profile thresholds
    "lovedMin": 0.05,
    "supportMin": 2,
    "supportShrink": 10,
    "topTags": 20,
    "topGenres": 8,
    "topStudios": 5,
    "topDisliked": 10,
}
