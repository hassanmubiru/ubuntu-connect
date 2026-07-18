"""Scam-scoring prompt builder.

This module builds the chat prompt used to ask OpenAI to assign a Scam_Score
— an integer from 0 to 100 — to a message (Req 8.1). Like the moderation
prompt, it contains prompt construction only: no HTTP calls, no OpenAI
client, and no fallback logic, keeping prompts independent of the service's
calling logic (Req 15.3). The Scam_Detector imports :func:`build_scam_prompt`,
sends the result through the OpenAI client, and parses the numeric reply
elsewhere.
"""

from __future__ import annotations

# Inclusive bounds of the Scam_Score the model is asked to produce (Req 8.1).
SCAM_SCORE_MIN: int = 0
SCAM_SCORE_MAX: int = 100

# System instruction describing the scoring task, the signals to weigh, and
# the exact, machine-parseable output contract expected from the model.
_SYSTEM_INSTRUCTION = (
    "You are a scam-detection analyzer for Ubuntu Connect, a social "
    "networking trust platform. Read the user message and estimate the "
    "likelihood that it is a scam. Weigh signals such as requests for money "
    "or airtime, urgency or deadlines, prize or reward lures, requests to "
    "move off-platform, and suspicious links.\n"
    f"Respond with only a single integer from {SCAM_SCORE_MIN} to "
    f"{SCAM_SCORE_MAX} (inclusive) representing the scam likelihood, where "
    f"{SCAM_SCORE_MIN} means clearly legitimate and {SCAM_SCORE_MAX} means "
    "almost certainly a scam. Output only the number and nothing else."
)


def build_scam_prompt(message_content: str) -> list[dict[str, str]]:
    """Build the chat messages that ask the model to score ``message_content``.

    Returns an ordered list of role/content message dicts suitable for the
    OpenAI Chat Completions API. The function performs no network I/O and has
    no dependency on the OpenAI client; it only assembles the prompt.
    """
    return [
        {"role": "system", "content": _SYSTEM_INSTRUCTION},
        {
            "role": "user",
            "content": f"Score this message:\n\n{message_content}",
        },
    ]
