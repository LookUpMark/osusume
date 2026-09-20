"""Test adapter AniList (P3) — i test TS non coprono direttamente questo modulo:
stessa ricetta (fake server su porta efimera, CACHE_DIR in tmp, backoff
sostituiti) applicata ai rami del client, alla cache, alla mappatura e al
fixture mode.

I vettori sha256 sono generati con node (``JSON.stringify`` + sha256), come in
``test_json_compat.py``: la cache su disco è condivisa col backend TS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager

import pytest

from app.adapters.anilist import cache, queries
from app.adapters.anilist import client as anilist_client
from app.adapters.anilist.media import (
    fetch_media_by_ids,
    fetch_media_page,
    fetch_media_reviews,
    fetch_media_search,
    fetch_recommendations,
    fetch_user_list,
    gather_reviews,
    map_media,
)
from app.core import config, js_json
from fake_http import FakeServer, Response
from harness import free_port


@pytest.fixture
def net(tmp_path, monkeypatch):
    """CACHE_DIR in tmp + backoff istantanei (registrati) + bucket accelerato.

    Il bucket NON è stubbato (attesa reale): solo il refill viene accelerato,
    altrimenti ogni test pagherebbe 2.4s/token col RATE_PER_MIN di default.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(config, "CACHE_DIR", str(cache_dir))
    sleeps: list[float] = []

    async def instant_sleep(ms: float) -> None:
        sleeps.append(ms)

    monkeypatch.setattr(anilist_client, "sleep_ms", instant_sleep)
    monkeypatch.setattr(anilist_client, "_refill_per_sec", 500.0)
    anilist_client.reset_bucket_for_tests()
    cache._inflight.clear()  # stati di processo: mai inflight tra loop pytest-asyncio
    yield sleeps
    cache._inflight.clear()


@asynccontextmanager
async def fake_anilist(handler):
    async with FakeServer(handler) as srv:
        yield srv


def raw_media(**over) -> dict:
    base: dict = {
        "id": 5,
        "title": {"english": "Title EN"},
        "format": "TV",
        "seasonYear": 2020,
        "genres": ["Action"],
        "tags": [
            {"name": "GeneralSpoil", "rank": 80, "isGeneralSpoiler": True, "isMediaSpoiler": False},
            {"name": "Keep", "rank": 70, "isGeneralSpoiler": False, "isMediaSpoiler": False},
            {"name": "MediaSpoil", "rank": 60, "isGeneralSpoiler": False, "isMediaSpoiler": True},
        ],
        "averageScore": 75,
        "popularity": 1234,
        "coverImage": {"large": "http://cover", "color": "#abc"},
        "studios": {"nodes": [{"name": "Studio A"}]},
        "siteUrl": "http://site",
        "description": "d" * 600,
        "relations": {
            "edges": [
                {"relationType": "PREQUEL", "node": {"id": 1}},
                {"relationType": "CHARACTER", "node": {"id": 2}},
                {"relationType": "SIDE_STORY", "node": {"id": 3}},
            ]
        },
    }
    base.update(over)
    return base


# --- client: token bucket -------------------------------------------------------


async def test_token_bucket_burst_di_3_poi_attesa(monkeypatch):
    monkeypatch.setattr(anilist_client, "_refill_per_sec", 200.0)  # 1 token ogni 5ms
    anilist_client.reset_bucket_for_tests()
    t0 = time.monotonic()
    for _ in range(3):
        await anilist_client.take_token()
    assert time.monotonic() - t0 < 0.5, "burst iniziale: capacità 3 subito disponibile"
    t1 = time.monotonic()
    await anilist_client.take_token()
    waited = time.monotonic() - t1
    assert waited >= 0.001, "il 4° token attende il refill"
    assert waited < 1.0, "refill veloce (bucket accelerato dal test)"


# --- client: retry ladder -------------------------------------------------------


