"""Profile router: bio, interests, photo, and profile view (Req 4, 9.4).

Thin HTTP handlers that authenticate the caller via the JWT guard
(:data:`CurrentUser`), validate the request body against the profile schemas,
delegate to :class:`ProfileService`, and return an explicit ``response_model``
so FastAPI documents both request and response schemas (Req 15.6). All
business rules — length/format/size validation, preservation of existing data
on rejection, and the object-storage key — live in the service.

Photo uploads are received as a raw binary request body with the image's
``Content-Type`` header rather than as multipart form data: the backend has no
multipart parser dependency, and a binary body is a clean fit for a
single-file upload. The service authenticates the true format from the
payload's magic bytes regardless of the declared content type.

Every successful update flows through the service's Trust Engine recalculation
hook (Req 5.3). The concrete engine is wired by a parallel task; until then the
hook is left unset and updates still succeed.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from app.config import Config
from app.repositories.dependencies import UserRepositoryDep
from app.routers.dependencies import CurrentUser
from app.schemas.profile import (
    BioUpdateRequest,
    InterestsUpdateRequest,
    PhotoUploadResponse,
    ProfileResponse,
)
from app.services.dependencies import TrustEngineDep
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _profile_service(users: UserRepositoryDep, trust: TrustEngineDep) -> ProfileService:
    """Build a request-scoped :class:`ProfileService`.

    The object-storage bucket is read from the environment-sourced config
    (Req 15.4); the repository and Trust Engine are the request-scoped
    instances from dependency injection so the whole request runs inside one
    transactional unit of work. The Trust Engine recalculation hook fires
    after any successful profile change so profile completeness is folded back
    into the score (Req 5.3).
    """
    return ProfileService(
        users,
        Config.from_env().photo_storage_bucket,
        trust_recalc=lambda user: trust.recalculate(user.id),
    )


@router.put(
    "/bio",
    response_model=ProfileResponse,
    summary="Update the authenticated user's bio (<=500 characters).",
)
def update_bio(
    body: BioUpdateRequest,
    current_user: CurrentUser,
    users: UserRepositoryDep,
    trust: TrustEngineDep,
) -> ProfileResponse:
    """Save a bio of at most 500 characters (Req 4.1, 4.2).

    A longer bio is rejected by the request schema before this runs, naming the
    ``bio`` field; the service enforces the same limit as a safety net.
    """
    updated = _profile_service(users, trust).update_bio(current_user, body.bio)
    return ProfileResponse.model_validate(updated)


@router.put(
    "/interests",
    response_model=ProfileResponse,
    summary="Update the authenticated user's interests (<=20 items, each <=50).",
)
def update_interests(
    body: InterestsUpdateRequest,
    current_user: CurrentUser,
    users: UserRepositoryDep,
) -> ProfileResponse:
    """Save up to 20 interests, each at most 50 characters (Req 4.3, 4.4).

    A list exceeding those limits is rejected naming the ``interests`` field
    and the previously stored interests are left unchanged.
    """
    updated = _profile_service(users).update_interests(current_user, body.interests)
    return ProfileResponse.model_validate(updated)


@router.post(
    "/photo",
    response_model=PhotoUploadResponse,
    summary="Upload a profile photo (JPEG or PNG, <=5 MB) as a binary body.",
)
async def upload_photo(
    request: Request,
    current_user: CurrentUser,
    users: UserRepositoryDep,
) -> PhotoUploadResponse:
    """Store a JPEG/PNG photo of at most 5 MB (Req 4.5, 4.6, 4.7).

    The raw image bytes are the request body and the declared format is the
    ``Content-Type`` header. A non-JPEG/PNG payload is rejected naming the
    accepted formats; a payload over 5 MB is rejected naming the size limit.
    """
    content = await request.body()
    content_type = request.headers.get("content-type")
    updated = _profile_service(users).update_photo(
        current_user, content, content_type
    )
    return PhotoUploadResponse(profile_photo=updated.profile_photo or "")


@router.get(
    "/{user_id}",
    response_model=ProfileResponse,
    summary="View a user's profile, including Trust_Score and Verified_Phone.",
)
def get_profile(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    users: UserRepositoryDep,
) -> ProfileResponse:
    """Return a user's profile with trust and verification state (Req 4.8, 9.4).

    An unknown ``user_id`` yields a not-found error.
    """
    user = _profile_service(users).get_profile(user_id)
    return ProfileResponse.model_validate(user)
