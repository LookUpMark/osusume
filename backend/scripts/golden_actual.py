#!/usr/bin/env python3
"""Cattura i golden "actual" lato Python (subset P1) per ``tests/golden/compare.py``.

Usage:
    python3 backend/scripts/golden_actual.py <outDir> [fixtureDir]

Stessa ricetta env di ``tests/golden/record.mjs`` (via ``backend/tests/harness.py``:
cwd radice repo, ANILIST_FIXTURES, LLM/LMS/OMLX morti, tmpdir fresco, senza
APP_VERSION) e stesso ordine di cattura — le transizioni di local-mode sono
sequenziali, l'ordine è parte della riproducibilità. Scrive ``{"status", "body"}``
pretty 2-space con i path di ``tests/golden/volatile.json`` scrubbed a null, come
record.mjs (compare.py scrubba comunque entrambi i lati).

Poi:
    python3 tests/golden/compare.py tests/golden/fixtures <outDir> \
        --only health-pre,health-post,localmode-off,localmode-retry-live,config,app-update,error-403
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend" / "tests"))

import httpx  # noqa: E402

import harness  # noqa: E402

# subset P1, nell'ordine di record.mjs (lo stato local-mode è sequenziale)
STEPS = [
    ("health-pre", lambda c: c.get("/api/health")),
    ("config", lambda c: c.get("/api/config")),
    ("app-update", lambda c: c.get("/api/app-update")),
    # error-403: come record.mjs usa http con Host forzato; qui httpx accetta l'header esplicito
    ("error-403", lambda c: c.get("/api/health", headers={"host": "evil.com"})),
    ("localmode-off", lambda c: c.post("/api/local-mode", json={"auto": False})),
    ("health-post", lambda c: c.get("/api/health")),
    (
        "localmode-retry-live",
        lambda c: c.post("/api/local-mode", json={"auto": True, "local": False}),
    ),
]


def scrub(doc: dict, paths: list[str]) -> None:
    """Path volatili (tests/golden/volatile.json, forma "body.x.y") → null."""
    for path in paths:
        keys = path.split(".")
        cur = doc
        for key in keys[:-1]:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        if isinstance(cur, dict) and keys[-1] in cur:
            cur[keys[-1]] = None


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    out = Path(sys.argv[1])
    fixture_dir = sys.argv[2] if len(sys.argv) > 2 else "fixtures"
    out.mkdir(parents=True, exist_ok=True)
    volatile = json.loads((REPO_ROOT / "tests" / "golden" / "volatile.json").read_text())

    async with harness.ServerHandle(fixture_dir=fixture_dir) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as client:
            for name, request in STEPS:
                res = await request(client)
                try:
                    body = res.json()
                except Exception:
                    body = res.text
                doc = {"status": res.status_code, "body": body}
                scrub(doc, volatile)
                (out / f"{name}.json").write_text(
                    json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                print(f"  {name} → {res.status_code}")
    print(f"actual → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
