"""Regressione bugfix round 2026-09-22 (audit ultracode wf_50d733d1-9d1).

Ogni test riproduce un bug CONFERMATO con evidenza live e ne fissa il fix:
deviazioni JS↔Python trovate dal differenziale col TS originale (git 5009fd5).
"""

from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest
import pytest_asyncio

from app.adapters.anilist.client import _null_non_finite, _reject_constant
from app.adapters.llm.client import llm_chat, llm_health
from app.domain.js_compat import js_length, js_log10, js_trim
from app.domain.scoring import tokenize
from app.shared.models import _js_numbers
from fake_http import FakeServer, Response
from harness import ServerHandle

# --- unit: dominio -----------------------------------------------------------------


def test_js_log10_negativo_nan():
    """Math.log10(-4) = NaN, non un numero finito dal ramo high-word unsigned."""
    assert math.isnan(js_log10(-4))
    assert math.isnan(js_log10(-1))
    # pin V8 (non libm): il port differisce da math.log10 di 1 ULP di proposito
    assert js_log10(115776) == 5.0636185408437


def test_tokenize_token_astrale_utf16():
    """String.length conta unità UTF-16: 3 code point astrali = 6 unità → token valido."""
    assert list(tokenize("𠀀𠀀𠀀 𠁢𠁢𠁢𠁢 normal words here")) == [
        "𠀀𠀀𠀀",
        "𠁢𠁢𠁢𠁢",
        "normal",
        "words",
        "here",
    ]
    # il filtro resta >3: i token ≤3 unità UTF-16 (anche astrali brevi) sono scartati
    assert list(tokenize("ab 𠀀𠀀 abc abcd")) == ["𠀀𠀀", "abcd"]


def test_js_trim_whitespace_ecma():
    """trim() JS: NEL/\\x1c NON sono whitespace (restano), BOM sì (viene tagliato)."""
    assert js_trim("\x85" + "x" * 80).startswith("\x85")
    assert js_trim("\x1c" + "x" * 80).startswith("\x1c")
    assert js_trim("\ufeff" + "x" * 80) == "x" * 80
    assert js_trim(" \t\n x 　") == "x"


def test_js_length_utf16():
    assert js_length("🦈" * 41) == 82  # length UTF-16, non 41
    assert js_length("x" * 80) == 80


def test_json_response_non_finite_null():
    """JSON.stringify: NaN/Infinity → null (es. final NaN con popularity negative)."""
    assert _js_numbers({"final": float("nan"), "rank": float("inf"), "ok": 1.5}) == {
        "final": None,
        "rank": None,
        "ok": 1.5,
    }


def test_anilist_body_sanitize():
    """1e999 passa il JSON.parse TS (→ Infinity → null nel payload), i letterali no."""
    assert _null_non_finite(json.loads('{"a":[1e999],"b":2}')) == {"a": [None], "b": 2}
    with pytest.raises(ValueError):
        json.loads('{"ids":[NaN]}', parse_constant=_reject_constant)
    with pytest.raises(ValueError):
        json.loads('{"ids":[Infinity]}', parse_constant=_reject_constant)


# --- adapter: LLM (fake server, stessa ricetta di test_llm.py) ----------------------


async def test_llm_models_entry_sporca_tollerata(tmp_path, monkeypatch):
    """Una entry non-oggetto in /models non spegne il chip né rompe il leaf-match."""

    async def handler(req):
        return Response({"data": [{"id": "mio-modello"}, "garbage-entry"]})

    async with FakeServer(handler) as srv:
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("LLM_MODEL", "mio-modello")
        assert await llm_health() is True


async def test_llm_chat_lone_surrogate_strip(tmp_path, monkeypatch):
    """Escape \\ud800 nel content LLM: testo ripulito, mai 500 su chat/explain."""

    async def h(req):
        if "/models" in req.path:
            return Response({"data": [{"id": "m"}]})
        return Response(raw=b'{"choices":[{"message":{"content":"[\\\"ok \\ud800 fine\\\"]"}}]}')

    async with FakeServer(h) as srv:
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("LLM_MODEL", "m")
        monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
        out = await llm_chat([{"role": "user", "content": "hi"}], model="m")
    assert out == '["ok  fine"]'


# --- e2e: server reale (server module-scoped: un solo spawn per il file) ------------
# loop_scope="module": il server module-scoped deve vivere in UN loop condiviso


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server_m():
    async with ServerHandle() as handle:
        yield handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client_m(server_m) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server_m.base, timeout=15.0) as c:
        yield c


