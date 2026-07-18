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
