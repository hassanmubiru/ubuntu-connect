"""Messaging request/response schemas.

Covers sending a message (content 1-2000 chars, Req 6.1/6.5) and the message
representation returned in conversation history and live delivery, including
its moderation result, scam score, and any scam safety warning (Req 6.1,
8.3-8.5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MessageContent


class MessageSendRequest(BaseModel):
    """POST /api/messages body: the recipient and the message content."""

    receiver_id: uuid.UUID = Field(description="Identifier of the recipient.")
    content: MessageContent


class MessageResponse(BaseModel):
    """A stored/delivered message.

    ``scam_score`` is null until the scam detector has scored the message
    (Req 8.1, 8.6); ``scam_warning`` is set when the score is 70 or greater
    (Req 8.3).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender_id: uuid.UUID
    receiver_id: uuid.UUID
    content: str
    moderation_result: str = Field(
        description='One of "approved", "flagged", or "blocked".'
    )
    scam_score: int | None = Field(default=None, ge=0, le=100)
    delivered: bool
    created_at: datetime
    scam_warning: bool = Field(
        default=False,
        description="True when the message is flagged as a likely scam.",
    )
