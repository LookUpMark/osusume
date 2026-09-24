"""Router ``/api`` — porting 1:1 di ``src/server/api.ts`` (P1 + P4)."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, StrictBool

from app.adapters.anilist.client import AniListError
from app.adapters.llm.chat import card_payload, chat_reply, recommended_cards
from app.adapters.llm.client import LlmError, llm_health, served_models
from app.adapters.system import setup as setup_mod
from app.adapters.system.setup import setup_router
from app.adapters.system.update import app_update_status
from app.core import config
from app.core.errors import ApiError
from app.domain import pipeline
from app.domain.js_compat import js_length, js_trim
# alias "recommend_query": la route POST /recommend si chiama `recommend` e
# ombreggerebbe il modulo nello scope del file
from app.queries import explain_query, profile_query
from app.queries import recommend as recommend_query

router = APIRouter()
router.include_router(setup_router, prefix="/setup")

# `\A…\Z` (NON `^…$`): il `$` Python accetta un `\n` finale, il `$` JS no —
# "abc\n" deve restare invalid_username come nel TS
USERNAME_RE = re.compile(r"\A[A-Za-z0-9_-]{1,32}\Z")
LANGS: frozenset[str] = frozenset({"en", "it"})


def _reject_constant(c: str) -> Any:
    """JSON.parse rifiuta i letterali NaN/Infinity: il decoder stdlib li accetta."""
    raise ValueError(f"non-JSON constant: {c}")


async def _js_body(request: Request) -> Any:
    """``await c.req.json().catch(() => null)`` del TS: parse STRICT (NaN/Infinity → None),
    qualunque fallimento → None. Il valore non-oggetto resta tale (nel TS è truthy) —
    ogni endpoint gli applica la propria navigazione ``body?.``, vedi i singoli handler."""
    raw = await request.body()
    if not raw:
        return None
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except Exception:
        return None


def _lang(value: Any) -> Any:
    """``LANGS.has(body?.lang ?? "") ? body.lang : "en"`` — default SILENZIOSO."""
    return value if isinstance(value, str) and value in LANGS else "en"


def _invalid_username() -> JSONResponse:
    return JSONResponse({"error": "invalid_username"}, status_code=400)


def _invalid_request() -> JSONResponse:
    return JSONResponse({"error": "invalid_request"}, status_code=400)


def _error_payload(e: Exception) -> dict:
    """Body canonico degli errori (vocabolario ``errorResponse``): condiviso da
    JSON e dall'evento ``error`` dello stream."""
    if isinstance(e, AniListError):
        if e.status == 404:
            return {"error": "user_not_found"}
        if e.status == 401:
            return {"error": "anilist_auth"}
        return {"error": "anilist_error", "message": str(e)}
    return {"error": "internal_error"}


def _error_response(e: Exception) -> JSONResponse:
    """``errorResponse`` (api.ts righe 201-207)."""
    payload = _error_payload(e)
    status = 404 if payload["error"] == "user_not_found" else 401 if payload["error"] == "anilist_auth" else 502
    if payload["error"] == "internal_error":
        status = 500
    return JSONResponse(payload, status_code=status)


