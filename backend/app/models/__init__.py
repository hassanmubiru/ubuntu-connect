"""SQLAlchemy ORM entities for Ubuntu Connect.

Importing this package registers every model on the shared
:class:`~app.models.base.Base` metadata, so ``Base.metadata.create_all``
sees the full schema. Re-exports the declarative base, shared helpers, and
each entity for convenient access (``from app.models import User``).
"""

from __future__ import annotations

from app.models.base import Base, JSONBType, UUIDType, new_uuid, utcnow
from app.models.message import Message
from app.models.notification_failure import NotificationFailure
from app.models.otp_code import OtpCode
from app.models.report import Report
from app.models.trust_reason import TrustReason
from app.models.user import User

__all__ = [
    "Base",
    "JSONBType",
    "UUIDType",
    "new_uuid",
    "utcnow",
    "User",
    "Message",
    "Report",
    "TrustReason",
    "OtpCode",
    "NotificationFailure",
]
