"""``GET /api/recommend/stream`` — progress SSE (nuovo, non nel TS).

Server subprocess (stessa ricetta di test_parity_fixes): fasi nell'ordine del
docstring di pipeline, ``done`` bit-a-bit identico al body di POST /recommend,
errori terminali col vocabolario condiviso.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from harness import ServerHandle

PHASES = ["list", "profile", "candidates", "franchise", "community", "mood", "scoring", "links", "whynot"]


def parse_sse(lines: list[str]) -> list[tuple[str, dict]]:
    """Righe SSE → [(event, data_json)] — ignora commenti/vuote."""
    out: list[tuple[str, dict]] = []
    event = ""
    for line in lines:
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            out.append((event, json.loads(line.split(":", 1)[1])))
    return out


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server_m():
    async with ServerHandle() as handle:
        yield handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client_m(server_m) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server_m.base, timeout=30.0) as c:
        yield c


@pytest.mark.asyncio(loop_scope="module")
async def test_stream_fasi_in_ordine_e_done_paritario(client_m: httpx.AsyncClient):
    lines: list[str] = []
    async with client_m.stream("GET", "/api/recommend/stream", params={"username": "LookUpMark", "lang": "en"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        async for line in r.aiter_lines():
            lines.append(line)
    events = parse_sse(lines)
    phases = [d["phase"] for e, d in events if e == "phase"]
    assert phases == PHASES, phases
    done = [d for e, d in events if e == "done"]
    assert len(done) == 1

    # parità NON circolare: server FRESCO (result-cache vuota) con POST diretto —
    # due computazioni indipendenti dello stesso input devono coincidere byte-a-byte
    async with ServerHandle() as fresh:
        async with httpx.AsyncClient(trust_env=False, base_url=fresh.base, timeout=30.0) as c2:
            post = await c2.post("/api/recommend", json={"username": "LookUpMark", "lang": "en"})
    assert post.status_code == 200
    assert done[0] == post.json()


@pytest.mark.asyncio(loop_scope="module")
async def test_stream_cache_hit_done_immediato(client_m: httpx.AsyncClient):
    """Autosufficiente: il test stesso popola la result-cache col POST, poi lo
    stream sulla stessa chiave deve dare SOLO done (nessuna fase)."""
    post = await client_m.post("/api/recommend", json={"username": "LookUpMark", "lang": "it"})
    assert post.status_code == 200
    lines: list[str] = []
    async with client_m.stream("GET", "/api/recommend/stream", params={"username": "LookUpMark", "lang": "it"}) as r:
        async for line in r.aiter_lines():
            lines.append(line)
    events = parse_sse(lines)
    assert [e for e, _ in events] == ["done"], events
    assert events[0][1] == post.json()


@pytest.mark.asyncio(loop_scope="module")
async def test_stream_username_invalido_400(client_m: httpx.AsyncClient):
    res = await client_m.get("/api/recommend/stream", params={"username": "bad name!"})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_username"}


@pytest.mark.asyncio(loop_scope="module")
async def test_stream_errore_terminale_con_vocabolario_condiviso():
    """Un run che fallisce emette ``event: error`` col vocabolario ``_error_payload``.

    Con ANILIST_FIXTURES pinato su dir mancante la local mode (env-pinned) fallisce
    la lettura fixture → FileNotFoundError → ``internal_error`` (stessa mappa del
    POST /recommend). La mappa anilist_error/user_not_found è coperta in unit."""
    async with ServerHandle(
        overrides={"ANILIST_FIXTURES": "fixtures-missing", "ANILIST_ENDPOINT": "http://127.0.0.1:1"}
    ) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=30.0) as c:
            lines: list[str] = []
            async with c.stream("GET", "/api/recommend/stream", params={"username": "LookUpMark", "lang": "en"}) as r:
                assert r.status_code == 200
                async for line in r.aiter_lines():
                    lines.append(line)
    events = parse_sse(lines)
    kinds = [e for e, _ in events]
    assert kinds[-1] == "error", kinds
    assert events[-1][1] == {"error": "internal_error"}
    # le fasi prima dell'errore sono un prefisso valido (list almeno)
    assert kinds[0] == "phase"


def test_error_payload_vocabolario():
    from app.adapters.anilist.media import AniListError
    from app.api.routes import _error_payload

    assert _error_payload(AniListError("not found", 404)) == {"error": "user_not_found"}
    assert _error_payload(AniListError("boom", 502)) == {"error": "anilist_error", "message": "boom"}
    assert _error_payload(ValueError("x")) == {"error": "internal_error"}
