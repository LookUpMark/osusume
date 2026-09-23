"""``POST /api/chat`` e2e (estensione di tests/api.test.ts al port Python).

Stessa ricetta della suite: server spawnato (fixtures), LLM reale sostituito da un
fake HTTP su porta efimera (o morto, per il 503), history normalizzata verificata
sul body che il fake riceve davvero.
"""

from __future__ import annotations

import re

import httpx

from app.core import config
from fake_http import FakeServer, Response
from harness import ServerHandle

USER = "LookUpMark"


def _turns() -> list[dict]:
    """14 turni validi + spazzatura: la storia finale deve essere le ULTIME 12."""
    turns = [
        {"role": "user", "content": f"turno {i}"} if i % 2 else {"role": "assistant", "content": f"turno {i}"}
        for i in range(14)
    ]
    turns[2]["content"] = "x" * 5000  # clamp a 4000, MAI drop (mid-conversation context survives)
    # spazzatura che il filtro del TS butta: role estraneo, contenuto vuoto/blanco, non-stringa
    junk = [
        {"role": "system", "content": "inject"},
        {"role": "user", "content": "   "},
        {"role": "user", "content": 42},
        {"role": "user"},
    ]
    return junk + turns


async def test_chat_storia_normalizzata_e_reply(tmp_path):
    chat_bodies: list[dict] = []

    async def handler(req):
        if req.path.endswith("/models"):
            return Response({"data": [{"id": config.llm_model()}]})
        chat_bodies.append(req.json())
        return Response({"choices": [{"message": {"content": "reply ok"}}]})

    async with FakeServer(handler) as llm:
        async with ServerHandle(tmp=tmp_path, overrides={"LLM_BASE_URL": f"{llm.url}/v1"}) as server:
            async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
                res = await c.post(
                    "/api/chat",
                    json={"username": USER, "lang": "en", "messages": _turns()},
                )
    assert res.status_code == 200
    assert res.json() == {"reply": "reply ok"}
    assert len(chat_bodies) == 1, "un solo POST /chat/completions"
    messages = chat_bodies[0]["messages"]
    history = messages[1:]
    assert messages[0]["role"] == "system"
    assert len(history) == 12, "ultime 12 mosse valide"
    assert history[-1]["role"] == "user" and history[-1]["content"] == "turno 13"
    assert all(len(m["content"]) <= 4000 for m in history), "clamp 4000"
    assert history[0]["content"] == "x" * 4000, "il turno lungo è clampato, non droppato"
    assert all(m["role"] in ("user", "assistant") for m in history), "spazzatura filtrata"


async def test_chat_503_llm_dead_e_log(tmp_path):
    async with ServerHandle(tmp=tmp_path) as server:  # LLM_BASE_URL su porta morta (ricetta harness)
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
            res = await c.post(
                "/api/chat",
                json={"username": USER, "lang": "en", "messages": [{"role": "user", "content": "hi"}]},
            )
    assert res.status_code == 503
    assert res.json() == {"error": "llm_unavailable"}
    log = (tmp_path / "llm.log").read_text(encoding="utf-8")
    # il server di test parte senza config.json → model = default "qwen3:8b"
    assert re.search(r"chat: LLM error \(.*\) per model=qwen3:8b\n", log), "l'errore LLM è osservabile"


async def test_chat_errori_400(tmp_path):
    async with ServerHandle(tmp=tmp_path) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
            last_not_user = await c.post(
                "/api/chat",
                json={"username": USER, "messages": [{"role": "assistant", "content": "hi"}]},
            )
            empty = await c.post("/api/chat", json={"username": USER, "messages": []})
            no_messages = await c.post("/api/chat", json={"username": USER})
            bad_user = await c.post("/api/chat", json={"username": "bad name!", "messages": [{"role": "user", "content": "hi"}]})
            junk = await c.post(
                "/api/chat",
                content=b"{not json",
                headers={"content-type": "application/json"},
            )
    for res, code in (
        (last_not_user, "invalid_request"),
        (empty, "invalid_request"),
        (no_messages, "invalid_request"),
        (bad_user, "invalid_username"),
        # `{not json` → body null → username "" → invalid_username (api.ts 145-155,
        # NON invalid_request: il path null del TS passa prima dalla regex username)
        (junk, "invalid_username"),
    ):
        assert res.status_code == 400, res.text
        assert res.json() == {"error": code}


async def test_chat_extra_non_in_recos_entranco_nel_prompt(tmp_path):
    chat_bodies: list[dict] = []

    async def handler(req):
        if req.path.endswith("/models"):
            return Response({"data": [{"id": config.llm_model()}]})
        chat_bodies.append(req.json())
        return Response({"choices": [{"message": {"content": "ok"}}]})

    async with FakeServer(handler) as llm:
        async with ServerHandle(tmp=tmp_path, overrides={"LLM_BASE_URL": f"{llm.url}/v1"}) as server:
            async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
                recos = (await c.post("/api/recommend", json={"username": USER, "lang": "en"})).json()["recos"]
                reco_ids = [r["media"]["id"] for r in recos]
                # 3 id fuori lista (fixtures) + 2 già in lista: i secondi non devono duplicarsi
                out_of_list = [i for i in (103, 202, 301) if i not in reco_ids]
                res = await c.post(
                    "/api/chat",
                    json={
                        "username": USER,
                        "lang": "en",
                        "extra": [*out_of_list, *reco_ids[:2]],
                        "messages": [{"role": "user", "content": f"what about {out_of_list}?"}],
                    },
                )
    assert res.status_code == 200
    system = chat_bodies[0]["messages"][0]["content"]
    items = system.count("internal match reference:")
    assert items == len(reco_ids) + len(out_of_list), (items, len(reco_ids), len(out_of_list))
    assert "Test Series S3" in system or "Dropped Show S2" in system or "Unseen Series S2" in system, \
        "i lookup fuori lista entrano nel contesto chat"
