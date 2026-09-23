"""Porting 1:1 di ``src/server/setup.ts`` (P5) — hardware, catalogo modelli, job
download singleton, ensure/auto-start del backend LLM, route ``/api/setup/*``.

Ogni sezione cita la riga del TS d'origine. Deviazioni richieste dal runtime
Python (documentate, il resto è riga-per-riga):

- hardware: ``cpus()[0].model`` non ha equivalente stdlib → su mac il chip arriva
  da ``sysctl -n machdep.cpu.brand_string`` (stesso valore che espone Node),
  altrove ``platform.processor()``; ``ramGb`` = ``SC_PAGE_SIZE × SC_PHYS_PAGES``
  (≈ ``os.totalmem()``), arrotondato come ``Math.round``.
- spawnSync (PATH probe di ``resolveLms`` + re-check Rosetta): restano chiamate
  sync con ``timeout=3`` — raggiunte solo quando LMS_PATH/config/default mancano
  o su mac x64, mai nel percorso dei golden e2e. Tutto il resto (runLms, download,
  ensure) è asyncio: nessun blocco dell'event loop.
- ``cleanupOnExit``: ``atexit`` — uvicorn possiede i signal handler e sovrascriverli
  spezzerebbe lo shutdown graceful; la via rapida resta ``POST /api/shutdown``.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import platform
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.adapters.llm.setup import (
    llm_auth_headers,
    log_llm,
    omlx_auth_headers,
    read_omlx_port,
)
from app.core import config

# --- model catalogue (setup.ts righe 28-41) ---------------------------------------
# Two tiers: Qwen3.6-35B-A3B needs ~19.5 GB of weights → 32 GB unified memory
# minimum; Gemma 4 12B 4bit covers everything below.

MODELS = {
    "qwen36": {
        "gguf": {"model": "lmstudio-community/Qwen3.6-35B-A3B-GGUF", "sizeGb": 21.5},
        "mlx": {"model": "mlx-community/Qwen3.6-35B-A3B-4bit", "sizeGb": 19.5},
        "mlxLms": {"model": "lmstudio-community/Qwen3.6-35B-A3B-MLX-4bit", "sizeGb": 19.5},
        "ollama": "hf.co/lmstudio-community/Qwen3.6-35B-A3B-GGUF:Q4_K_M",
    },
    "gemma4": {
        "gguf": {"model": "unsloth/gemma-4-12b-it-GGUF", "sizeGb": 8.1},
        "mlx": {"model": "mlx-community/gemma-4-12B-it-4bit", "sizeGb": 6.3},
        "mlxLms": {"model": "lmstudio-community/gemma-4-12B-it-MLX-4bit", "sizeGb": 7.9},
        "ollama": "hf.co/unsloth/gemma-4-12b-it-GGUF:Q4_K_M",
    },
}
RAM_TRESHOLD_GB = 32  # (sic) typo del TS conservato

# overridable so tests (and port-conflicted setups) can point elsewhere (setup.ts 44)
LMSTUDIO_BASE_DEFAULT = "http://127.0.0.1:1234/v1"


def lmstudio_base() -> str:
    return os.environ.get("LMSTUDIO_BASE_URL") or LMSTUDIO_BASE_DEFAULT


# --- hardware (setup.ts righe 50-60) -----------------------------------------------


def _mac_brand() -> str:
    """``machdep.cpu.brand_string`` (≈ ``cpus()[0].model`` su macOS) o ``""``."""
    try:
        return subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except Exception:
        return ""


def detect_hardware() -> dict:
    system = platform.system()
    os_name = "mac" if system == "Darwin" else "win" if system == "Windows" else "linux"
    brand = _mac_brand() if os_name == "mac" else ""
    apple_silicon = os_name == "mac" and platform.machine() == "arm64"
    if os_name == "mac" and not apple_silicon:
        # Rosetta caveat: node may report x64 on Apple Silicon
        apple_silicon = "Apple" in brand
    chip = brand or (platform.processor() or "").strip()
    ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30)
    return {"os": os_name, "chip": chip or "Unknown CPU", "ramGb": ram_gb, "appleSilicon": apple_silicon}


def suggest_model(hw: dict) -> dict:
    """``suggestModel`` (setup.ts righe 62-77): tier da RAM, pack MLX solo Apple."""
    tier = MODELS["qwen36"] if hw["ramGb"] >= RAM_TRESHOLD_GB else MODELS["gemma4"]
    return {
        "model": tier["gguf"]["model"],
        "sizeGb": tier["gguf"]["sizeGb"],
        "mlx": tier["mlx"] if hw["appleSilicon"] else None,
        "mlxLms": tier["mlxLms"] if hw["appleSilicon"] else None,
    }


def needs_setup_version(cfg: dict, version: str | None = None) -> bool:
    """``needsSetupVersion`` (setup.ts righe 81-83): packaged app only — a version
    mismatch reopens the wizard; in dev (no APP_VERSION) only setupDone decides."""
    v = config.APP_VERSION if version is None else version
    return bool(v) and cfg.get("setupVersion") != v


# --- oMLX / lms resolution (setup.ts righe 87-175) ----------------------------------


def _home(*parts: str) -> str:
    return os.path.join(os.path.expanduser("~"), *parts)


def omlx_base() -> str:
    """``OMLX_BASE`` (setup.ts righe 99): env > porta letta da settings.json > 8080.
    Calcolato a runtime: HOME/env possono cambiare tra test e server."""
    return os.environ.get("OMLX_BASE_URL") or f"http://127.0.0.1:{read_omlx_port() or '8080'}/v1"


def resolve_omlx() -> str | None:
    if os.environ.get("OMLX_BIN"):
        return os.environ["OMLX_BIN"]
    default = _home(".omlx", "bin", "omlx")
    return default if os.path.exists(default) else None


def local_omlx_models() -> list[str]:
    """``localOmlxModels`` (setup.ts righe 119-141): una dir-modello reale ha un
    config.json — bare (<model>/) o org-nested (<org>/<model>/)."""
    try:
        models_dir = _home(".omlx", "models")

        def has_config(p: str) -> bool:
            return os.path.exists(os.path.join(p, "config.json"))

        out: list[str] = []
        for name in sorted(os.listdir(models_dir)):
            p = os.path.join(models_dir, name)
            if not os.path.isdir(p):
                continue
            if has_config(p):
                out.append(name)
                continue
            try:
                out.extend(
                    sub
                    for sub in sorted(os.listdir(p))
                    if os.path.isdir(os.path.join(p, sub)) and has_config(os.path.join(p, sub))
                )
            except Exception:
                pass
        return out
    except Exception:
        return []


async def omlx_models(server_up: bool) -> list[str]:
    """``omlxModels`` (setup.ts righe 143-157): lista live dal server, directory scan al fallback."""
    if not server_up:
        return local_omlx_models()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await asyncio.wait_for(
                client.get(f"{omlx_base()}/models", headers=omlx_auth_headers()), 3.0
            )
        if not (200 <= res.status_code < 300):
            return local_omlx_models()
        ids = (m.get("id") or "" for m in res.json().get("data") or [])
        return [i for i in ids if i]
    except Exception:
        return local_omlx_models()


def resolve_lms() -> str | None:
    """``resolveLms`` (setup.ts righe 167-175): LMS_PATH > config.lmsPath > default
    piattaforma se esiste > ``lms --version`` sul PATH (spawnSync 3s)."""
    if os.environ.get("LMS_PATH"):
        return os.environ["LMS_PATH"]
    lms_path = config.read_config_file().get("lmsPath")
    if isinstance(lms_path, str) and lms_path and os.path.exists(lms_path):
        return lms_path
    default = _home(".lmstudio", "bin", "lms.exe" if platform.system() == "Windows" else "lms")
    if os.path.exists(default):
        return default
    try:
        probe = subprocess.run(["lms", "--version"], capture_output=True, timeout=3)
        return "lms" if probe.returncode == 0 else None
    except Exception:
        return None


# --- process helpers (setup.ts righe 190-274) ---------------------------------------

GB = 2**30

# riferimenti FORTI ai task fire-and-forget: asyncio non tiene i task vivi da solo
# (stesso pattern di routes.py) — un download GC-ato a metà lascerebbe il job
# "downloading" per sempre
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    """``void (async …)()`` del TS: fire-and-forget con riferimento forte."""
    task = asyncio.get_running_loop().create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def http_ok(url: str, timeout_ms: int, headers: dict[str, str] | None = None) -> bool:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await asyncio.wait_for(client.get(url, headers=headers or {}), timeout_ms / 1000)
        return 200 <= res.status_code < 300
    except Exception:
        return False


@dataclass
class RunResult:
    code: int | None
    stdout: str
    stderr: str


async def run_lms(
    lms: str,
    args: list[str],
    timeout_ms: int = 60_000,
    on_spawn=None,
) -> RunResult:
    """``runLms`` (setup.ts righe 231-274): spawn array-args (no shell), output
    raccolto e feedato al job, mai eccezioni — il chiamante decide sul codice.
    Timeout: SIGTERM, SIGKILL a +5s, settle forzato a +15s."""
    log_llm(f"$ {lms} {' '.join(args)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            lms,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:  # spawn error → stderr += message
        log_llm(f"spawn error: {e}")
        return RunResult(-1, "", str(e))
    if on_spawn:
        on_spawn(proc)
    out_parts: list[str] = []
    err_parts: list[str] = []

    async def drain(stream, sink: list[str]) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            text = chunk.decode(errors="replace")
            sink.append(text)
            job_feed(text)

    async def reap() -> int | None:
        assert proc.stdout is not None and proc.stderr is not None
        await asyncio.gather(drain(proc.stdout, out_parts), drain(proc.stderr, err_parts))
        return await proc.wait()

    # task creato UNA volta: wait_for non lo cancella (shield) tra i gradini della ladder
    task = asyncio.create_task(reap())
    try:
        code = await asyncio.wait_for(asyncio.shield(task), timeout_ms / 1000)
    except asyncio.TimeoutError:
        log_llm(f"timeout dopo {timeout_ms}ms — SIGTERM")
        _terminate(proc)
        try:
            code = await asyncio.wait_for(asyncio.shield(task), 5)
        except asyncio.TimeoutError:
            log_llm("SIGTERM ignorato — SIGKILL")
            _kill(proc)
            try:
                code = await asyncio.wait_for(asyncio.shield(task), 10)
            except asyncio.TimeoutError:
                code = -1  # last resort: the promise must settle
    return RunResult(code, "".join(out_parts), "".join(err_parts))


def _terminate(proc) -> None:
    try:
        proc.terminate()
    except ProcessLookupError:
        pass


def _kill(proc) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass


# --- download / install job (singleton) (setup.ts righe 278-466) --------------------


@dataclass
class SetupJob:
    state: str = "idle"  # idle | installing-cli | downloading | done | error
    model: str | None = None
    log_tail: str = ""
    error: str | None = None
    bytes_done: int | None = None
    total_bytes: int | None = None

    def payload(self) -> dict:
        """Chiavi optional del contratto OMESSE quando assenti (come JSON.stringify)."""
        out = {"state": self.state, "model": self.model, "logTail": self.log_tail}
        if self.error is not None:
            out["error"] = self.error
        if self.bytes_done is not None:
            out["bytesDone"] = self.bytes_done
        if self.total_bytes is not None:
            out["totalBytes"] = self.total_bytes
        return out


class SetupError(Exception):
    """Errore classificato del wizard: il codice è il body ``{"error": code}``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_job = SetupJob()
