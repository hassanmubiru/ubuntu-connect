"""Auth and OTP request/response schemas.

Covers registration, OTP verification, OTP resend, and login (design
"Auth and OTP" endpoints). Field constraints enforce a 2-100 character full
name, an E.164 phone, and a six-digit OTP code (Req 1.1, 1.3, 1.5, 2.1).

The data model has no password column; a user is identified for login by
their verified phone number, so ``LoginRequest`` carries the phone as its
single required credential (Req 3.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import FullNameMixin, OtpCodeField, Phone


class RegisterRequest(FullNameMixin):
    """POST /api/auth/register body: a full name and an E.164 phone."""

    phone: Phone


class RegisterResponse(BaseModel):
    """Result of a successful registration."""

    user_id: uuid.UUID = Field(description="Identifier of the created user.")
    otp_sent: bool = Field(
        description="Whether an OTP SMS was requested for the phone."
    )


class VerifyOtpRequest(BaseModel):
    """POST /api/auth/verify-otp body: the phone and the six-digit code."""

    phone: Phone
    code: OtpCodeField


class VerifyOtpResponse(BaseModel):
    """Result of an OTP verification attempt."""

    verified: bool = Field(description="Whether the phone is now verified.")


class ResendOtpRequest(BaseModel):
    """POST /api/auth/resend-otp body: the phone to resend a code to."""

    phone: Phone


class ResendOtpResponse(BaseModel):
    """Result of an OTP resend request."""

    otp_sent: bool = Field(
        description="Whether a replacement OTP SMS was requested."
    )


class LoginRequest(BaseModel):
    """POST /api/auth/login body: the phone identifying the account."""

    phone: Phone


class LoginResponse(BaseModel):
    """A successful login: the JWT and its absolute expiry time."""

    model_config = ConfigDict(from_attributes=True)

    jwt: str = Field(description="Signed JSON Web Token for the session.")
    expires_at: datetime = Field(
        description="UTC time the JWT expires (24 hours after issuance)."
    )
