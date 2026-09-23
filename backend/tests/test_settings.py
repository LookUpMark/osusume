"""Settings UI (nuovo, non nel TS): GET/PATCH /api/settings, GET /api/llm/models,
systemPromptExtra nei prompt (chat + explain) e nella cache key.

E2E su server subprocess (stessa ricetta di test_parity_fixes): nessun write
in-process su data/config.json — CONFIG_PATH del server è sempre in tmp.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from app.adapters.llm.client import served_models
from app.adapters.llm.explain import cache_key
from app.adapters.llm.prompts import build_chat_system, build_prompt
from app.core import config
from fake_http import FakeServer, Response
from harness import ServerHandle
from test_llm import Result, make_profile, make_reco

# --- unit: prompt injection ---------------------------------------------------------


@pytest.fixture
def extra_config(monkeypatch):
    monkeypatch.setattr(config, "_file_config", {"systemPromptExtra": "Prefer cozy slice-of-life, avoid heavy gore."})


def test_owner_extra_append_alone(extra_config):
    sys_text = build_chat_system(Result(make_profile("h"), [make_reco(1)]), "en")
    assert "OWNER NOTES" in sys_text
    assert "Prefer cozy slice-of-life" in sys_text
    assert "never override the output format rules" in sys_text


def test_owner_extra_in_explain_prompt(extra_config):
    prompt = build_prompt([make_reco(2)], make_profile("h"), "en")
    assert "OWNER NOTES" in prompt
    assert "Prefer cozy slice-of-life" in prompt
    # l'istruzione JSON resta in coda: il formato non si negozia
    assert prompt.index("OWNER NOTES") < prompt.index("Reply with ONLY a JSON array")


def test_owner_extra_assente_prompt_identici(monkeypatch):
    monkeypatch.setattr(config, "_file_config", {})
    sys_text = build_chat_system(Result(make_profile("h"), [make_reco(1)]), "en")
    prompt = build_prompt([make_reco(2)], make_profile("h"), "en")
    assert "OWNER NOTES" not in sys_text
    assert "OWNER NOTES" not in prompt


def test_cache_key_cambia_con_extra(monkeypatch):
    monkeypatch.setattr(config, "_file_config", {})
    recos, profile = [make_reco(1)], make_profile("h")
    base = cache_key(recos, profile, "en", "u")
    monkeypatch.setattr(config, "_file_config", {"systemPromptExtra": "x"})
    changed = cache_key(recos, profile, "en", "u")
    assert base != changed
    monkeypatch.setattr(config, "_file_config", {"systemPromptExtra": "  x  "})  # strip: stessa key
    assert cache_key(recos, profile, "en", "u") == changed


async def test_served_models_fake(monkeypatch):
    async def handler(req):
        if "/models" in req.path:
            return Response({"data": [{"id": "b"}, {"id": "a"}, "sporcha", {"id": "b"}]})
        return Response({"data": []})

    async with FakeServer(handler) as srv:
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        ids = await served_models()
    assert ids == ["b", "a", "b"]  # grezzo: dedupe/sort li fa la route


# --- e2e: server A (LLM dead) per settings CRUD + 503 -------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server_a():
    async with ServerHandle() as handle:
        yield handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client_a(server_a) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server_a.base, timeout=15.0) as c:
        yield c


@pytest.mark.asyncio(loop_scope="module")
async def test_settings_get_iniziale(client_a: httpx.AsyncClient):
    res = await client_a.get("/api/settings")
    assert res.status_code == 200
    body = res.json()
    # build_env punta LLM_BASE_URL su porta morta: il form mostra quella (live) + flag
    assert body["baseUrl"] == "http://127.0.0.1:1/v1"
    assert body["model"] is None
    assert body["defaultModel"] == "qwen3:8b"
    assert body["systemPromptExtra"] == ""
    assert body["envOverride"] is True


@pytest.mark.asyncio(loop_scope="module")
async def test_settings_patch_roundtrip(client_a: httpx.AsyncClient, server_a: ServerHandle):
    res = await client_a.patch(
        "/api/settings",
        json={
            "baseUrl": "http://127.0.0.1:1234/v1/",
            "model": " qwen3.6 ",
            "systemPromptExtra": "  Parla in prima persona.  ",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["baseUrl"] == "http://127.0.0.1:1234/v1"  # trailing slash normalizzato
    assert body["model"] == "qwen3.6"  # trim
    assert body["systemPromptExtra"] == "Parla in prima persona."
    # il file su disco (CONFIG_PATH del server in tmp) contiene le chiavi del wizard
    on_disk = json.loads((server_a.tmp / "config.json").read_text(encoding="utf-8"))
    assert on_disk["baseUrl"] == "http://127.0.0.1:1234/v1"
    assert on_disk["model"] == "qwen3.6"
    # /api/health vede il nuovo model (LLM_MODEL env assente nel server)
    health = (await client_a.get("/api/health")).json()
    assert health["llm"]["model"] == "qwen3.6"


@pytest.mark.asyncio(loop_scope="module")
async def test_settings_patch_vuoto_reverte_e_cancella(client_a: httpx.AsyncClient):
    res = await client_a.patch("/api/settings", json={"model": "", "systemPromptExtra": "   "})
    assert res.status_code == 200
    body = res.json()
    assert body["model"] is None  # "" → default del server
    assert body["systemPromptExtra"] == ""  # blank → cancellata


@pytest.mark.asyncio(loop_scope="module")
async def test_settings_patch_non_validi(client_a: httpx.AsyncClient):
    bad_urls = ["ftp://x", "http://", "not-a-url", "https://spazio spaz.com", "h" * 201, ""]
    for url in bad_urls:
        res = await client_a.patch("/api/settings", json={"baseUrl": url})
        assert res.status_code == 400, url
        assert res.json() == {"error": "invalid_request"}, url
    res = await client_a.patch("/api/settings", json={"model": "x" * 121})
    assert res.status_code == 400
    res = await client_a.patch("/api/settings", json={"systemPromptExtra": "x" * 4001})
    assert res.status_code == 400
    # chiave assente = no-op: PATCH {} non tocca nulla
    res = await client_a.patch("/api/settings", json={})
    assert res.status_code == 200
    # body non-oggetto → RequestValidationError → 400 invalid_request
    res = await client_a.patch("/api/settings", content=b"[1,2]", headers={"content-type": "application/json"})
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_request"}


@pytest.mark.asyncio(loop_scope="module")
async def test_llm_models_timeout_llm_unavailable(client_a: httpx.AsyncClient):
    res = await client_a.get("/api/llm/models")
    assert res.status_code == 503
    assert res.json() == {"error": "llm_unavailable"}


# --- e2e: server B dentro FakeServer LLM: lista modelli + OWNER NOTES nel prompt chat


@pytest.mark.asyncio(loop_scope="module")
async def test_llm_models_e_chat_prompt_con_extra():
    chats: list[dict] = []

    async def handler(req):
        if "/models" in req.path:
            return Response({"data": [{"id": "modello-test"}]})
        chats.append(req.json())
        return Response({"choices": [{"message": {"content": "Ecco cosa ti consiglio."}, "finish_reason": "stop"}]})

    async with FakeServer(handler) as llm:
        async with ServerHandle(overrides={"LLM_BASE_URL": f"{llm.url}/v1", "LLM_MODEL": "modello-test"}) as server:
            async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=30.0) as c:
                res = await c.patch(
                    "/api/settings",
                    json={"systemPromptExtra": "Mai fare spoiler della seconda stagione."},
                )
                assert res.status_code == 200
                res = await c.get("/api/llm/models")
                assert res.status_code == 200
                assert res.json() == {"models": ["modello-test"], "configured": "modello-test"}
                res = await c.post(
                    "/api/chat",
                    json={
                        "username": "LookUpMark",
                        "lang": "en",
                        "messages": [{"role": "user", "content": "What should I watch next?"}],
                    },
                )
                assert res.status_code == 200
                assert res.json() == {"reply": "Ecco cosa ti consiglio."}
    assert chats, "il server non ha chiamato il LLM"
    system = chats[0]["messages"][0]
    assert system["role"] == "system"
    assert "OWNER NOTES" in system["content"]
    assert "Mai fare spoiler della seconda stagione." in system["content"]
