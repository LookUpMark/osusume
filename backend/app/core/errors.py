"""Mappa errori canonica (docs/contract.md).

Il client mostra il codice grezzo: i codici SONO la UI di errore.
Unico campo extra ammesso: ``message`` (solo ``anilist_error``).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Errore classificato: status HTTP + codice snake_case."""

    def __init__(self, status: int, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message


# codici snake_case per gli HTTPException lanciati dal framework (route sconosciuta, metodo errato…)
_STATUS_CODE = {
    400: "invalid_request",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    422: "invalid_request",
}


def error_body(code: str, message: str | None = None) -> dict:
    body = {"error": code}
    if message:
        body["message"] = message
    return body


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # default FastAPI è 422 con il dettaglio: il contratto vuole 400 + codice
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        # Metodo sbagliato su route nota: nel TS non matchava Hono e cadeva nel
        # fallback statico di index.ts (use "/*" + get "/*" → SPA 200 per GET/HEAD;
        # gli altri metodi arrivavano al 404 default "404 Not Found" text/plain).
        if exc.status_code == 405:
            if request.method in ("GET", "HEAD"):
                try:
                    return HTMLResponse(Path("dist/index.html").read_text("utf-8"))
                except OSError:
                    pass
            return PlainTextResponse("404 Not Found", status_code=404)
        # il dettaglio è SEMPRE il codice snake_case, mai testo
        code = _STATUS_CODE.get(exc.status_code, "internal_error")
        return JSONResponse({"error": code}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def on_uncaught(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": "internal_error"}, status_code=500)
