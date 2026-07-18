"""Property test for a bounded Scam_Score, including on fallback (task 8.5).

Feature: ubuntu-connect, Property 30: For any message that passes moderation
— including when OpenAI errors or exceeds its time budget — the assigned
Scam_Score is an integer in [0, 100] and is stored on the message before
delivery.

Validates: Requirements 8.1, 8.2, 8.6

Strategy
--------
``ScamDetector.score`` owns orchestration, integer parsing, and clamping; the
OpenAI transport is injectable so this test exercises every path without any
network access. A *scripted fake* OpenAI client stands in for
:class:`~app.integrations.openai_client.OpenAIClient`, reproducing the four
behaviours the detector must survive:

1. **success (parseable, in range)** — returns a bare integer in [0, 100];
2. **success (parseable, out of range)** — returns an integer far outside the
   range (negative or > 100), which the detector must clamp;
3. **success (unparseable)** — returns text with no integer, which the
   detector treats like an outage and scores via the rule-based fallback;
4. **timeout** — raises :class:`OpenAITimeoutError` (Req 8.2);
5. **error** — raises :class:`OpenAIError` (Req 8.2).

Hypothesis generates arbitrary message text alongside a randomly chosen client
behaviour. Across every combination the test asserts the returned Scam_Score
is always a plain ``int`` in the inclusive range [0, 100] (Req 8.1). The
"stored on the message before delivery" aspect (Req 8.6) is exercised at the
messaging-pipeline level (task 9); here the focus is the detector always
yielding a bounded integer, including on fallback.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.ai.scam_detector import ScamDetector
from app.integrations.openai_client import (
    OpenAIError,
    OpenAIResponse,
    OpenAITimeoutError,
)

# Scam_Score bounds under test (Req 8.1, 8.6).
SCORE_MIN = 0
SCORE_MAX = 100


class _ScriptedOpenAIClient:
    """Fake OpenAI client reproducing every path the detector must survive.

    Mirrors the ``score_scam(messages) -> OpenAIResponse`` surface the
    ScamDetector depends on. Depending on ``behaviour`` it either returns a
    completion carrying ``content`` or raises the failure the detector treats
    as its fallback trigger.
    """

    def __init__(self, behaviour: str, content: str = "") -> None:
        self._behaviour = behaviour
        self._content = content

    def score_scam(self, messages, **_kwargs) -> OpenAIResponse:  # noqa: ANN001
        if self._behaviour == "timeout":
            raise OpenAITimeoutError("scam scoring exceeded its 3s budget")
        if self._behaviour == "error":
            raise OpenAIError("scam scoring transport failed")
        # success paths (in-range / out-of-range / unparseable) return text.
        return OpenAIResponse(content=self._content)


# Arbitrary message text, including the empty string and long bodies so both
# the primary and fallback scorers see a wide input space.
_MESSAGE_TEXT = st.text(max_size=400)

# In-range integers the provider might return as a bare number.
_IN_RANGE_CONTENT = st.integers(min_value=SCORE_MIN, max_value=SCORE_MAX).map(str)

# Out-of-range integers (below 0 or above 100) the detector must clamp; the
# leading-minus and large-positive cases both flow through integer parsing.
_OUT_OF_RANGE_CONTENT = st.one_of(
    st.integers(min_value=101, max_value=10_000).map(str),
    st.integers(min_value=-10_000, max_value=-1).map(str),
)

# Replies with no parseable integer, which the detector routes to the rules.
_UNPARSEABLE_CONTENT = st.text(alphabet="abcdefghijklmnop .,!?-", max_size=40)


@st.composite
def _clients(draw: st.DrawFn) -> _ScriptedOpenAIClient:
    """Draw a fake client covering success, unparseable, timeout, and error."""
    behaviour = draw(
        st.sampled_from(
            ["success_in_range", "success_out_of_range", "unparseable", "timeout", "error"]
        )
    )
    if behaviour == "success_in_range":
        return _ScriptedOpenAIClient("success", draw(_IN_RANGE_CONTENT))
    if behaviour == "success_out_of_range":
        return _ScriptedOpenAIClient("success", draw(_OUT_OF_RANGE_CONTENT))
    if behaviour == "unparseable":
        return _ScriptedOpenAIClient("success", draw(_UNPARSEABLE_CONTENT))
    # timeout / error paths ignore content.
    return _ScriptedOpenAIClient(behaviour)


# Feature: ubuntu-connect, Property 30: For any message that passes moderation
# — including when OpenAI errors or exceeds its time budget — the assigned
# Scam_Score is an integer in [0, 100] and is stored on the message before
# delivery.
# Validates: Requirements 8.1, 8.2, 8.6
@settings(max_examples=100)
@given(message=_MESSAGE_TEXT, client=_clients())
def test_scam_score_is_bounded_integer_across_all_paths(
    message: str, client: _ScriptedOpenAIClient
) -> None:
    detector = ScamDetector(openai_client=client)

    result = detector.score(message)

    # The score is a plain integer (not a bool, which is an int subclass).
    assert isinstance(result, int)
    assert not isinstance(result, bool)
    # And it always lands in the inclusive Scam_Score range (Req 8.1),
    # regardless of whether OpenAI succeeded, returned junk, timed out, or
    # errored into the rule-based fallback (Req 8.2).
    assert SCORE_MIN <= result <= SCORE_MAX
