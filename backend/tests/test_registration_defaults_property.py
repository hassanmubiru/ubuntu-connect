"""Property test for registration establishing defaults (task 4.2).

Feature: ubuntu-connect, Property 1: For any valid full name (2-100 characters)
and any E.164 phone not already registered, registering creates exactly one
user record with verified_phone false, trust_score 0, and created_at set.

Validates: Requirements 1.1, 1.6

Strategy
--------
Valid full names are generated as 2-100 non-whitespace-bordered strings, and
E.164 phones are built from the platform's African country prefixes (+234,
+27, +233, +254) followed by a national number, so every generated phone
matches the ``E164_PATTERN`` the ``RegisterRequest`` schema enforces.

Each generated example runs against its own fresh in-memory SQLite database
(via a context-manager engine, the pattern from ``test_notification_retry_property``)
so the DB starts empty and the generated phone is guaranteed not already
registered. The real :class:`AuthService` drives registration over a real
:class:`UserRepository`; the OTP trigger is left unset so no SMS/network is
touched. We assert exactly one user record exists and that it carries the
required defaults (``verified_phone`` false, ``trust_score`` 0) with
``created_at`` set at persistence.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.models import Base, User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest
from app.services.auth_service import AuthService

JWT_SECRET = "test-jwt-secret"


@contextmanager
def _in_memory_session():
    """Yield a live session on a fresh, isolated in-memory SQLite engine.

    A context manager (rather than a function-scoped fixture) so each generated
    Hypothesis example runs against its own reset database, avoiding the
    function-scoped-fixture health-check warning.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    session = db.get_session_factory()()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        db.reset_engine()


# Valid full names: 2-100 characters with no leading/trailing whitespace, so
# they pass the schema's trim-and-length rule (Req 1.1, 1.5).
_FULL_NAME = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF),
    min_size=2,
    max_size=100,
).map(lambda s: s.strip()).filter(lambda s: 2 <= len(s) <= 100)

# E.164 African phones: one of the platform's country prefixes followed by a
# national number, kept within E.164's 15-digit total (Req 1.1, matches
# E164_PATTERN ``^\+[1-9]\d{1,14}$``).
_PHONE_PREFIX = st.sampled_from(["234", "27", "233", "254"])


@st.composite
def _e164_phone(draw) -> str:
    prefix = draw(_PHONE_PREFIX)
    # Leave room so prefix + national digits never exceeds 15 total digits.
    max_national = 15 - len(prefix)
    national = draw(
        st.text(alphabet="0123456789", min_size=7, max_size=max_national)
    )
    return "+" + prefix + national


# Feature: ubuntu-connect, Property 1: For any valid full name (2-100
# characters) and any E.164 phone not already registered, registering creates
# exactly one user record with verified_phone false, trust_score 0, and
# created_at set.
# Validates: Requirements 1.1, 1.6
@settings(max_examples=100)
@given(full_name=_FULL_NAME, phone=_e164_phone())
def test_registration_establishes_defaults(full_name: str, phone: str) -> None:
    # The schema is the real entry point; it trims/validates before the service
    # runs, so route the generated inputs through it to mirror production.
    request = RegisterRequest(full_name=full_name, phone=phone)

    with _in_memory_session() as session:
        users = UserRepository(session)
        service = AuthService(users, JWT_SECRET)

        # Precondition: the phone is not already registered (fresh DB).
        assert users.exists_by_phone(request.phone) is False

        result = service.register(request.full_name, request.phone)
        session.flush()

        # Exactly one user record is created.
        assert users.count_users() == 1

        created = result.user
        assert created.verified_phone is False
        assert created.trust_score == 0
        assert isinstance(created.created_at, datetime)

        # The persisted record round-trips with the same defaults.
        persisted = users.get_by_phone(request.phone)
        assert persisted is not None
        assert persisted.id == created.id
        assert persisted.full_name == request.full_name
        assert persisted.verified_phone is False
        assert persisted.trust_score == 0
        assert isinstance(persisted.created_at, datetime)
        assert isinstance(persisted, User)