async def with_local_fallback(fn: Callable[[], Awaitable[dict]]) -> dict:
    """``withLocalFallback`` (api.ts righe 58-78).

    AniList down + auto on + fixtures on disk → flip to local mode and retry once.
    404 is a genuine "user not found", not an outage — never masked; 401 è un token
    scaduto (auth), non un outage: né fallback né mascheramento. Il fallimento
    del retry è inghiottito e risale l'errore AniList originale.
    """
    try:
        return await fn()
    except AniListError as e:
        if (
            e.status != 404
            and e.status != 401
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


# --- settings UI (nuovo, non nel TS): GET/PATCH /api/settings + GET /api/llm/models.
# Le chiavi sono le stesse del wizard (model/baseUrl): wizard e settings condividono lo stato.


class SettingsBody(BaseModel):
    # chiave ASSENTE = non toccare (model_fields_set); chiave presente:
    # baseUrl/model stringa validata, "" su model = torna al default del server,
    # "" su systemPromptExtra = cancella (update_config(None) dropa la chiave)
    baseUrl: str | None = None
    model: str | None = None
    systemPromptExtra: str | None = None


def _settings_payload() -> dict:
    # valori DEL FILE (quelli che il form edita): con env LLM_* attivo il file
    # non vince a runtime — il flag envOverride lo dice, il form resta editabile
    cfg = config.read_config_file()
    base = cfg.get("baseUrl")
    model = cfg.get("model")
    return {
        "baseUrl": base if isinstance(base, str) else config.llm_base_url(),
        "model": model if isinstance(model, str) else None,
        "defaultModel": "qwen3:8b",
        "systemPromptExtra": config.system_prompt_extra(),
        "envOverride": config.has_custom_env(),
    }


@router.get("/settings")
async def get_settings() -> dict:
    return _settings_payload()


_BASE_URL_RE = re.compile(r"\Ahttps?://\S+\Z")


@router.patch("/settings")
async def patch_settings(body: SettingsBody) -> dict:
    patch: dict = {}
    if "baseUrl" in body.model_fields_set:
        url = js_trim(body.baseUrl or "").rstrip("/")
        if not url or len(url) > 200 or not _BASE_URL_RE.match(url):
            raise ApiError(400, "invalid_request")
        patch["baseUrl"] = url
    if "model" in body.model_fields_set:
        model = js_trim(body.model or "")
        if len(model) > 120 or "\n" in model:
            raise ApiError(400, "invalid_request")
        patch["model"] = model if model else None  # "" → cancella: fallback al default
    if "systemPromptExtra" in body.model_fields_set:
        extra = (body.systemPromptExtra or "").strip()
        if len(extra) > 4000:
            raise ApiError(400, "invalid_request")
        patch["systemPromptExtra"] = extra if extra else None
    if patch:
        config.update_config(patch)
    return _settings_payload()


@router.get("/llm/models")
async def llm_models() -> dict:
    ids = await served_models()
    if ids is None:
        raise ApiError(503, "llm_unavailable")
    return {"models": sorted({m for m in ids if m}), "configured": config.configured_llm_model()}


# --- OAuth AniList + watchlist (nuovo, non nel TS) ----------------------------------


class AnilistAuthBody(BaseModel):
    # chiave assente = non toccare; "" = cancella (come SettingsBody)
    clientId: str | None = None
    clientSecret: str | None = None


_CLIENT_ID_RE = re.compile(r"\A\d{1,20}\Z")


@router.get("/auth/anilist")
async def anilist_auth_status() -> dict:
    from app.adapters.anilist import auth

    return auth.status_payload()  # mai token/secret nel payload


@router.patch("/auth/anilist")
async def anilist_auth_patch(body: AnilistAuthBody) -> dict:
    from app.adapters.anilist import auth

    patch: dict = {}
    if "clientId" in body.model_fields_set:
        cid = js_trim(body.clientId or "")
        if cid and not _CLIENT_ID_RE.match(cid):
            raise ApiError(400, "invalid_request")
        patch["anilistClientId"] = cid if cid else None
    if "clientSecret" in body.model_fields_set:
        secret = js_trim(body.clientSecret or "")
        if secret and not 8 <= len(secret) <= 200:
            raise ApiError(400, "invalid_request")
        patch["anilistClientSecret"] = secret if secret else None
    if patch:
        config.update_config(patch)
    return auth.status_payload()


@router.post("/auth/anilist/start")
async def anilist_auth_start() -> dict:
    from app.adapters.anilist import auth

    return {"url": await auth.start_flow()}


@router.post("/auth/anilist/disconnect")
async def anilist_auth_disconnect() -> dict:
    from app.adapters.anilist import auth

    auth.disconnect()
    return {"ok": True}


class WatchlistBody(BaseModel):
    mediaId: int


@router.get("/watchlist/status")
async def watchlist_status(username: str = "", mediaId: int = 0) -> dict:
    from app.adapters.anilist.media import fetch_media_list_status

    if not USERNAME_RE.match(username) or mediaId <= 0:
        return _invalid_request()
    try:
        return {"status": await fetch_media_list_status(username, mediaId)}
    except Exception as e:
        return _error_response(e)


@router.post("/watchlist")
async def watchlist_add(body: WatchlistBody) -> dict:
    """Aggiunge alla watchlist (PLANNING) per l'utente collegato via OAuth."""
    from app.adapters.anilist import auth, queries
    from app.adapters.anilist.client import AniListError, gql_uncached

    if body.mediaId <= 0:
        return _invalid_request()
    token = auth.anilist_token()
    if token is None:
        raise ApiError(401, "anilist_auth")
    try:
        data = await gql_uncached(queries.SAVE_PLANNING_MUTATION, {"mediaId": body.mediaId}, token=token)
    except AniListError as e:
        setup_mod.log_llm(f"watchlist: AniList error ({e})")
        if e.status == 401:
            raise ApiError(401, "anilist_auth") from e
        raise ApiError(502, "anilist_error") from e
    entry = data.get("SaveMediaListEntry") if isinstance(data, dict) else None
    status = entry.get("status") if isinstance(entry, dict) else "PLANNING"
    return {"ok": True, "status": status}


_shutdown_tasks: set[asyncio.Task] = set()


class UsernameBody(BaseModel):
    # `username: str` con default "": manca → "" → invalid_username (come il TS,
    # `body?.username ?? ""`). Un username NON stringa è invece 400 invalid_request
    # (deviazione: la regex TS .test() coerce a stringa) — stesso preambolo di LocalModeBody.
    # `lang: Any`: nel TS un lang non-stringa NON è un errore, `_lang` lo manda a "en".
    username: str = ""
    lang: Any = None


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
async def recommend(request: Request):
    raw = await _js_body(request)
    # TS: body null/non-oggetto → `body?.username ?? ""` → invalid_username (mai invalid_request)
    body = UsernameBody(**raw) if isinstance(raw, dict) else UsernameBody()
    if not USERNAME_RE.match(body.username):
        return _invalid_username()
    try:
        return await with_local_fallback(
            lambda: recommend_query.get_recommendation(body.username, _lang(body.lang))
        )
    except Exception as e:
        return _error_response(e)


def _sse(event: str, data: dict) -> bytes:
    """Frame SSE (spec: righe chiuse da blank line)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@router.get("/recommend/stream")
async def recommend_stream(username: str = "", lang: str | None = None):
    """Progress SSE della generazione (nuovo, non nel TS): eventi ``phase`` ai
    confini di ``recommend_for`` (ordine del docstring, mai riordinato), ``done``
    col body IDENTICO a POST /recommend, ``error`` col vocabolario condiviso.
    Cache hit / inflight join = solo ``done``: la UI tollera il flush unico.
    Un client che si disconnette NON cancella il task: la cache si popola comunque."""
    if not USERNAME_RE.match(username):
        return _invalid_username()
    resolved = _lang(lang)
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_phase(phase: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ("phase", {"phase": phase}))

    async def run_task() -> dict:
        try:
            body = await with_local_fallback(
                lambda: recommend_query.get_recommendation(username, resolved, on_phase=on_phase)
            )
            queue.put_nowait(("done", body))
        except Exception as e:
            queue.put_nowait(("error", _error_payload(e)))
        finally:
            queue.put_nowait(None)  # termine del generatore

    task = asyncio.ensure_future(run_task())

    async def gen():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item[0], item[1])
        finally:
            # il generatore muore col client: il task continua e riempie la cache
            pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


@router.post("/explain")
async def explain(request: Request):
    raw = await _js_body(request)
    # TS: null → `body?.ids ?? []` → size 0 → invalid_request (stesso codice del bad username)
    body = ExplainBody(**raw) if isinstance(raw, dict) else ExplainBody()
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
async def lookup(request: Request):
    raw = await _js_body(request)
    # TS: null → q "" → invalid_request
    body = LookupBody(**raw) if isinstance(raw, dict) else LookupBody()
    # trim() e length sono quelli JS (whitelist whitespace ECMA, unità UTF-16) —
    # str.strip()/len() divergono su NEL/\x1c-\x1f/BOM e sui token astrali
    q = js_trim(body.q)
    if not USERNAME_RE.match(body.username) or js_length(q) < 2 or js_length(q) > 80:
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
    lang: Any = None
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
        reply = await chat_reply(result, lang, history, extras)
        # card = titoli che il modello ha GRASSETTATO, matchati sullo stesso pool
        # che il system prompt gli mostra (prompts.build_chat_system)
        pool = [*result.recos[:12], *extras[:5]]
        return {"reply": reply, "cards": [card_payload(r) for r in recommended_cards(reply, pool)]}
    except LlmError as e:
        setup_mod.log_llm(f"chat: LLM error ({e}) per model={config.llm_model()}")
        raise ApiError(503, "llm_unavailable")


@router.post("/chat")
async def chat(request: Request):
    raw = await _js_body(request)
    # TS: body null/non-oggetto → username "" → invalid_username
    body = ChatBody(**raw) if isinstance(raw, dict) else ChatBody()
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
