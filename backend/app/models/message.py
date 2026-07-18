"""``Message`` ORM entity (table ``messages``).

Every message travels the moderate -> scam -> persist -> deliver pipeline.
The record stores sender/receiver, content (1-2000 chars, Req 6.1/6.5), the
moderation label (Req 7.1), a nullable scam score (unset until scored,
Req 8.1/8.6), a delivered flag (Req 6.2/6.6), and a creation timestamp
used for ascending conversation history (Req 6.3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDType, new_uuid, utcnow


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    receiver_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(String(2000), nullable=False)
    # moderation_result: "approved" | "flagged" | "blocked" (Req 7.1).
    moderation_result: Mapped[str] = mapped_column(String(20), nullable=False)
    # scam_score: integer in [0,100], nullable until scored (Req 8.1, 8.6).
    scam_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # delivered flag, default false (Req 6.2, 6.6).
    delivered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<Message id={self.id!s} sender={self.sender_id!s} "
            f"receiver={self.receiver_id!s} moderation={self.moderation_result!r}>"
        )
