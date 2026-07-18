"""Trust Engine request/response schemas.

Backs the current-score endpoint and the explanation endpoint that returns
one reason entry per contributing factor (Req 5.1, 5.6, 5.7).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class TrustReasonResponse(BaseModel):
    """One recorded contributing factor behind a Trust_Score (Req 5.6)."""

    model_config = ConfigDict(from_attributes=True)

    factor: str = Field(description="Name of the contributing factor.")
    contribution: int = Field(description="Signed contribution to the score.")
    description: str = Field(description="Human-readable explanation.")


class TrustScoreResponse(BaseModel):
    """A user's current Trust_Score, an integer in [0, 100] (Req 5.1)."""

    user_id: uuid.UUID
    trust_score: int = Field(ge=0, le=100)


class TrustExplanationResponse(BaseModel):
    """The recorded reason entries for a user's Trust_Score (Req 5.7)."""

    user_id: uuid.UUID
    reasons: list[TrustReasonResponse] = Field(default_factory=list)
