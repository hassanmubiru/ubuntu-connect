"""User reporting request/response schemas.

A report identifies a reported user and a reason of 1-1000 characters; the
created record carries a "pending" status and a creation timestamp
(Req 12.1, 12.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ReportReason


class ReportRequest(BaseModel):
    """POST /api/reports body: the reported user and the reason."""

    reported_user: uuid.UUID = Field(
        description="Identifier of the user being reported."
    )
    reason: ReportReason


class ReportResponse(BaseModel):
    """A stored report record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reporter: uuid.UUID
    reported_user: uuid.UUID
    reason: str
    status: str = Field(description='One of "pending", "confirmed", "dismissed".')
    created_at: datetime
