"""Authentication router: registration, OTP verification/resend, and login.

Thin HTTP handlers that validate the request body against the auth schemas,
delegate to :class:`AuthService` / :class:`OTPService`, and return an explicit
``response_model`` so FastAPI documents both the request and response schema of
every endpoint (Req 15.6). All business rules — duplicate-phone rejection,
verification gating, JWT issuance, and the whole OTP lifecycle — live in the
services; the router only adapts HTTP to service calls.

Endpoints:
- ``POST /api/auth/register`` — create a user and trigger the first OTP SMS
  (Req 1, 2.1).
- ``POST /api/auth/verify-otp`` — verify a submitted code (Req 2.3–2.6).
- ``POST /api/auth/resend-otp`` — issue a fresh code within the resend cap
  (Req 2.7–2.9).
- ``POST /api/auth/login`` — issue a 24-hour JWT for a verified account
  (Req 3).
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter

from app.config import Config
from app.integrations.sms_gateway import SmsGateway
from app.models.user import User
from app.repositories.dependencies import OtpRepositoryDep, UserRepositoryDep
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResendOtpRequest,
    ResendOtpResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.services.auth_service import AuthService
from app.services.otp_service import OTPService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _trust_recalc_hook(users: UserRepository) -> Callable[[User], None] | None:
    """Return the post-verification Trust Engine recalculation hook, if wired.

    Phone verification must trigger a Trust_Score recalculation (Req 5.2). The
    Trust Engine lives in a module delivered by a parallel task, so this uses a
    lazy import to avoid a hard dependency: when the module and its
    recalculation entry point are present the hook recalculates the verified
    user's score; until then it is a clean no-op (``None``). Wiring the Trust
    Engine here is a one-line change once task 7.1 lands.
    """
    try:
        from app.services import trust_engine  # noqa: WPS433 (lazy, task 7.1)
    except ImportError:
        return None

    recalc = getattr(trust_engine, "recalculate_for_user", None)
    if not callable(recalc):
        return None

    return lambda user: recalc(user, users)


def _otp_service(otps: OtpRepositoryDep, users: UserRepositoryDep) -> OTPService:
    """Build a request-scoped :class:`OTPService`.

    The OTP and user repositories are the request-scoped instances from
    dependency injection so the whole request runs inside one transactional
    unit of work; the SMS gateway reads its credentials from the environment
    (Req 15.4). A verified phone triggers the Trust Engine hook when wired.
    """
    return OTPService(
        otps,
        users,
        SmsGateway(),
        on_verified=_trust_recalc_hook(users),
    )


def _auth_service(users: UserRepositoryDep, otps: OtpRepositoryDep) -> AuthService:
    """Build a request-scoped :class:`AuthService` with the OTP trigger.

    The JWT secret is read from the environment-sourced config (Req 15.4). The
    ``otp_trigger`` issues the first OTP SMS on successful registration
    (Req 2.1); a delivery failure leaves ``otp_sent`` false while the stored
    code remains available for resend (Req 2.9).
    """
    otp_service = _otp_service(otps, users)
    return AuthService(
        users,
        Config.from_env().jwt_secret,
        otp_trigger=otp_service.generate_and_send,
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user with a full name and E.164 phone.",
)
def register(
    body: RegisterRequest,
    users: UserRepositoryDep,
    otps: OtpRepositoryDep,
) -> RegisterResponse:
    """Create a user with registration defaults and trigger an OTP (Req 1, 2.1).

    A duplicate phone is rejected with a conflict error and no record is
    written (Req 1.2); field-shape validation is handled by the request schema
    before this runs (Req 1.3, 1.4, 1.5). On success the first OTP is generated
    and an SMS is requested; ``otp_sent`` reports whether delivery was accepted.
    """
    result = _auth_service(users, otps).register(body.full_name, body.phone)
    return RegisterResponse(user_id=result.user.id, otp_sent=result.otp_sent)


@router.post(
    "/verify-otp",
    response_model=VerifyOtpResponse,
    summary="Verify a six-digit OTP for a phone number.",
)
def verify_otp(
    body: VerifyOtpRequest,
    users: UserRepositoryDep,
    otps: OtpRepositoryDep,
) -> VerifyOtpResponse:
    """Verify a submitted code (Req 2.3–2.6).

    A matching code before expiry marks the phone verified; an expired code,
    an incorrect code, or a code submitted after the attempt cap is rejected
    with the corresponding error. A successful verification triggers the Trust
    Engine recalculation hook when wired (Req 5.2).
    """
    verified = _otp_service(otps, users).verify(body.phone, body.code)
    return VerifyOtpResponse(verified=verified)


@router.post(
    "/resend-otp",
    response_model=ResendOtpResponse,
    summary="Request a replacement OTP within the resend limit.",
)
def resend_otp(
    body: ResendOtpRequest,
    users: UserRepositoryDep,
    otps: OtpRepositoryDep,
) -> ResendOtpResponse:
    """Issue a replacement OTP within the resend cap (Req 2.7–2.9).

    Invalidates any prior OTP and resets the failed-attempt count on a valid
    resend; the sixth request in the trailing 60-minute window is rejected with
    a resend-limit error, and a delivery failure is surfaced while leaving a
    further resend permitted.
    """
    otp_sent = _otp_service(otps, users).resend(body.phone)
    return ResendOtpResponse(otp_sent=otp_sent)


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Log in with a verified phone and receive a 24-hour JWT.",
)
def login(body: LoginRequest, users: UserRepositoryDep) -> LoginResponse:
    """Issue a JWT for a verified account (Req 3.1, 3.2, 3.3, 3.5).

    Rejects an unverified account with a verification-required error and an
    unknown phone with an authentication error.
    """
    result = _auth_service_login(users).login(body.phone)
    return LoginResponse(jwt=result.token, expires_at=result.expires_at)


def _auth_service_login(users: UserRepositoryDep) -> AuthService:
    """Build an :class:`AuthService` for login (no OTP trigger needed)."""
    return AuthService(users, Config.from_env().jwt_secret)
