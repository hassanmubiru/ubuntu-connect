"""Timeout-bounded OpenAI client wrapper.

This module wraps OpenAI Chat Completions calls behind a small, typed
interface whose single responsibility is *making the call within a bounded
time budget and surfacing failures as exceptions*. It contains no prompt
construction (that lives in :mod:`app.ai.prompts`) and no classification or
scoring logic (that lives in the AI services); it merely transports a
pre-built prompt to the provider and returns the raw completion text.

Two distinct time budgets are defined to match the requirements:

- Moderation calls get a 5-second budget (Req 7.6): if OpenAI does not
  respond within 5 seconds the call raises and the Moderation_Service falls
  back to its rule-based classifier.
- Scam-scoring calls get a 3-second budget (Req 8.2): if OpenAI errors or
  does not respond within 3 seconds the call raises and the Scam_Detector
  falls back to its rule-based scorer.

On *any* timeout or transport/protocol error the client raises
:class:`OpenAIError` (or its :class:`OpenAITimeoutError` subclass) so callers
have a single, explicit failure signal to trigger their deterministic
fallback (Req 7.6, 8.2). Credentials and the endpoint are read exclusively
from :class:`app.config.Config`, which sources them from the environment; no
credential or endpoint literal appears here (Req 15.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.config import Config

# Per-call time budgets (seconds). These are behavioural limits from the
# requirements, not endpoints or credentials, so defining them here is safe.
MODERATION_TIMEOUT_SECONDS: float = 5.0
SCAM_TIMEOUT_SECONDS: float = 3.0

# Default model identifier. A model name is neither a credential nor an
# endpoint; the base URL and API key still come from the environment.
DEFAULT_MODEL: str = "gpt-4o-mini"

# A chat prompt is an ordered list of role/content message dicts, exactly the
# shape produced by the prompt modules in :mod:`app.ai.prompts`.
ChatMessages = list[dict[str, str]]


class OpenAIError(RuntimeError):
    """Raised when an OpenAI call fails for any reason.

    Callers treat this as the signal to invoke their rule-based fallback so
    that protection never goes offline (Req 7.6, 8.2).
    """


class OpenAITimeoutError(OpenAIError):
    """Raised specifically when an OpenAI call exceeds its time budget."""


@dataclass(frozen=True)
class OpenAIResponse:
    """The text content of a completion plus the raw decoded payload."""

    content: str
    raw: dict = field(default_factory=dict)


class OpenAIClient:
    """Thin, timeout-bounded transport around OpenAI Chat Completions.

    The client is intentionally free of any moderation/scam semantics: it
    accepts an already-built prompt, enforces a caller-supplied timeout, and
    returns the raw completion text (or raises). This keeps prompt building
    (:mod:`app.ai.prompts`) and decision logic (AI services) independent of
    the transport (Req 15.3).

    An ``httpx.Client`` may be injected for testing; otherwise one is created
    per call and closed afterwards so the client holds no open sockets when
    idle.
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

    def complete(
        self,
        messages: ChatMessages,
        *,
        timeout: float,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.0,
    ) -> OpenAIResponse:
        """Send ``messages`` to OpenAI and return the completion text.

        ``timeout`` is the total per-call budget in seconds. Exceeding it
        raises :class:`OpenAITimeoutError`; any other transport, protocol, or
        malformed-response failure raises :class:`OpenAIError`. Successful
        calls return an :class:`OpenAIResponse` carrying the assistant text.
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._config.openai_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._config.openai_base_url.rstrip('/')}/chat/completions"

        data = self._post(url, payload=payload, headers=headers, timeout=timeout)
        return OpenAIResponse(content=self._extract_content(data), raw=data)

    def moderate(
        self,
        messages: ChatMessages,
        *,
        model: str = DEFAULT_MODEL,
    ) -> OpenAIResponse:
        """Run a moderation completion under the 5-second budget (Req 7.6)."""
        return self.complete(
            messages, timeout=MODERATION_TIMEOUT_SECONDS, model=model
        )

    def score_scam(
        self,
        messages: ChatMessages,
        *,
        model: str = DEFAULT_MODEL,
    ) -> OpenAIResponse:
        """Run a scam-scoring completion under the 3-second budget (Req 8.2)."""
        return self.complete(messages, timeout=SCAM_TIMEOUT_SECONDS, model=model)

    # -- internals ----------------------------------------------------------

    def _post(
        self,
        url: str,
        *,
        payload: dict,
        headers: dict[str, str],
        timeout: float,
    ) -> dict:
        """POST ``payload`` to ``url``, mapping every failure to OpenAIError."""
        try:
            if self._http_client is not None:
                response = self._http_client.post(
                    url, json=payload, headers=headers, timeout=timeout
                )
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise OpenAITimeoutError(
                f"OpenAI request exceeded its {timeout:g}s time budget"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenAIError(f"OpenAI request failed: {exc}") from exc
        except ValueError as exc:  # response.json() on a non-JSON body
            raise OpenAIError("OpenAI returned a malformed (non-JSON) response") from exc

    @staticmethod
    def _extract_content(data: dict) -> str:
        """Pull the assistant message text from a chat-completion payload."""
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenAIError(
                "OpenAI response did not contain a completion message"
            ) from exc
