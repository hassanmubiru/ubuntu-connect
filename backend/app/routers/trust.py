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

from app.schemas.trust import (
    TrustExplanationResponse,
    TrustReasonResponse,
    TrustScoreResponse,
)
from app.services.dependencies import TrustEngineDep

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get(
    "/{user_id}",
    response_model=TrustScoreResponse,
    summary="Get a user's current Trust_Score.",
)
def get_trust_score(
    user_id: uuid.UUID, trust: TrustEngineDep
) -> TrustScoreResponse:
    """Return the user's current Trust_Score, an integer in [0, 100] (Req 5.1).

    Rejects an unknown user with a not-found error.
    """
    return TrustScoreResponse(user_id=user_id, trust_score=trust.get_score(user_id))


@router.get(
    "/{user_id}/explanation",
    response_model=TrustExplanationResponse,
    summary="Get the recorded reason entries behind a user's Trust_Score.",
)
def get_trust_explanation(
    user_id: uuid.UUID, trust: TrustEngineDep
) -> TrustExplanationResponse:
    """Return the recorded reason entries for the user's score (Req 5.7).

    Rejects an unknown user with a not-found error, and a score with no
    recorded reason entries with a no-explanation-available error (Req 5.8).
    """
    reasons = trust.get_explanation(user_id)
    return TrustExplanationResponse(
        user_id=user_id,
        reasons=[TrustReasonResponse.model_validate(r) for r in reasons],
    )
