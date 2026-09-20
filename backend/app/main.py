"""App factory + uvicorn server (porting di ``src/server/index.ts``)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from app.api.routes import router
from app.core.errors import register_handlers
from app.core.middleware import HostAllowlistMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]

# istanza server conservata in modulo importabile: POST /api/shutdown la spegne
SERVER: uvicorn.Server | None = None


def set_server(server: uvicorn.Server) -> None:
    global SERVER
    SERVER = server


def dist_dir() -> Path | None:
    """dist/ alla radice repo (dev); override via env DIST_DIR (in TS era cwd-relative)."""
    override = os.environ.get("DIST_DIR")
    directory = Path(override) if override else REPO_ROOT / "dist"
    return directory if directory.is_dir() else None


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Static + SPA fallback, registrato DOPO tutte le route /api (precedenza API garantita).

    fastapi>=0.141: static + fallback SPA nativi, negoziati sull'header Accept
    (browser → index.html, client API → 404 not_found — vedi docs/contract.md).
    """
    app.frontend("/", directory=dist, fallback="index.html")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # bootstrap di src/server/index.ts righe 30-31: fire-and-forget + teardown
        from app.adapters.system import setup

        setup.cleanup_on_exit()  # the LLM backend lives and dies with the app
        setup.ensure_llm_server()  # no-op unless the setup wizard completed
        yield

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.add_middleware(HostAllowlistMiddleware)
    register_handlers(app)
    app.include_router(router, prefix="/api")
    dist = dist_dir()
    if dist is not None:
        _mount_frontend(app, dist)
    return app


app = create_app()
