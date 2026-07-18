"""``NotificationService`` — match notifications and safety alerts over SMS.

This service owns the delivery *policy* for outbound user notifications while
delegating the actual transport to
:class:`~app.integrations.sms_gateway.SmsGateway`. For every notification it:

- truncates the text to at most 160 characters before sending (Req 14.1, 14.2),
- attempts delivery at most 4 times total — an initial attempt plus up to 3
  retries — stopping as soon as the gateway accepts the message (Req 14.3), and
- when every attempt fails, records a ``notification_failures`` row capturing
  the target phone number and the notification type through the repository
  (Req 14.4).

Each 30-second delivery budget is enforced inside the gateway (Req 14.1, 14.2);
here we only decide how many times to try and what to record on total failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.integrations.sms_gateway import SmsGateway, SmsResult
from app.repositories.notification_failure_repository import (
    NotificationFailureRepository,
)

# Maximum length of an SMS notification body (Req 14.1, 14.2).
MAX_SMS_LENGTH: int = 160

# Total delivery attempts allowed: one initial attempt plus up to three
# retries when the gateway reports a delivery failure (Req 14.3).
MAX_ATTEMPTS: int = 4

# Canonical notification-type tags stored on a failure record (Req 14.4).
MATCH_NOTIFICATION: str = "match"
SAFETY_ALERT: str = "safety_alert"


@dataclass(frozen=True)
class NotificationResult:
    """Outcome of a notification-delivery request.

    ``delivered`` is ``True`` when some attempt succeeded. ``attempts`` is the
    number of send attempts made (1–:data:`MAX_ATTEMPTS`). When delivery never
    succeeds, ``delivered`` is ``False`` and a failure record has been written.
    """

    delivered: bool
    attempts: int
    notification_type: str


class NotificationService:
    """Deliver match notifications and safety alerts with retry + recording.

    The SMS gateway and the failure repository are injected so the policy can
    be exercised against a fake gateway and an in-memory session in tests, and
    so routers can supply request-scoped instances through dependency
    injection (Req 15.1).
    """

    def __init__(
        self,
        gateway: SmsGateway,
        failures: NotificationFailureRepository,
    ) -> None:
        self._gateway = gateway
        self._failures = failures

    # -- public API ---------------------------------------------------------

    def send_match_notification(
        self, phone: str, message: str
    ) -> NotificationResult:
        """Deliver a match notification to ``phone`` (Req 14.1)."""
        return self._deliver(phone, message, MATCH_NOTIFICATION)

    def send_safety_alert(self, phone: str, message: str) -> NotificationResult:
        """Deliver a safety alert to ``phone`` (Req 14.2)."""
        return self._deliver(phone, message, SAFETY_ALERT)

    # -- internals ----------------------------------------------------------

    def _deliver(
        self, phone: str, message: str, notification_type: str
    ) -> NotificationResult:
        """Truncate, then attempt delivery up to :data:`MAX_ATTEMPTS` times.

        Stops at the first accepted attempt. If all attempts fail, records a
        failure with the phone number and notification type (Req 14.4).
        """
        text = self._truncate(message)

        attempts = 0
        for attempts in range(1, MAX_ATTEMPTS + 1):
            result: SmsResult = self._gateway.send(phone, text)
            if result.success:
                return NotificationResult(
                    delivered=True,
                    attempts=attempts,
                    notification_type=notification_type,
                )

        # Every attempt failed: record the undeliverable notification.
        self._failures.create(phone=phone, notification_type=notification_type)
        return NotificationResult(
            delivered=False,
            attempts=attempts,
            notification_type=notification_type,
        )

    @staticmethod
    def _truncate(message: str) -> str:
        """Return ``message`` truncated to at most 160 characters (Req 14.1, 14.2)."""
        return message[:MAX_SMS_LENGTH]
