"""``ProfileService`` — bio, interests, and photo management (Req 4).

This service owns the business logic behind the profile endpoints. It never
touches a database session directly: all persistence flows through the
injected :class:`UserRepository`, keeping the repository boundary intact
(Req 15.1).

Responsibilities:

- **Bio** (Req 4.1, 4.2): persist a bio of at most 500 characters; reject a
  longer bio with a validation error naming the ``bio`` field.
- **Interests** (Req 4.3, 4.4): persist a list of at most 20 interests, each
  at most 50 characters; reject anything larger with a validation error
  naming the ``interests`` field **and leave the previously stored interests
  unchanged** (the service validates before it writes, so a rejected update
  never mutates the record).
- **Photo** (Req 4.5, 4.6, 4.7): accept a JPEG or PNG of at most 5 MB, storing
  the object-storage URL/key on the record; reject other formats with an
  error naming the accepted formats, and reject an oversized file with an
  error naming the size limit. The true format is detected from the file's
  magic bytes (with the declared content type as a secondary signal) so a
  mislabelled upload cannot slip through.
- **Display** (Req 4.8, 9.4): return the user record so the profile response
  can surface the current Trust_Score and Verified_Phone state.

Every successful update invokes the optional ``trust_recalc`` hook so the
Trust Engine can recompute profile-completeness (Req 5.3). The concrete Trust
Engine is built in a parallel task; wiring it here is optional, mirroring the
``otp_trigger`` hook on :class:`~app.services.auth_service.AuthService`. When
no hook is supplied the update still succeeds.
"""

from __future__ import annotations

import uuid
from typing import Callable

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.common import (
    BIO_MAX,
    INTEREST_ITEM_MAX,
    INTERESTS_MAX_ITEMS,
    MAX_PHOTO_BYTES,
    FieldError,
)
from app.schemas.errors import NotFoundError, ValidationAppError

# Magic-byte signatures of the accepted image formats (Req 4.5, 4.6).
# JPEG streams begin with the Start-Of-Image marker ``FF D8 FF``; PNG streams
# begin with the fixed 8-byte signature ``89 50 4E 47 0D 0A 1A 0A``.
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# File extensions used when building the stored object-storage key.
_EXTENSION_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png"}

# Client-facing (generic, safe) messages naming the relevant field/limit.
BIO_TOO_LONG_MESSAGE = f"Bio must be at most {BIO_MAX} characters."
INTERESTS_TOO_MANY_MESSAGE = (
    f"You may list at most {INTERESTS_MAX_ITEMS} interests."
)
INTEREST_TOO_LONG_MESSAGE = (
    f"Each interest must be at most {INTEREST_ITEM_MAX} characters."
)
PHOTO_FORMAT_MESSAGE = "Profile photo must be a JPEG or PNG image."
PHOTO_SIZE_MESSAGE = "Profile photo must be 5 MB or smaller."
PROFILE_NOT_FOUND_MESSAGE = "That profile could not be found."


def detect_image_format(content: bytes, content_type: str | None = None) -> str | None:
    """Return ``"image/jpeg"``/``"image/png"`` for a JPEG/PNG, else ``None``.

    The file's magic bytes are authoritative: a payload is only treated as a
    given format when it actually starts with that format's signature, so a
    mislabelled ``Content-Type`` cannot force acceptance. The declared
    ``content_type`` is accepted only as a tie-breaker when the bytes carry no
    recognizable signature (e.g. an empty payload), and even then only if it
    names one of the accepted formats.
    """
    if content.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if content.startswith(_PNG_MAGIC):
        return "image/png"
    return None


