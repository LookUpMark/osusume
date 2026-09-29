"""CF v2 — loader artefatto, segnale collaborativo, endpoint /api/cf.

Vincolo fondamentale: senza modello il motore è byte-identico (golden incluso);
con modello sintetico i `final` cambiano ma il payload resta shape-identico.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters import cf
from app.domain import pipeline
from app.domain.scoring import score_all
from app.shared.weights import WEIGHTS
from harness import ServerHandle
from test_llm import make_profile, make_reco


def write_synthetic_model(path, items: list[int], vectors, dim: int = 4) -> None:
    import numpy as np

    padded = np.zeros((len(items), dim), dtype=np.float32)
    for i, v in enumerate(vectors):
        padded[i, : len(v)] = v
    header = {"magic": "osusume-cf", "version": 1, "dim": dim, "count": len(items), "builtAt": "t", "smoke": False}
    hb = (json.dumps(header, separators=(",", ":")) + "\n").encode()
    with open(path, "wb") as f:
        f.write(len(hb).to_bytes(4, "little"))
        f.write(hb)
        f.write(np.asarray(items, dtype=np.int32).tobytes())
        f.write(padded.astype(np.float16).tobytes())


@pytest.fixture
def synthetic_model(tmp_path, monkeypatch):
    path = tmp_path / "cf" / "model.bin"
    path.parent.mkdir(parents=True)
    # 8 titoli: 5 "amati" (vettore ~[1,1,0,0]), 601 vicino, 602 lontano
    write_synthetic_model(
        path,
        [501, 502, 503, 511, 512, 601, 602, 603],
        [
            [1, 1, 0, 0],
            [1, 1, 0, 0],
            [0.9, 1, 0.1, 0],
            [1, 0.9, 0, 0],
            [0.9, 1, 0, 0],
            [0.9, 1, 0, 0],  # 601 vicino all'user-vector
            [0, 0, 1, 1],  # 602 ortogonale
            [1, 0.8, 0.2, 0],
        ],
    )
    monkeypatch.setattr(cf, "model_path", lambda: path)
    monkeypatch.setattr(cf, "_index_cache", None)
    assert cf.load_local()
    yield path
    cf._state.update(state="absent", header=None, ids=None, vectors=None, norms=None, error=None)
    monkeypatch.setattr(cf, "_index_cache", None)


def test_loader_parse_e_state(synthetic_model):
    st = cf.state()
    assert st["state"] == "loaded"
    assert st["count"] == 8
    assert st["enabled"] is True


def test_cf_scores_overlap_e_normalizzazione(synthetic_model):
    scores = cf.cf_scores([601, 602, 603], {501, 502, 503, 511, 512})
    assert set(scores) == {601, 602, 603}
    assert scores[601] > scores[602], "601 vicino all'user-vector deve dominare"
    # coseno clampato 0..1 (niente min-max sul pool: non porta informazione del modello)
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    assert scores[601] <= 1.0


def test_cf_scores_cold_start(synthetic_model):
    assert cf.cf_scores([601, 602], {501}) == {}, "overlap < 5 → segnale spento"


def test_cf_scores_spento_senza_modello(monkeypatch):
    monkeypatch.setattr(cf, "_state", {**cf._state, "state": "absent"})
    assert cf.cf_scores([1, 2, 3], {1, 2, 3, 4, 5}) == {}


def test_score_all_con_cf_cambia_final_senza_cf_identico():
    candidates = [make_reco(601).media, make_reco(602).media]
    profile = make_profile("h")
    base = score_all([m.model_copy() for m in candidates], profile, {}, {}, "en")
    with_cf = score_all([m.model_copy() for m in candidates], profile, {}, {}, "en", cf_scores={601: 1.0, 602: 0.5})
    by_id = {r.media.id: r for r in with_cf}
    base_by = {r.media.id: r for r in base}
    assert by_id[601].final > base_by[601].final
    assert by_id[602].final > base_by[602].final
    assert by_id[601].final > by_id[602].final
    # cap: cf=1.0 pesa esattamente WEIGHTS["cf"] (non oltre cfCap)
    assert round(by_id[601].final - base_by[601].final, 10) == WEIGHTS["cf"]


def test_pipeline_payload_shape_identico_con_cf(monkeypatch):
    """Il CF cambia `final` ma NON il payload: nessuna chiave nuova (contratto)."""
    from app.queries.recommend import result_payload

    reco_a = make_reco(1).media
    reco_b = make_reco(2).media
    payload_senza = result_payload(
        pipeline.RecoResult(profile=make_profile("h"), recos=score_all([reco_a, reco_b], make_profile("h"), {}, {}, "en"), avoided=[])
    )
    con_cf = score_all([make_reco(1).media, make_reco(2).media], make_profile("h"), {}, {}, "en", cf_scores={1: 1.0})
    payload_con = result_payload(pipeline.RecoResult(profile=make_profile("h"), recos=con_cf, avoided=[]))
    assert set(payload_senza["recos"][0].keys()) == set(payload_con["recos"][0].keys())
    assert set(payload_senza["recos"][0]["breakdown"].keys()) == set(payload_con["recos"][0]["breakdown"].keys())


@pytest.mark.asyncio
async def test_cf_endpoints(tmp_path):
    """Server reale con CF_MODEL_URL su porta morta: stato onesto, toggle,
    download fallito = 503 cf_unavailable (veloce: connect refused, niente rete)."""
    async with ServerHandle(overrides={"CF_MODEL_URL": "http://127.0.0.1:1/model.bin"}) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
            res = await c.get("/api/cf")
            assert res.status_code == 200
            body = res.json()
            assert body["state"] in ("absent", "disabled", "error")
            assert body["enabled"] is True

            res = await c.patch("/api/cf", json={"enabled": False})
            assert res.status_code == 200
            assert res.json()["state"] == "disabled"
            res = await c.patch("/api/cf", json={"enabled": True})
            assert res.status_code == 200
            assert res.json()["enabled"] is True

            # force=True bypassa il guard ANILIST_FIXTURES → connect refused → 503
            res = await c.post("/api/cf/download")
            assert res.status_code == 503
            assert res.json() == {"error": "cf_unavailable"}


@pytest.mark.asyncio
async def test_cf_download_e2e_da_fake_url(tmp_path):
    """Il path promesso dal docstring: CF_MODEL_URL → FakeServer che serve un
    artefatto sintetico → download, load, state=loaded con i metadati del header."""
    import struct

    import numpy as np

    from fake_http import FakeServer, Response as FakeResponse

    items = [501, 601, 602]
    vectors = np.eye(3, dtype=np.float16)
    header = {"magic": "osusume-cf", "version": 1, "dim": 3, "count": 3, "builtAt": "t", "smoke": False}
    hb = (json.dumps(header, separators=(",", ":")) + "\n").encode()
    blob = len(hb).to_bytes(4, "little") + hb + np.asarray(items, dtype=np.int32).tobytes() + vectors.tobytes()

    async def handler(req):
        if req.path.endswith("/model.bin"):
            return FakeResponse(raw=blob)
        return FakeResponse({"data": {}})

    async with FakeServer(handler) as srv:
        async with ServerHandle(overrides={"CF_MODEL_URL": f"{srv.url}/model.bin"}) as server:
            async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=15.0) as c:
                res = await c.post("/api/cf/download")
                assert res.status_code == 200, res.text
                body = res.json()
                assert body["state"] == "loaded"
                assert body["count"] == 3
                assert body["enabled"] is True
                # il file è atterrato nel DATA_DIR del server
                assert (server.tmp / "cf" / "model.bin").exists()