_job_gen = 0  # generation token: nessun writer superato può resuscitare un job
_dl_child: asyncio.subprocess.Process | None = None
_dl_abort: asyncio.Event | None = None
_ls_cache: dict | None = None  # {"at": monotonic, "models": [...]} stale-while-revalidate


def job_active() -> bool:
    return _job.state in ("downloading", "installing-cli")


def job_payload() -> dict:
    return _job.payload()


def job_feed(text: str) -> None:
    """Feed the wizard's log view; ring buffer keeps the last ~2000 chars."""
    if not job_active():
        return
    _job.log_tail = (_job.log_tail + text)[-2000:]


# model keys are HF-style org/repo; require it to start alphanumeric (no ".."-leading tricks)
MODEL_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _set_dl_child(child) -> None:
    global _dl_child
    _dl_child = child


def start_download(model: str) -> None:
    """``startDownload`` (setup.ts righe 307-331)."""
    global _job, _job_gen
    if job_active():
        raise SetupError("busy")
    if not isinstance(model, str) or not MODEL_KEY_RE.match(model):
        raise SetupError("invalid_model")
    lms = resolve_lms()
    if not lms:
        raise SetupError("lms_missing")
    _job_gen += 1
    gen = _job_gen
    _job = SetupJob(state="downloading", model=model)
    # --gguf/--mlx flag: disambiguazione difensiva tra varianti repo (case-insensitive)
    flag = "--mlx" if re.search(r"-mlx", model, re.IGNORECASE) else "--gguf"

    async def run() -> None:
        global _job, _dl_child, _ls_cache
        result = await run_lms(lms, ["get", model, flag], 60 * 60 * 1000, on_spawn=_set_dl_child)
        _set_dl_child(None)
        if gen != _job_gen:
            return  # cancelled or superseded — never resurrect the job
        if result.code == 0:
            _ls_cache = None
            _job = SetupJob(state="done", model=model, log_tail=_job.log_tail)
            ensure_llm_server(True)  # auto-get path: pick up the new model now
        else:
            log_llm(f"download fallito: {result.stderr[-500:]}")
            _job = SetupJob(
                state="error",
                model=model,
                log_tail=_job.log_tail,
                error=result.stderr[-300:] or f"exit {result.code}",
            )

    _spawn(run())


