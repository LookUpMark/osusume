"""Porting 1:1 di ``tests/llm.test.ts`` (274 righe, 8 scenari).

Stessa ricetta dei fake server TS: server asyncio su porta efimera, env
LLM_BASE_URL/ANILIST puntati lì, CACHE_DIR/DATA_DIR sempre in tmp. Nessuna
rete reale: AniList è servito da un fake che risponde ``{"data": {}}`` (le
reviews giustamente vuote) e il token bucket è accelerato.
"""

from __future__ import annotations

import json
import pathlib
import re
from contextlib import asynccontextmanager
from typing import Any, Callable

import pytest

from app.adapters.anilist import cache
from app.adapters.anilist import client as anilist_client
from app.adapters.anilist.media import ReviewLite
from app.adapters.llm.chat import build_chat_system, chat_reply, mentioned_titles
from app.adapters.llm.client import LlmError, llm_chat, llm_health
from app.adapters.llm.explain import explain_recos
from app.adapters.llm.parse import parse_explanations
from app.adapters.llm.prompts import build_prompt
from app.core import config
from app.shared.models import (
    DimValue,
    MediaTagLite,
    RecoBreakdown,
    ScoredReco,
    TasteProfile,
)
from fake_http import FakeServer, Response
from harness import free_port
from helpers import media


def make_media(id: int, **over):
    base = dict(
        genres=["Mystery"],
        tags=[MediaTagLite(name="Psychological", rank=90, isSpoiler=False)],
        studio="Madhouse",
        averageScore=80,
        popularity=50000,
    )
    base.update(over)
    return media(id, **base)


def make_reco(id: int, **over) -> ScoredReco:
    return ScoredReco(
        media=make_media(id, **over),
        final=0.8,
        breakdown=RecoBreakdown(affinity=0.7, quality=0.7, community=0),
        badges=[],
        rootId=None,
        groupSize=1,
        why=f"deterministic why for {id}",
    )


def make_profile(hash_: str) -> TasteProfile:
    return TasteProfile(
        userName="test",
        meanScore=70,
        scoredCount=10,
        confidence="ok",
        counts={"CURRENT": 0, "PLANNING": 0, "COMPLETED": 10, "DROPPED": 0, "PAUSED": 0, "REPEATING": 0},
        loved=[DimValue(dim="tag", value="Psychological", aff=0.6, support=5, examples=["X"])],
        disliked=[],
        hash=hash_,
    )


class Result:
    """``RecoResult`` minimo per buildChatSystem (il tipo vero arriva in P4)."""

    def __init__(self, profile: TasteProfile, recos: list[ScoredReco]) -> None:
        self.profile = profile
        self.recos = recos
        self.avoided = []


@pytest.fixture
async def hermetic(tmp_path, monkeypatch):
    """Fake AniList + CACHE_DIR/DATA_DIR in tmp + token bucket accelerato.

    explainRecos raccoglie le reviews in live mode: senza questo fixture ogni
    test andrebbe su graphql.anilist.co (rete reale nei test, mai).
    """

    async def anilist_handler(req):
        return Response({"data": {}})

    async with FakeServer(anilist_handler) as anilist:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", anilist.url)
        monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(anilist_client, "_refill_per_sec", 500.0)
        anilist_client.reset_bucket_for_tests()
        cache._inflight.clear()  # stati di processo: mai inflight tra loop pytest-asyncio
        yield anilist
        cache._inflight.clear()


@asynccontextmanager
async def fake_llm(handler: Callable[[dict, dict], Any]):
    """``withFakeLLM`` del TS: /models serve il modello configurato, il chat
    handler riceve (body, hits) e torna il content (o il body JSON intero);
    hits conta solo i chat."""
    hits = {"count": 0}

    async def h(req):
        if "/models" in req.path:
            return Response({"data": [{"id": config.llm_model()}]})
        hits["count"] += 1
        out = handler(req.json(), hits)
        body = out if isinstance(out, dict) else {"choices": [{"message": {"content": out}}]}
        return Response(body)

    async with FakeServer(h) as srv:
        yield srv, hits