@pytest.mark.asyncio(loop_scope="module")
async def test_username_newline_invalida(client_m: httpx.AsyncClient):
    """Il `$` JS non accetta il \\n finale: abc%0A era 200, deve essere 400."""
    res = await client_m.get("/api/profile/abc%0A")
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_username"}
    res = await client_m.post("/api/recommend", json={"username": "abc\n"})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_username"}


@pytest.mark.asyncio(loop_scope="module")
async def test_lang_non_stringa_default_en(client_m: httpx.AsyncClient):
    """LANGS.has(5) = false nel TS → default silenzioso "en", MAI 400."""
    res = await client_m.post("/api/recommend", json={"username": "LookUpMark", "lang": 5})
    assert res.status_code == 200
    res_de = await client_m.post("/api/recommend", json={"username": "LookUpMark", "lang": "de"})
    assert res_de.status_code == 200
    assert res.json() == res_de.json()  # entrambe "en": stesso identico risultato


@pytest.mark.asyncio(loop_scope="module")
async def test_body_malformato_invalid_username(client_m: httpx.AsyncClient):
    """body non-JSON/non-oggetto su /recommend e /chat → invalid_username (percorso
    null del TS), NON invalid_request."""
    for raw in (b"RAW", b"[1,2]", b'"hello"', b"42", b'{"username":"u","ids":[NaN]}'):
        res = await client_m.post("/api/recommend", content=raw, headers={"content-type": "application/json"})
        assert res.status_code == 400, raw
        assert res.json() == {"error": "invalid_username"}, raw
        res = await client_m.post("/api/chat", content=raw, headers={"content-type": "application/json"})
        assert res.json() == {"error": "invalid_username"}, raw
    # /explain e /lookup: lo stesso body dà invalid_request (come nel TS)
    res = await client_m.post("/api/explain", content=b"[1,2]", headers={"content-type": "application/json"})
    assert res.json() == {"error": "invalid_request"}
    res = await client_m.post("/api/lookup", content=b"[1,2]", headers={"content-type": "application/json"})
    assert res.json() == {"error": "invalid_request"}


@pytest.mark.asyncio(loop_scope="module")
async def test_explain_letterale_nan_400(client_m: httpx.AsyncClient):
    """JSON.parse rifiuta il letterale NaN → body null → ids vuoti → invalid_request."""
    res = await client_m.post(
        "/api/explain",
        content=b'{"username":"LookUpMark","ids":[NaN]}',
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_request"}


@pytest.mark.asyncio(loop_scope="module")
async def test_lookup_boundary_q_semantica_js(client_m: httpx.AsyncClient):
    """Boundary q con trim()/length() JS (UTF-16): i 4 casi che divergevano."""
    post = lambda q: client_m.post(  # noqa: E731
        "/api/lookup", json={"username": "LookUpMark", "q": q}
    )
    assert (await post("\x85" + "x" * 80)).status_code == 400  # NEL non è whitespace JS → 81
    assert (await post("\x1c" + "x" * 80)).status_code == 400  # FS idem
    assert (await post("\ufeff" + "x" * 80)).status_code == 200  # BOM è whitespace JS → 80
    assert (await post("🦈" * 41)).status_code == 400  # 82 unità UTF-16


@pytest.mark.asyncio(loop_scope="module")
async def test_setup_finish_empty_body_invalid_model(client_m: httpx.AsyncClient):
    """`{}`/`[]`/`"str"` sono truthy nel TS: arrivano a `!body.model` → invalid_model."""
    for raw, expected in ((b"{}", "invalid_model"), (b"[]", "invalid_model"), (b"null", "invalid_request")):
        res = await client_m.post("/api/setup/finish", content=raw, headers={"content-type": "application/json"})
        assert res.status_code == 400, raw
        assert res.json() == {"error": expected}, raw


@pytest.mark.asyncio(loop_scope="module")
async def test_metodo_sbagliato_fallback_spa(client_m: httpx.AsyncClient):
    """Nel TS il metodo sbagliato non matchava Hono: GET/HEAD → SPA 200 text/html,
    altri metodi → 404 default text/plain."""
    res = await client_m.get("/api/recommend")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "<div" in res.text
    res = await client_m.request("PUT", "/api/profile/abc")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("text/plain")


@pytest.mark.asyncio(loop_scope="module")
async def test_shutdown_exit_entro_5s():
    """Contratto: exit 0 entro ~3s da /api/shutdown (timeout_graceful_shutdown=3)."""
    async with ServerHandle() as server:
        proc = server.proc
        assert proc is not None
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            res = await c.post("/api/shutdown")
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        try:
            await asyncio.wait_for(proc.wait(), 5.0)
        except asyncio.TimeoutError:
            pytest.fail("il processo non è uscito entro 5s da /api/shutdown")
        assert proc.returncode == 0
