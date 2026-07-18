"""Property test for valid moderation labels including fallback (task 8.4).

Feature: ubuntu-connect, Property 26: For any message — including when the
OpenAI API is unavailable — moderation assigns a Moderation_Result that is one
of "approved", "flagged", or "blocked".

Validates: Requirements 7.1, 7.5

Strategy
--------
``ModerationService.evaluate`` must always return a member of
:data:`MODERATION_LABELS` regardless of how the OpenAI provider behaves. To
exercise every path without touching the network, a fake OpenAI client is
injected that simulates one of three behaviours per call:

- **success**: returns completion text. The text is drawn from both valid
  labels (with realistic surrounding noise/casing) and clearly invalid /
  unparseable content, so the parse + fail-safe-to-fallback branch is covered.
- **timeout**: raises :class:`OpenAITimeoutError` (the 5s budget was exceeded,
  Req 7.6), forcing the rule-based fallback.
- **error**: raises a generic :class:`OpenAIError` (provider unavailable,
  Req 7.5), forcing the rule-based fallback.

Hypothesis generates arbitrary message text — including harmful phrases that
the rule-based classifier would map to ``flagged``/``blocked`` — and asserts
the returned Moderation_Result is always one of the three valid labels across
all provider behaviours.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.ai.moderation_service import ModerationService
from app.ai.prompts.moderation_prompt import MODERATION_LABELS
from app.integrations.openai_client import (
    OpenAIError,
    OpenAIResponse,
    OpenAITimeoutError,
)

_VALID_LABELS = frozenset(MODERATION_LABELS)


class _FakeOpenAIClient:
    """Fake OpenAI client that simulates success, timeout, and error paths.

    Mirrors the ``moderate(messages) -> OpenAIResponse`` surface that
    :class:`ModerationService` depends on. The behaviour is fixed at
    construction so a single example drives one deterministic provider path:

    - ``"success"``: return an :class:`OpenAIResponse` whose ``content`` is the
      configured reply text (which may be a valid label, noisy label text, or
      unparseable garbage).
    - ``"timeout"``: raise :class:`OpenAITimeoutError` (Req 7.6).
    - ``"error"``: raise :class:`OpenAIError` (Req 7.5).
    """

    def __init__(self, behaviour: str, reply: str = "") -> None:
        self._behaviour = behaviour
        self._reply = reply

    def moderate(self, messages: list[dict[str, str]]) -> OpenAIResponse:
        if self._behaviour == "timeout":
            raise OpenAITimeoutError("simulated 5s moderation budget exceeded")
        if self._behaviour == "error":
            raise OpenAIError("simulated OpenAI provider unavailable")
        return OpenAIResponse(content=self._reply, raw={})


# Message content: arbitrary text plus harmful phrases that the rule-based
# fallback resolves to flagged/blocked, ensuring non-approved fallback labels
# are also produced during the timeout/error paths.
_MESSAGES = st.one_of(
    st.text(max_size=300),
    st.sampled_from(
        [
            "",
            "Hey, lovely to connect on Ubuntu Connect!",
            "Let's meet for coffee in Lagos this weekend.",
            "you are an idiot and worthless",  # -> flagged via rules
            "i will kill you",  # -> blocked via rules
            "send me nudes",  # -> blocked via rules
            "shut up you fool",  # -> flagged via rules
        ]
    ),
)

# Success-path reply text: valid labels (clean and noisy) plus clearly
# unparseable content that must fail safe to the rule-based fallback.
_SUCCESS_REPLIES = st.one_of(
    st.sampled_from(list(MODERATION_LABELS)),
    st.sampled_from(
        [
            "approved",
            "  FLAGGED  ",
            "Label: blocked.",
            "The classification is: approved",
            "APPROVED\n",
        ]
    ),
    # Unparseable / no-label replies — service must fall back to rules.
    st.sampled_from(["", "unknown", "42", "maybe?", "I cannot decide", "yes"]),
    st.text(max_size=40),
)


# Feature: ubuntu-connect, Property 26: For any message — including when the
# OpenAI API is unavailable — moderation assigns a Moderation_Result that is
# one of "approved", "flagged", or "blocked".
# Validates: Requirements 7.1, 7.5
@settings(max_examples=100)
@given(
    message=_MESSAGES,
    behaviour=st.sampled_from(["success", "timeout", "error"]),
    reply=_SUCCESS_REPLIES,
)
def test_moderation_result_is_always_a_valid_label(
    message: str, behaviour: str, reply: str
) -> None:
    client = _FakeOpenAIClient(behaviour=behaviour, reply=reply)
    service = ModerationService(openai_client=client)

    result = service.evaluate(message)

    # Across success (valid/invalid text), timeout, and error paths, the
    # assigned Moderation_Result is always one of the three valid labels.
    assert result in _VALID_LABELS