def install_cli() -> None:
    """``installCli`` (setup.ts righe 334-349): stringhe FISSE, mai interpolate."""
    global _job, _job_gen
    if job_active():
        raise SetupError("busy")
    os_name = detect_hardware()["os"]
    _job_gen += 1
    gen = _job_gen
    if os_name == "win":
        _job = SetupJob(state="installing-cli")
        _spawn(_install(gen, ["powershell", "-NoProfile", "-Command", "irm https://lmstudio.ai/install.ps1 | iex"]))
    elif os_name == "mac":
        _job = SetupJob(state="installing-cli")
        _spawn(_install(gen, ["bash", "-c", "curl -fsSL https://lmstudio.ai/install.sh | bash"]))
    else:
        _job = SetupJob(state="error", error="unsupported OS — try: npx lmstudio install-cli")


async def _install(gen: int, cmd: list[str]) -> None:
    """``runInstall`` (setup.ts righe 351-376): 10 min poi hard stop (il job singleton
    non deve mai rimanere incastrato)."""
    done = False

    def finish(state: str, error: str | None = None) -> None:
        nonlocal done
        if done or gen != _job_gen:
            return  # superseded (cancel/reset) — never resurrect
        done = True
        global _job
        _job = SetupJob(state=state, log_tail=_job.log_tail, error=error)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        finish("error", str(e))
        return

    async def feed(stream) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            job_feed(chunk.decode(errors="replace"))

    async def close_code() -> int | None:
        assert proc.stdout is not None and proc.stderr is not None
        await asyncio.gather(feed(proc.stdout), feed(proc.stderr))
        return await proc.wait()

    task = asyncio.create_task(close_code())
    try:
        code = await asyncio.wait_for(asyncio.shield(task), 600)
    except asyncio.TimeoutError:
        _terminate(proc)
        loop = asyncio.get_running_loop()
        loop.call_later(5, lambda: _kill(proc))
        try:
            code = await asyncio.wait_for(asyncio.shield(task), 6.5)
        except asyncio.TimeoutError:
            finish("error", "installer timed out (10 min)")
            return
    if code == 0:
        finish("done")
    else:
        finish("error", f"exit {code}")


