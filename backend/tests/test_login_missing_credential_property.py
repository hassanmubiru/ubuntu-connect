"""Property test for login credential validation (task 4.6).

Feature: ubuntu-connect, Property 11: For any login request omitting a required
credential field, the request is rejected identifying each missing field.

Validates: Requirements 3.4

``LoginRequest`` (POST /api/auth/login) identifies an account by a single
required credential — the E.164 ``phone``. This test drives the endpoint
through a FastAPI ``TestClient`` with the real global exception handlers, and
for any request body that omits ``phone`` (an empty body, or a body carrying
only unrelated/extraneous keys) asserts that:

* the request is rejected with the shared validation envelope (HTTP 422,
  ``error.code == "validation"``), and
* ``error.fields[]`` names every missing required field (here, ``phone``),
  each with a non-empty reason.

Because validation runs before the route body, no ``AuthService`` call or data
access occurs; the app needs no seeded users for these cases.
"""

from __future__ import annotations

import string

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.routers import auth as auth_router
from app.schemas.errors import register_exception_handlers

# The credential fields that POST /api/auth/login requires. Login is keyed on a
# verified phone (there is no password column), so ``phone`` is the sole
# required credential (Req 3.4).
_REQUIRED_CREDENTIAL_FIELDS = {"phone"}


def _build_app() -> FastAPI:
    """App mounting the real auth router and the shared error handlers."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    return app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_build_app())


# Keys that are never the required ``phone`` credential, used to build bodies
# that still omit the credential while carrying irrelevant/extra content.
_EXTRANEOUS_KEYS = st.text(
    alphabet=string.ascii_letters + "_", min_size=1, max_size=12
).filter(lambda k: k not in _REQUIRED_CREDENTIAL_FIELDS)

_JSON_SCALARS = st.one_of(
    st.text(max_size=20),
    st.integers(),
    st.booleans(),
    st.none(),
)


@st.composite
def _login_body_missing_credential(draw):
    """A login body that omits every required credential field.

    Produces either an empty object or an object of purely extraneous keys, so
    the required ``phone`` credential is always absent regardless of any noise.
    """
    extra = draw(
        st.dictionaries(
            keys=_EXTRANEOUS_KEYS,
            values=_JSON_SCALARS,
            min_size=0,
            max_size=4,
        )
    )
    # Defensive: never let a generated key coincide with a required field.
    body = {k: v for k, v in extra.items() if k not in _REQUIRED_CREDENTIAL_FIELDS}
    return body


# Feature: ubuntu-connect, Property 11: For any login request omitting a
# required credential field, the request is rejected identifying each missing
# field.
# Validates: Requirements 3.4
@settings(max_examples=100)
@given(body=_login_body_missing_credential())
def test_login_missing_credential_rejected_identifying_each_field(client, body):
    resp = client.post("/api/auth/login", json=body)

    # Rejected via the shared validation error envelope.
    assert resp.status_code == 422
    payload = resp.json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert error["code"] == "validation"
    assert isinstance(error["message"], str) and error["message"]

    # The envelope identifies each missing required credential field, each with
    # a non-empty reason. Field roots strip any nested location prefixes.
    fields = error["fields"]
    assert fields, "a missing-credential failure must report at least one field"
    reported_roots: set[str] = set()
    for f in fields:
        assert f["field"], "each reported field must be named"
        assert f["reason"], "each reported field must carry a reason"
        reported_roots.add(f["field"].split(".")[0])

    # Every required credential absent from the body must be named.
    missing = {f for f in _REQUIRED_CREDENTIAL_FIELDS if f not in body}
    assert missing <= reported_roots
