"""``TrustEngine`` — deterministic Trust_Score computation (Req 5).

The engine derives a user's Trust_Score from exactly four factors and records
one reason entry per factor on every recalculation. It owns no data-store
access of its own: every read and write flows through injected repositories,
keeping the repository boundary intact (Req 15.1).

Scoring (Req 5.1, 5.5):

    raw = 30 * verified
        + 10 * populated_profile_fields          (0..3 of {photo, bio, interests})
        + min(messages_sent, 40)                  (account activity)
        - 15 * confirmed_reports
    trust_score = clamp(raw, 0, 100)

The weighting makes the monotonicity guarantees the requirements demand:

* phone verification contributes a non-negative amount, so verifying a phone
  never lowers the score (Req 5.2);
* each populated profile field adds a fixed non-negative amount (Req 5.3);
* each confirmed report subtracts a fixed amount, so a newly confirmed report
  yields a score no higher than before (Req 5.4).

On every recalculation the engine clears the user's prior reason entries and
writes exactly one row per factor (Req 5.6), then persists the clamped score.
The explanation endpoint reads those rows back (Req 5.7); a score with no
recorded entries drives the no-explanation error path (Req 5.8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.user import User
from app.repositories.message_repository import MessageRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.trust_reason_repository import TrustReasonRepository
from app.repositories.user_repository import UserRepository
from app.schemas.errors import NotFoundError

# --- Scoring parameters (documented weights, Req 5.5) -----------------------

VERIFIED_PHONE_POINTS = 30
PER_PROFILE_FIELD_POINTS = 10
PER_CONFIRMED_REPORT_PENALTY = 15
ACTIVITY_CAP = 40

SCORE_MIN = 0
SCORE_MAX = 100

# Stable factor identifiers recorded on each reason row (Req 5.6). The order
# here is the order the reasons are written and read back.
FACTOR_PHONE_VERIFICATION = "phone_verification"
FACTOR_PROFILE_COMPLETENESS = "profile_completeness"
FACTOR_ACTIVITY = "activity"
FACTOR_CONFIRMED_REPORTS = "confirmed_reports"

# Generic, safe message for the no-explanation-available error (Req 5.8).
NO_EXPLANATION_MESSAGE = "No explanation is available for this trust score."
USER_NOT_FOUND_MESSAGE = "The requested user was not found."


def _clamp(value: int, low: int = SCORE_MIN, high: int = SCORE_MAX) -> int:
    """Clamp ``value`` into the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


def _populated_profile_fields(user: User) -> int:
    """Count how many of {profile_photo, bio, interests} are populated (Req 5.3).

    A field is populated when it holds a non-empty value: a non-blank photo
    reference, a bio with non-whitespace content, or a non-empty interests
    list.
    """
    count = 0
    if user.profile_photo and user.profile_photo.strip():
        count += 1
    if user.bio and user.bio.strip():
        count += 1
    if user.interests:
        count += 1
    return count


@dataclass(frozen=True)
class TrustCalculation:
    """The outcome of one recalculation: the clamped score and its factors.

    ``reasons`` holds the ``(factor, contribution, description)`` triples that
    were recorded, in the order they were written (Req 5.6).
    """

    user_id: uuid.UUID
    trust_score: int
    reasons: list[tuple[str, int, str]]


class TrustEngine:
    """Compute and persist Trust_Scores over the injected repositories.

    Repositories are injected so the engine can be exercised directly in tests
    and provided per-request through dependency injection, and so it never
    touches a database session (Req 15.1). :meth:`recalculate` is the single
    public entry point other services call after the events that change a
    score: phone verification (Req 5.2), profile updates (Req 5.3), a confirmed
    report (Req 5.4), and message activity (Req 5.5).
    """

    def __init__(
        self,
        users: UserRepository,
        messages: MessageRepository,
        reports: ReportRepository,
        trust_reasons: TrustReasonRepository,
    ) -> None:
        self._users = users
        self._messages = messages
        self._reports = reports
        self._trust_reasons = trust_reasons

    # -- computation --------------------------------------------------------

    def _build_reasons(
        self,
        *,
        verified: bool,
        populated_fields: int,
        messages_sent: int,
        confirmed_reports: int,
    ) -> list[tuple[str, int, str]]:
        """Build the ordered reason set for the four factors (Req 5.6)."""
        verification_points = VERIFIED_PHONE_POINTS if verified else 0
        profile_points = PER_PROFILE_FIELD_POINTS * populated_fields
        activity_points = min(messages_sent, ACTIVITY_CAP)
        report_penalty = PER_CONFIRMED_REPORT_PENALTY * confirmed_reports

        return [
            (
                FACTOR_PHONE_VERIFICATION,
                verification_points,
                (
                    f"Phone verification: "
                    f"{'verified' if verified else 'not verified'} "
                    f"(+{verification_points})"
                ),
            ),
            (
                FACTOR_PROFILE_COMPLETENESS,
                profile_points,
                (
                    f"Profile completeness: {populated_fields} of 3 fields "
                    f"(+{profile_points})"
                ),
            ),
            (
                FACTOR_ACTIVITY,
                activity_points,
                f"Activity: {messages_sent} messages (+{activity_points})",
            ),
            (
                FACTOR_CONFIRMED_REPORTS,
                -report_penalty,
                (
                    f"Confirmed reports: {confirmed_reports} "
                    f"(\u2212{report_penalty})"
                ),
            ),
        ]

    # -- public entry point -------------------------------------------------

    def recalculate(self, user_id: uuid.UUID) -> TrustCalculation:
        """Recompute, record reasons for, and persist a user's Trust_Score.

        Reads the four factors through the repositories, clamps the weighted
        sum to [0, 100] (Req 5.1), replaces the user's prior reason entries
        with one row per factor (Req 5.6), and persists the new score. Raises
        :class:`NotFoundError` when the user does not exist.
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(USER_NOT_FOUND_MESSAGE)

        verified = bool(user.verified_phone)
        populated_fields = _populated_profile_fields(user)
        messages_sent = self._messages.count_sent_by(user_id)
        confirmed_reports = self._reports.count_confirmed_against(user_id)

        reasons = self._build_reasons(
            verified=verified,
            populated_fields=populated_fields,
            messages_sent=messages_sent,
            confirmed_reports=confirmed_reports,
        )
        raw = sum(contribution for _factor, contribution, _desc in reasons)
        trust_score = _clamp(raw)

        # Replace the prior explanation with the fresh factor set (Req 5.6),
        # then persist the recalculated score (Req 5.1).
        self._trust_reasons.clear_for_user(user_id)
        self._trust_reasons.add_many(user_id, reasons)
        self._users.set_trust_score(user, trust_score)

        return TrustCalculation(
            user_id=user_id, trust_score=trust_score, reasons=reasons
        )

    # -- reads --------------------------------------------------------------

    def get_score(self, user_id: uuid.UUID) -> int:
        """Return a user's current Trust_Score (Req 5.1).

        Raises :class:`NotFoundError` when the user does not exist.
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(USER_NOT_FOUND_MESSAGE)
        return int(user.trust_score)

    def get_explanation(self, user_id: uuid.UUID) -> list:
        """Return the recorded reason entries for a user's score (Req 5.7).

        Raises :class:`NotFoundError` when the user does not exist, and a
        no-explanation-available error when the user has no recorded reason
        entries (Req 5.8).
        """
        user = self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError(USER_NOT_FOUND_MESSAGE)

        reasons = self._trust_reasons.list_for_user(user_id)
        if not reasons:
            raise NotFoundError(NO_EXPLANATION_MESSAGE)
        return reasons
