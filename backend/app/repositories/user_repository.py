"""``UserRepository`` — all data-store access for the ``users`` table (Req 15.1).

Backs registration (unique-phone existence check, Req 1.2), login lookups
(Req 3.x), profile persistence (Req 4), and the Trust Engine / USSD reads.
No SQLAlchemy queries for users live outside this class.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def __init__(self, session: Session) -> None:
        super().__init__(session)

    # -- create ---------------------------------------------------------
    def create(
        self,
        *,
        full_name: str,
        phone: str,
        bio: str | None = None,
        interests: list[str] | None = None,
        profile_photo: str | None = None,
        verified_phone: bool = False,
        trust_score: int = 0,
        is_admin: bool = False,
    ) -> User:
        """Insert a new user with registration defaults (Req 1.1, 1.6).

        ``created_at`` and ``id`` come from model defaults; the row is
        flushed so the generated ``id`` and the unique-phone constraint are
        observable within the request.
        """
        user = User(
            full_name=full_name,
            phone=phone,
            bio=bio,
            interests=interests if interests is not None else [],
            profile_photo=profile_photo,
            verified_phone=verified_phone,
            trust_score=trust_score,
            is_admin=is_admin,
        )
        return self.add(user)

    # -- reads ----------------------------------------------------------
    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with ``user_id`` or ``None``."""
        return self.get(user_id)

    def get_by_phone(self, phone: str) -> User | None:
        """Return the user registered with ``phone`` or ``None`` (Req 3.x)."""
        return self.session.scalar(select(User).where(User.phone == phone))

    def exists_by_phone(self, phone: str) -> bool:
        """Return ``True`` if a user already owns ``phone`` (Req 1.2)."""
        return (
            self.session.scalar(
                select(func.count()).select_from(User).where(User.phone == phone)
            )
            or 0
        ) > 0

    def count_users(self) -> int:
        """Return the total number of registered users (Req 1.2 checks)."""
        return self.count()

    # -- updates --------------------------------------------------------
    def set_verified_phone(self, user: User, verified: bool = True) -> User:
        """Mark the user's phone verified/unverified (Req 2.3) and flush."""
        user.verified_phone = verified
        self.flush()
        return user

    def update_bio(self, user: User, bio: str | None) -> User:
        """Persist a new bio value (Req 4.1) and flush."""
        user.bio = bio
        self.flush()
        return user

    def update_interests(self, user: User, interests: list[str]) -> User:
        """Persist a new interests list (Req 4.3) and flush."""
        user.interests = interests
        self.flush()
        return user

    def update_profile_photo(self, user: User, photo_ref: str | None) -> User:
        """Persist the stored photo URL/key (Req 4.5) and flush."""
        user.profile_photo = photo_ref
        self.flush()
        return user

    def set_trust_score(self, user: User, trust_score: int) -> User:
        """Persist a recalculated Trust_Score (Req 5) and flush."""
        user.trust_score = trust_score
        self.flush()
        return user
