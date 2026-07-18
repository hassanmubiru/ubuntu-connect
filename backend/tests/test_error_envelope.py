"""Unit tests for the shared error envelope and global handlers (task 3.1).

Verifies that validation failures produce a per-field error envelope
(Req 16.1), that typed application errors map to their declared code/status,
that framework HTTPExceptions are wrapped in the envelope, and that any
unexpected exception yields a generic internal_error with no internals
leaked (Req 16.2).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.schemas.common import Phone
from app.schemas.errors import (
    AuthError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    PolicyViolationError,
    RateLimitedError,
    register_exception_handlers,
)


class _Body(BaseModel):
    phone: Phone


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/validate")
    def _validate(body: _Body) -> dict[str, str]:  # pragma: no cover - trivial
        return {"phone": body.phone}

    @app.get("/auth")
    def _auth() -> None:
        raise AuthError()

    @app.get("/forbidden")
    def _forbidden() -> None:
        raise AuthorizationError()

    @app.get("/missing")
    def _missing() -> None:
        raise NotFoundError()

    @app.get("/conflict")
    def _conflict() -> None:
        raise ConflictError()

    @app.get("/policy")
    def _policy() -> None:
        raise PolicyViolationError()

    @app.get("/limited")
    def _limited() -> None:
        raise RateLimitedError()

    @app.get("/boom")
    def _boom() -> None:
        raise RuntimeError("secret database password leaked in message")

    return app


def _client(raise_server_exceptions: bool = True) -> TestClient:
    return TestClient(
        _build_app(), raise_server_exceptions=raise_server_exceptions
    )


def test_validation_error_envelope_names_field_and_reason():
    resp = _client().post("/validate", json={"phone": "not-e164"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation"
    assert body["error"]["message"]
    fields = body["error"]["fields"]
    assert any(f["field"] == "phone" and f["reason"] for f in fields)


def test_validation_error_missing_field():
    resp = _client().post("/validate", json={})
    assert resp.status_code == 422
    fields = resp.json()["error"]["fields"]
    assert any(f["field"] == "phone" for f in fields)


def test_auth_error_maps_to_401():
    resp = _client().get("/auth")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_authorization_error_maps_to_403():
    resp = _client().get("/forbidden")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "authorization"


def test_not_found_error_maps_to_404():
    resp = _client().get("/missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_conflict_error_maps_to_409():
    resp = _client().get("/conflict")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


def test_policy_violation_maps_to_422():
    resp = _client().get("/policy")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "policy_violation"


def test_rate_limited_maps_to_429():
    resp = _client().get("/limited")
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


def test_unknown_route_wrapped_in_envelope():
    resp = _client().get("/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "fields" in body["error"]


def test_unhandled_exception_is_generic_with_no_internals():
    resp = _client(raise_server_exceptions=False).get("/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    # No internal detail (exception type, message, stack) leaks out.
    serialized = str(body).lower()
    assert "secret" not in serialized
    assert "runtimeerror" not in serialized
    assert "traceback" not in serialized


def test_create_app_registers_handlers():
    # The real app factory installs the handlers so unknown routes are wrapped.
    from app.main import create_app

    client = TestClient(create_app())
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
