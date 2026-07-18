"""Unit tests for AuthService, the auth router, and the JWT guards (Task 4.1).

Covers registration defaults and duplicate rejection (Req 1.1, 1.2, 1.6),
registration field validation (Req 1.3, 1.4, 1.5), login gating by
verification and credentials (Req 3.1, 3.2, 3.3), JWT 24-hour expiry
(Req 3.5), and the protected-endpoint auth guard plus admin role guard
(Req 3.6, 11.1). AI/OTP are out of scope here; the OTP trigger is left unset.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config
from app.integrations.sms_gateway import SmsResult
from app.models import Base, User
from app.routers import auth as auth_router
from app.routers.dependencies import AdminUser, CurrentUser, get_sms_gateway
from app.schemas.errors import register_exception_handlers
from app.services.auth_service import (
    JWT_ALGORITHM,
    TOKEN_TTL,
    AuthService,
    create_access_token,
)

VERIFIED_PHONE = "+2348031234567"
UNVERIFIED_PHONE = "+27821234567"
ADMIN_PHONE = "+233201234567"


@pytest.fixture()
def engine():
    """Bind an isolated in-memory SQLite engine shared across requests."""
    eng = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        db.reset_engine()


def _seed_user(**overrides) -> User:
    """Insert a user directly through a session for arrange steps."""
    data = {
        "full_name": "Amara Okafor",
        "phone": VERIFIED_PHONE,
        "verified_phone": True,
        "trust_score": 0,
    }
    data.update(overrides)
    session = db.get_session_factory()()
    try:
        user = User(**data)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


class _FakeSmsGateway:
    """SMS gateway stub that accepts every send, so tests avoid the network."""

    def send_otp(self, phone: str, code: str) -> SmsResult:
        return SmsResult(success=True)

    def send(self, phone: str, message: str) -> SmsResult:
        return SmsResult(success=True)


def _build_app() -> FastAPI:
    """App with the auth router plus test-only protected/admin routes."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    # Override the SMS gateway so registration's OTP trigger never touches the
    # network; the OTP lifecycle itself is covered in test_otp_service.
    app.dependency_overrides[get_sms_gateway] = lambda: _FakeSmsGateway()

    @app.get("/protected")
    def _protected(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.id)}

    @app.get("/admin-only")
    def _admin(user: AdminUser) -> dict[str, str]:
        return {"user_id": str(user.id)}

    return app


@pytest.fixture()
def client(engine) -> TestClient:
    return TestClient(_build_app())


# --- Registration -----------------------------------------------------------


def test_register_creates_user_with_defaults(client, engine):
    resp = client.post(
        "/api/auth/register",
        json={"full_name": "Zainab Abdullahi", "phone": "+254712345678"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Registration now triggers the first OTP send; the fake gateway accepts it.
    assert body["otp_sent"] is True
    assert body["user_id"]

    session = db.get_session_factory()()
    try:
        user = session.scalar(select(User).where(User.phone == "+254712345678"))
        assert user is not None
        assert user.verified_phone is False
        assert user.trust_score == 0
        assert isinstance(user.created_at, datetime)
    finally:
        session.close()


def test_register_duplicate_phone_rejected_without_side_effects(client, engine):
    _seed_user(phone=VERIFIED_PHONE, verified_phone=False)

    resp = client.post(
        "/api/auth/register",
        json={"full_name": "Someone Else", "phone": VERIFIED_PHONE},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"

    session = db.get_session_factory()()
    try:
        count = session.scalar(
            select(func.count()).select_from(User).where(User.phone == VERIFIED_PHONE)
        )
        assert count == 1
    finally:
        session.close()


@pytest.mark.parametrize(
    "payload,bad_field",
    [
        ({"full_name": "Amara", "phone": "0803-not-e164"}, "phone"),
        ({"full_name": "Amara"}, "phone"),
        ({"phone": VERIFIED_PHONE}, "full_name"),
        ({"full_name": "   ", "phone": VERIFIED_PHONE}, "full_name"),
        ({"full_name": "A", "phone": VERIFIED_PHONE}, "full_name"),
        ({"full_name": "N" * 101, "phone": VERIFIED_PHONE}, "full_name"),
    ],
)
def test_register_input_validation(client, engine, payload, bad_field):
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation"
    assert any(f["field"] == bad_field for f in body["error"]["fields"])


# --- Login ------------------------------------------------------------------


def test_login_verified_issues_jwt_identifying_user(client, engine):
    user = _seed_user(phone=VERIFIED_PHONE, verified_phone=True)
    resp = client.post("/api/auth/login", json={"phone": VERIFIED_PHONE})
    assert resp.status_code == 200
    body = resp.json()
    claims = jwt.decode(body["jwt"], Config.from_env().jwt_secret, algorithms=[JWT_ALGORITHM])
    assert claims["sub"] == str(user.id)


def test_login_unverified_returns_verification_required(client, engine):
    _seed_user(phone=UNVERIFIED_PHONE, verified_phone=False)
    resp = client.post("/api/auth/login", json={"phone": UNVERIFIED_PHONE})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_login_unknown_phone_returns_auth_error(client, engine):
    resp = client.post("/api/auth/login", json={"phone": "+254700000000"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_login_missing_credential_field_rejected(client, engine):
    resp = client.post("/api/auth/login", json={})
    assert resp.status_code == 422
    assert any(f["field"] == "phone" for f in resp.json()["error"]["fields"])


# --- JWT expiry -------------------------------------------------------------


def test_jwt_expiry_is_24_hours_after_issuance():
    import uuid

    issued = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    token, expires_at = create_access_token(
        uuid.uuid4(), "test-secret", issued_at=issued
    )
    assert expires_at == issued + TOKEN_TTL
    # The token is deliberately issued in the past; skip expiry verification
    # so we can inspect the raw exp/iat claims regardless of the current time.
    claims = jwt.decode(
        token,
        "test-secret",
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    assert claims["exp"] - claims["iat"] == int(TOKEN_TTL.total_seconds())


# --- Guards -----------------------------------------------------------------


def test_protected_route_rejects_missing_token(client, engine):
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_protected_route_rejects_invalid_token(client, engine):
    resp = client.get(
        "/protected", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_protected_route_rejects_expired_token(client, engine):
    import uuid

    expired_issue = datetime.now(timezone.utc) - timedelta(hours=25)
    token, _ = create_access_token(
        uuid.uuid4(), Config.from_env().jwt_secret, issued_at=expired_issue
    )
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth"


def test_protected_route_accepts_valid_token(client, engine):
    user = _seed_user(phone=VERIFIED_PHONE, verified_phone=True)
    login = client.post("/api/auth/login", json={"phone": VERIFIED_PHONE})
    token = login.json()["jwt"]
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(user.id)


def test_admin_guard_rejects_non_admin(client, engine):
    _seed_user(phone=VERIFIED_PHONE, verified_phone=True, is_admin=False)
    token = client.post(
        "/api/auth/login", json={"phone": VERIFIED_PHONE}
    ).json()["jwt"]
    resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "authorization"


def test_admin_guard_allows_admin(client, engine):
    _seed_user(phone=ADMIN_PHONE, verified_phone=True, is_admin=True)
    token = client.post(
        "/api/auth/login", json={"phone": ADMIN_PHONE}
    ).json()["jwt"]
    resp = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
