"""Unit tests for OTPService and the OTP endpoints (Task 5.1).

Covers OTP generation shape and 10-minute expiry (Req 2.1, 2.2), correct-code
verification (Req 2.3), wrong-attempt accumulation and the fifth-attempt
invalidation (Req 2.4, 2.5), expired-code rejection (Req 2.6), resend
throttling with prior-OTP invalidation and failed-attempt reset plus the
sixth-request cap (Req 2.7, 2.8), and recoverable SMS delivery failure
(Req 2.9). Property tests for these behaviours live in tasks 5.2–5.7.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import db
from app.integrations.sms_gateway import SmsResult
from app.models import Base, OtpCode, User
from app.repositories.otp_repository import OtpRepository
from app.repositories.user_repository import UserRepository
from app.routers import auth as auth_router
from app.routers.dependencies import get_sms_gateway
from app.schemas.errors import (
    NotFoundError,
    RateLimitedError,
    SendFailureError,
    ValidationAppError,
)
from app.services.otp_service import (
    MAX_FAILED_ATTEMPTS,
    OTP_TTL,
    OTPService,
)

PHONE = "+2348031234567"


class _FakeSmsGateway:
    """Records OTP sends and reports a configurable success flag (Req 2.9)."""

    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.sent: list[tuple[str, str]] = []

    def send_otp(self, phone: str, code: str) -> SmsResult:
        self.sent.append((phone, code))
        return SmsResult(success=self.success)

    def send(self, phone: str, message: str) -> SmsResult:
        return SmsResult(success=self.success)


class _Clock:
    """A movable clock so expiry and windows are deterministic in tests."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture()
def engine():
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


@pytest.fixture()
def session(engine) -> Session:
    session = db.get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def _make_user(session: Session, phone: str = PHONE) -> User:
    users = UserRepository(session)
    return users.create(full_name="Amara Okafor", phone=phone)


def _wrong_code(code: str) -> str:
    """Return a six-digit code guaranteed to differ from ``code``."""
    return "999999" if code != "999999" else "000000"


# --- Generation shape and expiry (Req 2.1, 2.2) -----------------------------


