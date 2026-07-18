"""``TrustReasonRepository`` — data-store access for ``trust_reasons``.

The Trust Engine writes one row per contributing factor on every
recalculation (Req 5.6). Because each recalculation replaces the prior
explanation, this repository supports clearing a user's existing reasons
before writing the new set, and reading them back for the explanation
endpoint (Req 5.7, 5.8).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.trust_reason import TrustReason
from app.repositories.base import BaseRepository


class TrustReasonRepository(BaseRepository[TrustReason]):
    model = TrustReason

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # -- create ---------------------------------------------------------
    def create(
        self,
        *,
        user_id: uuid.UUID,
        factor: str,
        contribution: int,
        description: str,
    ) -> TrustReason:
        """Insert one reason entry for a contributing factor (Req 5.6)."""
        reason = TrustReason(
            user_id=user_id,
            factor=factor,
            contribution=contribution,
            description=description,
        )
        return self.add(reason)

    def add_many(
        self, user_id: uuid.UUID, reasons: Iterable[tuple[str, int, str]]
    ) -> list[TrustReason]:
        """Insert several ``(factor, contribution, description)`` rows.

        Used by the engine to record the full factor set produced by one
        recalculation in a single call (Req 5.6).
        """
        created: list[TrustReason] = []
        for factor, contribution, description in reasons:
            created.append(
                TrustReason(
                    user_id=user_id,
                    factor=factor,
                    contribution=contribution,
                    description=description,
                )
            )
        self.session.add_all(created)
        self.flush()
        return created

    # -- reads ----------------------------------------------------------
    def list_for_user(self, user_id: uuid.UUID) -> list[TrustReason]:
        """Return the recorded reason entries for a user (Req 5.7).

        Ordered by ``created_at`` ascending so factors read back in the
        order they were recorded. An empty list drives the no-explanation
        error path (Req 5.8).
        """
        stmt = (
            select(TrustReason)
            .where(TrustReason.user_id == user_id)
            .order_by(TrustReason.created_at.asc(), TrustReason.id.asc())
        )
        return list(self.session.scalars(stmt).all())

    def count_for_user(self, user_id: uuid.UUID) -> int:
        """Return how many reason entries a user currently has (Req 5.8)."""
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(TrustReason)
                .where(TrustReason.user_id == user_id)
            )
            or 0
        )

    # -- delete ---------------------------------------------------------
    def clear_for_user(self, user_id: uuid.UUID) -> None:
        """Remove a user's existing reasons before a recalculation (Req 5.6)."""
        self.session.execute(
            delete(TrustReason).where(TrustReason.user_id == user_id)
        )
        self.flush()
