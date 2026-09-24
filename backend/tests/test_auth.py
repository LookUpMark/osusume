"""OAuth AniList + watchlist (nuovo, non nel TS).

Flow e2e con FakeServer per token+Viewer, callback listener su porta efimera
(env ANILIST_OAUTH_CALLBACK_PORT), niente segreti nelle risposte API.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio

from fake_http import FakeServer, Response
from harness import ServerHandle

USER = "LookUpMark"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def server_a():
    async with ServerHandle() as handle:
        yield handle


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client_a(server_a) -> httpx.AsyncClient:
    async with httpx.AsyncClient(trust_env=False, base_url=server_a.base, timeout=15.0) as c:
        yield c


@pytest.mark.asyncio(loop_scope="module")
async def test_auth_status_vuoto(client_a: httpx.AsyncClient):
    res = await client_a.get("/api/auth/anilist")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["authenticated"] is False
    assert body["username"] is None
    assert body["redirectUri"].startswith("http://127.0.0.1:")


@pytest.mark.asyncio(loop_scope="module")
async def test_auth_patch_validazione(client_a: httpx.AsyncClient, server_a: ServerHandle):
    res = await client_a.patch("/api/auth/anilist", json={"clientId": "abc"})
    assert res.status_code == 400
    res = await client_a.patch("/api/auth/anilist", json={"clientSecret": "short"})
    assert res.status_code == 400
    res = await client_a.patch("/api/auth/anilist", json={"clientId": "12345", "clientSecret": "s" * 32})
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert "clientSecret" not in json.dumps(body), "il secret non torna mai nelle risposte"
    on_disk = json.loads((server_a.tmp / "config.json").read_text(encoding="utf-8"))
    assert on_disk["anilistClientId"] == "12345"
    assert on_disk["anilistClientSecret"] == "s" * 32


@pytest.mark.asyncio(loop_scope="module")
async def test_auth_flow_e2e():
    """Flow completo contro FakeServer: authorize URL → callback+state → token → Viewer."""
    async def handler(req):
        if "/oauth/token" in req.path:
            return Response({"access_token": "TOKEN-XYZ", "expires_in": 31536000, "token_type": "Bearer"})
        body = req.json()
        if "Viewer" in (body.get("query") or ""):
            return Response({"data": {"Viewer": {"name": "marco"}}})
        return Response({"data": {}})

    async with FakeServer(handler) as anilist:
        port = __import__("harness").free_port()
        async with ServerHandle(
            overrides={
                "ANILIST_ENDPOINT": anilist.url,  # Viewer via FakeServer (endpoint harness è morto)
                "ANILIST_OAUTH_TOKEN_URL": f"{anilist.url}/api/v2/oauth/token",
                "ANILIST_OAUTH_CALLBACK_PORT": str(port),
            }
        ) as server:
            base = server.base
            async with httpx.AsyncClient(trust_env=False, timeout=15.0) as c:
                # PATCH prima: credenziali sul server di QUESTA istanza
                await c.patch(f"{base}/api/auth/anilist", json={"clientId": "777", "clientSecret": "s" * 32})
                res = await c.post(f"{base}/api/auth/anilist/start")
                assert res.status_code == 200, res.text
                url = res.json()["url"]
                q = parse_qs(urlparse(url).query)
                assert q["client_id"] == ["777"]
                assert q["redirect_uri"] == [f"http://127.0.0.1:{port}/callback"]
                assert q["response_type"] == ["code"]
                state = q["state"][0]
                assert state, "state monouso presente"

                # start durante pending → 409
                busy = await c.post(f"{base}/api/auth/anilist/start")
                assert busy.status_code == 409
                assert busy.json() == {"error": "oauth_busy"}

                # callback con state sbagliato → rifiutata, flow resta pending
                wrong = await c.get(f"http://127.0.0.1:{port}/callback", params={"code": "C", "state": "evil"})
                assert wrong.status_code == 404
                status = (await c.get(f"{base}/api/auth/anilist")).json()
                assert status["authenticated"] is False

                # callback corretto → token + Viewer → configurazione salvata
                ok = await c.get(f"http://127.0.0.1:{port}/callback", params={"code": "C", "state": state})
                assert ok.status_code == 200
                assert b"close this window" in ok.content

                status = (await c.get(f"{base}/api/auth/anilist")).json()
                assert status["authenticated"] is True
                assert status["username"] == "marco"
                assert status["flow"] == "ok"
                # niente token in NESSUNA risposta
                assert "TOKEN-XYZ" not in json.dumps(status)

                on_disk = json.loads((server.tmp / "config.json").read_text(encoding="utf-8"))
                assert on_disk["anilistToken"] == "TOKEN-XYZ"
                assert on_disk["anilistUser"] == "marco"

                # disconnect: token/user via, credenziali restano
                res = await c.post(f"{base}/api/auth/anilist/disconnect")
                assert res.status_code == 200
                status = (await c.get(f"{base}/api/auth/anilist")).json()
                assert status["authenticated"] is False
                assert status["configured"] is True


@pytest.mark.asyncio(loop_scope="module")
async def test_watchlist_requires_token(client_a: httpx.AsyncClient):
    res = await client_a.post("/api/watchlist", json={"mediaId": 1})
    assert res.status_code == 401
    assert res.json() == {"error": "anilist_auth"}
    res = await client_a.post("/api/watchlist", json={"mediaId": 0})
    assert res.status_code == 400
    res = await client_a.get("/api/watchlist/status", params={"username": USER, "mediaId": 1})
    # server senza token: la query anonima su fixture mode... fixture dir è vera ma
    # MEDIA_LIST_STATUS non è tra i fixture: la chiamata va in locale? no: fetch_media_list_status
    # usa gql che in local mode NON è intercettato — AniList morto → {"status": None}
    assert res.status_code == 200
    assert res.json() == {"status": None}


def test_with_local_fallback_non_scatta_su_401(monkeypatch):
    from app.api import routes
    from app.adapters.anilist.client import AniListError
    from app.core import config

    called = {"n": 0}

    async def fn():
        called["n"] += 1
        raise AniListError("expired", 401)

    monkeypatch.setattr(config, "_auto_fallback", True)
    monkeypatch.setattr(config, "_local_mode", False)
    monkeypatch.setattr(config, "fixtures_available", lambda: True)

    import asyncio

    try:
        asyncio.run(routes.with_local_fallback(fn))
    except AniListError:
        pass
    assert called["n"] == 1, "401: nessun retry né flip a local mode"


def test_cache_auth_vs_anonima_diverse_chiavi(monkeypatch, tmp_path):
    """Stessa query+variables con/senza token → richieste di rete distinte."""
    import asyncio

    from app.adapters.anilist import cache, client
    from app.core import config

    async def main():
        async def handler(req):
            return Response({"data": {"ok": True}})

        async with FakeServer(handler) as srv:
            monkeypatch.setattr(config, "ANILIST_ENDPOINT", srv.url)
            monkeypatch.setattr(config, "CACHE_DIR", str(tmp_path))
            monkeypatch.setattr(client, "sleep_ms", _nosleep)
            client.reset_bucket_for_tests()
            cache._inflight.clear()
            hits = {"n": 0}

            real_fetch = client._gql_fetch

            async def counting(query, variables, headers=None):
                hits["n"] += 1
                return await real_fetch(query, variables, headers)

            monkeypatch.setattr(client, "_gql_fetch", counting)
            await client.gql("query { A }", {}, 60_000, token=None)
            await client.gql("query { A }", {}, 60_000, token="T1")
            assert hits["n"] == 2, "auth e anonima non collidono"
            await client.gql("query { A }", {}, 60_000, token="T1")
            assert hits["n"] == 2, "seconda auth servita da cache"
            await client.gql("query { A }", {}, 60_000, token="T2")
            assert hits["n"] == 3, "token diverso → cache diversa"

    async def _nosleep(ms):
        return None

    asyncio.run(main())
