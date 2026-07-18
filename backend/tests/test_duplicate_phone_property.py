"""Property test for duplicate-phone registration rejection (task 4.3).

Feature: ubuntu-connect, Property 2: For any phone already belonging to a
user, a subsequent registration with that phone is rejected and the total
user count is unchanged.

Validates: Requirements 1.2

Strategy
--------
The test drives registration end-to-end through a FastAPI ``TestClient`` that
mounts the real auth router and installs the real global exception handlers,
so the duplicate-phone path is exercised exactly as production code runs it.
The SMS gateway is overridden with a fake so the OTP trigger fired on the
first (successful) registration never touches the network.

For each generated example a fresh, thread-shared in-memory SQLite database is
created and torn down inside the test body (a context-manager engine). This
gives every Hypothesis example a clean, isolated data store and avoids the
function-scoped-fixture health-check warning that Hypothesis raises when a
``@given`` test consumes a per-function pytest fixture.

Each example:
* generates an E.164 phone (African prefixes) and two full names;
* registers a first user with that phone and asserts success (201);
* attempts a second registration with the *same* phone and asserts it is
  rejected with the ``conflict`` error envelope (HTTP 409);
* asserts the total user count is unchanged by the rejected second attempt.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app import db
from app.integrations.sms_gateway import SmsResult
from app.models import Base, User
from app.routers import auth as auth_router
from app.routers.dependencies import get_sms_gateway
from app.schemas.errors import register_exception_handlers


class _FakeSmsGateway:
    """SMS gateway stub that accepts every send, so tests avoid the network."""

    def send_otp(self, phone: str, code: str) -> SmsResult:
        return SmsResult(success=True)

    def send(self, phone: str, message: str) -> SmsResult:
        return SmsResult(success=True)


def _build_app() -> FastAPI:
    """App mounting the real auth router with a fake SMS gateway override."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.dependency_overrides[get_sms_gateway] = lambda: _FakeSmsGateway()
    return app


@contextmanager
def _isolated_store() -> Iterator[None]:
    """Bind a fresh, thread-shared in-memory store for a single example.

    A ``StaticPool`` keeps one underlying connection so the in-memory database
    is visible to both the test thread and the TestClient request thread. The
    engine is disposed and the global engine reset on exit.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


def _count_users() -> int:
    factory = db.get_session_factory()
    with factory() as session:
        return session.execute(select(func.count()).select_from(User)).scalar_one()


# --- Strategies --------------------------------------------------------------

# E.164 phones using realistic African country prefixes (Req 1.2 fixtures).
# The E.164 constraint is ^\+[1-9]\d{1,14}$; each prefix begins with a non-zero
# digit and the appended national number keeps the total within 15 digits.
_AFRICAN_PREFIXES = ["+234", "+27", "+233", "+254", "+255", "+256"]


@st.composite
def _e164_phones(draw: st.DrawFn) -> str:
    prefix = draw(st.sampled_from(_AFRICAN_PREFIXES))
    national_len = draw(st.integers(min_value=7, max_value=9))
    first = draw(st.integers(min_value=1, max_value=9))
    rest = draw(
        st.lists(
            st.integers(min_value=0, max_value=9),
            min_size=national_len - 1,
            max_size=national_len - 1,
        )
    )
    national = str(first) + "".join(str(d) for d in rest)
    return f"{prefix}{national}"


# Full names within the 2–100 character bound accepted by RegisterRequest.
_FULL_NAMES = st.one_of(
    st.sampled_from(
        ["Amara Okafor", "Thandiwe Nkosi", "Kwame Mensah", "Zainab Abdullahi"]
    ),
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=2,
        max_size=100,
    ),
)


# Feature: ubuntu-connect, Property 2: For any phone already belonging to a
# user, a subsequent registration with that phone is rejected and the total
# user count is unchanged.
# Validates: Requirements 1.2
@settings(max_examples=100)
@given(phone=_e164_phones(), first_name=_FULL_NAMES, second_name=_FULL_NAMES)
def test_duplicate_phone_registration_rejected_without_side_effects(
    phone: str, first_name: str, second_name: str
) -> None:
    with _isolated_store():
        client = TestClient(_build_app())

        # Arrange: the phone already belongs to a registered user.
        first = client.post(
            "/api/auth/register",
            json={"full_name": first_name, "phone": phone},
        )
        assert first.status_code == 201, first.text
        count_after_first = _count_users()
        assert count_after_first == 1

        # Act: a second registration reuses the same phone.
        second = client.post(
            "/api/auth/register",
            json={"full_name": second_name, "phone": phone},
        )

        # Assert: the duplicate is rejected with the conflict envelope...
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "conflict"

        # ...and the total user count is unchanged by the rejected attempt.
        assert _count_users() == count_after_first == 1
