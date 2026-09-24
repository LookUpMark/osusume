"""Lettura fixture per la local mode (anilist.ts righe 239-245)."""

from __future__ import annotations

import json
import os
from typing import Any

from app.core import config


async def read_fixture(name: str, dir: str | None = None) -> Any:
    """``join(process.cwd(), fixturesDir(), name)`` — i path assoluti di config vincono su cwd.
    ``dir`` override per il secondo mondo manga (``fixtures-manga``)."""
    base = dir if dir is not None else config.fixtures_dir()
    path = os.path.join(os.getcwd(), base, name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)
