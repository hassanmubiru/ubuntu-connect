"""``Report`` ORM entity (table ``reports``).

A report links a reporter to a reported user with a free-text reason
(1-1000 chars, Req 12.1/12.5) and a status of "pending" | "confirmed" |
"dismissed" (Req 12.1, 11.4). ``created_at`` is set at persistence and
drives the descending reports view (Req 11.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType, new_uuid, utcnow


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    reporter: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    reported_user: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    # status: "pending" | "confirmed" | "dismissed" (Req 12.1, 11.4).
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<Report id={self.id!s} reporter={self.reporter!s} "
            f"reported_user={self.reported_user!s} status={self.status!r}>"
        )