# --- catalogue MLX packs download into oMLX (setup.ts righe 384-453) ----------------

OMLX_DOWNLOADABLE = {
    "mlx-community/Qwen3.6-35B-A3B-4bit": 19.5,
    "mlx-community/gemma-4-12B-it-4bit": 6.3,
}


class _Aborted(Exception):
    """Fetch annullato (cancel) — job torna 'idle' SENZA error, come AbortError."""


def start_omlx_download(repo: str) -> None:
    """``startOmlxDownload`` (setup.ts righe 392-453): whitelist chiusa, streaming HF
    con progress; NESSUN timeout sui fetch (unico stop = cancel)."""
    global _job, _job_gen, _dl_abort
    if job_active():
        raise SetupError("busy")
    if repo not in OMLX_DOWNLOADABLE:
        raise SetupError("unsupported_repo")
    _job_gen += 1
    gen = _job_gen
    _job = SetupJob(
        state="downloading",
        model=repo,
        log_tail=f"resolving {repo} file list…\n",
        bytes_done=0,
        total_bytes=round(OMLX_DOWNLOADABLE[repo] * GB),
    )
    cancel = asyncio.Event()
    _dl_abort = cancel
    _spawn(_omlx_download(gen, repo, cancel))


async def _omlx_download(gen: int, repo: str, cancel: asyncio.Event) -> None:
    global _job, _ls_cache

    async def aborted() -> bool:
        return cancel.is_set() or gen != _job_gen

    try:
        # i fetch TS qui NON hanno AbortSignal.timeout: non scadono MAI (unico stop =
        # cancel) → timeout=None esplicito (il default httpx di 5s troncherebbe un
        # download di GB). Gli ALTRI client (AniList/LLM/probe) hanno i loro timeout.
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            meta = await client.get(f"https://huggingface.co/api/models/{repo}")
            if meta.status_code >= 300:
                raise RuntimeError(f"HF API {meta.status_code}")
            names = [
                s.get("rfilename") or ""
                for s in (meta.json().get("siblings") or [])
                if isinstance(s, dict)
            ]
            files = [f for f in names if f and not f.startswith(".") and "/" not in f]
            # exact total from HEAD content-lengths → real progress percentage
            total = 0
            for f in files:
                head = await client.head(f"https://huggingface.co/{repo}/resolve/main/{f}")
                total += int(head.headers.get("content-length") or 0)
            # oMLX discovery layout: models/<org>/<model>/ with config.json inside
            org, _, name = repo.partition("/")
            dest = _home(".omlx", "models", org, name)
            os.makedirs(dest, exist_ok=True)
            for f in files:
                if await aborted():
                    raise _Aborted()
                # parity TS (setup.ts 426): scritto sul job CORRENTE senza guard
                # jobActive() — dopo un cancel finisce nel job idle nuovo, same wart
                _job.log_tail = (_job.log_tail + f"↓ {f}\n")[-2000:]
                async with client.stream("GET", f"https://huggingface.co/{repo}/resolve/main/{f}") as res:
                    if res.status_code >= 300:
                        raise RuntimeError(f"{f}: HTTP {res.status_code}")
                    with open(os.path.join(dest, f), "wb") as fh:
                        async for chunk in res.aiter_bytes():
                            if await aborted():
                                raise _Aborted()
                            _job.bytes_done = (_job.bytes_done or 0) + len(chunk)
                            fh.write(chunk)
        if gen != _job_gen:
            return  # cancelled or superseded
        _ls_cache = None
        _job = SetupJob(state="done", model=repo, log_tail=_job.log_tail, bytes_done=total, total_bytes=total)
    except _Aborted:
        if gen != _job_gen:
            return  # cancelled or superseded — never resurrect the job
        _job = SetupJob(
            state="idle",
            model=repo,
            log_tail=_job.log_tail,
            bytes_done=_job.bytes_done,
            total_bytes=_job.total_bytes,
        )
    except Exception as e:
        if gen != _job_gen:
            return  # cancelled or superseded — never resurrect the job
        _job = SetupJob(
            state="error",
            model=repo,
            log_tail=_job.log_tail,
            error=str(e)[:300],
            bytes_done=_job.bytes_done,
            total_bytes=_job.total_bytes,
        )


