"""Porting e2e di ``tests/setup.test.ts`` — wizard con fake lms bash.

Stessa ricetta del TS: fake lms che logga ``$*`` su file e dorme (con trap TERM
che scrive KILLED ed esce 143 per il cancel), server Python spawnato con env
blindata (LMS_PATH=fake, LMSTUDIO_BASE su porta morta, HOME/CONFIG/DATA tmp,
niente APP_VERSION, fixtures) e ``LLM_BASE_URL`` RIMOSSA — l'ensure deve girare.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import httpx

from app.core import config
from harness import ServerHandle, free_port

MODEL = "prism-ml/Bonsai-27B-gguf"


def _fake_lms(tmp: Path, name: str, body: str) -> str:
    """Fake lms: logga ``$*`` su file (stesso pattern del TS), poi il body dello scenario."""
    calls = tmp / "lms-calls.log"
    script = tmp / name
    script.write_text(
        f'#!/bin/bash\necho "$*" >> {json.dumps(str(calls))}\n{body}\nexit 0\n', encoding="utf-8"
    )
    script.chmod(0o755)
    return str(script)


def _calls(path: Path) -> list[str]:
    try:
        return [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    except FileNotFoundError:
        return []


async def _wait_until(check, deadline_s: float, step: float = 0.2) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if check():
            return True
        await asyncio.sleep(step)
    return False


async def test_setup_flow_fake_lms_status_finish_sequenza_ensure(tmp_path):
    # fake lms: ls lista il modello solo dopo che è stato "get"-ato, load fallisce
    # (veloce, nessun poll HTTP) — identico allo scenario TS
    fake = _fake_lms(
        tmp_path,
        "fake-lms-wizard.sh",
        'if [ "$1" = "ls" ]; then\n'
        f'  if grep -q "^get " {json.dumps(str(tmp_path / "lms-calls.log"))}; then\n'
        "    echo '{\"models\":[{\"key\":\"" + MODEL + "\"}]}';\n"
        "  else\n"
        "    echo '[]';\n"
        "  fi\n"
        "fi\n"
        'if [ "$1" = "load" ]; then exit 1; fi',
    )
    dead_port = free_port()  # bind ephemeral + release = "LM Studio down" (come il TS)

    async with ServerHandle(
        tmp=tmp_path,
        drop=("LLM_BASE_URL",),  # l'ensure deve girare: baseUrl arriva da /setup/finish
        overrides={"LMS_PATH": fake, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{dead_port}/v1"},
    ) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            calls = tmp_path / "lms-calls.log"
            status = (await c.get("/api/setup/status")).json()
            assert status["setupDone"] is False
            assert status["needsSetup"] is True
            assert status["hardware"]["ramGb"] > 0
            assert re.search(r"Qwen3\.6|gemma-4", status["suggested"]["model"], re.IGNORECASE), \
                "suggestion comes from the live catalogue"
            assert status["lms"]["installed"] is True, "fake LMS_PATH must be detected"
            assert status["lms"]["path"] is None, "disclosure-minimal: mai il path del binario"
            assert status["job"]["state"] == "idle"
            # boot-time ensure è no-op finché !setupDone: nessun daemon/server/load prima del wizard
            pre = _calls(calls)
            assert not [l for l in pre if l.startswith(("daemon", "server", "load"))], pre

            bad = await c.post("/api/setup/download", json={"model": "bad name!"})
            assert bad.status_code == 400, "model key must be validated"
            assert bad.json() == {"error": "invalid_model"}

            fin = await c.post("/api/setup/finish", json={"model": MODEL})
            assert fin.status_code == 200
            cfg = config.read_config_file(str(tmp_path / "config.json"))
            assert cfg["setupDone"] is True
            assert cfg["backend"] == "lmstudio"
            assert cfg["baseUrl"] == f"http://127.0.0.1:{dead_port}/v1"
            assert cfg["lmsPath"] == fake
            assert "setupVersion" not in cfg, "senza APP_VERSION il marker non viene scritto"

            # ensure #1 si ferma dopo "ls --json" (modello assente → auto-get nel job
            # singleton); il completamento del download ri-kicka l'ensure (#2) che carica.
            # Ancora sull'ULTIMO "daemon up" (= ensure #2), come il TS.
            expected = [
                "daemon up",
                "server start",
                "ls --json",
                f"load {MODEL} -y --gpu=max --context-length=8192",
            ]
            seq: list[str] = []

            def last_is_load() -> bool:
                lines = _calls(calls)
                seq[:] = lines
                return bool(lines) and lines[-1].startswith("load")

            assert await _wait_until(last_is_load, 30, 0.3), f"sequenza ensure non completata: {_calls(calls)}"
            seq = _calls(calls)
            start = max(i for i, line in enumerate(seq) if line == "daemon up")
            assert seq[start : start + len(expected)] == expected, seq

            assert seq.count(f"get {MODEL} --gguf") == 1, \
                "exactly one download of the model, owned by the job singleton"

            # il load è fallito sul fake → backend deterministamente off (mai "up" fantasma)
            health = (await c.get("/api/health")).json()
            assert health["llm"]["state"] == "off"

            # reset: il wizard riappare, config torna vuota
            reset = await c.post("/api/setup/reset")
            assert reset.status_code == 200
            assert config.read_config_file(str(tmp_path / "config.json")) == {}
            status_after = (await c.get("/api/setup/status")).json()
            assert status_after["setupDone"] is False
            assert status_after["needsSetup"] is True


async def test_cancel_download_non_resuscita_il_job(tmp_path):
    # fake lms: "get" dorme 2s (un download vero ci mette), trap TERM registra il kill
    fake = _fake_lms(
        tmp_path,
        "fake-lms-cancel.sh",
        f'trap "echo KILLED >> {json.dumps(str(tmp_path / "lms-calls.log"))}; exit 143" TERM\n'
        'if [ "$1" = "get" ]; then sleep 2; fi\n'
        'if [ "$1" = "ls" ]; then echo \'{"models":[]}\'; fi',
    )
    calls = tmp_path / "lms-calls.log"

    async with ServerHandle(
        tmp=tmp_path,
        drop=("LLM_BASE_URL",),
        overrides={"LMS_PATH": fake, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1"},
    ) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            dl = await c.post("/api/setup/download", json={"model": MODEL})
            assert dl.status_code == 200
            assert (await c.get("/api/setup/status")).json()["job"]["state"] == "downloading"

            # aspetta che il child sia davvero partito: un TERM prima che bash registri
            # la trap lo uccide in silenzio (commento del TS)
            assert await _wait_until(lambda: "get " in "\n".join(_calls(calls)), 5), "download child must start"

            cancel = await c.post("/api/setup/cancel")
            assert cancel.status_code == 200
            idle = (await c.get("/api/setup/status")).json()["job"]
            assert idle["state"] == "idle", "il job va idle IMMEDIATAMENTE"

            assert await _wait_until(lambda: "KILLED" in "\n".join(_calls(calls)), 6), \
                "cancel must SIGTERM the download child"

            await asyncio.sleep(3.5)  # il child sarebbe ormai uscito
            after = (await c.get("/api/setup/status")).json()["job"]
            assert after["state"] == "idle", "cancelled job must never resurrect to done/error"
            assert after["model"] is None


async def test_ensure_lock_vince_su_force_una_sola_run(tmp_path):
    """Due ensure concorrenti (due /finish quasi simultanei) → UNA sola run():
    il lock vince anche su force — due run spawnerebbero due backend e ne
    perderebbero uno (owned punta all'ultimo child)."""
    # ls lista subito il modello (nessun auto-get), load dorme 1s per tenere il lock
    fake = _fake_lms(
        tmp_path,
        "fake-lms-lock.sh",
        'if [ "$1" = "ls" ]; then echo \'{"models":[{"key":"' + MODEL + '"}]}\' ; fi\n'
        'if [ "$1" = "load" ]; then sleep 1; exit 1; fi',
    )
    calls = tmp_path / "lms-calls.log"

    async with ServerHandle(
        tmp=tmp_path,
        drop=("LLM_BASE_URL",),
        overrides={"LMS_PATH": fake, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1"},
    ) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            first, second = await asyncio.gather(
                c.post("/api/setup/finish", json={"model": MODEL}),
                c.post("/api/setup/finish", json={"model": MODEL}),
            )
            assert first.status_code == 200 and second.status_code == 200
            assert await _wait_until(lambda: bool(_calls(calls)) and _calls(calls)[-1].startswith("load"), 15), _calls(calls)
            await asyncio.sleep(1.0)  # margine: un secondo ensure sbagliato apparirebbe qui
            seq = _calls(calls)
            assert seq.count("daemon up") == 1, seq
            assert seq.count(f"load {MODEL} -y --gpu=max --context-length=8192") == 1, seq


async def test_ensure_throttle_due_health_ravvicinate(tmp_path):
    """ensure è throttled: due /health ravvicinate NON rilanciano run() (finestra
    15s a backend off — la 60s a backend up è lo stesso ramo di codice)."""
    fake = _fake_lms(
        tmp_path,
        "fake-lms-throttle.sh",
        'if [ "$1" = "ls" ]; then echo \'{"models":[{"key":"' + MODEL + '"}]}\' ; fi\n'
        'if [ "$1" = "load" ]; then exit 1; fi',
    )
    calls = tmp_path / "lms-calls.log"

    async with ServerHandle(
        tmp=tmp_path,
        drop=("LLM_BASE_URL",),
        overrides={"LMS_PATH": fake, "LMSTUDIO_BASE_URL": f"http://127.0.0.1:{free_port()}/v1"},
    ) as server:
        async with httpx.AsyncClient(trust_env=False, base_url=server.base, timeout=10.0) as c:
            fin = await c.post("/api/setup/finish", json={"model": MODEL})
            assert fin.status_code == 200
            # ensure #1 (force) completa: attesa della sequenza intera
            assert await _wait_until(lambda: bool(_calls(calls)) and _calls(calls)[-1].startswith("load"), 15), _calls(calls)
            snapshot = _calls(calls)

            h1 = await c.get("/api/health")
            h2 = await c.get("/api/health")
            assert h1.status_code == 200 and h2.status_code == 200
            assert h1.json()["llm"]["state"] == "off"
            await asyncio.sleep(1.0)  # un ensure non-throttled avrebbe scritto qui
            assert _calls(calls) == snapshot, f"throttle violato: {_calls(calls)}"
