"""``NotificationFailure`` ORM entity (table ``notification_failures``).

When every SMS delivery attempt for a notification fails, Ubuntu Connect
records the failure with the target phone number and the notification type
(Req 14.4) so it is auditable even though the message never reached the user.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType, new_uuid, utcnow


class NotificationFailure(Base):
    __tablename__ = "notification_failures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    # target phone number for the undeliverable notification (Req 14.4).
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # notification type, e.g. "otp", "match", "safety_alert" (Req 14.4).
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<NotificationFailure id={self.id!s} phone={self.phone!r} "
            f"type={self.notification_type!r}>"
        )