def cancel_job() -> None:
    """``cancelJob`` (setup.ts righe 455-466): la generazione avanza → i writer in
    volo diventano stantii; SIGTERM al child lms, SIGKILL a +5s."""
    global _job_gen, _dl_abort, _dl_child, _job
    _job_gen += 1
    if _dl_abort is not None:
        _dl_abort.set()
        _dl_abort = None
    child, _dl_child = _dl_child, None
    if child is not None:

        def hard() -> None:
            _kill(child)

        asyncio.get_running_loop().call_later(5, hard)
        _terminate(child)
    if job_active():
        _job = SetupJob()


# --- auto-config on every app start (setup.ts righe 470-576) -------------------------

backend_state = "off"  # "up" | "starting" | "off"
_ensure_task: asyncio.Task | None = None
# servers this app process started: torn down on app exit (open-with-app, close-with-app)
_owned: dict | None = None  # {"kind": "omlx", "child": Popen} | {"kind": "lmstudio"}
_last_ensure = 0.0


def llm_backend_state() -> str:
    return backend_state


def _kill_omlx_tree(child: subprocess.Popen) -> None:
    """Kill the wrapper AND the omlx-server it spawned: the wrapper runs detached
    (own process group), so a negative pid reaches the whole tree — and only OUR
    instance (setup.ts righe 480-486)."""
    try:
        os.killpg(os.getpgid(child.pid), signal.SIGTERM)
    except Exception:
        try:
            child.terminate()
        except ProcessLookupError:
            pass


def shutdown_backend() -> None:
    """``shutdownBackend`` (setup.ts righe 491-501): stop del backend owned, anche via
    POST /api/shutdown (su Windows SIGTERM non esegue gli exit handler)."""
    global _owned
    if _owned is None:
        return
    log_llm(f"app in chiusura — arresto backend {_owned['kind']}")
    if _owned["kind"] == "omlx":
        _kill_omlx_tree(_owned["child"])
        _close_owned_log(_owned)
    else:
        lms = resolve_lms()
        if lms:
            try:
                subprocess.run([lms, "server", "stop"], capture_output=True, timeout=10)
            except Exception:
                pass
    _owned = None


def _close_owned_log(owned: dict) -> None:
    logf = owned.get("logf")
    if logf is not None:
        try:
            logf.close()
        except Exception:
            pass  # already closed


def cleanup_on_exit() -> None:
    """``cleanupOnExit`` (setup.ts righe 504-513): il backend LLM vive e muore con
    l'app. Deviazione: atexit (uvicorn possiede i signal handler)."""
    atexit.register(shutdown_backend)


def _match_tier(models: list[str]) -> str:
    for m in models:
        if re.search(r"qwen3\.6|gemma-?4", m, re.IGNORECASE):
            return m
    return models[0]


async def auto_pick_backend() -> dict | None:
    """``autoPickBackend`` (setup.ts righe 522-537): solo motori già su disco —
    le installazioni fresche passano dal wizard."""
    if resolve_omlx():
        models = await omlx_models(False)  # server not up yet → directory scan
        if models:
            return {"backend": "omlx", "model": _match_tier(models), "baseUrl": omlx_base()}
    lms = resolve_lms()
    if lms:
        try:
            models = await downloaded_models(lms)
        except Exception:
            models = []
        if models:
            return {"backend": "lmstudio", "model": _match_tier(models), "baseUrl": lmstudio_base()}
    return None


def ensure_llm_server(force: bool = False) -> None:
    """``ensureLlmServer`` (setup.ts righe 544-576): fire-and-forget, short-circuit
    NELL'ORDINE — env custom → wizard non finito → backend escluso → model mancante →
    lock (vince su force) → throttle."""
    global _last_ensure, _ensure_task, backend_state
    if config.has_custom_env():
        return  # env LLM_BASE_URL wins everywhere — hands off
    cfg = config.read_config_file()
    if not cfg.get("setupDone"):
        return  # wizard not finished — never probe/persist behind it
    if cfg.get("backend") in ("skipped", "custom"):
        return  # explicit user choice
    configured = cfg.get("backend") in ("lmstudio", "omlx")
    if configured and not cfg.get("model"):
        return
    # the lock wins over force: two concurrent run() spawn two backends and leak one
    if _ensure_task is not None and not _ensure_task.done():
        return
    now = time.monotonic()
    if not force and now - _last_ensure < (60.0 if backend_state == "up" else 15.0):
        return
    _last_ensure = now  # ponytail: time-based retry throttle, no backoff table
    backend_state = "starting"
    _ensure_task = asyncio.get_running_loop().create_task(_ensure(configured))


