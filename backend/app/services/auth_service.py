"""``AuthService`` — registration, login, and JWT issuance (Req 1, 3).

This service owns the business logic behind the ``/api/auth/register`` and
``/api/auth/login`` endpoints. It never touches a database session directly:
all persistence flows through the injected :class:`UserRepository`, keeping
the repository boundary intact (Req 15.1).

Registration (Req 1):
- rejects a phone that already belongs to a user, persisting nothing
  (Req 1.2 → :class:`ConflictError`);
- otherwise creates exactly one user with ``verified_phone`` false,
  ``trust_score`` 0, and ``created_at`` set at persistence (Req 1.1, 1.6).
  Field-shape validation (E.164 phone, 2–100 char full name) is enforced by
  the ``RegisterRequest`` schema before the service runs (Req 1.3, 1.4, 1.5).
- On user creation an OTP delivery should be triggered (Req 2.1). The concrete
  OTP service is built in a later task; this service exposes a clean,
  optional ``otp_trigger`` hook so that wiring can be added without changing
  the registration flow. When no trigger is supplied, ``otp_sent`` is False.

Login (Req 3):
- issues a JWT identifying the user only when the phone matches a record whose
  ``verified_phone`` is true (Req 3.1);
- rejects an unverified account with a verification-required error (Req 3.2);
- rejects an unknown phone with an authentication error (Req 3.3).
The issued JWT expires exactly 24 hours after issuance (Req 3.5). Missing
credential fields are rejected by the ``LoginRequest`` schema (Req 3.4).

The JWT encode/decode helpers live here as pure functions so both the login
flow and the request auth-guard dependency (``app.routers.dependencies``)
share one token format.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from jose import JWTError, jwt

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.errors import AuthError, ConflictError

# --- JWT parameters ---------------------------------------------------------

# HMAC-SHA256 keyed with the configured JWT secret; symmetric signing keeps
# verification dependency-free on every protected request.
JWT_ALGORITHM: str = "HS256"

# Every issued token expires 24 hours after it is issued (Req 3.5).
TOKEN_TTL: timedelta = timedelta(hours=24)

# Client-facing (generic, safe) messages. Login distinguishes the two reject
# reasons required by the spec while staying in the auth error category.
PHONE_ALREADY_REGISTERED_MESSAGE = "That phone number is already registered."
VERIFICATION_REQUIRED_MESSAGE = (
    "Phone verification is required before you can log in."
)
INVALID_CREDENTIALS_MESSAGE = "No account matches those credentials."
INVALID_TOKEN_MESSAGE = "Authentication is required or the credentials are invalid."


def _now() -> datetime:
    """Return the current timezone-aware UTC time (single clock source)."""
    return datetime.now(timezone.utc)


def create_access_token(
    user_id: uuid.UUID,
    secret: str,
    *,
    issued_at: datetime | None = None,
) -> tuple[str, datetime]:
    """Encode a signed JWT identifying ``user_id`` and return ``(token, exp)``.

    The token carries the user id as its ``sub`` claim, an ``iat`` issue time,
    and an ``exp`` set to exactly 24 hours after issuance (Req 3.5). The
    absolute expiry ``datetime`` is returned alongside the token so the login
    response can report it without re-decoding.
    """
    iat = issued_at or _now()
    # Normalize to whole seconds: JWT numeric dates are UNIX timestamps, so a
    # token's expiry is exactly issue-second + 24h with no sub-second drift.
    iat = iat.replace(microsecond=0)
    expires_at = iat + TOKEN_TTL
    claims = {
        "sub": str(user_id),
        "iat": int(iat.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str, secret: str) -> uuid.UUID:
    """Verify ``token`` and return the user id in its ``sub`` claim.

    Raises :class:`AuthError` when the token is missing, malformed, tampered,
    expired, or carries no valid user id (Req 3.6). Expiry is enforced by the
    decoder via the ``exp`` claim.
    """
    if not token:
        raise AuthError(INVALID_TOKEN_MESSAGE)
    try:
        claims = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:  # covers invalid signature and expired tokens
        raise AuthError(INVALID_TOKEN_MESSAGE) from exc

    subject = claims.get("sub")
    if not subject:
        raise AuthError(INVALID_TOKEN_MESSAGE)
    try:
        return uuid.UUID(str(subject))
    except (ValueError, TypeError) as exc:
        raise AuthError(INVALID_TOKEN_MESSAGE) from exc


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of a successful registration: the new user and OTP status."""

    user: User
    otp_sent: bool


@dataclass(frozen=True)
class LoginResult:
    """Outcome of a successful login: the JWT and its absolute expiry."""

    token: str
    expires_at: datetime


class AuthService:
    """Registration, login, and JWT issuance over a :class:`UserRepository`.

    The repository and JWT secret are injected so the service can be exercised
    directly in tests and provided per-request through dependency injection.
    ``otp_trigger`` is an optional hook invoked with the freshly created user
    on registration; it returns whether an OTP SMS was requested (Req 2.1).
    Later tasks supply the concrete OTP trigger; the default leaves it unsent.
    """

    def __init__(
        self,
        users: UserRepository,
        jwt_secret: str,
        *,
        otp_trigger: Callable[[User], bool] | None = None,
    ) -> None:
        self._users = users
        self._jwt_secret = jwt_secret
        self._otp_trigger = otp_trigger

    # -- registration -------------------------------------------------------

    def register(self, full_name: str, phone: str) -> RegistrationResult:
        """Create a new user, rejecting a duplicate phone (Req 1.1, 1.2, 1.6).

        The ``full_name`` and ``phone`` arrive already validated and trimmed by
        the ``RegisterRequest`` schema. If ``phone`` already belongs to a user,
        no record is written and a :class:`ConflictError` is raised (Req 1.2).
        Otherwise a single user is created with the required defaults, and the
        optional OTP trigger is invoked to request phone verification (Req 2.1).
        """
        if self._users.exists_by_phone(phone):
            raise ConflictError(PHONE_ALREADY_REGISTERED_MESSAGE)

        user = self._users.create(
            full_name=full_name,
            phone=phone,
            verified_phone=False,
            trust_score=0,
        )

        otp_sent = False
        if self._otp_trigger is not None:
            otp_sent = bool(self._otp_trigger(user))

        return RegistrationResult(user=user, otp_sent=otp_sent)

    # -- login --------------------------------------------------------------

    def login(self, phone: str) -> LoginResult:
        """Authenticate by phone and issue a 24h JWT (Req 3.1, 3.2, 3.3, 3.5).

        A phone matching no record raises an authentication error (Req 3.3); a
        matched but unverified account raises a verification-required error
        (Req 3.2). Only a verified account yields a JWT that identifies the
        user and expires 24 hours after issuance (Req 3.1, 3.5).
        """
        user = self._users.get_by_phone(phone)
        if user is None:
            raise AuthError(INVALID_CREDENTIALS_MESSAGE)
        if not user.verified_phone:
            raise AuthError(VERIFICATION_REQUIRED_MESSAGE)

        token, expires_at = create_access_token(user.id, self._jwt_secret)
        return LoginResult(token=token, expires_at=expires_at)
