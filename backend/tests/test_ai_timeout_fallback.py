"""Unit tests for AI timeout/error switchover to the rule-based fallback (task 8.6).

These tests pin down the *switchover behaviour* the property tests only assert
in aggregate: when the OpenAI provider exceeds its per-call time budget (the 5s
moderation budget of Req 7.6 / the 3s scam budget of Req 8.2) or otherwise
errors, the AI services must degrade to their deterministic rule-based fallback
and return *that* fallback's result -- not a hardcoded default or the AI path.

Validates: Requirements 7.6, 8.2

Approach
--------
A fake :class:`OpenAIClient` is injected into :class:`ModerationService` and
:class:`ScamDetector` that raises :class:`OpenAITimeoutError` (simulating the
call exceeding its time budget) or :class:`OpenAIError` (generic provider
failure). For each service the returned result is asserted to equal exactly
what the corresponding rule-based fallback
(:func:`app.ai.fallback.moderation_rules.classify` /
:func:`app.ai.fallback.scam_rules.score`) produces for the same input.

To prove the *fallback* path is exercised -- and not a default -- the inputs
are chosen so the rules produce a distinctive, non-default result:

- a moderation message the rules classify as ``"blocked"`` and one they
  classify as ``"flagged"`` (both differ from the ``"approved"`` default);
- a scam message the rules score at >= 70 (well above the 0 default).
"""

from __future__ import annotations

from app.ai.fallback import moderation_rules, scam_rules
from app.ai.moderation_service import ModerationService
from app.ai.scam_detector import ScamDetector
from app.integrations.openai_client import (
    OpenAIError,
    OpenAIResponse,
    OpenAITimeoutError,
)

# --- Inputs whose rule-based result is distinctive (not the default) --------

# Rules classify this as "blocked" (a policy violation, Req 7.2).
BLOCKED_MESSAGE = "i will kill you"
# Rules classify this as "flagged" (concerning but reviewable, Req 7.4).
FLAGGED_MESSAGE = "you are an idiot and worthless"
# Rules score this well above the >=70 warning threshold: money/airtime +
# prize lure + urgency (Req 8.3 grounding example).
HIGH_SCAM_MESSAGE = "send me airtime to unlock your prize before midnight"


class _TimeoutOpenAIClient:
    """Fake client that always exceeds its time budget (Req 7.6 / 8.2).

    Mirrors the ``moderate``/``score_scam`` surface the AI services depend on,
    raising :class:`OpenAITimeoutError` to simulate the OpenAI call blowing
    past its 5s (moderation) or 3s (scam) budget.
    """

    def moderate(self, messages, **_kwargs) -> OpenAIResponse:  # noqa: ANN001
        raise OpenAITimeoutError("simulated: exceeded the 5s moderation budget")

    def score_scam(self, messages, **_kwargs) -> OpenAIResponse:  # noqa: ANN001
        raise OpenAITimeoutError("simulated: exceeded the 3s scam budget")


class _ErrorOpenAIClient:
    """Fake client that always raises a generic provider error (Req 7.6 / 8.2)."""

    def moderate(self, messages, **_kwargs) -> OpenAIResponse:  # noqa: ANN001
        raise OpenAIError("simulated: OpenAI provider unavailable")

    def score_scam(self, messages, **_kwargs) -> OpenAIResponse:  # noqa: ANN001
        raise OpenAIError("simulated: OpenAI provider unavailable")


# --- Moderation: timeout / error -> rule-based classify ---------------------


def test_moderation_timeout_uses_rule_fallback_blocked() -> None:
    """A 5s moderation timeout returns the rules' 'blocked' verdict (Req 7.6)."""
    service = ModerationService(openai_client=_TimeoutOpenAIClient())

    result = service.evaluate(BLOCKED_MESSAGE)

    # The fallback result is used verbatim, and it is the distinctive
    # (non-default) "blocked" label -- proving the rule path ran.
    assert result == moderation_rules.classify(BLOCKED_MESSAGE)
    assert result == "blocked"


def test_moderation_timeout_uses_rule_fallback_flagged() -> None:
    """A 5s moderation timeout returns the rules' 'flagged' verdict (Req 7.6)."""
    service = ModerationService(openai_client=_TimeoutOpenAIClient())

    result = service.evaluate(FLAGGED_MESSAGE)

    assert result == moderation_rules.classify(FLAGGED_MESSAGE)
    assert result == "flagged"


def test_moderation_generic_error_uses_rule_fallback() -> None:
    """A generic OpenAIError also switches over to the rule fallback (Req 7.6)."""
    service = ModerationService(openai_client=_ErrorOpenAIClient())

    result = service.evaluate(BLOCKED_MESSAGE)

    assert result == moderation_rules.classify(BLOCKED_MESSAGE)
    assert result == "blocked"


# --- Scam: timeout / error -> rule-based score ------------------------------


def test_scam_timeout_uses_rule_fallback_high_score() -> None:
    """A 3s scam timeout returns the rules' high score, not a default (Req 8.2)."""
    detector = ScamDetector(openai_client=_TimeoutOpenAIClient())

    result = detector.score(HIGH_SCAM_MESSAGE)

    expected = scam_rules.score(HIGH_SCAM_MESSAGE)
    # The fallback result is used verbatim, and it clears the >=70 warning
    # threshold -- a distinctive, non-default score proving the rule path ran.
    assert result == expected
    assert result >= 70


def test_scam_generic_error_uses_rule_fallback() -> None:
    """A generic OpenAIError also switches over to the rule fallback (Req 8.2)."""
    detector = ScamDetector(openai_client=_ErrorOpenAIClient())

    result = detector.score(HIGH_SCAM_MESSAGE)

    expected = scam_rules.score(HIGH_SCAM_MESSAGE)
    assert result == expected
    assert result >= 70
