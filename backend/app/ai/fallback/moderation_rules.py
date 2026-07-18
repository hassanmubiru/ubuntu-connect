"""Deterministic rule-based moderation fallback (Req 7.5, 8.2).

This module is the fallback path for :mod:`app.ai.moderation_service`. When the
OpenAI API is unavailable or exceeds its 5-second budget (Req 7.6), moderation
degrades gracefully to these pure, deterministic rules rather than failing open
or blocking the whole platform (design "Protection never goes offline").

``classify`` is a pure function of the message text: it maps banned/harmful
keyword patterns to one of the three Moderation_Result labels required by
Req 7.1 -- ``"blocked"``, ``"flagged"``, or ``"approved"`` -- and returns the
most severe label that matches. There is no I/O, randomness, or hidden state,
so the same input always yields the same label. This is the same typed result
(a label string) the AI path produces, so the pipeline stays agnostic to which
path scored the message.
"""

from __future__ import annotations

import re
from typing import Final, List, Tuple

# The three Moderation_Result labels (Req 7.1), ordered by severity so the
# classifier can resolve to the most severe matching category.
BLOCKED: Final[str] = "blocked"
FLAGGED: Final[str] = "flagged"
APPROVED: Final[str] = "approved"

# Severity ranking used to pick the strongest matching label.
_SEVERITY: Final[dict[str, int]] = {APPROVED: 0, FLAGGED: 1, BLOCKED: 2}


def _pattern(*words: str) -> re.Pattern[str]:
    """Compile a case-insensitive, word-boundary alternation of ``words``.

    Using word boundaries avoids false positives on substrings (e.g. "kill"
    inside "skill" or "grass" containing a slur fragment).
    """

    alternation = "|".join(re.escape(w) for w in words)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


# --- "blocked" patterns -----------------------------------------------------
# Content that must never be delivered: credible threats of violence, explicit
# sexual solicitation, incitement, and encouragement of self-harm. A match
# means the message violates content policy (Req 7.2).
_BLOCKED_PATTERNS: Final[List[re.Pattern[str]]] = [
    _pattern(
        "kill you",
        "kill yourself",
        "i will kill",
        "i'll kill",
        "murder you",
        "rape",
        "rape you",
        "bomb",
        "shoot you",
        "stab you",
        "hang yourself",
        "go die",
        "kys",
    ),
    # Multi-word incitement / explicit solicitation phrases.
    re.compile(r"send\s+(?:me\s+)?nudes?", re.IGNORECASE),
    re.compile(r"child\s+porn", re.IGNORECASE),
    re.compile(r"(?:death|rape)\s+threat", re.IGNORECASE),
]

# --- "flagged" patterns -----------------------------------------------------
# Content that is concerning but not an outright violation: insults,
# harassment, and vulgar abuse. Flagged messages are persisted, withheld from
# the receiver, and surfaced to the Admin_Panel for human review (Req 7.4).
_FLAGGED_PATTERNS: Final[List[re.Pattern[str]]] = [
    _pattern(
        "idiot",
        "stupid",
        "moron",
        "loser",
        "worthless",
        "hate you",
        "shut up",
        "trash",
        "ugly",
        "dumb",
        "fool",
    ),
    _pattern("fuck", "fuck you", "shit", "bitch", "bastard", "asshole"),
]

# Ordered rule table: (compiled pattern, label). Evaluated top to bottom; the
# most severe matching label wins via ``_SEVERITY``.
_RULES: Final[List[Tuple[re.Pattern[str], str]]] = [
    *[(p, BLOCKED) for p in _BLOCKED_PATTERNS],
    *[(p, FLAGGED) for p in _FLAGGED_PATTERNS],
]


def classify(text: str) -> str:
    """Return the rule-based Moderation_Result for ``text``.

    Pure and deterministic. Returns the most severe label whose keyword
    patterns match the message: ``"blocked"`` for policy violations,
    ``"flagged"`` for concerning-but-reviewable content, otherwise
    ``"approved"``. A non-string or empty message is treated as ``"approved"``
    since there is nothing harmful to match.
    """

    if not text:
        return APPROVED

    result = APPROVED
    for pattern, label in _RULES:
        if pattern.search(text) and _SEVERITY[label] > _SEVERITY[result]:
            result = label
            if result == BLOCKED:
                # Nothing is more severe; short-circuit.
                break
    return result
