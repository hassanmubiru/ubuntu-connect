"""``TrustReason`` ORM entity (table ``trust_reasons``).

The Trust Engine writes one row per contributing factor on every
recalculation (Req 5.6): the factor name, its numeric contribution, and a
human-readable description. The explanation endpoint returns these rows
(Req 5.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType, new_uuid, utcnow


class TrustReason(Base):
    __tablename__ = "trust_reasons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    # factor name, e.g. "phone_verification", "profile_completeness".
    factor: Mapped[str] = mapped_column(String(50), nullable=False)
    # signed contribution this factor made to the score.
    contribution: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<TrustReason id={self.id!s} user={self.user_id!s} "
            f"factor={self.factor!r} contribution={self.contribution}>"
        )
