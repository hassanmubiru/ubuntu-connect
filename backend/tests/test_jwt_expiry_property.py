"""Property test for JWT 24-hour expiry (task 4.7).

Feature: ubuntu-connect, Property 12: For any issued JWT, its expiry timestamp
equals its issue timestamp plus 24 hours.

Validates: Requirements 3.5

``create_access_token`` issues a signed JWT whose ``exp`` claim is set to
exactly 24 hours after its ``iat`` (Req 3.5). Because JWT numeric dates are
UNIX timestamps (whole seconds), the issue time is first normalized to whole
seconds and the expiry is that normalized instant plus :data:`TOKEN_TTL`.

For any user id (UUID), signing secret, and issue instant, this test asserts:

* the returned ``expires_at`` equals the whole-second-normalized ``issued_at``
  plus 24 hours, and
* the decoded token's ``exp - iat`` equals 24 * 3600 seconds.

Generated issue times may fall in the past or the future, so decoding disables
``exp`` verification to inspect the raw ``iat``/``exp`` claims regardless of the
current wall clock.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st
from jose import jwt

from app.services.auth_service import (
    JWT_ALGORITHM,
    TOKEN_TTL,
    create_access_token,
)

_TTL_SECONDS = int(TOKEN_TTL.total_seconds())

# Non-empty signing secrets: HMAC-SHA256 accepts an arbitrary-length key, so
# any non-empty text is a valid secret for encode/decode round-tripping.
_secrets = st.text(min_size=1, max_size=64)

# Timezone-aware UTC issue instants across a wide range. Datetimes are drawn
# without microseconds because JWT numeric dates carry whole-second precision;
# the token helper normalizes sub-second components away in any case.
_issued_at = st.datetimes(
    min_value=datetime(1970, 1, 2, 0, 0, 0),
    max_value=datetime(2200, 1, 1, 0, 0, 0),
    timezones=st.just(timezone.utc),
)


# Feature: ubuntu-connect, Property 12: For any issued JWT, its expiry timestamp
# equals its issue timestamp plus 24 hours.
# Validates: Requirements 3.5
@settings(max_examples=100)
@given(
    user_id=st.uuids(),
    secret=_secrets,
    issued_at=_issued_at,
)
def test_jwt_expiry_equals_issuance_plus_24_hours(
    user_id: uuid.UUID, secret: str, issued_at: datetime
) -> None:
    token, expires_at = create_access_token(user_id, secret, issued_at=issued_at)

    # The returned absolute expiry is the whole-second-normalized issue instant
    # plus exactly 24 hours (Req 3.5).
    normalized_issue = issued_at.replace(microsecond=0)
    assert expires_at == normalized_issue + TOKEN_TTL

    # The token's numeric claims agree: exp is precisely 24h after iat. Skip
    # expiry verification since generated issue times may be past or future.
    claims = jwt.decode(
        token,
        secret,
        algorithms=[JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    assert claims["exp"] - claims["iat"] == _TTL_SECONDS
    assert claims["iat"] == int(normalized_issue.timestamp())
    assert claims["exp"] == int((normalized_issue + TOKEN_TTL).timestamp())
