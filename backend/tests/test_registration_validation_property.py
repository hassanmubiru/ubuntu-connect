"""Property test for registration input validation (task 4.4, Property 3).

Exercises ``POST /api/auth/register`` end-to-end through a FastAPI
``TestClient`` backed by an in-memory SQLite store and a fake SMS gateway
(so registration's OTP trigger never touches the network). For any
registration request the endpoint must:

* accept it (201) when the full name is 2-100 non-whitespace characters and
  the phone is a valid E.164 number; and
* reject it (422 validation envelope) identifying the offending field(s)
  when the phone is not valid E.164, when the phone or full name is missing,
  when the full name is empty/whitespace, or when the full name length is
  <2 or >100.

Valid phones are drawn from African E.164 prefixes (+234, +27, +233, +254)
and made unique per accepted request so a valid case is never mistaken for a
duplicate-phone conflict (Property 3 is about field validation, not the
duplicate rule covered by Property 2). Invalid phones are near-miss
non-E.164 strings.
"""

from __future__ import annotations

import string

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.integrations.sms_gateway import SmsResult
from app.models import Base
from app.routers import auth as auth_router
from app.routers.dependencies import get_sms_gateway
from app.schemas.common import FULL_NAME_MAX
from app.schemas.errors import register_exception_handlers


class _FakeSmsGateway:
    """SMS gateway stub that accepts every send, so tests avoid the network."""

    def send_otp(self, phone: str, code: str) -> SmsResult:
        return SmsResult(success=True)

    def send(self, phone: str, message: str) -> SmsResult:
        return SmsResult(success=True)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.dependency_overrides[get_sms_gateway] = lambda: _FakeSmsGateway()
    return app


@pytest.fixture(scope="module")
def client():
    """Bind a shared in-memory SQLite store and yield a TestClient.

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
    try:
        yield TestClient(_build_app())
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


# --- Unique valid phones from African E.164 prefixes ------------------------

_AFRICAN_PREFIXES = ("234", "27", "233", "254")
_phone_counter = {"n": 0}


def _next_valid_phone(prefix: str) -> str:
    """A unique valid E.164 phone with an African prefix.

    An 8-digit monotonic suffix keeps every accepted request's phone distinct
    (total digits stay within E.164's 15-digit ceiling), so a valid case is
    never rejected as a duplicate.
    """
    _phone_counter["n"] += 1
    return f"+{prefix}{_phone_counter['n']:08d}"


# --- Strategies -------------------------------------------------------------

# A valid full name: 2-100 visible characters, no surrounding whitespace, so
# it satisfies both the raw length bounds and the trimmed non-blank rule.
_VALID_NAME = st.text(
    alphabet=string.ascii_letters + " ",
    min_size=2,
    max_size=FULL_NAME_MAX,
).map(lambda s: s.strip()).filter(lambda s: 2 <= len(s) <= FULL_NAME_MAX)

# full_name values that always fail validation.
_INVALID_NAME = st.one_of(
    st.just(""),  # empty
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=1),  # too short
    st.text(alphabet=" \t", min_size=1, max_size=6),  # whitespace-only
    st.text(
        alphabet=string.ascii_letters,
        min_size=FULL_NAME_MAX + 1,
        max_size=FULL_NAME_MAX + 25,
    ),  # too long
)

# Near-miss phone values that never match E.164 ^\+[1-9]\d{1,14}$.
_INVALID_PHONE = st.one_of(
    st.just(""),
    st.just("+"),
    st.just("0803-not-e164"),
    st.just("2348031234567"),  # missing leading '+'
    st.just("+0348031234567"),  # leading zero after '+'
    st.just("+234 803 123 4567"),  # embedded spaces
    st.text(alphabet=string.ascii_letters, min_size=1, max_size=12),
    st.from_regex(r"\+[1-9][0-9]{15,20}", fullmatch=True),  # too many digits
)


@st.composite
def _registration_case(draw):
    """A registration request plus whether it is valid and the flagged roots.

    Returns a dict with ``json`` (the request body), ``valid`` (expected
    acceptance), and ``roots`` (the field roots the error envelope must name
    when invalid).
    """
    variant = draw(
        st.sampled_from(
            [
                "valid",
                "bad_phone",
                "bad_name",
                "bad_both",
                "missing_name",
                "missing_phone",
                "missing_both",
            ]
        )
    )

    if variant == "valid":
        prefix = draw(st.sampled_from(_AFRICAN_PREFIXES))
        return {
            "json": {
                "full_name": draw(_VALID_NAME),
                "phone": _next_valid_phone(prefix),
            },
            "valid": True,
            "roots": set(),
        }
    if variant == "bad_phone":
        return {
            "json": {"full_name": draw(_VALID_NAME), "phone": draw(_INVALID_PHONE)},
            "valid": False,
            "roots": {"phone"},
        }
    if variant == "bad_name":
        prefix = draw(st.sampled_from(_AFRICAN_PREFIXES))
        return {
            "json": {
                "full_name": draw(_INVALID_NAME),
                "phone": _next_valid_phone(prefix),
            },
            "valid": False,
            "roots": {"full_name"},
        }
    if variant == "bad_both":
        return {
            "json": {
                "full_name": draw(_INVALID_NAME),
                "phone": draw(_INVALID_PHONE),
            },
            "valid": False,
            "roots": {"full_name", "phone"},
        }
    if variant == "missing_name":
        prefix = draw(st.sampled_from(_AFRICAN_PREFIXES))
        return {
            "json": {"phone": _next_valid_phone(prefix)},
            "valid": False,
            "roots": {"full_name"},
        }
    if variant == "missing_phone":
        return {
            "json": {"full_name": draw(_VALID_NAME)},
            "valid": False,
            "roots": {"phone"},
        }
    return {"json": {}, "valid": False, "roots": {"full_name", "phone"}}


# Feature: ubuntu-connect, Property 3: For any registration request, it is
# rejected identifying the offending field(s) when the phone is not valid
# E.164, when the phone or full name is missing, when the full name is
# empty/whitespace, or when the full name length is <2 or >100; otherwise it
# is accepted.
# Validates: Requirements 1.3, 1.4, 1.5
@settings(max_examples=100)
@given(case=_registration_case())
def test_registration_input_validation(client, case):
    resp = client.post("/api/auth/register", json=case["json"])

    if case["valid"]:
        # A well-formed request is accepted and creates the user.
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user_id"]
        return

    # An ill-formed request is rejected with the shared validation envelope.
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == "validation"
    assert isinstance(error["message"], str) and error["message"]

    # The envelope identifies each offending field together with a reason.
    fields = error["fields"]
    assert fields, "a validation failure must report at least one field"
    returned_roots: set[str] = set()
    for f in fields:
        assert f["field"], "each reported field must be named"
        assert f["reason"], "each reported field must carry a reason"
        returned_roots.add(f["field"].split(".")[0])
    assert case["roots"] <= returned_roots
