"""Tutor-only application for the production `tutor` service (T033, ADR-031).

Serves only the tutor page, its static files and /api/tutor/*: no student, practice or development
routes. Production runs it in its own container, published on the server's 127.0.0.1:8081 and reached by
SSH tunnel; the student service never holds the tutor token.

Fails closed at startup: MENTOR_PRO_TUTOR_TOKEN must have at least 32 characters, and
MENTOR_PRO_TUTOR_ALLOWED_HOSTS must be a non-empty list of exact IP addresses (the compose bridge
gateway). Uvicorn runs with forwarded headers disabled, so the client address is always the TCP peer.

    python -m app.tutor_main          # what the tutor service runs
"""

from __future__ import annotations

import ipaddress
import sys

import psycopg

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.main import STATIC_DIR, ApiError
from app.writing.routes import WritingService
from app.writing.tutor import build_tutor_router
from curriculum import db

MIN_SERVICE_TOKEN = 32
PORT = 8000
EX_CONFIG = 78  # sysexits.h: configuration error; the exit code of a refused start
# Forwarded headers off: X-Forwarded-For can never change the client address the tutor check reads.
UVICORN_OPTIONS = {"host": "0.0.0.0", "port": PORT, "proxy_headers": False, "server_header": False}


class TutorConfigurationError(ValueError):
    """The tutor service is misconfigured; it refuses to start (never falls back to an open setting)."""


def parse_allowed_hosts(value: str | None) -> frozenset[str]:
    """Exact IP addresses, comma-separated. No ranges, names, wildcards or empty lists."""
    entries = [e.strip() for e in (value or "").split(",") if e.strip()]
    if not entries:
        raise TutorConfigurationError("MENTOR_PRO_TUTOR_ALLOWED_HOSTS is empty")
    hosts = set()
    for entry in entries:
        try:
            address = ipaddress.ip_address(entry)
        except ValueError:
            raise TutorConfigurationError(f"not an exact IP address: {entry!r}") from None
        if address.is_unspecified or address.is_multicast or (address.version == 4 and entry.endswith(".255")):
            raise TutorConfigurationError(f"not a single host address: {entry!r}")
        hosts.add(str(address))
    return frozenset(hosts)


def create_tutor_app(database_url: str | None = None, token: str | None = None,
                     allowed_hosts: str | None = None) -> FastAPI:
    token = token if token is not None else (db.setting("MENTOR_PRO_TUTOR_TOKEN") or "")
    if len(token) < MIN_SERVICE_TOKEN:
        raise TutorConfigurationError(f"MENTOR_PRO_TUTOR_TOKEN must have at least {MIN_SERVICE_TOKEN} characters")
    hosts = parse_allowed_hosts(allowed_hosts if allowed_hosts is not None
                                else db.setting("MENTOR_PRO_TUTOR_ALLOWED_HOSTS"))
    app = FastAPI(title="Mentor Pro tutor", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message_es": exc.message_es})

    # Only reached after the tutor check passed: the database is down or not configured.
    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(db.ConfigurationError)
    async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={
            "error": "database_unavailable", "message_es": "La base de datos no está disponible. Intentá más tarde."})

    service = WritingService(lambda: database_url or db.database_url())
    app.include_router(build_tutor_router(service, ApiError, token, hosts))

    @app.get("/tutor", include_in_schema=False)
    def tutor_page(request: Request) -> FileResponse:
        if (request.client.host if request.client else "") not in hosts:
            raise ApiError(403, "tutor_only", "Acceso solo para el tutor.")
        return FileResponse(STATIC_DIR / "tutor.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


if __name__ == "__main__":
    import uvicorn

    try:
        tutor_app = create_tutor_app()
    except TutorConfigurationError as exc:  # never prints the token itself
        print(f"tutor configuration rejected: {exc}", file=sys.stderr)
        raise SystemExit(EX_CONFIG) from None
    uvicorn.run(tutor_app, **UVICORN_OPTIONS)
