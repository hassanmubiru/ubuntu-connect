"""Property test for safe unhandled-exception responses (task 3.3).

Feature: ubuntu-connect, Property 54: For any backend operation that raises an
unhandled exception, the response carries a generic message with no internal
details and previously persisted data is left unchanged.

Validates: Requirements 16.2

Strategy
--------
A small FastAPI app is built that installs the real global exception handlers
(``register_exception_handlers``) and exposes one write-path route wired to the
real transactional session dependency (``app.db.get_session``). The route, on
every request, mutates a *previously persisted* user and inserts a brand-new
user, then raises an arbitrary generated exception.

For each example Hypothesis generates:
* a varied exception *type* (built-ins plus a custom class whose name looks
  sensitive), and
* a message built from a sensitive-looking fragment plus a unique sentinel
  token,

and the test asserts that the response is the generic ``internal_error``
envelope, that none of the exception's internal details (message, sentinel
token, sensitive fragment, exception type name, or a stack-trace marker) leak
into the body, and that the transaction rolled back so the prior user is
unchanged and the interloper insert never persisted.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import db
from app.models import Base, User
from app.schemas.errors import register_exception_handlers

# The user seeded (and committed) before any faulting request runs. Its stored
# state must survive every unhandled exception unchanged (Req 16.2).
SEEDED_PHONE = "+27821234567"
SEEDED_NAME = "Thandiwe Nkosi"

# Mutable container the faulting route reads to decide what to do this request.
_PENDING: dict[str, object] = {}


class DatabaseCredentialError(Exception):
    """Custom exception whose name would be damaging if it leaked."""


# Exception constructors used to exercise varied unhandled-exception types.
_EXCEPTION_TYPES = [
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    ZeroDivisionError,
    PermissionError,
    DatabaseCredentialError,
]

# Sensitive-looking fragments that must never appear in a client response.
_SENSITIVE_FRAGMENTS = [
    "database password is hunter2",
    "AWS_SECRET_ACCESS_KEY=AKIAEXAMPLE",
    "connection string postg:secret@db",
    "/etc/passwd contents",
    "private RSA key -----BEGIN",
    "internal stack frame at line 42",
]


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/trigger")
    def _trigger(session: Session = Depends(db.get_session)) -> dict[str, str]:
        # Mutate previously persisted data...
        seeded = session.scalar(select(User).where(User.phone == SEEDED_PHONE))
        if seeded is not None:
            seeded.bio = str(_PENDING["sensitive_bio"])
            seeded.full_name = "TAMPERED NAME"
        # ...and insert a brand-new record...
        session.add(
            User(
                full_name="Interloper",
                phone=str(_PENDING["new_phone"]),
                interests=[],
            )
        )
        session.flush()  # push both writes into the open transaction
        # ...then fail with an arbitrary unhandled exception.
        raise _PENDING["exc"]  # type: ignore[misc]

    return app


# A message that packs a sensitive-looking fragment together with a unique
# sentinel token so we can assert with certainty that neither leaks.
def _messages() -> st.SearchStrategy[tuple[str, str, str]]:
    return st.tuples(
        st.sampled_from(_SENSITIVE_FRAGMENTS),
        st.integers(min_value=0, max_value=10_000_000),
    ).map(
        lambda pair: (
            # full message
            f"{pair[0]} :: sentineltok{pair[1]}xyz",
            # sensitive fragment
            pair[0],
            # unique sentinel token
            f"sentineltok{pair[1]}xyz",
        )
    )


@given(
    exc_type=st.sampled_from(_EXCEPTION_TYPES),
    message_bundle=_messages(),
    phone_suffix=st.integers(min_value=0, max_value=9_999_999),
)
def test_unhandled_exception_is_generic_and_leaves_data_unchanged(
    exc_type: type[Exception],
    message_bundle: tuple[str, str, str],
    phone_suffix: int,
) -> None:
    # Feature: ubuntu-connect, Property 54: For any backend operation that
    # raises an unhandled exception, the response carries a generic message
    # with no internal details and previously persisted data is left unchanged.
    message, fragment, token = message_bundle
    new_phone = f"+234701{phone_suffix:07d}"

    # Fresh, thread-shared in-memory database for full isolation per example.
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    try:
        # Seed and COMMIT the prior data before the faulting request.
        factory = db.get_session_factory()
        seed_session = factory()
        try:
            seed_session.add(
                User(full_name=SEEDED_NAME, phone=SEEDED_PHONE, interests=[])
            )
            seed_session.commit()
        finally:
            seed_session.close()

        _PENDING.clear()
        _PENDING.update(
            {
                "sensitive_bio": message,
                "new_phone": new_phone,
                "exc": exc_type(message),
            }
        )

        client = TestClient(_build_app(), raise_server_exceptions=False)
        resp = client.post("/trigger")

        # --- The response is the generic internal_error envelope -----------
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"]  # a non-empty, generic message
        assert body["error"]["fields"] == []

        # --- No internal details leak into the response body ---------------
        serialized = str(body)
        lowered = serialized.lower()
        assert message not in serialized
        assert token not in serialized
        assert fragment not in serialized
        assert exc_type.__name__.lower() not in lowered
        assert "traceback" not in lowered

        # --- Previously persisted data is left unchanged (rollback) --------
        verify = db.get_session_factory()()
        try:
            seeded = verify.scalar(
                select(User).where(User.phone == SEEDED_PHONE)
            )
            assert seeded is not None
            assert seeded.full_name == SEEDED_NAME  # tampering rolled back
            assert seeded.bio is None  # mutation rolled back
            # The interloper insert never survived the failed transaction.
            interloper = verify.scalar(
                select(User).where(User.phone == new_phone)
            )
            assert interloper is None
        finally:
            verify.close()
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()
