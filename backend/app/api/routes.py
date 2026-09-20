"""Router ``/api`` — subset P1 del porting 1:1 di ``src/server/api.ts``."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, StrictBool

from app.adapters.system.update import app_update_status
from app.core import config

router = APIRouter()


class LocalModeBody(BaseModel):
    # StrictBool su ENTRAMBI: in TS `auto` e `local` sono confrontati strict
    # (typeof/===), niente coercizione "yes"/1/0 — altrimenti {"local":0} sarebbe
    # un retry-live fantasma. Nota: in TS un `local` di tipo strano viene ignorato
    # (200), qui è un 400 invalid_request — deviazione documentata nel contract.
    auto: StrictBool
    local: StrictBool | None = None


def _local_state() -> dict:
    return {
        "on": config.local_mode_on(),
        "available": config.fixtures_available(),
        "auto": config.auto_fallback_on(),
    }


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        # P1: nessun backend LLM ancora — enabled False / state "off"
        "llm": {"model": config.llm_model(), "enabled": False, "state": "off"},
        "local": _local_state(),
    }


@router.get("/app-update")
async def app_update(fresh: str | None = None) -> dict:
    return await app_update_status(fresh == "1")


# UI toggle: auto-fallback on AniList failure. Switching it off also retries live.
# {local:false} forces a live retry without touching the auto preference (banner button).
@router.post("/local-mode")
async def local_mode(body: LocalModeBody) -> dict:
    config.set_auto_fallback(body.auto)
    if body.local is False:
        config.set_local_mode(False)
    return {"ok": True, "local": _local_state()}


# disclosure-minimal: the base URL can point anywhere after a custom finish — don't announce it
@router.get("/config")
async def get_config() -> dict:
    return {"llm": {"model": config.llm_model()}}


_shutdown_tasks: set[asyncio.Task] = set()


@router.post("/shutdown")
async def shutdown() -> dict:
    # la risposta {"ok":true} DEVE partire prima dello shutdown (contratto Windows/desktop)
    from app import main  # import differito: main importa questo router

    async def _exit_later() -> None:
        await asyncio.sleep(0.2)
        if main.SERVER is not None:
            main.SERVER.should_exit = True  # graceful: la richiesta corrente completa

    task = asyncio.create_task(_exit_later())
    _shutdown_tasks.add(task)  # riferimento forte: asyncio non tiene i task vivi da solo
    task.add_done_callback(_shutdown_tasks.discard)
    return {"ok": True}
