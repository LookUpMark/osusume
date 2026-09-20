"""Porting di ``src/server/update.ts`` — update check GitHub."""

from __future__ import annotations

import time

import httpx

from app.core import config

RELEASES_URL = "https://api.github.com/repos/LookUpMark/osusume/releases/latest"

_MEMO_S = 5 * 60  # GitHub anonymous rate limit is 60/h
# -inf: il PRIMO check non-fresh non deve mai servire il memo (Date.now() del TS è
# già lontano da 0, monotonic() di un processo appena nato no)
_memo_at = float("-inf")
_memo: tuple[str | None, str | None] = (None, None)


def cmp_version(a: str, b: str) -> int:
    """Numeric 3-part compare: >0 if a is newer. Tolerant of a "v" prefix and a
    "-prerelease" suffix (prereleases never count as newer than their release)."""

    def parts(v: str) -> list[int]:
        if v.startswith("v"):
            v = v[1:]
        return [int(x) if x.isdigit() else 0 for x in v.split("-")[0].split(".")]

    pa, pb = parts(a), parts(b)
    for i in range(3):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x != y:
            return x - y
    return 0


async def latest_release(fresh: bool = False) -> tuple[str | None, str | None]:
    global _memo_at, _memo
    if not fresh and time.monotonic() - _memo_at < _MEMO_S:
        return _memo
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(RELEASES_URL, headers={"accept": "application/vnd.github+json"})
            res.raise_for_status()
            json = res.json()
        _memo = (json.get("tag_name"), json.get("html_url"))
    except Exception:
        _memo = (None, None)  # offline / rate-limited → "no update info", never an error
    _memo_at = time.monotonic()
    return _memo


async def app_update_status(fresh: bool = False) -> dict:
    """Update check: APP_VERSION is injected by the Electron main (absent in dev/docker).
    `fresh` bypasses the memo — the manual "check now" button must hit GitHub."""
    current = config.APP_VERSION
    if not current:
        return {"current": None, "latest": None, "url": None, "available": False}
    tag, url = await latest_release(fresh)
    return {
        "current": current,
        "latest": tag,
        "url": url,
        "available": bool(tag and url and cmp_version(tag, current) > 0),
    }
