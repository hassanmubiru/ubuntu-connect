"""Africa's Talking SMS client (``SmsGateway``).

This module wraps the Africa's Talking SMS API behind a small, typed
interface whose single responsibility is *transporting one SMS to the
provider and reporting whether it was accepted for delivery*. It carries no
retry policy or truncation logic — those belong to
:class:`~app.services.notification_service.NotificationService` (Req 14.1–14.3)
so the gateway stays a thin, replaceable transport.

Three convenience methods cover the three message types the platform sends:

- OTP delivery (Req 2.1, 2.9),
- match notifications (Req 14.1), and
- safety alerts (Req 14.2).

Each returns an :class:`SmsResult` whose ``success`` flag lets callers react
to a delivery failure without catching exceptions — the OTP service surfaces
a send-failure error while keeping resend available (Req 2.9), and the
notification service uses it to drive its retry/record policy (Req 14.3, 14.4).

Credentials (API key, username, sender id) are read exclusively from
:class:`app.config.Config`, which sources them from the environment; no
credential literal appears here (Req 15.4). The Africa's Talking messaging
endpoint is a public, non-secret URL kept as a module constant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.config import Config

# Public Africa's Talking messaging endpoint. This is a well-known,
# non-secret service URL (not a credential); the API key, username, and
# sender id that authenticate the request all come from the environment.
AFRICASTALKING_SMS_URL: str = "https://api.africastalking.com/version1/messaging"

# Per-notification delivery budget (seconds). The SMS_Gateway must deliver a
# notification within 30 seconds of it being generated (Req 14.1, 14.2); a
# call that exceeds this budget is treated as a delivery failure.
SMS_DELIVERY_TIMEOUT_SECONDS: float = 30.0


@dataclass(frozen=True)
class SmsResult:
    """Outcome of a single SMS send attempt.

    ``success`` is ``True`` only when the provider accepted the message for
    delivery. ``detail`` carries a short human-readable reason on failure
    (timeout, transport error, provider rejection) for logging/diagnostics,
    and ``raw`` holds the decoded provider payload when one was returned.
    """

    success: bool
    detail: str = ""
    raw: dict = field(default_factory=dict)


class SmsGateway:
    """Thin transport around the Africa's Talking SMS API.

    An ``httpx.Client`` may be injected for testing; otherwise one is created
    per call and closed afterwards so the gateway holds no open sockets when
    idle. Delivery failures (timeouts, transport errors, non-2xx responses,
    provider-reported rejections) are reported as ``SmsResult(success=False)``
    rather than raised, giving callers a single, uniform failure signal.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = config or Config.from_env()
        self._http_client = http_client

    # -- public API ---------------------------------------------------------

    def send_otp(self, phone: str, code: str) -> SmsResult:
        """Send a one-time passcode to ``phone`` (Req 2.1, 2.9)."""
        return self.send(phone, f"Your Ubuntu Connect verification code is {code}.")

    def send_match_notification(self, phone: str, message: str) -> SmsResult:
        """Send a match notification to ``phone`` (Req 14.1).

        The caller (NotificationService) is responsible for truncation and
        retries; this simply transports the already-prepared text.
        """
        return self.send(phone, message)

    def send_safety_alert(self, phone: str, message: str) -> SmsResult:
        """Send a safety alert to ``phone`` (Req 14.2)."""
        return self.send(phone, message)

    def send(self, phone: str, message: str) -> SmsResult:
        """Transport one SMS to Africa's Talking and report the outcome.

        Returns ``SmsResult(success=True)`` when the provider accepts the
        message for delivery; otherwise returns a failing result describing
        why. Never raises for a delivery failure so callers can branch on
        ``result.success`` (Req 2.9, 14.3).
        """
        payload = {
            "username": self._config.at_username,
            "to": phone,
            "message": message,
            "from": self._config.at_sms_sender_id,
        }
        headers = {
            "apiKey": self._config.at_api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            data = self._post(payload=payload, headers=headers)
        except httpx.TimeoutException:
            return SmsResult(
                success=False,
                detail=(
                    "SMS delivery exceeded its "
                    f"{SMS_DELIVERY_TIMEOUT_SECONDS:g}s budget"
                ),
            )
        except httpx.HTTPError as exc:
            return SmsResult(success=False, detail=f"SMS transport error: {exc}")
        except ValueError:
            return SmsResult(
                success=False, detail="SMS provider returned a malformed response"
            )

        return self._interpret(data)

    # -- internals ----------------------------------------------------------

    def _post(self, *, payload: dict, headers: dict[str, str]) -> dict:
        """POST ``payload`` (form-encoded) to the messaging endpoint.

        Raises ``httpx`` errors on timeout/transport failure and ``ValueError``
        on a non-JSON body; :meth:`send` maps these to failing results.
        """
        if self._http_client is not None:
            response = self._http_client.post(
                AFRICASTALKING_SMS_URL,
                data=payload,
                headers=headers,
                timeout=SMS_DELIVERY_TIMEOUT_SECONDS,
            )
        else:
            with httpx.Client(timeout=SMS_DELIVERY_TIMEOUT_SECONDS) as client:
                response = client.post(
                    AFRICASTALKING_SMS_URL, data=payload, headers=headers
                )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _interpret(data: dict) -> SmsResult:
        """Map an Africa's Talking messaging payload to an :class:`SmsResult`.

        A successful send lists one recipient per number with a ``status`` of
        ``"Success"``. Any recipient not accepted, or a payload missing the
        expected structure, is treated as a delivery failure.
        """
        recipients = (
            data.get("SMSMessageData", {}).get("Recipients", [])
            if isinstance(data, dict)
            else []
        )
        if recipients and all(
            r.get("status") == "Success" for r in recipients
        ):
            return SmsResult(success=True, raw=data)
        return SmsResult(
            success=False,
            detail="SMS provider did not accept the message for delivery",
            raw=data if isinstance(data, dict) else {},
        )
