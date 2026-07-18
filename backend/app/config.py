"""Environment-variable configuration with fail-fast validation.

Every external service credential and endpoint used by Ubuntu Connect is
read from the process environment. No credential or endpoint literal ever
appears in source (Req 15.4). At application construction the backend calls
:func:`Config.validate`, which collects *every* missing required variable
and raises :class:`MissingConfigError` before any port is bound, so the
process halts without serving requests and the emitted error names each
missing variable (Req 15.5).

Usage (wired into the app factory in ``app.main``)::

    config = Config.from_env()
    config.validate()   # raises MissingConfigError naming all missing vars
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, fields

# Names of the required environment variables. Keeping these as a single
# ordered tuple lets ``validate`` report missing variables deterministically
# and keeps the source free of any credential/endpoint literal values.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "DATABASE_URL",
    "JWT_SECRET",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "AT_API_KEY",
    "AT_USERNAME",
    "AT_SMS_SENDER_ID",
    "AT_USSD_SERVICE_CODE",
    "PHOTO_STORAGE_BUCKET",
)


class MissingConfigError(RuntimeError):
    """Raised at startup when one or more required env vars are absent.

    The exception message names every missing variable so operators can fix
    the whole set of gaps at once rather than discovering them one at a time.
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        joined = ", ".join(self.missing)
        super().__init__(
            "Missing required environment variable(s): "
            f"{joined}. Set them before starting the Ubuntu Connect backend."
        )


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of configuration read from the environment.

    Field values default to empty strings so a partially configured
    environment still produces a fully constructed object; the absence of a
    value is surfaced by :meth:`validate` rather than by construction failing.
    """

    database_url: str = ""
    jwt_secret: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    at_api_key: str = ""
    at_username: str = ""
    at_sms_sender_id: str = ""
    at_ussd_service_code: str = ""
    photo_storage_bucket: str = ""

    # Maps each dataclass field to the environment variable it is read from.
    _ENV_BY_FIELD: Mapping[str, str] = field(
        default_factory=lambda: {
            "database_url": "DATABASE_URL",
            "jwt_secret": "JWT_SECRET",
            "openai_api_key": "OPENAI_API_KEY",
            "openai_base_url": "OPENAI_BASE_URL",
            "at_api_key": "AT_API_KEY",
            "at_username": "AT_USERNAME",
            "at_sms_sender_id": "AT_SMS_SENDER_ID",
            "at_ussd_service_code": "AT_USSD_SERVICE_CODE",
            "photo_storage_bucket": "PHOTO_STORAGE_BUCKET",
        },
        repr=False,
        compare=False,
    )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        """Build a :class:`Config` from ``environ`` (defaults to ``os.environ``).

        A missing variable is stored as an empty string; validation is a
        separate, explicit step performed by :meth:`validate`.
        """
        env = os.environ if environ is None else environ
        return cls(
            database_url=env.get("DATABASE_URL", ""),
            jwt_secret=env.get("JWT_SECRET", ""),
            openai_api_key=env.get("OPENAI_API_KEY", ""),
            openai_base_url=env.get("OPENAI_BASE_URL", ""),
            at_api_key=env.get("AT_API_KEY", ""),
            at_username=env.get("AT_USERNAME", ""),
            at_sms_sender_id=env.get("AT_SMS_SENDER_ID", ""),
            at_ussd_service_code=env.get("AT_USSD_SERVICE_CODE", ""),
            photo_storage_bucket=env.get("PHOTO_STORAGE_BUCKET", ""),
        )

    def missing_vars(self) -> list[str]:
        """Return the names of required env vars that are absent or blank.

        The order matches :data:`REQUIRED_ENV_VARS` so reporting is stable.
        A value consisting only of whitespace counts as missing.
        """
        values = {
            self._ENV_BY_FIELD[f.name]: getattr(self, f.name)
            for f in fields(self)
            if f.name in self._ENV_BY_FIELD
        }
        return [name for name in REQUIRED_ENV_VARS if not values.get(name, "").strip()]

    def validate(self) -> "Config":
        """Fail fast when required configuration is missing.

        Collects *every* missing required variable and raises
        :class:`MissingConfigError` naming each one. Returns ``self`` when all
        required variables are present so callers can chain construction and
        validation. This runs during app construction, before any port is
        bound (Req 15.5).
        """
        missing = self.missing_vars()
        if missing:
            raise MissingConfigError(missing)
        return self
