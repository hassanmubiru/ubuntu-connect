"""Ubuntu Connect FastAPI application factory.

This module exposes :func:`create_app`, the single entry point used to
construct the FastAPI application. Startup configuration validation
(fail-fast on missing environment variables, Req 15.5) and router
registration are wired in by later tasks; this scaffold establishes the
factory pattern the rest of the backend builds on.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Config
from app.schemas.errors import register_exception_handlers

APP_TITLE = "Ubuntu Connect API"
APP_DESCRIPTION = (
    "AI-powered trust platform for safe social networking across Africa."
)
APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    """Build and return the Ubuntu Connect FastAPI application.

    Required environment variables are validated up front: if any are
    missing, :meth:`Config.validate` raises before the app is constructed
    and before any port is bound, halting startup without serving requests
    and naming each missing variable (Req 15.5). Later tasks register the
    router modules under ``app.routers``.
    """
    Config.from_env().validate()

    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
    )

    # Install the global handlers that render every failure as the shared
    # error envelope: field-level validation errors (Req 16.1), typed
    # application errors, and a generic no-internals response for anything
    # unexpected (Req 16.2). All write-path requests run inside the
    # transactional session dependency (app.db.get_session), so a raised
    # exception rolls the transaction back before the response is formatted
    # and no partial write survives.
    register_exception_handlers(app)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Liveness probe used by infrastructure and smoke tests."""
        return {"status": "ok"}

    return app


app = create_app()
