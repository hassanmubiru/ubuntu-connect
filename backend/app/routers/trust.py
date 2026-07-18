"""Trust Engine router: current score and explanation (Req 5.1, 5.7, 5.8).

Thin HTTP handlers that resolve a user's Trust_Score and the recorded reason
entries behind it. Each endpoint declares an explicit ``response_model`` so
FastAPI documents both request and response schemas (Req 15.6); all scoring
logic lives in :class:`TrustEngine`, and every read flows through injected
repositories so the router never touches a session (Req 15.1).

* ``GET /api/trust/{userId}`` returns the user's current Trust_Score (Req 5.1).
* ``GET /api/trust/{userId}/explanation`` returns the recorded reason entries
  (Req 5.7), or a no-explanation-available error when none exist (Req 5.8).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.repositories.dependencies import (
    MessageRepositoryDep,
    ReportRepositoryDep,
    TrustReasonRepositoryDep,
    UserRepositoryDep,
)
from app.schemas.trust import (
    TrustExplanationResponse,
    TrustReasonResponse,
    TrustScoreResponse,
)
from app.services.trust_engine import TrustEngine

router = APIRouter(prefix="/api/trust", tags=["trust"])


def _trust_engine(
    users: UserRepositoryDep,
    messages: MessageRepositoryDep,
    reports: ReportRepositoryDep,
    trust_reasons: TrustReasonRepositoryDep,
) -> TrustEngine:
    """Build a request-scoped :class:`TrustEngine` over the repositories.

    All four repositories are the request-scoped instances from dependency
    injection, so any recalculation triggered elsewhere runs inside one
    transactional unit of work.
    """
    return TrustEngine(users, messages, reports, trust_reasons)


@router.get(
    "/{user_id}",
    response_model=TrustScoreResponse,
    summary="Get a user's current Trust_Score.",
)
def get_trust_score(
    user_id: uuid.UUID,
    users: UserRepositoryDep,
    messages: MessageRepositoryDep,
    reports: ReportRepositoryDep,
    trust_reasons: TrustReasonRepositoryDep,
) -> TrustScoreResponse:
    """Return the user's current Trust_Score, an integer in [0, 100] (Req 5.1).

    Rejects an unknown user with a not-found error.
    """
    engine = _trust_engine(users, messages, reports, trust_reasons)
    score = engine.get_score(user_id)
    return TrustScoreResponse(user_id=user_id, trust_score=score)


@router.get(
    "/{user_id}/explanation",
    response_model=TrustExplanationResponse,
    summary="Get the recorded reason entries behind a user's Trust_Score.",
)
def get_trust_explanation(
    user_id: uuid.UUID,
    users: UserRepositoryDep,
    messages: MessageRepositoryDep,
    reports: ReportRepositoryDep,
    trust_reasons: TrustReasonRepositoryDep,
) -> TrustExplanationResponse:
    """Return the recorded reason entries for the user's score (Req 5.7).

    Rejects an unknown user with a not-found error, and a score with no
    recorded reason entries with a no-explanation-available error (Req 5.8).
    """
    engine = _trust_engine(users, messages, reports, trust_reasons)
    reasons = engine.get_explanation(user_id)
    return TrustExplanationResponse(
        user_id=user_id,
        reasons=[TrustReasonResponse.model_validate(r) for r in reasons],
    )
