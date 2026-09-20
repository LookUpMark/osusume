"""Entry point del sidecar desktop (PyInstaller onedir, P7).

Stesso bootstrap di ``run_dev.py`` — l'app è quella di ``app.main`` e il
``uvicorn.Server`` resta conservato in ``app.main.SERVER`` perché ``POST
/api/shutdown`` funzioni. Config via env del contratto desktop (PORT, HOST,
ALR_DATA_DIR, APP_VERSION, DIST_DIR — lette da ``app.core.config``).
"""

from __future__ import annotations

import os

import uvicorn

from app.core import config
from app.main import app, set_server

HOST = os.environ.get("HOST") or "127.0.0.1"


def main() -> None:
    # timeout_graceful_shutdown: il browser (Electron) tiene keep-alive aperti e il
    # graceful shutdown di uvicorn può restare in attesa delle connessioni — a 3s
    # forza la chiusura, così il sidecar non sopravvive mai al quit dell'app
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=config.PORT, log_level="info", timeout_graceful_shutdown=3)
    )
    set_server(server)
    print(f"osusume on http://127.0.0.1:{config.PORT}", flush=True)
    server.run()


if __name__ == "__main__":
    main()