def test_generate_and_send_produces_six_digit_code_and_ten_minute_expiry(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    gateway = _FakeSmsGateway()
    fixed = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    sent = OTPService(otps, users, gateway, clock=_Clock(fixed)).generate_and_send(
        user
    )

    assert sent is True
    otp = otps.get_active_for_user(user.id)
    assert otp is not None
    assert re.fullmatch(r"\d{6}", otp.code)
    assert otp.expires_at == fixed + OTP_TTL
    assert gateway.sent == [(user.phone, otp.code)]


def test_generated_codes_preserve_leading_zeros_over_many_draws(session):
    # A generated code is always exactly six characters, even with leading
    # zeros, because it is stored zero-padded as text (Req 2.1).
    from app.services.otp_service import _generate_code

    for _ in range(2000):
        code = _generate_code()
        assert len(code) == 6
        assert code.isdigit()


# --- Correct code verifies the phone (Req 2.3) ------------------------------


def test_correct_code_before_expiry_verifies_phone(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    svc = OTPService(otps, users, _FakeSmsGateway())
    svc.generate_and_send(user)
    otp = otps.get_active_for_user(user.id)

    assert svc.verify(user.phone, otp.code) is True
    assert user.verified_phone is True


def test_correct_code_triggers_on_verified_hook(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    recalculated: list[User] = []
    svc = OTPService(
        otps,
        users,
        _FakeSmsGateway(),
        on_verified=recalculated.append,
    )
    svc.generate_and_send(user)
    otp = otps.get_active_for_user(user.id)

    svc.verify(user.phone, otp.code)

    assert recalculated == [user]


# --- Wrong attempts accumulate and cap at five (Req 2.4, 2.5) ---------------


def test_wrong_attempts_increment_then_fifth_invalidates(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    svc = OTPService(otps, users, _FakeSmsGateway())
    svc.generate_and_send(user)
    otp = otps.get_active_for_user(user.id)
    wrong = _wrong_code(otp.code)

    # The first four wrong submissions are rejected as incorrect and counted.
    for expected in range(1, MAX_FAILED_ATTEMPTS):
        with pytest.raises(ValidationAppError) as exc:
            svc.verify(user.phone, wrong)
        assert "incorrect" in str(exc.value).lower()
        assert otp.failed_attempts == expected

    # The fifth wrong submission invalidates the OTP and reports max attempts.
    with pytest.raises(ValidationAppError) as exc:
        svc.verify(user.phone, wrong)
    assert "maximum" in str(exc.value).lower()
    assert otps.get_active_for_user(user.id) is None
    assert user.verified_phone is False


# --- Expired code is rejected (Req 2.6) -------------------------------------


def test_code_at_or_after_expiry_is_rejected_as_expired(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    clock = _Clock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    svc = OTPService(otps, users, _FakeSmsGateway(), clock=clock)
    svc.generate_and_send(user)
    otp = otps.get_active_for_user(user.id)

    # Advance past the ten-minute expiry, then submit the *correct* code.
    clock.now = clock.now + OTP_TTL + timedelta(seconds=1)
    with pytest.raises(ValidationAppError) as exc:
        svc.verify(user.phone, otp.code)

    assert "expired" in str(exc.value).lower()
    assert user.verified_phone is False


# --- Resend throttling (Req 2.7, 2.8) ---------------------------------------


def test_resend_invalidates_prior_and_resets_failed_attempts(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    svc = OTPService(otps, users, _FakeSmsGateway())
    svc.generate_and_send(user)
    first = otps.get_active_for_user(user.id)

    # Accumulate a failed attempt on the first code.
    with pytest.raises(ValidationAppError):
        svc.verify(user.phone, _wrong_code(first.code))
    assert first.failed_attempts == 1

    assert svc.resend(user.phone) is True

    replacement = otps.get_active_for_user(user.id)
    assert replacement.id != first.id
    assert replacement.failed_attempts == 0
    assert first.invalidated is True


def test_sixth_request_within_window_is_rejected_with_resend_limit(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    svc = OTPService(otps, users, _FakeSmsGateway())

    # One initial send plus four resends = five requests within the window.
    svc.generate_and_send(user)
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert svc.resend(user.phone) is True

    # The sixth request is rejected, and the message names the 60-minute window.
    with pytest.raises(RateLimitedError) as exc:
        svc.resend(user.phone)
    assert "60" in str(exc.value)


# --- Recoverable SMS delivery failure (Req 2.9) -----------------------------


def test_send_failure_is_recoverable(session):
    users, otps = UserRepository(session), OtpRepository(session)
    user = _make_user(session)
    gateway = _FakeSmsGateway(success=False)
    svc = OTPService(otps, users, gateway)

    # Initial send fails: the code is stored but reported as not delivered.
    assert svc.generate_and_send(user) is False
    assert otps.get_active_for_user(user.id) is not None

    # A resend that also fails surfaces a send-failure error.
    with pytest.raises(SendFailureError):
        svc.resend(user.phone)

    # Once delivery recovers, a subsequent resend succeeds.
    gateway.success = True
    assert svc.resend(user.phone) is True


# --- Unknown phone ----------------------------------------------------------


def test_verify_unknown_phone_is_not_found(session):
    users, otps = UserRepository(session), OtpRepository(session)
    svc = OTPService(otps, users, _FakeSmsGateway())
    with pytest.raises(NotFoundError):
        svc.verify("+254700000000", "123456")


# --- Endpoint wiring --------------------------------------------------------


def _build_client() -> TestClient:
    app = FastAPI()
    from app.schemas.errors import register_exception_handlers

    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.dependency_overrides[get_sms_gateway] = lambda: _FakeSmsGateway()
    return TestClient(app)


def _active_code(phone: str) -> str:
    session = db.get_session_factory()()
    try:
        user = session.scalar(select(User).where(User.phone == phone))
        otp = session.scalar(
            select(OtpCode)
            .where(OtpCode.user_id == user.id)
            .where(OtpCode.invalidated.is_(False))
            .order_by(OtpCode.created_at.desc(), OtpCode.id.desc())
        )
        return otp.code
    finally:
        session.close()


def test_verify_otp_endpoint_verifies_phone(engine):
    client = _build_client()
    client.post(
        "/api/auth/register",
        json={"full_name": "Zainab Abdullahi", "phone": PHONE},
    )
    resp = client.post(
        "/api/auth/verify-otp",
        json={"phone": PHONE, "code": _active_code(PHONE)},
    )
    assert resp.status_code == 200
    assert resp.json()["verified"] is True


def test_verify_otp_endpoint_rejects_wrong_code(engine):
    client = _build_client()
    client.post(
        "/api/auth/register",
        json={"full_name": "Zainab Abdullahi", "phone": PHONE},
    )
    wrong = _wrong_code(_active_code(PHONE))
    resp = client.post(
        "/api/auth/verify-otp", json={"phone": PHONE, "code": wrong}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation"


def test_resend_otp_endpoint_issues_replacement(engine):
    client = _build_client()
    client.post(
        "/api/auth/register",
        json={"full_name": "Zainab Abdullahi", "phone": PHONE},
    )
    resp = client.post("/api/auth/resend-otp", json={"phone": PHONE})
    assert resp.status_code == 200
    assert resp.json()["otp_sent"] is True
