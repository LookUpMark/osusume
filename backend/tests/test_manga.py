"""Secondo mondo manga (nuovo): recommend/stream/chat/lookup con mediaType=MANGA
su fixtures-manga, cache ANIME≠MANGA, prompt wording per tipo.

Profilo UNICO: i gusti restano quelli della lista anime — in fixtures-manga la
stessa lista fa da profilo (local mode), le asserzioni riguardano pool/formati.
"""

from __future__ import annotations

import json

import httpx
import pytest
import pytest_asyncio

from app.adapters.llm.explain import cache_key as explain_cache_key
from app.adapters.llm.prompts import _media, build_prompt
from app.core import config
from fake_http import FakeServer, Response
from harness import ServerHandle
from test_llm import Result, make_profile, make_reco

USER = "LookUpMark"
ANIME_FORMATS = {"TV", "TV_SHORT", "OVA", "ONA", "MOVIE", "SPECIAL"}
MANGA_FORMATS = {"MANGA", "LIGHT_NOVEL", "ONE_SHOT"}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server_m():
    async with ServerHandle(fixture_dir="fixtures-manga") as handle:
        yield handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client_m(server_m) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server_m.base, timeout=30.0) as c:
        yield c


@pytest.mark.asyncio(loop_scope="module")
async def test_manga_recommend_solo_formati_manga(client_m: httpx.AsyncClient):
    res = await client_m.post("/api/recommend", json={"username": USER, "lang": "en", "mediaType": "MANGA"})
    assert res.status_code == 200
    body = res.json()
    recos = body["recos"]
    assert recos, "pool manga non vuoto"
    assert all(r["media"]["format"] in MANGA_FORMATS for r in recos), [r["media"]["format"] for r in recos]
    ids = {r["media"]["id"] for r in recos}
    # 605 = sequel del manga DROPPED 504 → catena EXCLUDED → avoided, mai consigliato
    assert 605 not in ids
    assert any(a["media"]["id"] == 605 for a in body["avoided"])
    # 506 è in PLANNING → escluso dalla lista utente
    assert 506 not in ids


@pytest.mark.asyncio(loop_scope="module")
async def test_default_assente_e_anime(client_m: httpx.AsyncClient):
    body_no = (await client_m.post("/api/recommend", json={"username": USER, "lang": "en"})).json()
    body_anime = (
        await client_m.post("/api/recommend", json={"username": USER, "lang": "en", "mediaType": "ANIME"})
    ).json()
    assert body_no == body_anime
    # mediaType estraneo → default silenzioso (come _lang)
    body_weird = (
        await client_m.post("/api/recommend", json={"username": USER, "lang": "en", "mediaType": "NOVEL"})
    ).json()
    assert body_weird == body_no


@pytest.mark.asyncio(loop_scope="module")
async def test_stream_manga_fasi_e_done_paritario(client_m: httpx.AsyncClient):
    # lang=it = chiave cache fredda (l'en è già calda dal test precedente): il
    # stream mostra le fasi; il POST successivo è cache hit → stessi byte del done
    lines: list[str] = []
    async with client_m.stream(
        "GET", "/api/recommend/stream", params={"username": USER, "lang": "it", "mediaType": "MANGA"}
    ) as r:
        assert r.status_code == 200
        async for line in r.aiter_lines():
            lines.append(line)
    events = [l for l in lines if l.startswith("event:")]
    assert events[0] == "event: phase"
    assert events[-1] == "event: done"
    done_payload = json.loads([l.split(":", 1)[1] for l in lines if l.startswith("data:")][-1])
    post = await client_m.post("/api/recommend", json={"username": USER, "lang": "it", "mediaType": "MANGA"})
    assert done_payload == post.json()  # cache hit del POST successivo: stessi byte


@pytest.mark.asyncio(loop_scope="module")
async def test_lookup_manga(client_m: httpx.AsyncClient):
    res = await client_m.post(
        "/api/lookup", json={"username": USER, "q": "Candidate", "lang": "en", "mediaType": "MANGA"}
    )
    assert res.status_code == 200
    recos = res.json()["recos"]
    assert recos
    assert all(r["media"]["format"] in MANGA_FORMATS for r in recos)


@pytest.mark.asyncio(loop_scope="module")
async def test_chat_manga_prompt_senza_studio():
    """Il system prompt manga parla di manga (niente 'anime expert') e non stampa 'studio ?'."""
    chats: list[dict] = []

    async def handler(req):
        if req.path.endswith("/models"):
            return Response({"data": [{"id": config.llm_model()}]})
        chats.append(req.json())
        return Response({"choices": [{"message": {"content": "**Candidate Manga A** is a great next read."}, "finish_reason": "stop"}]})

    async with FakeServer(handler) as llm:
        async with ServerHandle(
            fixture_dir="fixtures-manga",
            overrides={"LLM_BASE_URL": f"{llm.url}/v1"},
        ) as server:
            async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=30.0) as c:
                res = await c.post(
                    "/api/chat",
                    json={"username": USER, "lang": "en", "mediaType": "MANGA", "messages": [{"role": "user", "content": "what should I read next?"}]},
                )
    assert res.status_code == 200
    system = chats[0]["messages"][0]["content"]
    assert "manga expert" in system
    assert "anime expert" not in system
    assert "studio ?" not in system


# --- unit: wording + cache keys -----------------------------------------------------


def test_media_wording():
    assert _media("ANIME")["noun"] == "anime" and _media("ANIME")["person"] == "viewer"
    assert _media("MANGA")["noun"] == "manga" and _media("MANGA")["person"] == "reader"
    assert _media("MANGA")["consumed"] == "read"
    assert _media("boh") == _media("ANIME"), "default silenzioso"


def test_prompt_manga_wording_e_studio_assente():
    reco_anime = make_reco(1)
    reco_anime.media.studio = "Madhouse"
    reco_manga = make_reco(2)
    reco_manga.media.studio = None
    reco_manga.media.title = "Candidate Manga A"

    anime_prompt = build_prompt([reco_anime], make_profile("h"), "en")
    manga_prompt = build_prompt([reco_manga], make_profile("h"), "en", media_type="MANGA")
    assert "veteran anime critic" in anime_prompt
    assert "veteran manga critic" in manga_prompt
    assert "Madhouse" in anime_prompt
    # nel blocco item del manga la riga studio sparisce (il "studio lineage" della
    # COMPARISON_STANDARD resta: è dottrina condivisa, non un campo del titolo)
    item_block = manga_prompt[manga_prompt.index("- id=2") :]
    assert "studio" not in item_block


def test_explain_cache_key_distinta_per_tipo():
    recos, profile = [make_reco(1)], make_profile("h")
    k_anime = explain_cache_key(recos, profile, "en", "u", "ANIME")
    k_manga = explain_cache_key(recos, profile, "en", "u", "MANGA")
    assert k_anime != k_manga
    assert explain_cache_key(recos, profile, "en", "u") == k_anime
