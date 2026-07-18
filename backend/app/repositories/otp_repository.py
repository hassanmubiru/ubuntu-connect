"""``OtpRepository`` — all data-store access for the ``otp_codes`` table.

Backs OTP generation/storage (Req 2.1, 2.2), verification lookups of the
active code (Req 2.3–2.6), attempt-count and invalidation updates
(Req 2.4, 2.5), and the 5-requests-per-60-minute resend throttle, which
counts OTP requests in the trailing 60-minute window (Req 2.7, 2.8).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.otp_code import OtpCode
from app.repositories.base import BaseRepository


class OtpRepository(BaseRepository[OtpCode]):
    model = OtpCode

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # -- create ---------------------------------------------------------
    def create(
        self,
        *,
        user_id: uuid.UUID,
        code: str,
        expires_at: datetime,
        failed_attempts: int = 0,
        invalidated: bool = False,
    ) -> OtpCode:
        """Insert a new OTP row (Req 2.1, 2.2) and flush to assign its id."""
        otp = OtpCode(
            user_id=user_id,
            code=code,
            expires_at=expires_at,
            failed_attempts=failed_attempts,
            invalidated=invalidated,
        )
        return self.add(otp)

    # -- reads ----------------------------------------------------------
    def get_by_id(self, otp_id: uuid.UUID) -> OtpCode | None:
        """Return the OTP with ``otp_id`` or ``None``."""
        return self.get(otp_id)

    def get_active_for_user(self, user_id: uuid.UUID) -> OtpCode | None:
        """Return the user's most recent non-invalidated OTP, if any.

        Verification and resend both act on the current active code; the
        latest by ``created_at`` is the authoritative one (Req 2.3–2.7).
        """
        stmt = (
            select(OtpCode)
            .where(OtpCode.user_id == user_id)
            .where(OtpCode.invalidated.is_(False))
            .order_by(OtpCode.created_at.desc(), OtpCode.id.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def count_requests_since(
        self, user_id: uuid.UUID, since: datetime
    ) -> int:
        """Return how many OTPs were created for a user at/after ``since``.

        Callers pass ``now - 60 minutes`` to enforce the resend cap of 5
        requests in the trailing 60-minute window (Req 2.7, 2.8).
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(OtpCode)
                .where(OtpCode.user_id == user_id)
                .where(OtpCode.created_at >= since)
            )
            or 0
        )

    # -- updates --------------------------------------------------------
    def increment_failed_attempts(self, otp: OtpCode) -> OtpCode:
        """Record a wrong submission (Req 2.4) and flush."""
        otp.failed_attempts += 1
        self.flush()
        return otp

    def invalidate(self, otp: OtpCode) -> OtpCode:
        """Invalidate a single OTP (Req 2.5) and flush."""
        otp.invalidated = True
        self.flush()
        return otp

    def invalidate_all_for_user(self, user_id: uuid.UUID) -> None:
        """Invalidate every active OTP for a user before a resend (Req 2.7)."""
        self.session.execute(
            update(OtpCode)
            .where(OtpCode.user_id == user_id)
            .where(OtpCode.invalidated.is_(False))
            .values(invalidated=True)
        )
        self.flush()
