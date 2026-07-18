"""Shared schema building blocks: field constraints and the error envelope.

This module centralizes the validation constraints drawn directly from the
requirements (full name 2-100, E.164 phone, bio <=500, interests <=20 items
each <=50, message content 1-2000, report reason 1-1000) and defines the
platform-wide error envelope ``{error:{code,message,fields[]}}`` returned by
every failure path (Req 16.1, 16.2).

Keeping the constraints here as reusable ``Annotated`` types means the same
rules are applied identically across auth, profile, messaging, reporting, and
admin schemas, and the OpenAPI documentation (Req 15.6) reflects them.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# --- Constraint constants (sourced from the requirements) -------------------

FULL_NAME_MIN = 2
FULL_NAME_MAX = 100
BIO_MAX = 500
INTERESTS_MAX_ITEMS = 20
INTEREST_ITEM_MAX = 50
MESSAGE_CONTENT_MIN = 1
MESSAGE_CONTENT_MAX = 2000
REPORT_REASON_MIN = 1
REPORT_REASON_MAX = 1000
OTP_CODE_LENGTH = 6

# E.164: a leading '+', a non-zero leading digit, then up to 14 more digits.
E164_PATTERN = r"^\+[1-9]\d{1,14}$"
# A one-time password is exactly six decimal digits (Req 2.1).
OTP_CODE_PATTERN = r"^\d{6}$"

# Accepted profile photo content types and maximum size (Req 4.5-4.7).
ACCEPTED_PHOTO_CONTENT_TYPES: tuple[str, ...] = ("image/jpeg", "image/png")
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 megabytes


# --- Reusable constrained field types ---------------------------------------

Phone = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=E164_PATTERN),
    Field(description="Phone number in E.164 format, e.g. +2348031234567."),
]

OtpCodeField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=OTP_CODE_PATTERN),
    Field(description="Six-digit one-time password."),
]

Bio = Annotated[
    str,
    StringConstraints(max_length=BIO_MAX),
    Field(description=f"Profile bio, at most {BIO_MAX} characters."),
]

Interest = Annotated[str, StringConstraints(max_length=INTEREST_ITEM_MAX)]

Interests = Annotated[
    list[Interest],
    Field(
        max_length=INTERESTS_MAX_ITEMS,
        description=(
            f"Up to {INTERESTS_MAX_ITEMS} interests, each at most "
            f"{INTEREST_ITEM_MAX} characters."
        ),
    ),
]

MessageContent = Annotated[
    str,
    StringConstraints(min_length=MESSAGE_CONTENT_MIN, max_length=MESSAGE_CONTENT_MAX),
    Field(description="Message body, 1 to 2000 characters."),
]

ReportReason = Annotated[
    str,
    StringConstraints(min_length=REPORT_REASON_MIN, max_length=REPORT_REASON_MAX),
    Field(description="Report reason, 1 to 1000 characters."),
]


class FullNameMixin(BaseModel):
    """Mixin providing a validated ``full_name`` field.

    ``full_name`` must be 2-100 characters after trimming surrounding
    whitespace; an empty or whitespace-only value is rejected (Req 1.4, 1.5).
    The trimmed value is what gets stored.
    """

    full_name: str = Field(
        min_length=FULL_NAME_MIN,
        max_length=FULL_NAME_MAX,
        description="Full name, 2 to 100 characters.",
    )

    @field_validator("full_name")
    @classmethod
    def _full_name_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if len(trimmed) < FULL_NAME_MIN:
            raise ValueError(
                f"full_name must be at least {FULL_NAME_MIN} non-whitespace characters"
            )
        if len(trimmed) > FULL_NAME_MAX:
            raise ValueError(
                f"full_name must be at most {FULL_NAME_MAX} characters"
            )
        return trimmed


# --- Error envelope ----------------------------------------------------------


class ErrorCode(str, Enum):
    """Stable, client-facing error codes carried in the error envelope.

    Codes are deliberately coarse-grained and generic: they classify the
    failure without leaking any internal implementation detail (Req 16.2).
    """

    VALIDATION = "validation"
    AUTH = "auth"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    POLICY_VIOLATION = "policy_violation"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"


class FieldError(BaseModel):
    """One field-level validation failure: which field and why it failed."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(description="Name of the field that failed validation.")
    reason: str = Field(description="Human-readable reason the field is invalid.")


class ErrorDetail(BaseModel):
    """The body of the error envelope: a code, a message, and field details."""

    code: ErrorCode = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Generic, safe-to-display error message.")
    fields: list[FieldError] = Field(
        default_factory=list,
        description="Per-field validation failures, when applicable.",
    )


class ErrorEnvelope(BaseModel):
    """The uniform error response shape returned by every failure path."""

    error: ErrorDetail
