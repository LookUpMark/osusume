"""Lettura fixture per la local mode (anilist.ts righe 239-245)."""

from __future__ import annotations

import json
import os
from typing import Any

from app.core import config


async def read_fixture(name: str) -> Any:
    """``join(process.cwd(), fixturesDir(), name)`` — i path assoluti di config vincono su cwd."""
    path = os.path.join(os.getcwd(), config.fixtures_dir(), name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)