async def test_explain_llm_cached_fallback_never_cached_request_contract(hermetic, monkeypatch):
    """explainRecos: LLM narrations cached, fallbacks never cached, request contract held."""
    profile = make_profile(hash_="h-abc123")
    captured: dict[str, Any] = {}

    def handler(body, _hits):
        captured.update(body)
        # request-contract asserts: model = whatever llmModel() resolves, profile + language present
        assert body["model"] == config.llm_model()
        user = body["messages"][-1]["content"]
        assert "Psychological" in user, "taste profile must reach the prompt"
        assert "English" in user, "language directive must be present"
        ids = [int(m) for m in re.findall(r"id=(\d+)", user)]
        return json.dumps([{"id": i, "why": ("" if i == 2 else f"llm says {i}")} for i in ids])

    async with fake_llm(handler) as (srv, hits):
        monkeypatch.setenv("LLM_MODEL", "env-model-x")  # env > config
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        recos = [make_reco(1), make_reco(2)]
        first = await explain_recos(recos, profile, "en", "testuser")
        assert first[1].source == "llm"
        assert first[1].text == "llm says 1"
        assert first[2].source == "fallback", "empty LLM answer falls back"
        assert first[2].text == "deterministic why for 2"
        assert hits["count"] == 1

        second = await explain_recos(recos, profile, "en", "testuser")
        assert second[1].source == "cache", "LLM text is cached"
        assert second[2].source == "fallback", "fallbacks are NOT cached — model retried"
        assert hits["count"] == 2, "second call retries the failed id with the LLM"

    assert captured["model"] == "env-model-x", "model = llm_model() (env vince su config)"


async def test_explain_unreachable_degrades_to_deterministic_fallbacks(hermetic, monkeypatch):
    """explainRecos: unreachable LLM degrades to deterministic fallbacks without throwing."""
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{free_port()}/v1")  # bind+release: nothing listens here
    out = await explain_recos([make_reco(7)], make_profile(hash_="h-unreach"), "it", "testuser")
    assert out[7].source == "fallback"
    assert "deterministic why for 7" in out[7].text


async def test_llm_chat_thinking_disabled_think_blocks_stripped_budget_default(hermetic, monkeypatch):
    """llmChat: thinking disabled at the source, think blocks stripped, budget default."""

    async with fake_llm(
        lambda _body, _hits: '<think>let me reason at length…</think>[{"id":30,"why":"ok"}]'
    ) as (srv, _hits):
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        out = await llm_chat([{"role": "user", "content": "hi"}], "m")
        assert out == '[{"id":30,"why":"ok"}]'
        body = srv.requests[-1].json()
        assert body["chat_template_kwargs"]["enable_thinking"] is False
        assert body["max_tokens"] == 1200  # explanation-sized, not reasoning-sized
        assert body["temperature"] == 0.3
        assert body["repetition_penalty"] == 1.12


async def test_llm_chat_server_down_raises_llm_error(hermetic, monkeypatch):
    """llmChat: server down throws LlmError ('unreachable'), not a bare TypeError."""
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{free_port()}/v1")  # bind+release: nothing listens here
    with pytest.raises(LlmError, match="unreachable"):
        await llm_chat([{"role": "user", "content": "hi"}], "m")


def test_parse_explanations_prose_wrapped_fenced_truncated_and_garbage():
    assert parse_explanations('bla [{"id":1,"why":"a"}] tra') == [{"id": 1, "why": "a"}]
    assert parse_explanations('```json\n[{"id":2,"why":"b"}]\n```') == [{"id": 2, "why": "b"}]
    # prose containing multiple arrays: the LAST valid one wins (thinking models
    # write bracketed fragments first, the real answer last)
    assert parse_explanations('[{"id":3,"why":"c"}] and [{"id":9,"why":"x"}]') == [{"id": 9, "why": "x"}]
    # a bracketed fragment inside reasoning is skipped when it doesn't parse as items
    assert parse_explanations('think [0, 1] more [{"id":5,"why":"e"}]') == [{"id": 5, "why": "e"}]
    # string ids coerce when integer (small models), garbage ids drop
    assert parse_explanations('[{"id":"4","why":"d"}]') == [{"id": 4, "why": "d"}]
    assert parse_explanations('[{"id":"abc","why":"e"}]') == []
    assert parse_explanations("no array here at all") == []
    assert parse_explanations("[unclosed") == []
    # JSON.parse rifiuta NaN/Infinity, json.loads li accetta: lo span con quei
    # token va SCARTATO e si passa al precedente (vettori verificati sul TS)
    assert parse_explanations('[{"id":1,"why":"a","score":NaN}]') == []
    assert (
        parse_explanations('[{"id":7,"why":"bad","score":NaN}] then [{"id":8,"why":"good"}]')
        == [{"id": 8, "why": "good"}]
    )
    assert parse_explanations('[{"id":4,"why":"d","n":-Infinity}]') == []


