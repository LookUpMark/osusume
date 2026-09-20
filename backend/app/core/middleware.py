r"""Middleware Host-allowlist (docs/contract.md).

Loopback binding is not per-user: reject Host headers that don't match the local
host so DNS-rebinding pages (browser same-origin) and other machines' processes
can't reach privileged endpoints. Primo middleware, copre tutto ``/api`` e ``/api/*``
(esattamente come ``api.use("*")`` su router montato: ``/apifoo`` non è API e resta
fuori dal guard). Attivo anche con ``HOST=0.0.0.0``: la allowlist è sull'header.

Semantica IDENTICA a ``src/server/api.ts``: ``host.replace(/:\d+$/, "")`` poi
``.replace(/^\[|\]$/g, "")`` — quindi ``::1`` senza porta è FUORI allowlist
(la regex porta via ``:1``) e ``::1:3000`` è DENTRO.
"""

from __future__ import annotations

import re

from fastapi.responses import JSONResponse

ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# stessa regex di src/server/api.ts, due passaggi nello stesso ordine
_STRIP_PORT = re.compile(r":\d+$")
_STRIP_BRACKETS = re.compile(r"^\[|\]$")


def hostname(header_value: str) -> str:
    return _STRIP_BRACKETS.sub("", _STRIP_PORT.sub("", header_value))


class HostAllowlistMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == "/api" or path.startswith("/api/")):
            header = next(
                (v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"host"),
                "",
            )
            if hostname(header) not in ALLOWED_HOSTS:
                await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
