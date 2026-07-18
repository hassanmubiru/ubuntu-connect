"""Property test for SMS notification truncation (task 12.2).

Feature: ubuntu-connect, Property 50: For any match notification or safety
alert, the text sent through the SMS_Gateway is truncated to 160 characters
or fewer.

Validates: Requirements 14.1, 14.2

Strategy
--------
``NotificationService`` owns the truncation policy and delegates transport to
an injected :class:`~app.integrations.sms_gateway.SmsGateway`. To observe the
exact text that reaches the gateway, a *capturing fake* gateway records every
``(phone, message)`` pair passed to ``send`` and reports success so the
service sends exactly once per notification.

Hypothesis generates arbitrary-length message bodies — deliberately including
values far longer than the 160-character limit — and the test asserts that,
for both ``send_match_notification`` and ``send_safety_alert``, the text the
gateway actually receives is never longer than ``MAX_SMS_LENGTH`` (160).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations.sms_gateway import SmsResult
from app.services.notification_service import MAX_SMS_LENGTH, NotificationService


class _CapturingGateway:
    """Fake SMS gateway that records the text passed to ``send``.

    Mirrors the ``send(phone, message) -> SmsResult`` surface the service
    depends on, always accepting the message so exactly one send happens per
    notification, and stores each captured message for assertions.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, phone: str, message: str) -> SmsResult:
        self.sent.append((phone, message))
        return SmsResult(success=True)


class _NoopFailures:
    """Failure repository stand-in; unused because every send succeeds."""

    def create(self, *, phone: str, notification_type: str) -> None:  # pragma: no cover
        raise AssertionError("no failure should be recorded when delivery succeeds")


# Phone numbers are irrelevant to truncation; a small valid E.164 sample keeps
# the focus on message length.
_PHONES = st.sampled_from(
    ["+2348031234567", "+27821234567", "+233201234567", "+254712345678"]
)

# Messages of arbitrary length, biased to include values longer than the
# 160-character cap so truncation is exercised on both sides of the boundary.
_MESSAGES = st.one_of(
    st.text(max_size=MAX_SMS_LENGTH),
    st.text(min_size=MAX_SMS_LENGTH, max_size=MAX_SMS_LENGTH),
    st.text(min_size=MAX_SMS_LENGTH + 1, max_size=MAX_SMS_LENGTH * 6),
)


# Feature: ubuntu-connect, Property 50: For any match notification or safety
# alert, the text sent through the SMS_Gateway is truncated to 160 characters
# or fewer.
# Validates: Requirements 14.1, 14.2
@settings(max_examples=100)
@given(
    phone=_PHONES,
    message=_MESSAGES,
    kind=st.sampled_from(["match", "safety_alert"]),
)
def test_sms_text_is_truncated_to_160_chars(
    phone: str, message: str, kind: str
) -> None:
    gateway = _CapturingGateway()
    service = NotificationService(gateway=gateway, failures=_NoopFailures())

    if kind == "match":
        service.send_match_notification(phone, message)
    else:
        service.send_safety_alert(phone, message)

    # Exactly one send happened, and the text the gateway received respects
    # the 160-character cap regardless of how long the original message was.
    assert len(gateway.sent) == 1
    _, sent_text = gateway.sent[0]
    assert len(sent_text) <= MAX_SMS_LENGTH
