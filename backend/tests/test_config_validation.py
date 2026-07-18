"""Property test for fail-fast environment-variable validation (Task 1.3).

Covers design Property 52 (Req 15.5): for any subset of required environment
variables that is absent at startup, the backend must halt *without serving
requests* and emit an error that names every missing variable.

The test drives the real application factory ``create_app`` with a manipulated
process environment. If validation fails, ``create_app`` raises
:class:`MissingConfigError` before a FastAPI app is ever constructed, so no
port is bound and no request is served — exactly the fail-fast behaviour the
property requires. When the environment is complete, the app is built and the
``/health`` endpoint serves, confirming the guard does not over-reject.
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from app.config import REQUIRED_ENV_VARS, MissingConfigError
from app.main import create_app

# A fully populated environment. These are inert test fixtures, not real
# credentials or endpoints; individual variables are removed/blanked per
# example to model the "absent at startup" scenarios of Property 52.
COMPLETE_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+psycopg://test:test@localhost:5432/ubuntu_connect_test",
    "JWT_SECRET": "test-jwt-secret",
    "OPENAI_API_KEY": "test-openai-key",
    "OPENAI_BASE_URL": "http://localhost:9/v1",
    "AT_API_KEY": "test-at-key",
    "AT_USERNAME": "test-at-username",
    "AT_SMS_SENDER_ID": "UBUNTU",
    "AT_USSD_SERVICE_CODE": "*384*0000#",
    "PHOTO_STORAGE_BUCKET": "test-photo-bucket",
}

# Sanity check: the fixture env must cover every required variable, otherwise
# the "complete" baseline would itself be invalid.
assert set(COMPLETE_ENV) == set(REQUIRED_ENV_VARS)


def _apply_env(env: dict[str, str]) -> None:
    """Replace the process environment's required vars with ``env``."""
    for name in REQUIRED_ENV_VARS:
        os.environ.pop(name, None)
    os.environ.update(env)


@st.composite
def _absent_subsets(draw):
    """Generate a non-empty set of required vars made absent at startup.

    Each chosen variable is made "absent" in one of three ways that all count
    as missing per :meth:`Config.missing_vars`: removed entirely, set blank,
    or set to whitespace only. Returns ``(missing_names, env)``.
    """
    missing = draw(
        st.lists(st.sampled_from(REQUIRED_ENV_VARS), min_size=1, unique=True)
    )
    env = dict(COMPLETE_ENV)
    for name in missing:
        mode = draw(st.sampled_from(["remove", "blank", "whitespace"]))
        if mode == "remove":
            env.pop(name, None)
        elif mode == "blank":
            env[name] = ""
        else:
            env[name] = draw(st.sampled_from(["   ", "\t", "\n", " \t \n "]))
    return sorted(set(missing)), env


# Feature: ubuntu-connect, Property 52: For any subset of required environment
# variables that is absent at startup, the backend halts without serving
# requests and emits an error naming each missing variable.
# Validates: Requirements 15.5
@given(case=_absent_subsets())
def test_missing_env_vars_halt_startup_and_are_all_named(case) -> None:
    missing, env = case
    saved = dict(os.environ)
    try:
        _apply_env(env)

        # Startup must fail fast: create_app raises before returning a
        # FastAPI app, so the backend never begins serving requests.
        with pytest.raises(MissingConfigError) as exc_info:
            create_app()

        error = exc_info.value
        message = str(error)

        # The error names *every* missing variable (whole set at once).
        assert set(error.missing) == set(missing)
        for name in missing:
            assert name in message

        # It must not falsely name variables that are present.
        present = set(REQUIRED_ENV_VARS) - set(missing)
        assert not (present & set(error.missing))
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_complete_env_starts_and_serves() -> None:
    """Boundary: with no variables absent, the app is built and serves."""
    saved = dict(os.environ)
    try:
        _apply_env(dict(COMPLETE_ENV))
        app = create_app()
        assert isinstance(app, FastAPI)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        os.environ.clear()
        os.environ.update(saved)