class ProfileService:
    """Validate and persist profile fields over a :class:`UserRepository`.

    ``photo_bucket`` is the environment-sourced object-storage bucket name
    (Req 15.4) used to build the stored photo key. ``trust_recalc`` is an
    optional hook invoked with the updated user after any successful profile
    change so the Trust Engine can recompute profile completeness (Req 5.3).
    """

    def __init__(
        self,
        users: UserRepository,
        photo_bucket: str,
        *,
        trust_recalc: Callable[[User], None] | None = None,
    ) -> None:
        self._users = users
        self._photo_bucket = photo_bucket
        self._trust_recalc = trust_recalc

    # -- reads --------------------------------------------------------------

    def get_profile(self, user_id: uuid.UUID) -> User:
        """Return the user whose profile is being displayed (Req 4.8, 9.4).

        Raises :class:`NotFoundError` when no user has ``user_id``. The caller
        renders the record — which carries the current Trust_Score and
        Verified_Phone state — into the profile response.
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(PROFILE_NOT_FOUND_MESSAGE)
        return user

    # -- bio ----------------------------------------------------------------

    def update_bio(self, user: User, bio: str | None) -> User:
        """Persist a bio of at most 500 characters (Req 4.1, 4.2).

        A bio longer than the limit is rejected with a validation error naming
        the ``bio`` field; nothing is written.
        """
        if bio is not None and len(bio) > BIO_MAX:
            raise ValidationAppError(
                BIO_TOO_LONG_MESSAGE,
                fields=[FieldError(field="bio", reason=BIO_TOO_LONG_MESSAGE)],
            )
        updated = self._users.update_bio(user, bio)
        self._trigger_recalc(updated)
        return updated

    # -- interests ----------------------------------------------------------

    def update_interests(self, user: User, interests: list[str]) -> User:
        """Persist up to 20 interests, each at most 50 characters (Req 4.3, 4.4).

        Validation runs before any write, so an update that exceeds the item
        count or per-item length is rejected with a validation error naming the
        ``interests`` field while the previously stored interests are left
        unchanged.
        """
        if len(interests) > INTERESTS_MAX_ITEMS:
            raise ValidationAppError(
                INTERESTS_TOO_MANY_MESSAGE,
                fields=[
                    FieldError(field="interests", reason=INTERESTS_TOO_MANY_MESSAGE)
                ],
            )
        if any(len(item) > INTEREST_ITEM_MAX for item in interests):
            raise ValidationAppError(
                INTEREST_TOO_LONG_MESSAGE,
                fields=[
                    FieldError(field="interests", reason=INTEREST_TOO_LONG_MESSAGE)
                ],
            )
        updated = self._users.update_interests(user, list(interests))
        self._trigger_recalc(updated)
        return updated

    # -- photo --------------------------------------------------------------

    def update_photo(
        self, user: User, content: bytes, content_type: str | None = None
    ) -> User:
        """Store a JPEG/PNG of at most 5 MB and associate it (Req 4.5, 4.6, 4.7).

        The real format is detected from the payload's magic bytes. A payload
        that is not JPEG or PNG is rejected with an error naming the accepted
        formats (Req 4.6); a payload larger than 5 MB is rejected with an error
        naming the size limit (Req 4.7). On success the object-storage URL/key
        is persisted on the user's record.
        """
        detected = detect_image_format(content, content_type)
        if detected is None:
            raise ValidationAppError(
                PHOTO_FORMAT_MESSAGE,
                fields=[FieldError(field="photo", reason=PHOTO_FORMAT_MESSAGE)],
            )
        if len(content) > MAX_PHOTO_BYTES:
            raise ValidationAppError(
                PHOTO_SIZE_MESSAGE,
                fields=[FieldError(field="photo", reason=PHOTO_SIZE_MESSAGE)],
            )

        photo_ref = self._build_photo_ref(user.id, detected)
        updated = self._users.update_profile_photo(user, photo_ref)
        self._trigger_recalc(updated)
        return updated

    # -- internals ----------------------------------------------------------

    def _build_photo_ref(self, user_id: uuid.UUID, content_type: str) -> str:
        """Return the object-storage key for a user's stored photo.

        The key namespaces the object under the configured bucket and the
        user id, with a random component so each upload is distinct and an
        extension reflecting the detected format.
        """
        extension = _EXTENSION_BY_TYPE[content_type]
        return f"{self._photo_bucket}/profiles/{user_id}/{uuid.uuid4().hex}.{extension}"

    def _trigger_recalc(self, user: User) -> None:
        """Invoke the optional Trust Engine recalculation hook (Req 5.3)."""
        if self._trust_recalc is not None:
            self._trust_recalc(user)
