"""OAuth AniList (nuovo, non nel TS): authorization-code grant con callback
loopback su PORTA FISSA registrata sull'app AniList (default 47321).

Il token vive SOLO server-side (config.json / env ``ANILIST_TOKEN``) — il
frontend non lo vede mai, come la oMLX key. Il listener è un socket proprio
FUORI dal middleware Host-allowlist: la difesa CSRF è il ``state`` monouso
confrontato a tempo costante (il repo non ha check Origin/Referer).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core import config
from app.core.errors import ApiError

_AUTHORIZE_URL = "https://anilist.co/api/v2/oauth/authorize"
TOKEN_URL = os.environ.get("ANILIST_OAUTH_TOKEN_URL") or "https://anilist.co/api/v2/oauth/token"
FLOW_TIMEOUT_S = 600.0

_flow: dict[str, Any] = {"state": "idle", "error": None, "state_param": None}
_listener: asyncio.Server | None = None
_flow_task: asyncio.Task | None = None


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ[key])
    except (KeyError, ValueError):
        return default


def callback_port() -> int:
    return _int_env("ANILIST_OAUTH_CALLBACK_PORT", 47321)


def redirect_uri() -> str:
    return f"http://127.0.0.1:{callback_port()}/callback"


def client_credentials() -> tuple[str | None, str | None]:
    cfg = config.read_config_file()
    cid = os.environ.get("ANILIST_CLIENT_ID") or cfg.get("anilistClientId")
    secret = os.environ.get("ANILIST_CLIENT_SECRET") or cfg.get("anilistClientSecret")
    cid = cid if isinstance(cid, str) and cid else None
    secret = secret if isinstance(secret, str) and secret else None
    return cid, secret


def anilist_token() -> str | None:
    env = os.environ.get("ANILIST_TOKEN")
    if env:
        return env
    value = config.read_config_file().get("anilistToken")
    return value if isinstance(value, str) and value else None


def token_for(username: str) -> str | None:
    """Token del profilo collegato: usato solo quando coincide con la lista
    richiesta — mai per liste di terzi."""
    token = anilist_token()
    if token is None:
        return None
    cfg = config.read_config_file()
    user = cfg.get("anilistUser")
    return token if isinstance(user, str) and user == username else None


def status_payload() -> dict:
    cfg = config.read_config_file()
    cid, _ = client_credentials()
    token = anilist_token()
    user = cfg.get("anilistUser")
    return {
        "configured": cid is not None,
        "authenticated": token is not None and isinstance(user, str),
        "username": user if isinstance(user, str) else None,
        "flow": _flow["state"],
        "flowError": _flow["error"],
        "redirectUri": redirect_uri(),
        "tokenExpiresAt": cfg.get("anilistTokenExpires") if isinstance(cfg.get("anilistTokenExpires"), str) else None,
    }


def disconnect() -> None:
    config.update_config({"anilistToken": None, "anilistUser": None, "anilistTokenAt": None, "anilistTokenExpires": None})
    _flow.update(state="idle", error=None, state_param=None)


async def start_flow() -> str:
    """Avvia il flow: listener loopback + URL authorize. ``ApiError`` mai None-error."""
    global _listener, _flow_task
    client_id, client_secret = client_credentials()
    if not client_id or not client_secret:
        raise ApiError(400, "oauth_not_configured")
    if _flow["state"] == "pending":
        raise ApiError(409, "oauth_busy")

    state = secrets.token_hex(16)
    try:
        server = await asyncio.start_server(lambda r, w: _on_callback(r, w, state), "127.0.0.1", callback_port())
    except OSError as e:
        raise ApiError(409, "oauth_port_busy") from e
    _listener = server
    _flow.update(state="pending", error=None, state_param=state)

    async def _timeout() -> None:
        try:
            await asyncio.wait_for(server.serve_forever(), FLOW_TIMEOUT_S)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            server.close()
            if _flow["state"] == "pending":
                _flow.update(state="error", error="timeout")

    _flow_task = asyncio.ensure_future(_timeout())
    return (
        f"{_AUTHORIZE_URL}?client_id={client_id}&redirect_uri={redirect_uri()}"
        f"&response_type=code&state={state}"
    )


def _reset_flow() -> None:
    global _listener, _flow_task
    if _listener is not None:
        _listener.close()
    if _flow_task is not None:
        _flow_task.cancel()
    _listener = None
    _flow_task = None


def _html_page(message: str) -> bytes:
    body = f"<!doctype html><title>Osusume</title><p style='font-family:sans-serif'>{message}</p>"
    return (
        f"HTTP/1.1 200 OK\r\ncontent-type: text/html; charset=utf-8\r\ncontent-length: {len(body.encode())}\r\n"
        f"connection: close\r\n\r\n{body}"
    ).encode("utf-8")


async def _reject(writer: asyncio.StreamWriter, status: str, body: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\ncontent-type: text/plain\r\ncontent-length: {len(body)}\r\nconnection: close\r\n\r\n{body}".encode())
    await writer.drain()
    writer.close()


async def _on_callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, state: str) -> None:
    """Una richiesta per connessione: solo GET /callback con state corretto.
    I callback rifiutati NON chiudono il listener (il browser dell'utente può
    riprovare); il reset avviene solo a flow concluso (ok/error)."""
    terminal = False
    try:
        request_line = await asyncio.wait_for(reader.readline(), 10)
        path = request_line.decode("latin-1").split(" ", 2)[1] if request_line else ""
        if not path.startswith("/callback") or "state=" not in path:
            await _reject(writer, "404 Not Found", "not a callback")
            return
        query = dict(pair.split("=", 1) for pair in path.split("?", 1)[1].split("&") if "=" in pair)
        if not hmac.compare_digest(query.get("state", ""), state):
            await _reject(writer, "404 Not Found", "state mismatch")
            return
        code = query.get("code")
        if not code:
            await _reject(writer, "404 Not Found", "missing code")
            return
        try:
            await exchange_and_store(code)
        except ApiError as e:
            _flow.update(state="error", error=e.code)
            terminal = True
            await _reject(writer, "502 Bad Gateway", e.code)
            return
        except Exception:
            # mai una connessione appesa: qualunque fallimento chiude il flow
            _flow.update(state="error", error="anilist_error")
            terminal = True
            await _reject(writer, "502 Bad Gateway", "anilist_error")
            return
        terminal = True
        writer.write(_html_page("Signed in to Osusume. You can close this window and go back to the app."))
        await writer.drain()
    finally:
        writer.close()
        if terminal:
            _reset_flow()


async def exchange_and_store(code: str) -> str:
    """Code → token → Viewer name → config. Ritorna lo username collegato."""
    client_id, client_secret = client_credentials()
    if not client_id or not client_secret:
        raise ApiError(400, "oauth_not_configured")
    import httpx

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            res = await asyncio.wait_for(
                client.post(
                    TOKEN_URL,
                    headers={"content-type": "application/json", "accept": "application/json"},
                    content=json.dumps(
                        {
                            "grant_type": "authorization_code",
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "redirect_uri": redirect_uri(),
                            "code": code,
                        }
                    ).encode("utf-8"),
                    timeout=10,
                ),
                15,
            )
    except (httpx.TransportError, asyncio.TimeoutError) as e:
        raise ApiError(502, "anilist_error") from e
    if res.status_code != 200:
        raise ApiError(502, "anilist_error")
    token = res.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise ApiError(502, "anilist_error")

    from app.adapters.anilist import queries
    from app.adapters.anilist.client import gql_uncached

    data = await gql_uncached(queries.VIEWER_QUERY, {}, token=token)
    name = data.get("Viewer", {}).get("name")
    if not isinstance(name, str) or not name:
        raise ApiError(502, "anilist_error")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=int(res.json().get("expires_in", 365 * 24 * 3600)))
    config.update_config(
        {
            "anilistToken": token,
            "anilistUser": name,
            "anilistTokenAt": now.isoformat(timespec="seconds"),
            "anilistTokenExpires": expires.isoformat(timespec="seconds"),
        }
    )
    _flow.update(state="ok", error=None, state_param=None)
    return name
