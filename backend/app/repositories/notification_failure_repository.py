"""``NotificationFailureRepository`` — data-store access for the
``notification_failures`` table (Req 14.4).

When every SMS delivery attempt for a notification fails, the
:class:`~app.services.notification_service.NotificationService` records the
failure here so it is auditable. Following the repository-boundary rule
(Req 15.1), this class owns all SQLAlchemy access for the table; services
persist failures through it rather than touching a session directly.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.notification_failure import NotificationFailure
from app.repositories.base import BaseRepository


class NotificationFailureRepository(BaseRepository[NotificationFailure]):
    model = NotificationFailure

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def create(
        self, *, phone: str, notification_type: str
    ) -> NotificationFailure:
        """Insert a failure record capturing the target phone number and the
        notification type (Req 14.4) and flush so its key is assigned."""
        failure = NotificationFailure(
            phone=phone, notification_type=notification_type
        )
        return self.add(failure)
