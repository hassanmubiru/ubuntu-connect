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

APP_TITLE = "Ubuntu Connect API"
APP_DESCRIPTION = (
    "AI-powered trust platform for safe social networking across Africa."
)
APP_VERSION = "0.1.0"


def create_app() -> FastAPI:
    """Build and return the Ubuntu Connect FastAPI application.

    Later tasks extend this factory to validate required environment
    variables before serving requests (Req 15.5) and to register the
    router modules under ``app.routers``.
    """
    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
    )

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        """Liveness probe used by infrastructure and smoke tests."""
        return {"status": "ok"}

    return app


app = create_app()
