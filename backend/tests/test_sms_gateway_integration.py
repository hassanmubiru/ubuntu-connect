"""Integration test for SMS client request shaping and retries (Task 12.4).

This test wires the *real* :class:`~app.integrations.sms_gateway.SmsGateway`
and :class:`~app.services.notification_service.NotificationService` together
over a real ``httpx.Client`` whose transport is an ``httpx.MockTransport``.
The mock transport stands in for the Africa's Talking messaging endpoint so
the actual outgoing HTTP request can be captured and asserted against, and so
provider failures/successes can be scripted to exercise the retry policy.

It covers two behaviours:

- Request shaping (Req 14.1): the gateway POSTs to the Africa's Talking
  messaging endpoint with the ``apiKey`` header taken from configuration and a
  form body carrying ``username``, ``to``, ``message``, and ``from`` shaped
  from the config + call arguments.
- Retry behaviour (Req 14.3): when the provider keeps rejecting the message,
  ``NotificationService`` attempts delivery at most 4 times total (initial plus
  3 retries) and records a failure; when an attempt succeeds it stops early and
  records nothing.

Fixtures use realistic African data: Amara Okafor (+2348031234567) and inert,
non-secret credential placeholders (never real Africa's Talking credentials).
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import create_engine

from app import db
from app.config import Config
from app.integrations.sms_gateway import AFRICASTALKING_SMS_URL, SmsGateway
from app.models import Base
from app.repositories.notification_failure_repository import (
    NotificationFailureRepository,
)
from app.services.notification_service import (
    MATCH_NOTIFICATION,
    MAX_ATTEMPTS,
    NotificationService,
)

# Inert, non-secret configuration placeholders. These are test fixtures, not
# real Africa's Talking credentials; the point is to prove the gateway sources
# the apiKey header and form fields from config, whatever their values.
TEST_CONFIG = Config(
    at_api_key="test-at-key",
    at_username="test-at-username",
    at_sms_sender_id="UBUNTU",
)

AMARA_PHONE = "+2348031234567"

# Africa's Talking messaging payloads: a recipient with status "Success" is an
# accepted send; any other status is a provider-reported delivery failure.
AT_SUCCESS = {"SMSMessageData": {"Recipients": [{"status": "Success"}]}}
AT_FAILURE = {"SMSMessageData": {"Recipients": [{"status": "InvalidPhoneNumber"}]}}


@pytest.fixture()
def session():
    """Bind an isolated in-memory SQLite engine and yield a live session.

    Used so the retry tests write real ``notification_failures`` rows through
    the real repository rather than a stub.
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


def _client_capturing(captured: list[httpx.Request], responses: list[dict]):
    """Build an ``httpx.Client`` whose mock transport records each request.

    Each call consumes the next payload in ``responses`` (the last payload is
    reused once the list is exhausted), returning it as a 200 JSON response.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        index = min(len(captured) - 1, len(responses) - 1)
        return httpx.Response(200, json=responses[index])

    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Request shaping (Req 14.1)
# ---------------------------------------------------------------------------
def test_send_shapes_africastalking_request() -> None:
    """The outgoing request targets the AT endpoint with config-derived fields."""
    captured: list[httpx.Request] = []
    with _client_capturing(captured, [AT_SUCCESS]) as client:
        gateway = SmsGateway(TEST_CONFIG, http_client=client)
        result = gateway.send_match_notification(
            AMARA_PHONE, "You have a new match on Ubuntu Connect!"
        )

    assert result.success is True
    assert len(captured) == 1
    request = captured[0]

    # URL is the Africa's Talking messaging endpoint, sent as a POST.
    assert request.method == "POST"
    assert str(request.url) == AFRICASTALKING_SMS_URL

    # The apiKey header is taken from configuration (Req 14.1, 15.4).
    assert request.headers["apiKey"] == TEST_CONFIG.at_api_key
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"

    # The form body carries username/to/message/from shaped from config + args.
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form["username"] == TEST_CONFIG.at_username
    assert form["to"] == AMARA_PHONE
    assert form["message"] == "You have a new match on Ubuntu Connect!"
    assert form["from"] == TEST_CONFIG.at_sms_sender_id


# ---------------------------------------------------------------------------
# Retry behaviour (Req 14.3)
# ---------------------------------------------------------------------------
def test_retries_up_to_four_attempts_then_records_failure(session) -> None:
    """When the provider keeps rejecting, delivery is tried 4 times total."""
    captured: list[httpx.Request] = []
    failures = NotificationFailureRepository(session)
    with _client_capturing(captured, [AT_FAILURE]) as client:
        gateway = SmsGateway(TEST_CONFIG, http_client=client)
        service = NotificationService(gateway, failures)
        result = service.send_match_notification(
            AMARA_PHONE, "You have a new match on Ubuntu Connect!"
        )
    session.flush()

    # Initial attempt plus three retries — exactly four outgoing requests.
    assert MAX_ATTEMPTS == 4
    assert len(captured) == MAX_ATTEMPTS
    assert result.delivered is False
    assert result.attempts == MAX_ATTEMPTS

    # Every request went to the AT endpoint with the config apiKey.
    assert all(str(r.url) == AFRICASTALKING_SMS_URL for r in captured)
    assert all(r.headers["apiKey"] == TEST_CONFIG.at_api_key for r in captured)

    # A failure record captures the target phone and notification type (Req 14.4).
    from app.models.notification_failure import NotificationFailure

    rows = session.query(NotificationFailure).all()
    assert len(rows) == 1
    assert rows[0].phone == AMARA_PHONE
    assert rows[0].notification_type == MATCH_NOTIFICATION


def test_stops_early_on_success_without_recording_failure(session) -> None:
    """A successful attempt stops the retry loop and records no failure."""
    captured: list[httpx.Request] = []
    failures = NotificationFailureRepository(session)
    # Fail twice, then the third attempt succeeds.
    responses = [AT_FAILURE, AT_FAILURE, AT_SUCCESS]
    with _client_capturing(captured, responses) as client:
        gateway = SmsGateway(TEST_CONFIG, http_client=client)
        service = NotificationService(gateway, failures)
        result = service.send_safety_alert(
            AMARA_PHONE, "Safety alert: be cautious sharing personal info."
        )
    session.flush()

    # Stops as soon as an attempt is accepted: three requests, no fourth.
    assert len(captured) == 3
    assert result.delivered is True
    assert result.attempts == 3

    from app.models.notification_failure import NotificationFailure

    assert session.query(NotificationFailure).count() == 0
