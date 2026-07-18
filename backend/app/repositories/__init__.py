"""Repository layer: all data-store access lives here (Req 15.1).

Business logic components never issue SQLAlchemy queries directly; they
receive these repositories through the FastAPI dependency providers in
:mod:`app.repositories.dependencies`. Re-exports the repository classes and
their providers for convenient import.
"""

from __future__ import annotations

from app.repositories.base import ASC, DESC, BaseRepository
from app.repositories.dependencies import (
    MessageRepositoryDep,
    OtpRepositoryDep,
    ReportRepositoryDep,
    TrustReasonRepositoryDep,
    UserRepositoryDep,
    get_message_repository,
    get_otp_repository,
    get_report_repository,
    get_trust_reason_repository,
    get_user_repository,
)
from app.repositories.message_repository import MessageRepository
from app.repositories.otp_repository import OtpRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.trust_reason_repository import TrustReasonRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "ASC",
    "DESC",
    "BaseRepository",
    "UserRepository",
    "MessageRepository",
    "ReportRepository",
    "OtpRepository",
    "TrustReasonRepository",
    "get_user_repository",
    "get_message_repository",
    "get_report_repository",
    "get_otp_repository",
    "get_trust_reason_repository",
    "UserRepositoryDep",
    "MessageRepositoryDep",
    "ReportRepositoryDep",
    "OtpRepositoryDep",
    "TrustReasonRepositoryDep",
]
