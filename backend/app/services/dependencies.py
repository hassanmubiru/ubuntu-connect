"""FastAPI dependency providers for the service layer.

Services are constructed from request-scoped repositories so the whole request
runs as one transactional unit of work and no route handler touches a session
directly (Req 15.1). This module currently exposes the Trust Engine provider,
the shared recalculation entry point other feature routers (OTP verification,
profile updates, confirmed-report resolution, message activity) depend on to
recompute a user's Trust_Score after the events in Req 5.2–5.5.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.repositories.dependencies import (
    MessageRepositoryDep,
    ReportRepositoryDep,
    TrustReasonRepositoryDep,
    UserRepositoryDep,
)
from app.services.trust_engine import TrustEngine


def get_trust_engine(
    users: UserRepositoryDep,
    messages: MessageRepositoryDep,
    reports: ReportRepositoryDep,
    trust_reasons: TrustReasonRepositoryDep,
) -> TrustEngine:
    """Provide a request-scoped :class:`TrustEngine` over the repositories."""
    return TrustEngine(users, messages, reports, trust_reasons)


# Annotated alias so routers/services can inject the engine directly:
#   trust: TrustEngineDep
TrustEngineDep = Annotated[TrustEngine, Depends(get_trust_engine)]