async def test_llm_health_200_is_not_up_unless_model_is_served(hermetic, monkeypatch):
    """llmHealth: 200 on /models is not 'up' unless the configured model is served."""

    async def handler(req):
        if "/models" in req.path:
            return Response({"data": [{"id": "altro-modello"}]})
        return Response({}, status=404)

    async with FakeServer(handler) as srv:
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("LLM_MODEL", "prism-ml/Ternary-Bonsai-2-27B-gguf")
        assert await llm_health() is False, "missing model → honest off (never a phantom green chip)"
        monkeypatch.setenv("LLM_MODEL", "altro-modello")
        assert await llm_health() is True, "model served → up"
        monkeypatch.setenv("LLM_MODEL", "org/altro-modello")
        assert await llm_health() is True, "org-prefixed config tolerated against bare server id"


async def test_chat_system_prompt_expert_grounded_in_visible_result(hermetic):
    """chat: system prompt is an expert grounded in the visible result, algorithm-speak banned."""
    result = Result(make_profile(hash_="h-chat"), [make_reco(1), make_reco(2)])
    sys_en = build_chat_system(result, "en")
    assert "m1" in sys_en and "m2" in sys_en, "titles present"
    assert "BANNED" in sys_en, "explicit ban on algorithm-speak"
    assert "Psychological (they enjoyed it in" in sys_en, "taste links with seen titles"
    assert "LEADS, not facts" in sys_en, "comparison doctrine reaches chat"
    assert "English" in sys_en, "language directive present"
    sys_it = build_chat_system(result, "it")
    assert "Italian" in sys_it, "language follows the requested lang"


def test_build_prompt_doctrine_and_reception_only_with_reviews():
    """buildPrompt: comparison doctrine + reception line only when reviews exist."""
    profile = make_profile(hash_="h-prompt")
    base = build_prompt([make_reco(1)], profile, "en")
    assert "veteran anime critic" in base, "critic voice, not friend-wiki"
    assert "LEADS, not facts" in base, "doctrine present"
    assert "possible leads (verify, drop if shallow)" in base, "leads are framed as unverified"
    assert "reception:" not in base, "no reception line without reviews"

    grounded = build_prompt(
        [make_reco(1)],
        profile,
        "en",
        {
            1: [
                ReviewLite(
                    summary="A slow burn",
                    body="the payoff recontextualizes every early scene",
                    score=85,
                    rating=12,
                )
            ]
        },
    )
    assert "reception:" in grounded, "reception reaches the prompt"
    assert "payoff recontextualizes" in grounded, "review body excerpt present"
    assert "A slow burn" not in grounded, "summary omitted — punchy lines get echoed verbatim"


def test_mentioned_titles_last_user_message_min_length_cap():
    """mentionedTitles: last user message only, min title length, capped at 2."""
    cands = [
        make_reco(1, title="Monster"),
        make_reco(2, title="Vinland Saga"),
        make_reco(3, title="mx"),
    ]
    # titles below 4 chars ("mx") never match; case-insensitive
    hit = mentioned_titles([{"role": "user", "content": "tell me about MONSTER please"}], cands)
    assert len(hit) == 1
    assert hit[0].media.id == 1
    # last message is the assistant's → no match even if a title appears
    assert (
        mentioned_titles(
            [
                {"role": "user", "content": "Monster?"},
                {"role": "assistant", "content": "Monster is great"},
            ],
            cands,
        )
        == []
    )
    assert (
        len(mentioned_titles([{"role": "user", "content": "Monster or Vinland Saga first?"}], cands)) == 2
    ), "two mentions matched, cap enforced"


async def test_chat_reply_retry_su_truncation_altri_errori_propagano(hermetic, monkeypatch):
    """chatReply: UN retry 4000 HARDCODED su truncation; gli altri errori salgono."""
    profile = make_profile(hash_="h-reply")
    result = Result(profile, [make_reco(1)])
    history = [{"role": "user", "content": "Monster?"}]
    calls = {"n": 0}

    def handler(body, _hits):
        calls["n"] += 1
        assert body["messages"][0]["role"] == "system", "il system prompt apre i messaggi"
        assert body["messages"][-1] == {"role": "user", "content": "Monster?"}
        if calls["n"] == 1:
            return {"choices": [{"finish_reason": "length"}]}
        assert body["max_tokens"] == 4000, "safety net — thinking is off at the source"
        return "reply ok"

    async with fake_llm(handler) as (srv, _hits):
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        assert await chat_reply(result, "en", history) == "reply ok"
    assert calls["n"] == 2

    async with fake_llm(lambda _b, _h: {"choices": [{"message": {"content": ""}}]}) as (srv, _hits):
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        with pytest.raises(LlmError):
            await chat_reply(result, "en", history)  # non-truncation → propagate


