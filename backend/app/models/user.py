"""``User`` ORM entity (table ``users``).

Backs registration and identity requirements: a user is created with
``verified_phone`` false and ``trust_score`` 0 (Req 1.1), stores a unique
E.164 phone (Req 1.2), optional bio/interests/photo (Req 4), and a
``created_at`` timestamp set at persistence (Req 1.6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONBType, UUIDType, new_uuid, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=new_uuid
    )
    # full_name 2-100 chars enforced at the schema layer (Req 1.1, 1.5).
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # E.164 phone, globally unique (Req 1.2, 1.3).
    phone: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True
    )
    # bio <=500 chars, optional (Req 4.1, 4.2).
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # interests: JSONB array of strings, <=20 items each <=50 chars (Req 4.3).
    interests: Mapped[list[str]] = mapped_column(
        JSONBType, nullable=False, default=list
    )
    # object-storage URL/key for the profile photo, optional (Req 4.5).
    profile_photo: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # trust_score integer in [0,100], default 0 (Req 1.1, 5.1).
    trust_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # verified_phone, default false until OTP verification (Req 1.1, 2.3).
    verified_phone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # is_admin gates the Admin_Panel (Req 11.1).
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User id={self.id!s} phone={self.phone!r} verified={self.verified_phone}>"
