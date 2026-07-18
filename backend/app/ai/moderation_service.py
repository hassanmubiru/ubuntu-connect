"""AI-backed content moderation service (Req 7.1, 7.5, 7.6).

``ModerationService`` evaluates a message and assigns a Moderation_Result --
one of ``"approved"``, ``"flagged"``, or ``"blocked"`` (Req 7.1). It follows
the design's two-path structure:

1. **Primary (OpenAI) path:** build the moderation prompt
   (:mod:`app.ai.prompts.moderation_prompt`), send it through the
   timeout-bounded :class:`app.integrations.openai_client.OpenAIClient` under
   its 5-second budget, and parse the returned label.
2. **Fallback (rule-based) path:** if OpenAI errors, exceeds its 5-second
   budget, or returns text that does not parse to a valid label, degrade to
   the deterministic :func:`app.ai.fallback.moderation_rules.classify`
   (Req 7.5, 7.6).

Both paths return *the same typed result* -- a label string that is always a
member of :data:`MODERATION_LABELS` -- so the messaging pipeline is agnostic
to which path produced it. The prompt module (prompt construction) and the
OpenAI client (transport) stay independent of this decision logic (Req 15.3).

The :class:`OpenAIClient` is injectable so tests can drive the success,
timeout, error, and unparseable-response paths without touching the network.
"""

from __future__ import annotations

from app.ai.fallback import moderation_rules
from app.ai.prompts.moderation_prompt import MODERATION_LABELS, build_moderation_prompt
from app.integrations.openai_client import OpenAIClient, OpenAIError

# The set of valid Moderation_Result labels, for O(1) membership checks.
_VALID_LABELS: frozenset[str] = frozenset(MODERATION_LABELS)


class ModerationService:
    """Assign a Moderation_Result to a message via OpenAI with a rule fallback.

    The service owns only orchestration and result parsing; prompt building
    and transport live in their own modules (Req 15.3). Whatever path runs,
    :meth:`evaluate` returns a label guaranteed to be one of ``"approved"``,
    ``"flagged"``, or ``"blocked"`` (Req 7.1).
    """

    def __init__(self, openai_client: OpenAIClient | None = None) -> None:
        # An OpenAIClient may be injected for testing; otherwise a default,
        # environment-configured client is created lazily on construction.
        self._client = openai_client or OpenAIClient()

    def evaluate(self, message_content: str) -> str:
        """Return the Moderation_Result label for ``message_content``.

        Tries the OpenAI path first under its 5-second budget. On any
        :class:`OpenAIError` (which includes timeout) or on a reply that does
        not parse to a valid label, falls back to the deterministic
        rule-based classifier (Req 7.5, 7.6). The returned value is always a
        member of :data:`MODERATION_LABELS` (Req 7.1).
        """
        try:
            prompt = build_moderation_prompt(message_content)
            response = self._client.moderate(prompt)
            label = self._parse_label(response.content)
        except OpenAIError:
            # OpenAI unavailable or exceeded its 5s budget (Req 7.5, 7.6).
            return moderation_rules.classify(message_content)

        if label is None:
            # Provider responded but the reply was not a usable label; treat
            # it like an outage and use the deterministic fallback so we never
            # return an out-of-contract result.
            return moderation_rules.classify(message_content)

        return label

    @staticmethod
    def _parse_label(content: str) -> str | None:
        """Extract a valid Moderation_Result label from raw completion text.

        The prompt asks the model to reply with only the lowercase label, but
        real replies may carry surrounding whitespace, punctuation, or casing
        variations. Normalise the text and return the matching label, or
        ``None`` when no valid label can be identified.
        """
        if not content:
            return None

        normalised = content.strip().lower()

        # Exact match after normalisation is the common, well-behaved case.
        if normalised in _VALID_LABELS:
            return normalised

        # Otherwise scan the reply's word tokens for a valid label so a reply
        # like "Label: blocked." still resolves. Prefer the most severe label
        # present to fail safe (blocked > flagged > approved).
        tokens = {token.strip(".,:;!?\"'()[]{}") for token in normalised.split()}
        for label in ("blocked", "flagged", "approved"):
            if label in tokens:
                return label

        return None