async def _ensure(configured: bool) -> None:
    global backend_state, _ensure_task
    try:
        if not configured:
            pick = await auto_pick_backend()
            if not pick:
                backend_state = "off"  # no engine on this machine — wizard's job
                return
            config.update_config(pick)  # persist so the next boot skips the probe
        await _run()
    except Exception as e:
        log_llm(f"ensure fallito: {e}")
        backend_state = "off"
    finally:
        _ensure_task = None


async def _run() -> None:
    """``run`` (setup.ts righe 578-716)."""
    global backend_state
    cfg = config.read_config_file()
    # `cfg.baseUrl ?? LMSTUDIO_BASE` (?? del TS: "" resta "")
    base = cfg["baseUrl"] if cfg.get("baseUrl") is not None else lmstudio_base()
    # generous probe: a server busy generating answers /models slowly — a miss
    # here spawns a second backend on the same port
    if await http_ok(f"{base}/models", 4000, llm_auth_headers()):
        backend_state = "up"
        return
    if cfg.get("backend") == "omlx":
        await _run_omlx(cfg, base)
        return
    await _run_lmstudio(cfg, base)


async def _run_lmstudio(cfg: dict, base: str) -> None:
    global backend_state, _owned
    lms = resolve_lms()
    if not lms:
        log_llm("lms non trovato — backend LLM non avviato")
        backend_state = "off"
        return
    daemon = await run_lms(lms, ["daemon", "up"], 30_000)
    if daemon.code != 0:
        log_llm(f"daemon up: exit {daemon.code} — {daemon.stderr[-200:]}")
    server = await run_lms(lms, ["server", "start"], 30_000)
    if server.code != 0:
        log_llm(f"server start: exit {server.code} — {server.stderr[-200:]} (porta occupata?)")
        backend_state = "off"
        return
    _owned = {"kind": "lmstudio"}  # we started it → we stop it on app exit
    ls = await run_lms(lms, ["ls", "--json"], 30_000)
    installed = False
    try:
        parsed = json.loads(ls.stdout)
        installed = any(
            _key_or_path(m) == cfg.get("model") for m in (parsed.get("models") or [])
        )
    except Exception:
        pass  # unparseable output — treat as absent
    if not installed:
        if job_active():
            log_llm("un download del wizard è già in corso — salto l'auto-get")
            backend_state = "off"
            return
        # route the auto-get through the download job singleton: one owner, the
        # wizard shows real progress, completion re-kicks ensure (startDownload)
        log_llm(f"modello {cfg.get('model')} assente — lo scarico (può volerci molto)")
        try:
            start_download(cfg["model"])
        except Exception as e:
            log_llm(f"auto-get non partito: {e}")
        backend_state = "off"
        return
    load = await run_lms(lms, ["load", cfg["model"], "-y", "--gpu=max", "--context-length=8192"], 180_000)
    if load.code != 0:
        # a 200 on /v1/models means nothing if the model failed to load — stay off
        log_llm(f"load: exit {load.code} — {load.stderr[-200:]}")
        backend_state = "off"
        return
    for _ in range(10):
        if await http_ok(f"{base}/models", 2000):
            break
        await asyncio.sleep(2)
    backend_state = "up" if await http_ok(f"{base}/models", 2000) else "off"
    log_llm(f"backend: {backend_state}")


