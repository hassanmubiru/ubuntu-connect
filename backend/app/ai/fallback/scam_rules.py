"""Deterministic rule-based scam-scoring fallback (Req 8.2).

This module is the fallback path for :mod:`app.ai.scam_detector`. When the
OpenAI API errors or exceeds its 3-second budget (Req 8.2), scam detection
degrades gracefully to these pure, deterministic rules so protection never
goes offline (design "Protection never goes offline").

``score`` is a pure function of the message text. It accumulates weighted
points for four families of scam signal commonly seen in the African social
context -- money requests, urgency pressure, prize/airtime lures, and links --
then clamps the total to an integer in the inclusive range [0, 100] (matching
the Scam_Score contract of Req 8.1/8.6). The same input always yields the same
score, and the result is the same typed value (an int in [0,100]) the AI path
produces, so the messaging pipeline is agnostic to which path scored it.

Grounding example from the spec: "I need you to send airtime to unlock your
prize before midnight." combines a money/airtime request, a prize lure, and
urgency, so it scores high enough to trip the >=70 warning threshold (Req 8.3).
"""

from __future__ import annotations

import re
from typing import Final, List, Tuple

# Bounds of a Scam_Score (Req 8.1, 8.6).
MIN_SCORE: Final[int] = 0
MAX_SCORE: Final[int] = 100

# --- Signal families --------------------------------------------------------
# Each entry is (compiled pattern, points). Points are tuned so a single strong
# signal is suspicious but not alarming, while a message combining several
# families (money + urgency + prize) clears the >=70 warning threshold.

# Money requests: asking the recipient to send funds or share payment details.
_MONEY_PATTERNS: Final[List[Tuple[re.Pattern[str], int]]] = [
    (re.compile(r"send\s+(?:me\s+)?(?:money|cash|funds)", re.IGNORECASE), 40),
    (re.compile(r"\bsend\s+(?:me\s+)?airtime\b", re.IGNORECASE), 40),
    (re.compile(r"\b(?:mpesa|m-pesa|mobile\s+money|wire\s+transfer)\b", re.IGNORECASE), 30),
    (re.compile(r"\b(?:bank\s+details|account\s+number|pin\s+code|otp\s+code)\b", re.IGNORECASE), 30),
    (re.compile(r"\b(?:western\s+union|paypal|gift\s+card)\b", re.IGNORECASE), 25),
    (re.compile(r"\b(?:deposit|transfer|pay(?:ment)?)\b", re.IGNORECASE), 15),
    (re.compile(r"[$£€]\s?\d+|\b\d+\s?(?:usd|naira|ngn|rand|zar|ksh|kes|dollars?)\b", re.IGNORECASE), 15),
]

# Urgency / pressure: manufactured time pressure to short-circuit judgement.
_URGENCY_PATTERNS: Final[List[Tuple[re.Pattern[str], int]]] = [
    (re.compile(r"\bbefore\s+midnight\b", re.IGNORECASE), 25),
    (re.compile(r"\b(?:urgent(?:ly)?|immediately|right\s+now|asap)\b", re.IGNORECASE), 20),
    (re.compile(r"\b(?:act\s+now|expires?|expiring|last\s+chance|limited\s+time)\b", re.IGNORECASE), 20),
    (re.compile(r"\b(?:hurry|don'?t\s+delay|within\s+\d+\s+(?:minutes?|hours?))\b", re.IGNORECASE), 15),
]

# Prize / airtime lures: unsolicited winnings and rewards used as bait.
_PRIZE_PATTERNS: Final[List[Tuple[re.Pattern[str], int]]] = [
    (re.compile(r"\b(?:you(?:'ve| have)?\s+won|winner|congratulations)\b", re.IGNORECASE), 30),
    (re.compile(r"\b(?:prize|lottery|jackpot|reward|bonus)\b", re.IGNORECASE), 25),
    (re.compile(r"\bunlock\s+your\s+(?:prize|reward|bonus|account)\b", re.IGNORECASE), 25),
    (re.compile(r"\bfree\s+(?:airtime|data|gift|cash|money)\b", re.IGNORECASE), 25),
    (re.compile(r"\bclaim\s+(?:your\s+)?(?:prize|reward|money|gift)\b", re.IGNORECASE), 20),
]

# Links: URLs and shortened links steering the victim off-platform.
_LINK_PATTERNS: Final[List[Tuple[re.Pattern[str], int]]] = [
    (re.compile(r"https?://\S+", re.IGNORECASE), 25),
    (re.compile(r"\b(?:bit\.ly|tinyurl\.com|t\.me|wa\.me)/\S*", re.IGNORECASE), 30),
    (re.compile(r"\bwww\.\S+\.\S+", re.IGNORECASE), 20),
    (re.compile(r"\bclick\s+(?:the\s+|this\s+)?link\b", re.IGNORECASE), 20),
]

# All families combined for a single pass.
_ALL_PATTERNS: Final[List[Tuple[re.Pattern[str], int]]] = [
    *_MONEY_PATTERNS,
    *_URGENCY_PATTERNS,
    *_PRIZE_PATTERNS,
    *_LINK_PATTERNS,
]


def score(text: str) -> int:
    """Return the rule-based Scam_Score for ``text`` as an int in [0, 100].

    Pure and deterministic. Sums the weighted points of every matching scam
    signal (money, urgency, prize/airtime, links) and clamps the total to the
    inclusive range [0, 100]. An empty or non-truthy message scores 0 since it
    carries no scam signal.
    """

    if not text:
        return MIN_SCORE

    total = 0
    for pattern, points in _ALL_PATTERNS:
        if pattern.search(text):
            total += points

    # Clamp to the Scam_Score bounds (Req 8.1, 8.6).
    if total < MIN_SCORE:
        return MIN_SCORE
    if total > MAX_SCORE:
        return MAX_SCORE
    return total
