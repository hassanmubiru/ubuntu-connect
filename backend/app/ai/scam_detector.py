"""AI-backed scam detection service (Req 8.1, 8.2, 8.6).

``ScamDetector`` assigns a Scam_Score -- an integer in the inclusive range
[0, 100] (Req 8.1) -- to a message. It mirrors the moderation service's
two-path structure:

1. **Primary (OpenAI) path:** build the scam prompt
   (:mod:`app.ai.prompts.scam_prompt`), send it through the timeout-bounded
   :class:`app.integrations.openai_client.OpenAIClient` under its 3-second
   budget, parse the returned integer, and clamp it into [0, 100].
2. **Fallback (rule-based) path:** if OpenAI errors, exceeds its 3-second
   budget, or returns text with no parseable integer, degrade to the
   deterministic :func:`app.ai.fallback.scam_rules.score` (Req 8.2).

Both paths return *the same typed result* -- an ``int`` clamped to [0, 100] --
so the messaging pipeline that stores the score before delivery (Req 8.6) is
agnostic to which path produced it. Prompt construction and transport remain
independent of this scoring logic (Req 15.3).

The :class:`OpenAIClient` is injectable so tests can exercise the success,
timeout, error, and unparseable-response paths without any network access.
"""

from __future__ import annotations

import re

from app.ai.fallback import scam_rules
from app.ai.prompts.scam_prompt import (
    SCAM_SCORE_MAX,
    SCAM_SCORE_MIN,
    build_scam_prompt,
)
from app.integrations.openai_client import OpenAIClient, OpenAIError

# First run of digits appearing in the model's reply; the prompt asks for a
# bare integer but tolerate surrounding text such as "Score: 82".
_INTEGER_PATTERN = re.compile(r"\d+")


class ScamDetector:
    """Assign a Scam_Score to a message via OpenAI with a rule fallback.

    The detector owns only orchestration, integer parsing, and clamping;
    prompt building and transport live in their own modules (Req 15.3).
    Whatever path runs, :meth:`score` returns an ``int`` in the inclusive
    range [0, 100] (Req 8.1).
    """

    def __init__(self, openai_client: OpenAIClient | None = None) -> None:
        # An OpenAIClient may be injected for testing; otherwise a default,
        # environment-configured client is created on construction.
        self._client = openai_client or OpenAIClient()

    def score(self, message_content: str) -> int:
        """Return the Scam_Score for ``message_content`` as an int in [0, 100].

        Tries the OpenAI path first under its 3-second budget. On any
        :class:`OpenAIError` (which includes timeout) or on a reply with no
        parseable integer, falls back to the deterministic rule-based scorer
        (Req 8.2). The returned value is always clamped into the inclusive
        range [0, 100] (Req 8.1).
        """
        try:
            prompt = build_scam_prompt(message_content)
            response = self._client.score_scam(prompt)
            parsed = self._parse_score(response.content)
        except OpenAIError:
            # OpenAI errored or exceeded its 3s budget (Req 8.2).
            return scam_rules.score(message_content)

        if parsed is None:
            # Provider responded but with no usable integer; treat it like an
            # outage and use the deterministic fallback rather than guessing.
            return scam_rules.score(message_content)

        return self._clamp(parsed)

    @staticmethod
    def _parse_score(content: str) -> int | None:
        """Extract the first integer from raw completion text, or ``None``.

        The prompt asks for a bare integer, but replies may include stray
        text or punctuation; take the first run of digits as the score.
        """
        if not content:
            return None
        match = _INTEGER_PATTERN.search(content)
        if match is None:
            return None
        return int(match.group())

    @staticmethod
    def _clamp(value: int) -> int:
        """Clamp ``value`` into the inclusive Scam_Score range [0, 100]."""
        if value < SCAM_SCORE_MIN:
            return SCAM_SCORE_MIN
        if value > SCAM_SCORE_MAX:
            return SCAM_SCORE_MAX
        return value
