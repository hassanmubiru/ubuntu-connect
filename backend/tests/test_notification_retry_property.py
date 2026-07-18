"""Property test for notification retry bound and failure recording (task 12.3).

Feature: ubuntu-connect, Property 51: For any notification whose delivery keeps
failing, delivery is attempted at most 4 times total (initial plus 3 retries),
and if all attempts fail a failure record is written capturing the target phone
number and the notification type.

Validates: Requirements 14.3, 14.4

Strategy
--------
A fake ``SmsGateway`` counts every ``send`` call and is configured to either
fail every attempt or to succeed on a chosen attempt ``k``. The real
:class:`NotificationService` drives its retry/record policy against this fake
gateway and a real :class:`NotificationFailureRepository` backed by an isolated
in-memory SQLite session (the fixture pattern from ``test_repositories.py``).

For each generated scenario:
* always-fail — delivery is attempted exactly :data:`MAX_ATTEMPTS` (4) times,
  the result is undelivered, and exactly one ``notification_failures`` row is
  written capturing the target phone and the notification type; and
* succeed-on-attempt-``k`` (``k`` in 1..4) — delivery stops at attempt ``k``,
  the result is delivered, and no failure record is written.
"""

from __future__ import annotations

from contextlib import contextmanager

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select

from app import db
from app.integrations.sms_gateway import SmsResult
from app.models import Base
from app.models.notification_failure import NotificationFailure
from app.repositories.notification_failure_repository import (
    NotificationFailureRepository,
)
from app.services.notification_service import (
    MATCH_NOTIFICATION,
    MAX_ATTEMPTS,
    SAFETY_ALERT,
    NotificationService,
)


@contextmanager
def _in_memory_session():
    """Yield a live session on a fresh, isolated in-memory SQLite engine.

    A context manager (rather than a function-scoped fixture) so each generated
    Hypothesis example runs against its own reset database.
    """
    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    sess = db.get_session_factory()()
    try:
        yield sess
    finally:
        sess.close()
        Base.metadata.drop_all(engine)
        db.reset_engine()


class _FakeGateway:
    """A fake SMS gateway that counts sends and fails per a fixed policy.

    ``succeed_on`` is the 1-based attempt number that should succeed; ``None``
    means every attempt fails. ``attempts`` records how many times the service
    called :meth:`send`.
    """

    def __init__(self, succeed_on: int | None) -> None:
        self._succeed_on = succeed_on
        self.attempts = 0
        self.last_phone: str | None = None
        self.last_message: str | None = None

    def send(self, phone: str, message: str) -> SmsResult:
        self.attempts += 1
        self.last_phone = phone
        self.last_message = message
        if self._succeed_on is not None and self.attempts == self._succeed_on:
            return SmsResult(success=True)
        return SmsResult(success=False, detail="fake delivery failure")


# Realistic African fixture phone numbers and the two notification types.
_PHONE = st.sampled_from(
    ["+2348031234567", "+27821234567", "+233201234567", "+254712345678"]
)
_KIND = st.sampled_from([MATCH_NOTIFICATION, SAFETY_ALERT])
_MESSAGE = st.text(min_size=0, max_size=400)


def _count_failures(session) -> int:
    return session.execute(
        select(func.count()).select_from(NotificationFailure)
    ).scalar_one()


def _deliver(service: NotificationService, kind: str, phone: str, message: str):
    if kind == MATCH_NOTIFICATION:
        return service.send_match_notification(phone, message)
    return service.send_safety_alert(phone, message)


# Feature: ubuntu-connect, Property 51: For any notification whose delivery
# keeps failing, delivery is attempted at most 4 times total (initial plus 3
# retries), and if all attempts fail a failure record is written capturing the
# target phone number and the notification type.
# Validates: Requirements 14.3, 14.4
@settings(max_examples=100)
@given(
    # succeed_on: None => always fail; 1..MAX_ATTEMPTS => succeed on that attempt.
    succeed_on=st.one_of(st.none(), st.integers(min_value=1, max_value=MAX_ATTEMPTS)),
    phone=_PHONE,
    kind=_KIND,
    message=_MESSAGE,
)
def test_retry_bound_and_failure_recording(succeed_on, phone, kind, message):
    with _in_memory_session() as session:
        gateway = _FakeGateway(succeed_on)
        failures = NotificationFailureRepository(session)
        service = NotificationService(gateway, failures)

        result = _deliver(service, kind, phone, message)
        session.flush()

        # Delivery is never attempted more than the 4-attempt bound.
        assert gateway.attempts <= MAX_ATTEMPTS

        if succeed_on is None:
            # Always-fail: exactly MAX_ATTEMPTS attempts, undelivered, one record.
            assert gateway.attempts == MAX_ATTEMPTS
            assert result.delivered is False
            assert result.attempts == MAX_ATTEMPTS

            assert _count_failures(session) == 1
            record = session.execute(
                select(NotificationFailure)
            ).scalars().one()
            assert record.phone == phone
            assert record.notification_type == kind
        else:
            # Success on attempt k: stops early at k, delivered, no failure record.
            assert gateway.attempts == succeed_on
            assert result.delivered is True
            assert result.attempts == succeed_on
            assert result.notification_type == kind
            assert _count_failures(session) == 0
