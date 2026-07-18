"""Property test for protected-endpoint token rejection (task 4.8).

Feature: ubuntu-connect, Property 13: For any protected endpoint request
carrying no token, an expired token, or an invalid/tampered token, the request
is rejected with an authentication error.

Exercises the JWT auth guard (``get_current_user`` / ``CurrentUser``) end-to-end
through a FastAPI ``TestClient`` backed by an isolated in-memory data store. A
test-only route depends on ``CurrentUser``; every generated bad-token case must
be rejected with HTTP 401 and an ``auth`` error envelope (Req 3.6):

- no Authorization header at all;
- malformed/garbage bearer tokens that are not valid JWTs;
- tokens signed with the wrong secret (tampered signature);
- expired tokens (issued 24h+ in the past, so ``exp`` is in the past).

Each example runs against a freshly built engine created inside a context
manager (``_guard_harness``) and torn down afterwards, keeping every Hypothesis
example independent and avoiding the function-scoped fixture health check.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.config import Config
from app.models import Base
from app.routers.dependencies import CurrentUser
from app.schemas.errors import register_exception_handlers
from app.services.auth_service import TOKEN_TTL, create_access_token


@contextmanager
def _guard_harness() -> Iterator[TestClient]:
    """Yield a client over a fresh in-memory store with a protected route.

    A ``StaticPool`` keeps one underlying connection so the in-memory database
    is shared between the test and the request thread. The engine is bound for
    the duration of the block and fully discarded on exit, so each Hypothesis
    example is independent.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/protected")
    def _protected(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.id)}

    try:
        yield TestClient(app)
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


# --- bad-token strategies ---------------------------------------------------

# Garbage bearer values that are not valid, signature-verifiable JWTs: random
# text, empty/blank strings, and JWT-shaped-but-nonsense three-part tokens.
_garbage_tokens = st.one_of(
    st.text(max_size=40),
    st.text(alphabet="abcdefghij.0123456789", max_size=40),
    st.builds(
        lambda a, b, c: f"{a}.{b}.{c}",
        st.text(alphabet="abcXYZ0123456789", min_size=1, max_size=12),
        st.text(alphabet="abcXYZ0123456789", min_size=1, max_size=12),
        st.text(alphabet="abcXYZ0123456789", min_size=1, max_size=12),
    ),
)


@st.composite
def _bad_token_case(draw) -> dict:
    """Draw one of the four bad-token categories for a protected request."""
    kind = draw(
        st.sampled_from(["missing", "garbage", "tampered", "expired"])
    )
    real_secret = Config.from_env().jwt_secret

    if kind == "missing":
        return {"kind": kind}

    if kind == "garbage":
        return {"kind": kind, "token": draw(_garbage_tokens)}

    if kind == "tampered":
        # A structurally valid JWT signed with a secret other than the app's.
        wrong_secret = draw(
            st.text(min_size=1, max_size=32).filter(lambda s: s != real_secret)
        )
        token, _ = create_access_token(uuid.uuid4(), wrong_secret)
        return {"kind": kind, "token": token}

    # expired: correctly signed but issued far enough in the past that exp < now.
    extra = draw(st.integers(min_value=0, max_value=240))
    issued_at = datetime.now(timezone.utc) - TOKEN_TTL - timedelta(minutes=1 + extra)
    token, _ = create_access_token(uuid.uuid4(), real_secret, issued_at=issued_at)
    return {"kind": kind, "token": token}


# Feature: ubuntu-connect, Property 13: For any protected endpoint request
# carrying no token, an expired token, or an invalid/tampered token, the
# request is rejected with an authentication error.
# Validates: Requirements 3.6
@settings(max_examples=100)
@given(case=_bad_token_case())
def test_protected_endpoint_rejects_bad_tokens(case):
    with _guard_harness() as client:
        if case["kind"] == "missing":
            resp = client.get("/protected")
        else:
            resp = client.get(
                "/protected",
                headers={"Authorization": f"Bearer {case['token']}"},
            )

        # Req 3.6: every bad-token request is an authentication rejection.
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "auth"
