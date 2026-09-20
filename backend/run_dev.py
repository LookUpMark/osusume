"""Dev launcher: uvicorn in-process con HOST/PORT da env (equivalente di ``src/server/index.ts``).

Eseguendo il server dentro ``uvicorn.Server`` (e non via CLI ``uvicorn``), l'istanza
resta raggiungibile da ``app.main.SERVER`` → ``POST /api/shutdown`` funziona.
"""

from __future__ import annotations

import os

import uvicorn

from app.core import config
from app.main import app, set_server

# 127.0.0.1 by default (loopback-only by design); containers set HOST=0.0.0.0 —
# the /api Host allowlist middleware still guards what comes through the mapping
HOST = os.environ.get("HOST") or "127.0.0.1"


def main() -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=config.PORT, log_level="info"))
    set_server(server)
    print(f"osusume on http://127.0.0.1:{config.PORT}", flush=True)
    server.run()


if __name__ == "__main__":
    main()
