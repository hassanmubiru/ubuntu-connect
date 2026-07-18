"""Property test for validation rejection with per-field reasons (task 3.2).

Exercises the platform's global validation behaviour end-to-end through a
FastAPI ``TestClient`` backed by an in-memory data store: for any request
whose body fails schema validation, the request must be rejected with the
shared error envelope, the envelope must name every invalid field together
with the reason it failed, and nothing must be written to the data store.

The app under test registers the real global exception handlers
(``app.schemas.errors.register_exception_handlers``) and mounts write
endpoints that use the real request schemas (``RegisterRequest``,
``BioUpdateRequest``, ``InterestsUpdateRequest``, ``MessageSendRequest``,
``ReportRequest``). Each write endpoint depends on the transactional
``get_session`` and, on valid input, persists a row. Because validation runs
before the handler body, an invalid request never reaches the write, so the
store's row count is invariant across every generated invalid request.
"""

from __future__ import annotations

import string
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import db
from app.db import get_session
from app.models import Base, User
from app.schemas.auth import RegisterRequest
from app.schemas.common import (
    BIO_MAX,
    FULL_NAME_MAX,
    INTEREST_ITEM_MAX,
    INTERESTS_MAX_ITEMS,
    MESSAGE_CONTENT_MAX,
    REPORT_REASON_MAX,
)
from app.schemas.errors import register_exception_handlers
from app.schemas.message import MessageSendRequest
from app.schemas.profile import BioUpdateRequest, InterestsUpdateRequest
from app.schemas.report import ReportRequest

# A synthetic but unique E.164 phone per persisted row, so the write a handler
# *would* perform never collides with the seeded baseline rows.
_write_counter = {"n": 0}


def _next_phone() -> str:
    _write_counter["n"] += 1
    return f"+199{_write_counter['n']:07d}"


def _build_app() -> FastAPI:
    """Build an app whose write endpoints persist a row on valid input."""
    app = FastAPI()
    register_exception_handlers(app)

    def _write(session: Session) -> None:
        # Represents the data-store mutation each write endpoint performs on
        # success. Reached only when the body validates.
        session.add(User(full_name="Written By Handler", phone=_next_phone()))

    @app.post("/register")
    def _register(
        body: RegisterRequest, session: Session = Depends(get_session)
    ) -> dict[str, bool]:
        _write(session)
        return {"ok": True}

    @app.post("/bio")
    def _bio(
        body: BioUpdateRequest, session: Session = Depends(get_session)
    ) -> dict[str, bool]:
        _write(session)
        return {"ok": True}

    @app.post("/interests")
    def _interests(
        body: InterestsUpdateRequest, session: Session = Depends(get_session)
    ) -> dict[str, bool]:
        _write(session)
        return {"ok": True}

    @app.post("/message")
    def _message(
        body: MessageSendRequest, session: Session = Depends(get_session)
    ) -> dict[str, bool]:
        _write(session)
        return {"ok": True}

    @app.post("/report")
    def _report(
        body: ReportRequest, session: Session = Depends(get_session)
    ) -> dict[str, bool]:
        _write(session)
        return {"ok": True}

    return app


