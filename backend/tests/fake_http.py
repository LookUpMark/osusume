"""Fake HTTP server per i test adapter (stessa ricetta dei test TS: server su
porta efimera, risposta JSON per scenario, nessuna rete reale).

Minimal asyncio server: una richiesta per connessione (``connection: close``),
body letto da content-length. L'handler decide status/headers/body.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

_REASONS = {
    200: "OK",
    204: "No Content",
    400: "Bad Request",
    404: "Not Found",
    429: "Too Many Requests",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


class Request:
    def __init__(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
        self.method = method
        self.path = path
        self.body = body
        self.headers = headers

    def json(self) -> Any:
        return json.loads(self.body or b"null")


class Response:
    def __init__(
        self,
        json_body: Any = None,
        *,
        raw: bytes | None = None,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.body = raw if raw is not None else json.dumps(json_body, ensure_ascii=False).encode("utf-8")


Handler = Callable[[Request], Awaitable[Response]]


class FakeServer:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[Request] = []
        self.server: asyncio.Server | None = None
        self.port: int | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def __aenter__(self) -> "FakeServer":
        self.server = await asyncio.start_server(self._on_conn, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _on_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            method, target, _version = request_line.decode().split(" ", 2)
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                name, _, value = line.decode().partition(":")
                headers[name.strip().lower()] = value.strip()
            length = int(headers.get("content-length", "0"))
            body = await reader.read(length) if length else b""
            req = Request(method, target, body, headers)
            self.requests.append(req)
            try:
                res = await self.handler(req)
            except Exception:
                res = Response({"error": "fake handler crash"}, status=500)
            head = (
                f"HTTP/1.1 {res.status} {_REASONS.get(res.status, 'OK')}\r\n"
                f"content-type: application/json\r\n"
                f"content-length: {len(res.body)}\r\n"
                f"connection: close\r\n"
            )
            for key, value in res.headers.items():
                head += f"{key}: {value}\r\n"
            writer.write(head.encode("latin-1") + b"\r\n" + res.body)
            await writer.drain()
        except Exception:
            pass  # il client se ne va a metà risposta: irrilevante per il test
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
