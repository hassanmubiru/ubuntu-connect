"""FastAPI dependency providers for the repository layer (Req 15.1).

Services depend on repositories through these providers, never on a raw
session. Each provider takes the request-scoped transactional ``Session``
from :func:`app.db.get_session` and hands back a repository bound to it, so
the whole request runs as one unit of work while services stay free of any
``sqlalchemy`` import.

Usage in a router::

    from fastapi import Depends
    from app.repositories.dependencies import get_user_repository

    @router.post("/api/auth/register")
    def register(users: UserRepository = Depends(get_user_repository)):
        ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.repositories.message_repository import MessageRepository
from app.repositories.otp_repository import OtpRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.trust_reason_repository import TrustReasonRepository
from app.repositories.user_repository import UserRepository

# Reusable annotated session dependency so providers read cleanly.
SessionDep = Annotated[Session, Depends(get_session)]


def get_user_repository(session: SessionDep) -> UserRepository:
    """Provide a :class:`UserRepository` bound to the request session."""
    return UserRepository(session)


def get_message_repository(session: SessionDep) -> MessageRepository:
    """Provide a :class:`MessageRepository` bound to the request session."""
    return MessageRepository(session)


def get_report_repository(session: SessionDep) -> ReportRepository:
    """Provide a :class:`ReportRepository` bound to the request session."""
    return ReportRepository(session)


def get_otp_repository(session: SessionDep) -> OtpRepository:
    """Provide an :class:`OtpRepository` bound to the request session."""
    return OtpRepository(session)


def get_trust_reason_repository(session: SessionDep) -> TrustReasonRepository:
    """Provide a :class:`TrustReasonRepository` bound to the request session."""
    return TrustReasonRepository(session)


# Annotated aliases so services/routers can declare typed injected params:
#   users: UserRepositoryDep
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
MessageRepositoryDep = Annotated[
    MessageRepository, Depends(get_message_repository)
]
ReportRepositoryDep = Annotated[ReportRepository, Depends(get_report_repository)]
OtpRepositoryDep = Annotated[OtpRepository, Depends(get_otp_repository)]
TrustReasonRepositoryDep = Annotated[
    TrustReasonRepository, Depends(get_trust_reason_repository)
]