@pytest.fixture(scope="module")
def harness():
    """Bind a shared in-memory SQLite store, seed a baseline, yield a client.

    A ``StaticPool`` keeps a single underlying connection so the same
    in-memory database is visible to both the test and the request thread.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)

    factory = db.get_session_factory()
    # Seed a non-empty baseline so "count unchanged" is a meaningful assertion.
    with factory() as seed:
        seed.add_all(
            [
                User(full_name="Amara Okafor", phone="+2348031234567"),
                User(full_name="Thandiwe Nkosi", phone="+27821234567"),
                User(full_name="Kwame Mensah", phone="+233201234567"),
            ]
        )
        seed.commit()

    def count_users() -> int:
        with factory() as s:
            return s.execute(select(func.count()).select_from(User)).scalar_one()

    client = TestClient(_build_app())
    baseline = count_users()
    try:
        yield client, count_users, baseline
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


# --- Strategies producing invalid request cases ------------------------------

_VALID_NAME = st.sampled_from(
    ["Amara Okafor", "Thandiwe Nkosi", "Kwame Mensah", "Zainab Abdullahi"]
)
_VALID_PHONE = st.sampled_from(
    ["+2348031234567", "+27821234567", "+233201234567", "+254712345678"]
)

# full_name values that always fail validation: empty, single char (too short),
# whitespace-only (blank after trimming), or longer than the 100-char maximum.
_INVALID_NAME = st.one_of(
    st.just(""),
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=1),
    st.text(alphabet=" \t", min_size=1, max_size=4),
    st.text(alphabet=string.ascii_letters, min_size=FULL_NAME_MAX + 1, max_size=FULL_NAME_MAX + 20),
)

# phone values that never match the E.164 pattern ^\+[1-9]\d{1,14}$.
_INVALID_PHONE = st.one_of(
    st.just(""),
    st.just("+"),
    st.just("2348031234567"),  # missing leading '+'
    st.just("+0348031234567"),  # leading zero after '+'
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=10),
    st.from_regex(r"\+[1-9][0-9]{15,20}", fullmatch=True),  # too many digits
)


@st.composite
def _register_case(draw):
    """An invalid /register body plus the field roots that must be flagged."""
    variant = draw(
        st.sampled_from(
            [
                "bad_name",
                "bad_phone",
                "bad_both",
                "missing_name",
                "missing_phone",
                "missing_both",
            ]
        )
    )
    if variant == "bad_name":
        return {
            "path": "/register",
            "json": {"full_name": draw(_INVALID_NAME), "phone": draw(_VALID_PHONE)},
            "roots": {"full_name"},
        }
    if variant == "bad_phone":
        return {
            "path": "/register",
            "json": {"full_name": draw(_VALID_NAME), "phone": draw(_INVALID_PHONE)},
            "roots": {"phone"},
        }
    if variant == "bad_both":
        return {
            "path": "/register",
            "json": {"full_name": draw(_INVALID_NAME), "phone": draw(_INVALID_PHONE)},
            "roots": {"full_name", "phone"},
        }
    if variant == "missing_name":
        return {
            "path": "/register",
            "json": {"phone": draw(_VALID_PHONE)},
            "roots": {"full_name"},
        }
    if variant == "missing_phone":
        return {
            "path": "/register",
            "json": {"full_name": draw(_VALID_NAME)},
            "roots": {"phone"},
        }
    return {"path": "/register", "json": {}, "roots": {"full_name", "phone"}}


@st.composite
def _bio_case(draw):
    """An invalid /bio body: over-length bio, or the field omitted."""
    if draw(st.booleans()):
        overlong = draw(st.text(min_size=BIO_MAX + 1, max_size=BIO_MAX + 50))
        return {"path": "/bio", "json": {"bio": overlong}, "roots": {"bio"}}
    return {"path": "/bio", "json": {}, "roots": {"bio"}}


@st.composite
def _interests_case(draw):
    """An invalid /interests body: too many items or an over-length item."""
    if draw(st.booleans()):
        too_many = draw(
            st.lists(
                st.text(min_size=1, max_size=INTEREST_ITEM_MAX),
                min_size=INTERESTS_MAX_ITEMS + 1,
                max_size=INTERESTS_MAX_ITEMS + 10,
            )
        )
        return {
            "path": "/interests",
            "json": {"interests": too_many},
            "roots": {"interests"},
        }
    long_item = draw(
        st.text(min_size=INTEREST_ITEM_MAX + 1, max_size=INTEREST_ITEM_MAX + 20)
    )
    items = draw(
        st.lists(st.text(min_size=1, max_size=INTEREST_ITEM_MAX), min_size=0, max_size=5)
    )
    items.append(long_item)
    return {"path": "/interests", "json": {"interests": items}, "roots": {"interests"}}


@st.composite
def _message_case(draw):
    """An invalid /message body: empty/over-length content, or omitted."""
    variant = draw(st.sampled_from(["empty", "overlong", "missing"]))
    if variant == "empty":
        return {
            "path": "/message",
            "json": {"receiver_id": str(uuid.uuid4()), "content": ""},
            "roots": {"content"},
        }
    if variant == "overlong":
        overlong = draw(
            st.text(min_size=MESSAGE_CONTENT_MAX + 1, max_size=MESSAGE_CONTENT_MAX + 50)
        )
        return {
            "path": "/message",
            "json": {"receiver_id": str(uuid.uuid4()), "content": overlong},
            "roots": {"content"},
        }
    return {
        "path": "/message",
        "json": {"receiver_id": str(uuid.uuid4())},
        "roots": {"content"},
    }


@st.composite
def _report_case(draw):
    """An invalid /report body: empty/over-length reason, or omitted."""
    variant = draw(st.sampled_from(["empty", "overlong", "missing"]))
    if variant == "empty":
        return {
            "path": "/report",
            "json": {"reported_user": str(uuid.uuid4()), "reason": ""},
            "roots": {"reason"},
        }
    if variant == "overlong":
        overlong = draw(
            st.text(min_size=REPORT_REASON_MAX + 1, max_size=REPORT_REASON_MAX + 50)
        )
        return {
            "path": "/report",
            "json": {"reported_user": str(uuid.uuid4()), "reason": overlong},
            "roots": {"reason"},
        }
    return {
        "path": "/report",
        "json": {"reported_user": str(uuid.uuid4())},
        "roots": {"reason"},
    }


_INVALID_CASE = st.one_of(
    _register_case(),
    _bio_case(),
    _interests_case(),
    _message_case(),
    _report_case(),
)


# Feature: ubuntu-connect, Property 53: For any request with input that fails
# validation, the request is rejected, no changes are written to the data
# store, and the error response identifies each invalid field together with
# the reason it failed.
# Validates: Requirements 16.1
@settings(max_examples=100)
@given(case=_INVALID_CASE)
def test_validation_rejects_with_per_field_reasons_and_no_writes(harness, case):
    client, count_users, baseline = harness

    before = count_users()
    resp = client.post(case["path"], json=case["json"])

    # The request is rejected via the shared validation error envelope.
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "validation"
    assert isinstance(error["message"], str) and error["message"]

    # The envelope identifies each invalid field together with a reason.
    fields = error["fields"]
    assert fields, "a validation failure must report at least one field"
    returned_roots: set[str] = set()
    for f in fields:
        assert f["field"], "each reported field must be named"
        assert f["reason"], "each reported field must carry a reason"
        returned_roots.add(f["field"].split(".")[0])
    assert case["roots"] <= returned_roots

    # No changes are written to the data store.
    assert count_users() == before == baseline
