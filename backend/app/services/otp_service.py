"""``OTPService`` — OTP generation, delivery, verification, and throttling (Req 2).

This service owns the full one-time-password lifecycle behind the
``/api/auth/verify-otp`` and ``/api/auth/resend-otp`` endpoints, and the OTP
that is issued when a user first registers (Req 2.1). Like every service it
touches the data store only through injected repositories (Req 15.1); the
Africa's Talking transport is the injected :class:`SmsGateway`.

Generation and delivery (Req 2.1, 2.2):
- a fresh code is six numeric digits, stored as text so a leading zero is
  preserved (e.g. ``"004217"``);
- the stored ``expires_at`` is exactly the creation time plus ten minutes;
- an SMS delivery is requested to the user's phone. When the gateway reports
  a delivery failure the code is still stored so the user can resend (Req 2.9).

Verification (Req 2.3–2.6) checks, in order, **match → expiry → attempt-count**:
- a code that matches and is submitted before expiry verifies the phone
  (Req 2.3);
- any submission at or after expiry is rejected as expired (Req 2.6);
- a non-matching code increments the failed-attempt count and is rejected as
  incorrect while fewer than five attempts have been made (Req 2.4); the fifth
  wrong submission invalidates the stored OTP and returns a maximum-attempts
  error (Req 2.5).

Resend throttling (Req 2.7, 2.8):
- while fewer than five OTP requests have been made for the user in the
  trailing sixty minutes, a resend invalidates any prior OTP, resets the
  failed-attempt count (a new code always starts at zero), and issues a
  replacement (Req 2.7);
- the sixth request inside that window is rejected with a resend-limit error
  that names the sixty-minute window (Req 2.8).

After a successful verification the optional ``on_verified`` hook is invoked so
the Trust Engine can recalculate the user's score (Req 5.2). The hook is
optional and injected, so this service does not hard-depend on the Trust
Engine module, which is delivered by a parallel task.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.integrations.sms_gateway import SmsGateway, SmsResult
from app.models.otp_code import OtpCode
from app.models.user import User
from app.repositories.otp_repository import OtpRepository
from app.repositories.user_repository import UserRepository
from app.schemas.errors import (
    NotFoundError,
    RateLimitedError,
    SendFailureError,
    ValidationAppError,
)

# --- OTP policy parameters (sourced from the requirements) ------------------

# Codes are six numeric digits (Req 2.1).
OTP_CODE_DIGITS: int = 6

# A stored OTP expires ten minutes after it is generated (Req 2.2).
OTP_TTL: timedelta = timedelta(minutes=10)

# The stored OTP is invalidated on the fifth failed attempt (Req 2.4, 2.5).
MAX_FAILED_ATTEMPTS: int = 5

# At most five OTP requests are allowed in any trailing sixty-minute window
# (Req 2.7, 2.8).
RESEND_WINDOW: timedelta = timedelta(minutes=60)
MAX_REQUESTS_PER_WINDOW: int = 5

# --- Client-facing (generic, safe) messages ---------------------------------

INCORRECT_CODE_MESSAGE = "The verification code is incorrect."
MAX_ATTEMPTS_MESSAGE = (
    "The maximum number of attempts has been reached. Request a new code."
)
EXPIRED_CODE_MESSAGE = (
    "The verification code has expired. Request a new code."
)
NO_ACTIVE_CODE_MESSAGE = (
    "There is no active verification code for this phone. Request a new code."
)
UNKNOWN_PHONE_MESSAGE = "No account matches that phone number."
SEND_FAILURE_MESSAGE = (
    "The verification code could not be sent. Please request it again."
)
RESEND_LIMIT_MESSAGE = (
    "The resend limit has been reached. You can request a new code after "
    "60 minutes."
)


def _now() -> datetime:
    """Return the current timezone-aware UTC time (single clock source)."""
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    """Return a cryptographically-random six-digit code, zero-padded.

    ``secrets`` gives an unpredictable code; zero-padding preserves leading
    zeros so the stored string is always exactly six digits (Req 2.1).
    """
    return f"{secrets.randbelow(10 ** OTP_CODE_DIGITS):0{OTP_CODE_DIGITS}d}"


@dataclass(frozen=True)
class IssuedOtp:
    """A freshly issued OTP and whether its SMS was accepted for delivery."""

    otp: OtpCode
    sms_delivered: bool


class OTPService:
    """OTP generation, verification, and resend throttling over repositories.

    The OTP and user repositories, the SMS gateway, and an optional
    ``on_verified`` hook are injected so the service is exercised directly in
    tests and provided per-request through dependency injection. ``clock`` is
    injectable so expiry and windowing can be tested deterministically.
    """

    def __init__(
        self,
        otps: OtpRepository,
        users: UserRepository,
        sms: SmsGateway,
        *,
        on_verified: Callable[[User], None] | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._otps = otps
        self._users = users
        self._sms = sms
        self._on_verified = on_verified
        self._clock = clock

    # -- issuing ------------------------------------------------------------

    def generate_and_send(self, user: User) -> bool:
        """Issue the first OTP for a newly registered user (Req 2.1, 2.2).

        Returns whether the SMS was accepted for delivery. The code is stored
        regardless of the send outcome so a failed delivery can be retried
        with a resend (Req 2.9). Intended as the ``otp_trigger`` supplied to
        :class:`~app.services.auth_service.AuthService` at registration.
        """
        return self._issue(user).sms_delivered

    def resend(self, phone: str) -> bool:
        """Invalidate any prior OTP and issue a replacement (Req 2.7–2.9).

        Enforces the five-per-sixty-minute cap before issuing: the sixth
        request in the trailing window is rejected with a resend-limit error
        naming the window (Req 2.8). A valid resend invalidates the prior OTP
        and resets the failed-attempt count by issuing a brand-new code
        (Req 2.7). If the replacement SMS cannot be sent, a send-failure error
        is raised while leaving the user free to request the code again
        (Req 2.9).
        """
        user = self._require_user(phone)

        since = self._clock() - RESEND_WINDOW
        if self._otps.count_requests_since(user.id, since) >= MAX_REQUESTS_PER_WINDOW:
            raise RateLimitedError(RESEND_LIMIT_MESSAGE)

        # Invalidate every active OTP first so the new code is the only one
        # that can verify, and its zero failed-attempt count is authoritative
        # (Req 2.7).
        self._otps.invalidate_all_for_user(user.id)

        issued = self._issue(user)
        if not issued.sms_delivered:
            raise SendFailureError(SEND_FAILURE_MESSAGE)
        return True

    # -- verification -------------------------------------------------------

    def verify(self, phone: str, code: str) -> bool:
        """Verify ``code`` for ``phone`` in match → expiry → attempt order.

        Returns ``True`` and sets ``verified_phone`` when a matching code is
        submitted before expiry (Req 2.3). Raises an expired error for any
        submission at or after expiry (Req 2.6), an incorrect-code error for a
        wrong code below the attempt cap (Req 2.4), and a maximum-attempts
        error — invalidating the OTP — on the fifth wrong submission (Req 2.5).
        """
        user = self._require_user(phone)

        otp = self._otps.get_active_for_user(user.id)
        if otp is None:
            raise NotFoundError(NO_ACTIVE_CODE_MESSAGE)

        expired = self._clock() >= _as_utc(otp.expires_at)

        # 1) match
        if secrets.compare_digest(otp.code, code):
            # 2) expiry — a correct but expired code is rejected (Req 2.6).
            if expired:
                raise ValidationAppError(EXPIRED_CODE_MESSAGE)
            self._users.set_verified_phone(user, True)
            # Invalidate the code so it cannot be replayed after success.
            self._otps.invalidate(otp)
            if self._on_verified is not None:
                self._on_verified(user)
            return True

        # No match. An expired OTP is still reported as expired for any
        # submission after its expiry, before any attempt is counted (Req 2.6).
        if expired:
            raise ValidationAppError(EXPIRED_CODE_MESSAGE)

        # 3) attempt-count (Req 2.4, 2.5)
        self._otps.increment_failed_attempts(otp)
        if otp.failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._otps.invalidate(otp)
            raise ValidationAppError(MAX_ATTEMPTS_MESSAGE)
        raise ValidationAppError(INCORRECT_CODE_MESSAGE)

    # -- internals ----------------------------------------------------------

    def _issue(self, user: User) -> IssuedOtp:
        """Create a stored OTP and request its SMS delivery (Req 2.1, 2.2)."""
        created_at = self._clock()
        otp = self._otps.create(
            user_id=user.id,
            code=_generate_code(),
            expires_at=created_at + OTP_TTL,
        )
        result: SmsResult = self._sms.send_otp(user.phone, otp.code)
        return IssuedOtp(otp=otp, sms_delivered=result.success)

    def _require_user(self, phone: str) -> User:
        """Return the user for ``phone`` or raise a not-found error."""
        user = self._users.get_by_phone(phone)
        if user is None:
            raise NotFoundError(UNKNOWN_PHONE_MESSAGE)
        return user


def _as_utc(moment: datetime) -> datetime:
    """Return ``moment`` as timezone-aware UTC for a safe comparison.

    SQLite (used under test) can return naive datetimes even for
    ``DateTime(timezone=True)`` columns; treat a naive value as UTC so expiry
    comparisons never raise on offset-naive/aware mismatches.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment
