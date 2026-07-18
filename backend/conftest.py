"""Global pytest configuration for the Ubuntu Connect backend.

Registers Hypothesis profiles so every property-based test runs a
minimum of 100 generated examples, as required by the design's testing
strategy. The active profile is selected via the ``HYPOTHESIS_PROFILE``
environment variable and defaults to ``dev``.

Profiles:
- ``dev``   : 100 examples (the design's required minimum).
- ``ci``    : 200 examples for a deeper sweep in continuous integration.
- ``debug`` : 100 examples with verbose output for local triage.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, Verbosity, settings

# Provide placeholder values for every required environment variable so the
# app factory's fail-fast config validation (Req 15.5) is satisfied during
# tests. These are test fixtures, not real credentials or endpoints, and only
# set defaults when the variable is not already present in the environment.
_TEST_ENV_DEFAULTS = {
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
for _key, _value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

MIN_EXAMPLES = 100

settings.register_profile(
    "dev",
    max_examples=MIN_EXAMPLES,
    deadline=None,
)
settings.register_profile(
    "ci",
    max_examples=max(MIN_EXAMPLES, 200),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "debug",
    max_examples=MIN_EXAMPLES,
    deadline=None,
    verbosity=Verbosity.verbose,
)

settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "dev"))
