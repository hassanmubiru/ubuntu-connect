"""``ReportRepository`` — all data-store access for the ``reports`` table.

Backs report creation with defaults (Req 12.1), the duplicate-pending-report
existence check (Req 12.6), the Trust Engine's confirmed-report count factor
(Req 5.4, 5.5), the Admin_Panel reports view (Req 11.3), and resolution
updates (Req 11.4, 11.6).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.report import Report
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[Report]):
    model = Report

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # -- create ---------------------------------------------------------
    def create(
        self,
        *,
        reporter: uuid.UUID,
        reported_user: uuid.UUID,
        reason: str,
        status: str = "pending",
    ) -> Report:
        """Insert a report with status "pending" by default (Req 12.1)."""
        report = Report(
            reporter=reporter,
            reported_user=reported_user,
            reason=reason,
            status=status,
        )
        return self.add(report)

    # -- reads ----------------------------------------------------------
    def get_by_id(self, report_id: uuid.UUID) -> Report | None:
        """Return the report with ``report_id`` or ``None``."""
        return self.get(report_id)

    def has_pending(
        self, reporter: uuid.UUID, reported_user: uuid.UUID
    ) -> bool:
        """Return ``True`` if this reporter already has a pending report
        against ``reported_user`` (Req 12.6)."""
        return (
            self.session.scalar(
                select(func.count())
                .select_from(Report)
                .where(Report.reporter == reporter)
                .where(Report.reported_user == reported_user)
                .where(Report.status == "pending")
            )
            or 0
        ) > 0

    def count_confirmed_against(self, reported_user: uuid.UUID) -> int:
        """Return the count of confirmed reports against a user (Req 5.4).

        This is the confirmed-report factor consumed by the Trust Engine.
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Report)
                .where(Report.reported_user == reported_user)
                .where(Report.status == "confirmed")
            )
            or 0
        )

    def list_ordered(self) -> list[Report]:
        """Return all reports ordered by ``created_at`` descending (Req 11.3)."""
        stmt = select(Report).order_by(
            Report.created_at.desc(), Report.id.desc()
        )
        return list(self.session.scalars(stmt).all())

    def list_confirmed_against(self, reported_user: uuid.UUID) -> list[Report]:
        """Return confirmed reports against a user, newest first (Req 11.2)."""
        stmt = (
            select(Report)
            .where(Report.reported_user == reported_user)
            .where(Report.status == "confirmed")
            .order_by(Report.created_at.desc(), Report.id.desc())
        )
        return list(self.session.scalars(stmt).all())

    # -- updates --------------------------------------------------------
    def set_status(self, report: Report, status: str) -> Report:
        """Update a report's status (Req 11.4) and flush."""
        report.status = status
        self.flush()
        return report
