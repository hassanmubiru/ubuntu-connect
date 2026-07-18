"""Property test for login gating by verification and credentials (task 4.5).

Exercises the login flow end-to-end through a FastAPI ``TestClient`` backed by
an isolated in-memory data store. For any account and any unknown phone, login
must behave as a three-way gate:

- a verified account (``verified_phone`` true) -> a JWT whose decoded ``sub``
  identifies exactly that user, returned with HTTP 200 (Req 3.1);
- an unverified account -> rejected with a verification-required auth error,
  HTTP 401 (Req 3.2);
- a phone matching no record -> rejected with an authentication error,
  HTTP 401 (Req 3.3).

Each generated example runs against a freshly built engine created inside a
context manager (``_login_harness``) and torn down afterwards. Building the
store per example — rather than through a function-scoped pytest fixture —
keeps every example independent and avoids Hypothesis's function-scoped
fixture health-check warning.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config
from app.integrations.sms_gateway import SmsResult
from app.models import Base, User
from app.routers import auth as auth_router
from app.routers.dependencies import get_sms_gateway
from app.schemas.errors import register_exception_handlers
from app.services.auth_service import decode_access_token

# Realistic African names for seeded accounts (design test-fixture guidance).
_NAMES = st.sampled_from(
    ["Amara Okafor", "Thandiwe Nkosi", "Kwame Mensah", "Zainab Abdullahi"]
)

# E.164 prefixes drawn from the platform's target markets.
_PREFIXES = ["+234", "+27", "+233", "+254", "+20", "+256", "+255"]


@st.composite
def _e164_phone(draw) -> str:
    """Draw a valid E.164 phone: an African country prefix plus 7-9 digits."""
    prefix = draw(st.sampled_from(_PREFIXES))
    rest = draw(st.text(alphabet="0123456789", min_size=7, max_size=9))
    return prefix + rest


@st.composite
def _login_case(draw) -> dict:
    """A seeded account (with a verification state) plus an unknown phone."""
    registered = draw(_e164_phone())
    unknown = draw(_e164_phone().filter(lambda p: p != registered))
    return {
        "phone": registered,
        "unknown_phone": unknown,
        "verified": draw(st.booleans()),
        "full_name": draw(_NAMES),
    }


class _FakeSmsGateway:
    """SMS gateway stub so any OTP trigger stays off the network."""

    def send_otp(self, phone: str, code: str) -> SmsResult:
        return SmsResult(success=True)

    def send(self, phone: str, message: str) -> SmsResult:
        return SmsResult(success=True)


@contextmanager
def _login_harness() -> Iterator[TestClient]:
    """Yield a login-capable client over a fresh, isolated in-memory store.

    A ``StaticPool`` keeps one underlying connection so the in-memory database
    is shared between the test and the request thread. The engine is bound for
    the duration of the block and fully discarded on exit, so each Hypothesis
    example is independent.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.dependency_overrides[get_sms_gateway] = lambda: _FakeSmsGateway()

    try:
        yield TestClient(app)
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


def _seed_user(*, phone: str, full_name: str, verified: bool) -> str:
    """Insert one account directly and return its id as a string."""
    factory = db.get_session_factory()
    with factory() as session:
        user = User(
            full_name=full_name,
            phone=phone,
            verified_phone=verified,
            trust_score=0,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return str(user.id)


# Feature: ubuntu-connect, Property 10: For any account, login issues a JWT
# identifying that user only when credentials are valid and verified_phone is
# true; it is rejected with a verification-required error when unverified, and
# with an authentication error when credentials match no record.
# Validates: Requirements 3.1, 3.2, 3.3
@settings(max_examples=100)
@given(case=_login_case())
def test_login_gates_by_verification_and_credentials(case):
    secret = Config.from_env().jwt_secret

    with _login_harness() as client:
        user_id = _seed_user(
            phone=case["phone"],
            full_name=case["full_name"],
            verified=case["verified"],
        )

        # Login against the seeded account.
        resp = client.post("/api/auth/login", json={"phone": case["phone"]})

        if case["verified"]:
            # Req 3.1: a verified account receives a JWT identifying the user.
            assert resp.status_code == 200
            token = resp.json()["jwt"]
            assert decode_access_token(token, secret) == uuid.UUID(user_id)
        else:
            # Req 3.2: an unverified account is rejected (verification required).
            assert resp.status_code == 401
            assert resp.json()["error"]["code"] == "auth"

        # Req 3.3: a phone matching no record is an authentication error.
        unknown_resp = client.post(
            "/api/auth/login", json={"phone": case["unknown_phone"]}
        )
        assert unknown_resp.status_code == 401
        assert unknown_resp.json()["error"]["code"] == "auth"