async def test_explain_batch_unparseabile_retry_correttivo(hermetic, monkeypatch):
    """il ramo del TS: JSON valido ma chiave sbagliata → UN retry correttivo con append."""
    profile = make_profile(hash_="h-corrective")
    calls = {"n": 0}

    def handler(_body, _hits):
        calls["n"] += 1
        if calls["n"] == 1:
            return '[{"id":1,"where":"wrong key"}]'
        assert calls["n"] == 2
        return '[{"id":1,"why":"fixed"}]'

    async with fake_llm(handler) as (srv, hits):
        monkeypatch.setenv("LLM_BASE_URL", srv.url + "/v1")
        out = await explain_recos([make_reco(1)], profile, "en", "testuser")
    assert out[1].source == "llm" and out[1].text == "fixed"
    assert calls["n"] == 2 and hits["count"] == 2
    log = (pathlib.Path(config.DATA_DIR) / "llm.log").read_text(encoding="utf-8")
    assert "explain: batch unparseabile" in log and "retry correttivo" in log


async def test_explain_errore_llm_break_non_continue(hermetic, monkeypatch):
    """errore LLM di batch → log + BREAK: i batch successivi non vengono tentati."""
    profile = make_profile(hash_="h-break")
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{free_port()}/v1")  # bind+release: nothing listens here
    recos = [make_reco(i) for i in range(1, 16)]  # 2 batch (10 + 5)
    out = await explain_recos(recos, profile, "en", "testuser")
    assert all(out[i].source == "fallback" for i in range(1, 16))
    log = (pathlib.Path(config.DATA_DIR) / "llm.log").read_text(encoding="utf-8")
    assert log.count("explain: LLM error") == 1, "BREAK: il secondo batch non è tentato"
    assert "prose deterministiche in uso" in log


# --- markdown card extraction (nuovo: chat UI) --------------------------------------


def test_recommended_cards_bold_match_e_filtri():
    """Bold esatto case-insensitive; fallback contains >=4; fuori pool ignorato;
    *italic* non è card; dedup per id; cap 4; niente bold → []."""
    from app.adapters.llm.chat import CARDS_MAX, card_payload, recommended_cards

    pool = [make_reco(i) for i in range(1, 7)]
    for i, r in enumerate(pool):
        r.media.title = ["Vinland Saga", "Monster", "Series Three", "Series Four", "Series Five", "Series Six"][i]

    # esatto case-insensitive + contiene
    out = recommended_cards("Try **VINLAND SAGA** and **Monster**.", pool)
    assert [r.media.id for r in out] == [1, 2]
    # contains bidirezionale: bold parziale ("Vinland") trova "Vinland Saga"
    out = recommended_cards("Start with **Vinland**.", pool)
    assert [r.media.id for r in out] == [1]
    # fuori pool / italic / bold corto: nessuna card
    assert recommended_cards("**Cowboy Bebop** and *Vinland Saga* and **ab**.", pool) == []
    # dedup + ordine di apparizione
    out = recommended_cards("**Monster** first, then **Monster** again.", pool)
    assert [r.media.id for r in out] == [2]
    # cap CARDS_MAX
    reply = " ".join(f"**{pool[i].media.title}**" for i in range(6))
    assert len(recommended_cards(reply, pool)) == CARDS_MAX
    # bold cross-riga non matcha (regex esclude \n)
    assert recommended_cards("**Vinland\nSaga**", pool) == []


def test_card_payload_campi_minimi():
    from app.adapters.llm.chat import card_payload

    reco = make_reco(1)
    reco.media.title = "Monster"
    reco.final = 0.875
    card = card_payload(reco)
    assert set(card) == {"id", "title", "coverImage", "coverColor", "seasonYear", "format", "score", "siteUrl"}
    assert card["score"] == 88, "js_round(final*100) = Math.round del frontend"


def test_chat_system_prompt_markdown_rules():
    """Le nuove regole markdown nel prompt chat; il vecchio ban liste è andato."""
    result = Result(make_profile(hash_="h-md"), [make_reco(1)])
    sys_en = build_chat_system(result, "en")
    assert "EVERY anime you recommend in **bold**" in sys_en
    assert "exact title as listed in CURRENT RECOMMENDATIONS" in sys_en
    assert "NEVER use headings" in sys_en and "code blocks" in sys_en
    assert "No bullet lists unless asked" not in sys_en, "rilassato: liste brevi ammesse"
    assert "BANNED" in sys_en and "English" in sys_en, "dottrina e lingua intatte"
