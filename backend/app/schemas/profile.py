"""Profile request/response schemas.

Backs the bio (<=500), interests (<=20 items each <=50), and photo
(JPEG/PNG, <=5 MB) update endpoints, plus the profile view that includes the
user's Trust_Score and Verified_Phone state (Req 4.1-4.8, 9.4).

Photo uploads arrive as multipart files, so their format/size checks live in
the router/service using the constants in :mod:`app.schemas.common`; here we
define the response returned once a photo is stored.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Bio, Interests


class BioUpdateRequest(BaseModel):
    """PUT /api/profile/bio body: a bio of at most 500 characters."""

    bio: Bio


class InterestsUpdateRequest(BaseModel):
    """PUT /api/profile/interests body: up to 20 interests, each <=50 chars."""

    interests: Interests


class PhotoUploadResponse(BaseModel):
    """Result of a successful profile photo upload."""

    profile_photo: str = Field(
        description="Object-storage URL or key of the stored photo."
    )


class ProfileResponse(BaseModel):
    """A user profile, including trust and verification state (Req 4.8, 9.4)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    bio: str | None = None
    interests: list[str] = Field(default_factory=list)
    profile_photo: str | None = None
    trust_score: int = Field(ge=0, le=100)
    verified_phone: bool
