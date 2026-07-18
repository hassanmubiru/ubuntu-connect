"""Admin panel request/response schemas.

Report resolution accepts only "confirmed" or "dismissed"; any other decision
is a validation error naming the accepted values (Req 11.4, 11.5). Using a
``Literal`` means Pydantic rejects other values before the service runs and
the resulting field error enumerates the allowed decisions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The only decisions an administrator may apply to a pending report.
ReportDecision = Literal["confirmed", "dismissed"]


class ReportResolutionRequest(BaseModel):
    """PUT/POST resolution body: the decision to apply to a pending report."""

    decision: ReportDecision = Field(
        description='Resolution decision: "confirmed" or "dismissed".'
    )


class ReportResolutionResponse(BaseModel):
    """The report's updated status after resolution."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str = Field(description="Updated report status.")


class FlaggedUserResponse(BaseModel):
    """A user surfaced in the flagged-users view (Req 11.2)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    trust_score: int = Field(ge=0, le=100)
    verified_phone: bool


class ScamAlertResponse(BaseModel):
    """A message surfaced in the scam-alerts view (Req 11.7)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    content: str
    scam_score: int = Field(ge=0, le=100)
    created_at: datetime
