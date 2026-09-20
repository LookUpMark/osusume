"""Spawn del server Python con la STESSA ricetta env di ``tests/golden/record.mjs``.

cwd = radice repo (le fixture sono lette relative a cwd, come il server TS),
tmpdir fresco per cache/config/dati, LLM/LM Studio/OMLX su porta morta,
LMS fake bash, HOME reindirizzata, senza APP_VERSION e senza .env.
Usato da conftest (pytest) e da scripts/golden_actual.py (golden subset).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import tempfile
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
UV = shutil.which("uv") or str(Path.home() / ".local/bin/uv")

READY_DEADLINE_S = 15.0
POLL_S = 0.3

# come record.mjs: nessuna variabile critica ereditata → vincono quelle iniettate qui
_DELETED = [
    "APP_VERSION",
    "ANILIST_ENDPOINT",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_MS",
    "LMSTUDIO_BASE_URL",
    "OMLX_BASE_URL",
    "RATE_PER_MIN",
    # extra lato Python: HOST decide il bind, DIST_DIR decide il static — mai ereditati
    "HOST",
    "DIST_DIR",
]


def free_port() -> int:
    """Bind :0, read the port, release — no fixed-port collisions across runs."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_env(
    tmp: Path,
    port: int,
    fixture_dir: str = "fixtures",
    drop: tuple[str, ...] = (),
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    cache_dir = tmp / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # fake lms (stesso pattern di tests/setup.test.ts): logga e esce 0 — mai un backend vero
    fake_lms = tmp / "fake-lms.sh"
    fake_lms.write_text(
        f'#!/bin/bash\necho "lms-fake $*" >> {json.dumps(str(tmp / "lms-calls.log"))}\nexit 0\n',
        encoding="utf-8",
    )
    fake_lms.chmod(0o755)

    env = {k: v for k, v in os.environ.items() if k not in _DELETED}
    env.update(
        HOME=str(tmp),  # homedir() → tmpdir: ~/.omlx assente → deterministicamente off
        ANILIST_FIXTURES=fixture_dir,  # local mode bloccata on
        ALR_DATA_DIR=str(tmp),
        CACHE_DIR=str(cache_dir),
        CONFIG_PATH=str(tmp / "config.json"),
        LLM_BASE_URL="http://127.0.0.1:1/v1",  # dead → fallback deterministico
        LMS_PATH=str(fake_lms),
        LMSTUDIO_BASE_URL="http://127.0.0.1:1/v1",
        OMLX_BASE_URL="http://127.0.0.1:1/v1",
        PORT=str(port),
    )
    # test setup wizard: niente LLM_BASE_URL (l'ensure deve girare) e fake lms propri
    for key in drop:
        env.pop(key, None)
    env.update(overrides or {})
    return env


class ServerHandle:
    """Server come subprocess reale (ladder di kill inclusa). Usabile come async context."""

    def __init__(
        self,
        tmp: Path | None = None,
        fixture_dir: str = "fixtures",
        drop: tuple[str, ...] = (),
        overrides: dict[str, str] | None = None,
    ) -> None:
        self.tmp = Path(tmp) if tmp else Path(tempfile.mkdtemp(prefix="osusume-py-"))
        self.fixture_dir = fixture_dir
        self.drop = drop
        self.overrides = overrides or {}
        self.port = free_port()
        self.proc: asyncio.subprocess.Process | None = None

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def __aenter__(self) -> "ServerHandle":
        self.proc = await asyncio.create_subprocess_exec(
            UV,
            "run",
            "--project",
            str(BACKEND),
            "python",
            str(BACKEND / "run_dev.py"),
            cwd=REPO_ROOT,  # fixture relative a cwd, come record.mjs
            env=build_env(self.tmp, self.port, self.fixture_dir, self.drop, self.overrides),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # killpg colpisce uv + figli
        )
        await self.wait_ready()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def wait_ready(self, deadline_s: float = READY_DEADLINE_S) -> None:
        assert self.proc is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + deadline_s
        while True:
            if self.proc.returncode is not None:
                out, err = await self.proc.communicate()
                raise RuntimeError(
                    f"server morto durante l'avvio (exit {self.proc.returncode})\n"
                    f"{err.decode(errors='replace')[-2000:]}"
                )
            try:
                async with httpx.AsyncClient(trust_env=False, timeout=2.0) as client:
                    res = await client.get(f"{self.base}/api/health")
                if res.status_code < 500:
                    return
            except httpx.HTTPError:
                pass  # not up yet
            if loop.time() > deadline:
                raise TimeoutError(f"server non partito in {deadline_s}s")
            await asyncio.sleep(POLL_S)

    async def stop(self) -> None:
        """Ladder: SIGTERM (graceful) → killpg SIGTERM → killpg SIGKILL."""
        proc = self.proc
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.communicate(), 5)
            return
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            await asyncio.wait_for(proc.wait(), 5)
            return
        except (ProcessLookupError, asyncio.TimeoutError):
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
