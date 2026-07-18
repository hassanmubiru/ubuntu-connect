"""Authentication router: registration and login (Req 1, 3).

Thin HTTP handlers that validate the request body against the auth schemas,
delegate to :class:`AuthService`, and return an explicit ``response_model`` so
FastAPI documents both the request and response schema of every endpoint
(Req 15.6). All business rules — duplicate-phone rejection, verification
gating, and JWT issuance — live in the service; the router only adapts HTTP
to service calls.

The OTP verification and resend endpoints (``/api/auth/verify-otp`` and
``/api/auth/resend-otp``) are added by the OTP task; this module intentionally
exposes only ``/register`` and ``/login``.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import Config
from app.repositories.dependencies import UserRepositoryDep
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_service(users: UserRepositoryDep) -> AuthService:
    """Build a request-scoped :class:`AuthService`.

    The JWT secret is read from the environment-sourced config (Req 15.4); the
    repository is the request-scoped instance from dependency injection so the
    whole request runs inside one transactional unit of work.
    """
    return AuthService(users, Config.from_env().jwt_secret)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
    summary="Register a new user with a full name and E.164 phone.",
)
def register(body: RegisterRequest, users: UserRepositoryDep) -> RegisterResponse:
    """Create a user with registration defaults (Req 1.1, 1.6).

    A duplicate phone is rejected with a conflict error and no record is
    written (Req 1.2); field-shape validation is handled by the request schema
    before this runs (Req 1.3, 1.4, 1.5).
    """
    result = _auth_service(users).register(body.full_name, body.phone)
    return RegisterResponse(user_id=result.user.id, otp_sent=result.otp_sent)


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
    result = _auth_service(users).login(body.phone)
    return LoginResponse(jwt=result.token, expires_at=result.expires_at)