async def _run_omlx(cfg: dict, base: str) -> None:
    global backend_state, _owned
    omlx = resolve_omlx()
    if not omlx:
        log_llm("omlx non trovato — backend LLM non avviato")
        backend_state = "off"
        return
    # TS `new URL(base).port || "8080"`: per "http://host:80" il TS normalizza port
    # a "" → 8080; urlparse invece restituisce 80. Deviazione favorevole, solo sulla
    # porta default esplicita nel baseUrl (comportamento invariato per tutti gli altri).
    port = urlparse(base).port or 8080

    def spawn_serve() -> None:
        global _owned, backend_state
        log_llm(f"avvio omlx serve sulla porta {port}")
        try:
            logf = open(os.path.join(config.DATA_DIR, "llm.log"), "a")
        except Exception as e:
            log_llm(f"omlx serve spawn error: {e}")
            backend_state = "off"
            return
        try:
            # detached: own process group → _kill_omlx_tree reaches wrapper + omlx-server
            child = subprocess.Popen(
                [omlx, "serve", "--host", "127.0.0.1", "--port", str(port)],
                stdin=subprocess.DEVNULL,
                stdout=logf,
                stderr=logf,
                start_new_session=True,
            )
        except Exception as e:
            log_llm(f"omlx serve spawn error: {e}")
            backend_state = "off"
            logf.close()
            return
        _owned = {"kind": "omlx", "child": child, "logf": logf}

    async def model_visible() -> bool:
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                res = await asyncio.wait_for(client.get(f"{base}/models", headers=omlx_auth_headers()), 3.0)
            if not (200 <= res.status_code < 300):
                return False
            ids = [m.get("id") for m in res.json().get("data") or []]
        except Exception:
            return False
        # oMLX serves bare names while the wizard may persist an org/repo id:
        # tolerate both spellings or the backend stays permanently "off"
        model = cfg.get("model")
        leaf = model.split("/")[-1] if isinstance(model, str) and model else None
        return any(m == model or (leaf is not None and m == leaf) for m in ids)

    if not await http_ok(f"{base}/models", 4000, omlx_auth_headers()):
        spawn_serve()
        for _ in range(60):
            if await http_ok(f"{base}/models", 2000, omlx_auth_headers()):
                break
            await asyncio.sleep(2)
    # oMLX scans models only at boot: a model downloaded while it was running is
    # invisible until a restart — rescan and restart when needed (one retry first:
    # killing a busy server mid-generation is exactly the bug we don't want)
    first = await model_visible()
    if not first:
        await asyncio.sleep(5)
    if not first and not await model_visible():
        log_llm(f"oMLX non vede {cfg.get('model')} — riavvio del server per rescan")
        owned = _owned
        if owned is not None and owned.get("kind") == "omlx":
            _kill_omlx_tree(owned["child"])  # whole group: the old server must free the port
            _close_owned_log(owned)
            _owned = None
            for _ in range(30):
                if not await http_ok(f"{base}/models", 1000, omlx_auth_headers()):
                    break
                await asyncio.sleep(1)
            spawn_serve()
            for _ in range(60):
                if await http_ok(f"{base}/models", 2000, omlx_auth_headers()):
                    break
                await asyncio.sleep(2)
        else:
            log_llm("server oMLX esterno all'app: serve un riavvio manuale per vedere i modelli nuovi")
    backend_state = "up" if await model_visible() else "off"
    log_llm(f"backend omlx: {backend_state}")


# --- downloaded models (memoized) (setup.ts righe 720-747) --------------------------


def _key_or_path(m: dict) -> str | None:
    """``m.key ?? m.path`` (?? del TS: "" NON cade sul fallback)."""
    key = m.get("key")
    return key if key is not None else m.get("path")


async def _refresh_ls(lms: str) -> None:
    global _ls_cache
    ls = await run_lms(lms, ["ls", "--json"], 15_000)
    if ls.code != 0:
        return  # keep serving whatever we had
    try:
        parsed = json.loads(ls.stdout)
        models = [m for m in (_key_or_path(m) for m in (parsed.get("models") or [])) if m]
        _ls_cache = {"at": time.monotonic(), "models": models}
    except Exception:
        pass  # non-json output (older lms) — keep old cache


async def downloaded_models(lms: str | None) -> list[str]:
    """Stale-while-revalidate: /status must never block on ``lms ls`` — serve the
    last known list and refresh in background (first call in the process blocks once)."""
    global _ls_cache
    if not lms:
        return []
    cached = _ls_cache
    if cached is None:
        await _refresh_ls(lms)
        return list(_ls_cache["models"]) if _ls_cache else []
    if time.monotonic() - cached["at"] >= 10:
        _spawn(_refresh_ls(lms))  # expired → revalidate
    return cached["models"]


# --- routes (setup.ts righe 751-898) -------------------------------------------------

setup_router = APIRouter()


def reported_llm_state(server_up: bool) -> str:
    """Backend state reconciled with a live probe at read time (setup.ts righe 754-757)."""
    if server_up:
        return "up"
    return "starting" if backend_state == "starting" else "off"


async def _body(request: Request) -> dict | None:
    """``await c.req.json().catch(() => null)`` + guard dict (i body del wizard sono oggetti)."""
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@setup_router.get("/status")
async def setup_status() -> dict:
    cfg = config.read_config_file()
    hw = detect_hardware()
    lms = resolve_lms()
    omlx = resolve_omlx()
    omlx_up = omlx is not None and await http_ok(f"{omlx_base()}/models", 1000, omlx_auth_headers())

    async def dl() -> list[str]:
        return [] if job_active() else await downloaded_models(lms)

    async def omlx_list() -> list[str]:
        return await omlx_models(omlx_up) if omlx is not None else []

    # `cfg.baseUrl ?? LMSTUDIO_BASE` (?? del TS: "" resta "")
    base = cfg["baseUrl"] if cfg.get("baseUrl") is not None else lmstudio_base()
    models, omlx_models_list, server_up = await asyncio.gather(
        dl(),
        omlx_list(),
        http_ok(f"{base}/models", 1000, llm_auth_headers()),
    )
    # "up" only if the configured model is actually among the served ones — a live
    # server that doesn't serve our model would show a green chip on a broken setup
    model = cfg.get("model")
    leaf = model.split("/")[-1] if isinstance(model, str) and model else None
    model_served = model is None or any(
        m == model or m == leaf for m in [*omlx_models_list, *models]
    )
    # disclosure-minimal: no absolute binary path, no raw env details beyond hw summary
    return {
        "setupDone": bool(cfg.get("setupDone")),
        "needsSetup": not cfg.get("setupDone") or needs_setup_version(cfg),
        "customEnv": config.has_custom_env(),
        "hardware": hw,
        "suggested": suggest_model(hw),
        "lms": {"installed": lms is not None, "path": None, "serverUp": server_up},
        "omlx": {
            "installed": omlx is not None,
            "serverUp": omlx_up,
            "models": omlx_models_list,
            "downloadable": [{"model": k, "sizeGb": v} for k, v in OMLX_DOWNLOADABLE.items()],
        },
        "downloadedModels": models,
        "job": job_payload(),
        "llm": {"state": reported_llm_state(server_up and model_served)},
    }


