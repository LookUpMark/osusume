"""Router ``/api`` — porting 1:1 di ``src/server/api.ts`` (P1 + P4)."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool

from app.adapters.anilist.client import AniListError
from app.adapters.system.update import app_update_status
from app.core import config
# alias "recommend_query": la route POST /recommend si chiama `recommend` e
# ombreggerebbe il modulo nello scope del file
from app.queries import explain_query, profile_query
from app.queries import recommend as recommend_query

router = APIRouter()

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
LANGS: frozenset[str] = frozenset({"en", "it"})


def _lang(value: Any) -> Any:
    """``LANGS.has(body?.lang ?? "") ? body.lang : "en"`` — default SILENZIOSO."""
    return value if isinstance(value, str) and value in LANGS else "en"


def _invalid_username() -> JSONResponse:
    return JSONResponse({"error": "invalid_username"}, status_code=400)


def _invalid_request() -> JSONResponse:
    return JSONResponse({"error": "invalid_request"}, status_code=400)


def _error_response(e: Exception) -> JSONResponse:
    """``errorResponse`` (api.ts righe 201-207)."""
    if isinstance(e, AniListError):
        if e.status == 404:
            return JSONResponse({"error": "user_not_found"}, status_code=404)
        return JSONResponse({"error": "anilist_error", "message": str(e)}, status_code=502)
    return JSONResponse({"error": "internal_error"}, status_code=500)


async def with_local_fallback(fn: Callable[[], Awaitable[dict]]) -> dict:
    """``withLocalFallback`` (api.ts righe 58-78).

    AniList down + auto on + fixtures on disk → flip to local mode and retry once.
    404 is a genuine "user not found", not an outage — never masked; il fallimento
    del retry è inghiottito e risale l'errore AniList originale.
    """
    try:
        return await fn()
    except AniListError as e:
        if (
            e.status != 404
            and config.auto_fallback_on()
            and not config.local_mode_on()
            and config.fixtures_available()
        ):
            config.set_local_mode(True)
            try:
                return await fn()
            except Exception:
                pass  # fixtures failed too — report the original AniList error
        raise


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


class UsernameBody(BaseModel):
    # `username: str` con default "": manca → "" → invalid_username (come il TS,
    # `body?.username ?? ""`). Un username NON stringa è invece 400 invalid_request
    # (deviazione: la regex TS .test() coerce a stringa) — stesso preambolo di LocalModeBody.
    username: str = ""
    lang: str | None = None


class ExplainBody(UsernameBody):
    ids: list[Any] = []


class LookupBody(UsernameBody):
    q: str = ""


@router.get("/profile/{username}")
async def profile(username: str):
    if not USERNAME_RE.match(username):
        return _invalid_username()  # `regex.test`: `$` JS tolera il \n finale, .match pure
    try:
        return await with_local_fallback(lambda: profile_query.get_profile(username))
    except Exception as e:
        return _error_response(e)


@router.post("/recommend")
async def recommend(body: UsernameBody | None = None):
    if body is None:
        body = UsernameBody()
    if not USERNAME_RE.match(body.username):
        return _invalid_username()
    try:
        return await with_local_fallback(
            lambda: recommend_query.get_recommendation(body.username, _lang(body.lang))
        )
    except Exception as e:
        return _error_response(e)


@router.post("/explain")
async def explain(body: ExplainBody | None = None):
    if body is None:
        body = ExplainBody()
    ids = explain_query.normalize_ids(body.ids)
    if not USERNAME_RE.match(body.username) or len(ids) == 0:
        return _invalid_request()
    try:
        # stale-tolerant like /chat: the dialog explains a result the UI already shows
        return await with_local_fallback(
            lambda: explain_query.explain(body.username, ids, _lang(body.lang))
        )
    except Exception as e:
        return _error_response(e)


@router.post("/lookup")
async def lookup(body: LookupBody | None = None):
    if body is None:
        body = LookupBody()
    q = body.q.strip()
    if not USERNAME_RE.match(body.username) or len(q) < 2 or len(q) > 80:
        return _invalid_request()
    try:
        return await with_local_fallback(lambda: recommend_query.lookup(body.username, q, _lang(body.lang)))
    except Exception as e:
        return _error_response(e)


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
