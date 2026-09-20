"""Contratto HTTP (docs/contract.md) — subset P1, e2e su server reale."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.core.middleware import hostname
from harness import ServerHandle

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "tests" / "golden" / "fixtures"


def golden_body(name: str):
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))["body"]


async def test_health_shape_identico_al_golden(client: httpx.AsyncClient):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert res.json() == golden_body("health-pre")


async def test_host_fuori_allowlist_403(server):
    async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
        res = await c.get("/api/health", headers={"Host": "evil.com"})
    assert res.status_code == 403
    assert res.json() == {"error": "forbidden"}


async def test_host_semantica_regex_ts(server):
    # casistiche verificate su node con la regex di src/server/api.ts:
    #   host.replace(/:\d+$/, "").replace(/^\[|\]$/g, "")
    async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
        # "::1" senza porta: la regex porta via ":1" → ":" → fuori allowlist (403)
        assert (await c.get("/api/health", headers={"Host": "::1"})).status_code == 403
        # ":" finale senza cifre: la regex non matcha → host con ":" → 403
        assert (await c.get("/api/health", headers={"Host": "127.0.0.1:"})).status_code == 403
        # "::1:3000": la regex matcha solo le cifre finali → "::1" → 200
        assert (await c.get("/api/health", headers={"Host": "::1:3000"})).status_code == 200
        assert (await c.get("/api/health", headers={"Host": "[::1]:8000"})).status_code == 200
        assert (await c.get("/api/health", headers={"Host": "localhost:9999"})).status_code == 200


async def test_host_guard_solo_su_api(server):
    # il guard copre /api e /api/* (come api.use("*") sul router), NON /apifoo
    async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
        res = await c.get("/apifoo", headers={"Host": "evil.com"})
    assert res.status_code != 403


@pytest.mark.parametrize(
    "header,expected",
    [
        ("::1", ":"),  # la regex mangia ":1"
        ("127.0.0.1:", "127.0.0.1:"),  # ":" senza cifre: nessuno strip
        ("::1:3000", "::1"),
        ("[::1]:8000", "::1"),
        ("1:2:3", "1:2"),
        ("evil.com", "evil.com"),
        ("", ""),
        ("[::1]", "::1"),
    ],
)
def test_hostname_uguale_a_regex_ts(header, expected):
    assert hostname(header) == expected


async def test_local_mode_off_aggiorna_lo_stato(client: httpx.AsyncClient):
    res = await client.post("/api/local-mode", json={"auto": False})
    assert res.status_code == 200
    assert res.json() == golden_body("localmode-off")
    health = (await client.get("/api/health")).json()
    assert health["local"] == {"on": True, "available": True, "auto": False}


async def test_local_mode_auto_non_bool_400(client: httpx.AsyncClient):
    for bad in ("yes", 1, None):
        res = await client.post("/api/local-mode", json={"auto": bad})
        assert res.status_code == 400
        assert res.json() == {"error": "invalid_request"}


async def test_local_mode_body_non_json_400(client: httpx.AsyncClient):
    res = await client.post(
        "/api/local-mode",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 400
    assert res.json() == {"error": "invalid_request"}


async def test_local_mode_local_non_bool_400(client: httpx.AsyncClient):
    # in TS un `local` di tipo strano è ignorato (200): il port è strict → 400,
    # niente {"local":0} che scatenerebbe un retry-live fantasma
    for bad in (0, "x", {"a": 1}):
        res = await client.post("/api/local-mode", json={"auto": True, "local": bad})
        assert res.status_code == 400
        assert res.json() == {"error": "invalid_request"}
    # lo stato non è stato toccato dai tentativi falliti
    assert (await client.get("/api/health")).json()["local"]["auto"] is True


async def test_local_mode_retry_live(client: httpx.AsyncClient):
    res = await client.post("/api/local-mode", json={"auto": True, "local": False})
    assert res.status_code == 200
    assert res.json() == golden_body("localmode-retry-live")


async def test_config_solo_modello(client: httpx.AsyncClient):
    res = await client.get("/api/config")
    assert res.status_code == 200
    assert res.json() == golden_body("config")


async def test_app_update_senza_versione_niente_rete(client: httpx.AsyncClient):
    res = await client.get("/api/app-update")
    assert res.status_code == 200
    assert res.json() == golden_body("app-update")
    # ?fresh=1 non cambia nulla senza APP_VERSION: short-circuit prima di GitHub
    fresh = await client.get("/api/app-update", params={"fresh": "1"})
    assert fresh.json() == res.json()


async def test_shutdown_termina_il_processo_con_exit_0(tmp_path):
    async with ServerHandle(tmp_path) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            res = await c.post("/api/shutdown")
        assert res.status_code == 200
        assert res.json() == {"ok": True}
        # la risposta è già partita: il processo esce da solo, graceful, entro 5s
        await asyncio.wait_for(server.proc.communicate(), 5)
    assert server.proc.returncode == 0


async def test_route_api_sconosciuta_404_codice(client: httpx.AsyncClient):
    res = await client.get("/api/unknown")
    assert res.status_code == 404
    assert res.json() == {"error": "not_found"}
