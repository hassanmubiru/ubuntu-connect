"""Moderation prompt builder.

This module builds the chat prompt used to ask OpenAI to classify a message
into one of the three Moderation_Result labels — ``approved``, ``flagged``,
or ``blocked`` (Req 7.1). It contains prompt construction only: no HTTP
calls, no OpenAI client, and no fallback logic. Keeping the prompt in a
module that is independent of the service's calling logic satisfies the
modular-AI requirement (Req 15.3); the Moderation_Service imports
:func:`build_moderation_prompt`, hands the result to the OpenAI client, and
interprets the reply elsewhere.
"""

from __future__ import annotations

# The three valid Moderation_Result labels the model is constrained to.
MODERATION_LABELS: tuple[str, ...] = ("approved", "flagged", "blocked")

# System instruction describing the classification task and the exact,
# machine-parseable output contract expected from the model.
_SYSTEM_INSTRUCTION = (
    "You are a content-moderation classifier for Ubuntu Connect, a social "
    "networking trust platform. Read the user message and classify it into "
    "exactly one label:\n"
    "- \"blocked\": content that clearly violates policy (hate speech, "
    "threats of violence, sexual exploitation, harassment) and must not be "
    "delivered.\n"
    "- \"flagged\": borderline or potentially harmful content that should be "
    "withheld for human review.\n"
    "- \"approved\": ordinary, policy-compliant content.\n"
    "Respond with only the single lowercase label and nothing else."
)


def build_moderation_prompt(message_content: str) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to moderate ``message_content``.

    Returns an ordered list of role/content message dicts suitable for the
    OpenAI Chat Completions API. The function performs no network I/O and has
    no dependency on the OpenAI client; it only assembles the prompt.
    """
    return [
        {"role": "system", "content": _SYSTEM_INSTRUCTION},
        {
            "role": "user",
            "content": f"Classify this message:\n\n{message_content}",
        },
    ]
