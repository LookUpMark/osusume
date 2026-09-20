"""Router ``/api`` — porting 1:1 di ``src/server/api.ts`` (P1 + P4)."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictBool

from app.adapters.anilist.client import AniListError
from app.adapters.llm.chat import chat_reply
from app.adapters.llm.client import LlmError, llm_health
from app.adapters.system import setup as setup_mod
from app.adapters.system.setup import setup_router
from app.adapters.system.update import app_update_status
from app.core import config
from app.core.errors import ApiError
from app.domain import pipeline
# alias "recommend_query": la route POST /recommend si chiama `recommend` e
# ombreggerebbe il modulo nello scope del file
from app.queries import explain_query, profile_query
from app.queries import recommend as recommend_query

router = APIRouter()
router.include_router(setup_router, prefix="/setup")

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
    setup_mod.ensure_llm_server()  # throttled no-op unless the backend should be up (or retried)
    return {
        "ok": True,
        "llm": {
            "model": config.llm_model(),
            "enabled": await llm_health(),
            "state": setup_mod.llm_backend_state(),
        },
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


class ChatBody(BaseModel):
    """Body di ``/chat`` (api.ts righe 145-152). ``messages``/``extra`` restano LOOSE
    (dict/Any): la normalizzazione filtro-per-tipo è semantica del TS, non della
    validazione pydantic — un turno malformato va scartato, non rifiutato in 422."""

    username: str = ""
    lang: str | None = None
    extra: list[Any] = []
    messages: list[dict[str, Any]] = []


def _normalize_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """``history`` (api.ts righe 158-166): normalize, never drop — un turno troppo
    lungo viene clampato così il contesto di conversazione sopravvive."""
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content[:4000]})
    return out[-12:]


def chat_extra_ids(extra: list[Any], recos: list) -> list[float | int]:
    """``extraIds`` (api.ts righe 176-179): numeri non presenti nelle recos, poi
    ``slice(0, 5)`` — NESSUNA dedup (a differenza di /explain, qui l'ordine del
    client conta e i doppioni sono innocui)."""
    return [
        x
        for x in extra
        if isinstance(x, (int, float)) and not isinstance(x, bool) and not any(r.media.id == x for r in recos)
    ][:5]


async def _chat_turn(username: str, lang: str, history: list[dict[str, str]], extra: list[Any]) -> dict:
    """Corpo di ``/chat`` (api.ts righe 170-190): LlmError → 503 + log, il resto sale."""
    try:
        # stale-tolerant: a 10-minute-old result beats a full recompute mid-chat
        result = await pipeline.get_recommendation(username, lang, stale_ok=True)
        # titles opened via the chat lookup join the context (bounded, never duplicates)
        extra_ids = chat_extra_ids(extra, result.recos)
        extras = (await pipeline.score_arbitrary(extra_ids, username, lang))[1] if extra_ids else []
        return {"reply": await chat_reply(result, lang, history, extras)}
    except LlmError as e:
        setup_mod.log_llm(f"chat: LLM error ({e}) per model={config.llm_model()}")
        raise ApiError(503, "llm_unavailable")


@router.post("/chat")
async def chat(body: ChatBody | None = None):
    if body is None:
        body = ChatBody()
    if not USERNAME_RE.match(body.username):
        return _invalid_username()
    history = _normalize_history(body.messages)
    if not history or history[-1]["role"] != "user":
        return _invalid_request()
    try:
        return await with_local_fallback(lambda: _chat_turn(body.username, _lang(body.lang), history, body.extra))
    except ApiError:
        raise
    except Exception as e:
        return _error_response(e)


@router.post("/shutdown")
async def shutdown() -> dict:
    setup_mod.shutdown_backend()  # il backend LLM owned muore con l'app (anche via HTTP)
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
