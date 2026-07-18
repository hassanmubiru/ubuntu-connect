"""``MessageRepository`` — all data-store access for the ``messages`` table.

Backs the messaging pipeline persistence (Req 6.1), ascending conversation
history (Req 6.3), offline retention/delivery (Req 6.6), the Trust Engine's
"messages sent" activity factor (Req 5.5), the admin flagged-message and
scam-alert views (Req 11.2, 11.7), and the USSD inbox preview (Req 13.7).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.message import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # -- create ---------------------------------------------------------
    def create(
        self,
        *,
        sender_id: uuid.UUID,
        receiver_id: uuid.UUID,
        content: str,
        moderation_result: str,
        scam_score: int | None = None,
        delivered: bool = False,
    ) -> Message:
        """Persist a message row (Req 6.1) and flush to assign its id."""
        message = Message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            content=content,
            moderation_result=moderation_result,
            scam_score=scam_score,
            delivered=delivered,
        )
        return self.add(message)

    # -- reads ----------------------------------------------------------
    def get_by_id(self, message_id: uuid.UUID) -> Message | None:
        """Return the message with ``message_id`` or ``None``."""
        return self.get(message_id)

    def conversation_between(
        self, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> list[Message]:
        """Return messages exchanged between two users, oldest first.

        Ordered by ``created_at`` ascending as required for conversation
        history (Req 6.3).
        """
        stmt = (
            select(Message)
            .where(
                or_(
                    (Message.sender_id == user_a)
                    & (Message.receiver_id == user_b),
                    (Message.sender_id == user_b)
                    & (Message.receiver_id == user_a),
                )
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def recent_for_receiver(
        self, receiver_id: uuid.UUID, limit: int = 5
    ) -> list[Message]:
        """Return a receiver's most recent messages, newest first (Req 13.7).

        Used by the USSD inbox preview, which shows at most the 5 latest.
        """
        stmt = (
            select(Message)
            .where(Message.receiver_id == receiver_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def count_sent_by(self, sender_id: uuid.UUID) -> int:
        """Return how many messages ``sender_id`` has sent (Req 5.5).

        This is the account-activity factor consumed by the Trust Engine.
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.sender_id == sender_id)
            )
            or 0
        )

    def list_flagged(self) -> list[Message]:
        """Return all flagged messages, newest first (Req 7.4, 11.2)."""
        stmt = (
            select(Message)
            .where(Message.moderation_result == "flagged")
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
        return list(self.session.scalars(stmt).all())

    def list_high_scam(self, threshold: int = 70) -> list[Message]:
        """Return messages with ``scam_score >= threshold``, newest first.

        Backs the Admin_Panel scam-alerts view (Req 8.4, 11.7).
        """
        stmt = (
            select(Message)
            .where(Message.scam_score.is_not(None))
            .where(Message.scam_score >= threshold)
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
        return list(self.session.scalars(stmt).all())

    # -- updates --------------------------------------------------------
    def set_scam_score(self, message: Message, scam_score: int) -> Message:
        """Store the assigned Scam_Score before delivery (Req 8.6) and flush."""
        message.scam_score = scam_score
        self.flush()
        return message

    def mark_delivered(self, message: Message, delivered: bool = True) -> Message:
        """Flag a message as delivered to an active session (Req 6.2) and flush."""
        message.delivered = delivered
        self.flush()
        return message