@setup_router.post("/ack")
async def setup_ack() -> dict:
    """Wizard reopen after an app update: persist only the version marker (setup.ts 798-803)."""
    config.update_config({"setupDone": True, "setupVersion": config.APP_VERSION})
    return {"ok": True}


@setup_router.post("/install-cli")
async def setup_install_cli() -> dict:
    try:
        install_cli()
    except SetupError as e:
        return JSONResponse({"error": e.code}, status_code=409)
    return {"ok": True}


@setup_router.post("/download")
async def setup_download(request: Request) -> dict:
    body = await _body(request)
    if not body or not body.get("model"):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    try:
        start_download(body["model"])
    except SetupError as e:
        return JSONResponse({"error": e.code}, status_code=409 if e.code == "busy" else 400)
    return {"ok": True}


@setup_router.post("/finish")
async def setup_finish(request: Request) -> dict:
    """Ordine branch di ``/finish`` (setup.ts righe 826-867)."""
    # qui il TS naviga il body SENZA il guard dict degli altri endpoint: `{}`/`[]`/
    # "str"/5 sono TRUTHY e arrivano a `if (!body.model)` → invalid_model; solo
    # null / body non decodificabile → invalid_request
    try:
        raw = await request.json()
    except Exception:
        raw = None
    if raw is None:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    body: dict = raw if isinstance(raw, dict) else {}
    version = {"setupDone": True, "setupVersion": config.APP_VERSION}
    if body.get("backend") == "skipped":
        # an LLM the user declined must not keep receiving prompts through a stale model/baseUrl
        config.update_config({**version, "backend": "skipped", "model": None, "baseUrl": None})
        return {"ok": True}
    model = body.get("model")
    if model is not None and (not isinstance(model, str) or not MODEL_KEY_RE.match(model)):
        return JSONResponse({"error": "invalid_model"}, status_code=400)
    base_url = body.get("baseUrl")
    if base_url is not None:
        if not isinstance(base_url, str) or not re.match(r"^https?://[\w.:/-]+$", base_url):
            return JSONResponse({"error": "invalid_url"}, status_code=400)
        patch: dict = {**version, "backend": "custom", "baseUrl": base_url}
        if model:
            patch["model"] = model
        config.update_config(patch)
        return {"ok": True}
    if body.get("backend") == "omlx":
        if not model:
            return JSONResponse({"error": "invalid_model"}, status_code=400)
        if not resolve_omlx():
            return JSONResponse({"error": "omlx_missing"}, status_code=400)
        config.update_config({**version, "backend": "omlx", "model": model, "baseUrl": omlx_base()})
        ensure_llm_server(True)
        return {"ok": True}
    if not model:
        return JSONResponse({"error": "invalid_model"}, status_code=400)
    lms = resolve_lms()
    if not lms:
        return JSONResponse({"error": "lms_missing"}, status_code=400)
    config.update_config(
        {
            **version,
            "backend": "lmstudio",
            "model": model,
            "baseUrl": lmstudio_base(),
            "lmsPath": lms,
        }
    )
    ensure_llm_server(True)
    return {"ok": True}


@setup_router.post("/omlx-download")
async def setup_omlx_download(request: Request) -> dict:
    body = await _body(request)
    if not body or not body.get("model"):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    try:
        start_omlx_download(body["model"])
    except SetupError as e:
        return JSONResponse({"error": e.code}, status_code=409 if e.code == "busy" else 400)
    return {"ok": True}


@setup_router.post("/cancel")
async def setup_cancel() -> dict:
    cancel_job()
    return {"ok": True}


@setup_router.post("/reset")
async def setup_reset() -> dict:
    try:
        os.unlink(config.CONFIG_PATH)
    except FileNotFoundError:
        pass
    except Exception:
        return JSONResponse({"error": "reset_failed"}, status_code=500)
    # reset shared state too, so the app truly returns to pre-setup
    config.update_config({})
    cancel_job()  # kills an in-flight download and bumps the generation
    # (solo job; il backend LLM già up viene riconciliato dalla probe)
    return {"ok": True}