async def test_gql_retry_su_5xx_poi_successo(net, monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return Response({"message": "boom"}, status=500)
        return Response({"data": {"Page": {"media": []}}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        data = await anilist_client.gql(queries.MEDIA_BY_IDS_QUERY, {"id_in": [1]}, 1000)
    assert calls["n"] == 3
    assert data == {"Page": {"media": []}}
    assert net == [1000, 2000], "backoff 1s · 2^attempt"


async def test_gql_errore_rete_dopo_3_retry_poi_502(net, monkeypatch):
    # porta senza listener: ConnectError per ogni tentativo (niente cache implicata:
    # la chiave è unica per questo test e CACHE_DIR è fresco)
    monkeypatch.setattr(config, "ANILIST_ENDPOINT", f"http://127.0.0.1:{free_port()}/")  # bind+release
    from app.adapters.anilist.client import AniListError

    with pytest.raises(AniListError) as exc:
        await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert exc.value.status == 502
    assert str(exc.value).startswith("AniList unreachable:")
    assert net == [1000, 2000, 4000], "esattamente 3 retry"


async def test_gql_429_usa_retry_after_limitato_a_60(net, monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return Response({"data": {}}, status=429, headers={"retry-after": "120"})
        return Response({"data": {"ok": True}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        data = await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert calls["n"] == 2
    assert data == {"ok": True}
    assert net == [60_000], "sleep = min(retry-after, 60)"


async def test_gql_429_senza_header_sleep_default_5s(net, monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return Response({"data": {}}, status=429)  # nessun retry-after
        return Response({"data": {}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert net == [5_000]


async def test_gql_body_non_json_4_tentativi_poi_errore(net, monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        return Response(raw=b"<html>not json</html>")

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        from app.adapters.anilist.client import AniListError

        with pytest.raises(AniListError) as exc:
            await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert calls["n"] == 4, "3 retry + tentativo finale (il commento del TS sul for)"
    assert str(exc.value) == "AniList HTTP 200 (non-JSON body)"
    assert exc.value.status == 200
    assert net == [1000, 2000, 4000]


async def test_gql_graphql_errors_prende_message_e_status(net, monkeypatch):
    async def handler(req):
        return Response({"errors": [{"message": "Not Found", "status": 404}]})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        from app.adapters.anilist.client import AniListError

        with pytest.raises(AniListError) as exc:
            await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert str(exc.value) == "Not Found"
    assert exc.value.status == 404


async def test_gql_graphql_errors_senza_status_usa_http_status(net, monkeypatch):
    async def handler(req):
        return Response({"errors": [{"message": "Bad request"}]})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        from app.adapters.anilist.client import AniListError

        with pytest.raises(AniListError) as exc:
            await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert exc.value.status == 200


async def test_gql_data_assente_errore_http(net, monkeypatch):
    async def handler(req):
        return Response({"data": None})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        from app.adapters.anilist.client import AniListError

        with pytest.raises(AniListError) as exc:
            await anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "x"}, 1000)
    assert str(exc.value) == "AniList HTTP 200"
    assert exc.value.status == 200


# --- cache ----------------------------------------------------------------------


async def test_cache_hit_senza_rete_e_chiave_stabile(net, monkeypatch):
    """chiave = sha256(query + JSON.stringify(variables)) — vettori da node."""
    query, variables = "query ($id: Int)", {"id": 12, "chunk": 0}
    key = js_json.sha256_key(query, variables)
    # vettore node: sha256('query ($id: Int)' + '{"id":12,"chunk":0}')
    assert key == "3343205cca770266266f0a6731f0bb21bae4b37d101e431cfe4538b0162020bb"
    # unicode NON escapata nel serializzatore (ensure_ascii=False)
    assert js_json.sha256_key("q", {"name": "café"}) == (
        "dde96e4e4c405fd130abf64ff030a744b625f7d6db51644df1870fae4e07c142"
    )

    file = cache.cache_file(key)  # il nome file ri-hasha la key (come il TS)
    assert file.endswith(f"{hashlib.sha256(key.encode()).hexdigest()}.json")
    with open(file, "w", encoding="utf-8") as f:
        json.dump({"exp": cache.now_ms() + 60_000, "data": {"marker": 1}}, f)

    async def handler(req):
        raise AssertionError("la cache deve evitare la rete")

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        data = await anilist_client.gql(query, variables, 1000)
    assert data == {"marker": 1}


async def test_cache_scaduta_è_miss(net, monkeypatch):
    query, variables = "query ($id: Int)", {"id": 7}
    key = js_json.sha256_key(query, variables)
    with open(cache.cache_file(key), "w", encoding="utf-8") as f:
        json.dump({"exp": cache.now_ms() - 1, "data": {"old": True}}, f)

    async def handler(req):
        return Response({"data": {"fresh": True}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        data = await anilist_client.gql(query, variables, 1000)
    assert data == {"fresh": True}
    # il file scaduto NON viene cancellato, ma è stato sovrascritto dalla scrittura
    with open(cache.cache_file(key), encoding="utf-8") as f:
        assert json.load(f)["data"] == {"fresh": True}


async def test_cache_dedup_inflight_una_sola_richiesta(net, monkeypatch):
    calls = {"n": 0}

    async def handler(req):
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return Response({"data": {"n": calls["n"]}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        results = await asyncio.gather(
            anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "same"}, 1000),
            anilist_client.gql(queries.MEDIA_SEARCH_QUERY, {"q": "same"}, 1000),
        )
    assert calls["n"] == 1, "le lookup identiche condividono una sola richiesta"
    assert results[0] == results[1]


# --- mapping --------------------------------------------------------------------


def test_map_media_title_fallback():
    assert map_media(raw_media()).title == "Title EN"
    assert map_media(raw_media(title={"romaji": "Romaji T"})).title == "Romaji T"
    assert map_media(raw_media(title={})).title == "(id 5)"
    assert map_media(raw_media(title={"romaji": None, "english": None})).title == "(id 5)"


def test_map_media_spoiler_e_studio_e_popularity():
    m = map_media(raw_media())
    assert [t.name for t in m.tags] == ["Keep"]
    assert all(t.isSpoiler is False for t in m.tags)
    assert m.studio == "Studio A"
    assert m.popularity == 1234
    assert map_media(raw_media(popularity=None)).popularity == 0, "popularity ?? 0"
    assert map_media(raw_media(studios={"nodes": []})).studio is None


def test_map_media_relations_filtrate():
    m = map_media(raw_media())
    assert [(r.id, r.relationType) for r in m.relations] == [(1, "PREQUEL"), (3, "SIDE_STORY")]
    assert map_media(raw_media(relations=None)).relations == []
    # edge senza relationType → drop (il filter TS è includes(e.relationType)), non KeyError
    partial = raw_media(
        relations={"edges": [
            {"node": {"id": 7}},
            {"relationType": "SEQUEL", "node": {"id": 8}},
        ]}
    )
    assert [(r.id, r.relationType) for r in map_media(partial).relations] == [(8, "SEQUEL")]


def test_map_media_description_500_char():
    assert len(map_media(raw_media()).description) == 500
    assert map_media(raw_media(description=None)).description is None
    assert map_media(raw_media(description="")).description is None, "stringa vuota → null (ternario TS)"


# --- fetch: chunking e live -----------------------------------------------------


async def test_fetch_media_by_ids_chunk_di_50(net, monkeypatch):
    bodies: list[dict] = []

    async def handler(req):
        bodies.append(req.json())
        return Response({"data": {"Page": {"media": []}}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        out = await fetch_media_by_ids(list(range(1, 121)))
    assert out == []
    assert [b["variables"]["id_in"] for b in bodies] == [list(range(1, 51)), list(range(51, 101)), list(range(101, 121))]
    assert [b["query"] for b in bodies] == [queries.MEDIA_BY_IDS_QUERY] * 3


async def test_fetch_media_by_ids_vuoto_non_chiede_rete(net):
    assert await fetch_media_by_ids([]) == []


async def test_fetch_media_reviews_mai_blocking_e_slice_2(net, monkeypatch):
    """il .catch(() => null) del TS: un fallimento NON deve propagare, e SLICE(0,2)."""
    async def handler(req):
        return Response({"data": {"Media": {"reviews": {"nodes": [
            {"summary": "  a   b ", "body": "body1", "score": 8, "rating": 10},
            {"summary": None, "body": None, "score": None, "rating": 1},
            {"summary": "c", "body": "body3", "score": 3, "rating": 2},
        ]}}}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        out = await fetch_media_reviews(9)
    assert len(out) == 2, "perPage 3 ma SLICE(0,2)"
    assert out[0].summary == "a b", "collapse whitespace + trim + slice 120"
    assert out[0].body == "body1"
    assert (out[0].score, out[0].rating) == (8, 10)

    async def broken(req):
        return Response(raw=b"not json")

    async with fake_anilist(broken) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        assert await fetch_media_reviews(11) == [], "fallimento → [] (mai blocking)"

    # gather: dedup e solo id con >0 reviews (l'id 10 non ha recensioni)
    async def sparse(req):
        body = req.json()
        if body["variables"]["id"] == 10:
            return Response({"data": {"Media": {"reviews": {"nodes": []}}}})
        return await handler(req)

    async with fake_anilist(sparse) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        got = await gather_reviews([9, 9, 10])
    assert set(got) == {9}, "dedup id e solo id con reviews"


async def test_fetch_user_list_due_chunk_custom_list_non_vince(net, monkeypatch):
    """fetchUserList live: 2 chunk (break al primo hasNextChunk=false), una custom-list
    che fa da shadow NON sostituisce la status-list; updatedAt resta in secondi."""

    def entry(mid: int, score: float, updated: int) -> dict:
        return {
            "status": "COMPLETED",
            "score": score,
            "repeat": 0,
            "updatedAt": updated,
            "media": {"id": mid, "title": {"romaji": f"R{mid}"}},
        }

    chunks = [
        {
            "hasNextChunk": True,
            "lists": [{"isCustomList": False, "entries": [entry(1, 88, 1700000001)]}],
        },
        {
            "hasNextChunk": False,
            "lists": [
                # custom-list shadow della stessa entry: NON deve vincere
                {"isCustomList": True, "entries": [entry(1, 50, 999)]},
                {"isCustomList": False, "entries": [entry(2, 70, 1700000002)]},
            ],
        },
    ]
    bodies: list[dict] = []

    async def handler(req):
        body = req.json()
        bodies.append(body)
        return Response({"data": {"MediaListCollection": chunks[body["variables"]["chunk"]]}})

    async with fake_anilist(handler) as srv:
        monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
        ul = await fetch_user_list("someuser")

    assert [b["variables"]["chunk"] for b in bodies] == [0, 1], "due chunk, poi break"
    assert queries.LIST_LIST_QUERY == bodies[0]["query"]
    assert {e.mediaId: e for e in ul.entries}[1].score == 88.0, "status-list vince sulla custom"
    assert {e.mediaId: e for e in ul.entries}[1].updatedAt == 1700000001, "updatedAt in SECONDI"
    assert {e.mediaId: e for e in ul.entries}[2].updatedAt == 1700000002
    assert set(ul.mediaById) == {1, 2}


# --- fixture mode ---------------------------------------------------------------


@pytest.fixture
def local_mode(tmp_path, monkeypatch):
    """local mode pinned on + fixture dir in tmp (i 3 file)."""
    fdir = tmp_path / "fixtures"
    fdir.mkdir()
    (fdir / "userlist.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"mediaId": 1, "status": "COMPLETED", "score": 90, "repeat": 0, "updatedAt": 1700000000, "title": "Alpha"},
                ],
                "media": [json.loads(map_media(raw_media(id=1, title={"english": "Alpha"})).model_dump_json())],
            }
        ),
        encoding="utf-8",
    )
    candidates = [
        {"id": i, "title": f"Attack on Titan {i}", "format": "TV", "seasonYear": 2013, "genres": [],
         "tags": [], "studio": None, "averageScore": 80, "popularity": 1000, "coverImage": None,
         "coverColor": None, "siteUrl": None, "description": None, "relations": []}
        for i in range(1, 9)
    ]
    candidates.append({"id": 99, "title": "Other", "format": "TV", "seasonYear": 2013, "genres": [],
                       "tags": [], "studio": None, "averageScore": 80, "popularity": 1000,
                       "coverImage": None, "coverColor": None, "siteUrl": None, "description": None,
                       "relations": []})
    (fdir / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
    (fdir / "recommendations.json").write_text(
        json.dumps({"5": [{"targetId": 9, "rating": 100}]}), encoding="utf-8"
    )
    monkeypatch.setattr(config, "_local_mode", True)
    monkeypatch.setattr(config, "FIXTURES_DIR", str(fdir))
    return fdir


async def test_fixture_userlist(local_mode):
    ul = await fetch_user_list("someone")
    assert [e.model_dump() for e in ul.entries] == [
        {"mediaId": 1, "status": "COMPLETED", "score": 90.0, "repeat": 0, "updatedAt": 1700000000, "title": "Alpha"}
    ]
    assert 1 in ul.mediaById and ul.mediaById[1].title == "Alpha"


async def test_fixture_page_ignora_i_filtri(local_mode):
    out = await fetch_media_page(
        sort=["POPULARITY_DESC"], page=1, genres=["Drama"], tags=["Space"], minimum_tag_rank=80
    )
    assert out["hasNextPage"] is False
    assert [m.id for m in out["media"]] == list(range(1, 9)) + [99], "il pool registrato è servito intero"


async def test_fixture_by_ids_filtra(local_mode):
    out = await fetch_media_by_ids([3, 99, 1000])
    assert [m.id for m in out] == [3, 99]


async def test_fixture_search_substring_case_insensitive_slice_6(local_mode):
    out = await fetch_media_search("ATTACK ON")
    assert [m.id for m in out] == [1, 2, 3, 4, 5, 6], "slice 6"
    assert [m.id for m in await fetch_media_search("nessun-match")] == []


async def test_fixture_recommendations(local_mode):
    assert await fetch_recommendations(5) == [{"targetId": 9, "rating": 100}]
    assert await fetch_recommendations(777) == [], "id mancante → []"


async def test_fixture_reviews_sempre_vuote(local_mode):
    assert await fetch_media_reviews(5) == []
