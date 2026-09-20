"""Fixture e2e: server Python spawnato come subprocess con la ricetta env golden."""

from __future__ import annotations

import httpx
import pytest

from harness import ServerHandle


@pytest.fixture
async def server():
    async with ServerHandle() as handle:
        yield handle


@pytest.fixture
async def client(server) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
        yield c
