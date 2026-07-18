"""``OtpCode`` ORM entity (table ``otp_codes``).

Stores a 6-digit code with an expiry of 10 minutes after generation
(Req 2.2), a failed-attempt counter that caps at 5 (Req 2.4/2.5), and an
``invalidated`` flag set on the 5th failed attempt or on resend (Req 2.5,
2.7). ``created_at`` timestamps back the 5-per-60-minute resend window
(Req 2.7/2.8).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType, new_uuid, utcnow


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    # 6-digit numeric code stored as text to preserve leading zeros (Req 2.1).
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    # expires_at = created_at + 10 minutes (Req 2.2).
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    invalidated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<OtpCode id={self.id!s} user={self.user_id!s} "
            f"failed_attempts={self.failed_attempts} invalidated={self.invalidated}>"
        )
