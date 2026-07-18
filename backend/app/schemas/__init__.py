"""Pydantic request/response schemas and the shared error envelope.

Re-exports the request/response models for every endpoint plus the error
envelope, error codes, typed application exceptions, and the handler
registrar. Importing from ``app.schemas`` gives routers and services a single
place to pull request/response contracts and error types from.
"""

from __future__ import annotations

from app.schemas.admin import (
    FlaggedUserResponse,
    ReportDecision,
    ReportResolutionRequest,
    ReportResolutionResponse,
    ScamAlertResponse,
)
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    ResendOtpRequest,
    ResendOtpResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from app.schemas.common import (
    ACCEPTED_PHOTO_CONTENT_TYPES,
    MAX_PHOTO_BYTES,
    ErrorCode,
    ErrorDetail,
    ErrorEnvelope,
    FieldError,
)
from app.schemas.errors import (
    AppError,
    AuthError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    PolicyViolationError,
    RateLimitedError,
    TimeoutAppError,
    ValidationAppError,
    register_exception_handlers,
)
from app.schemas.message import MessageResponse, MessageSendRequest
from app.schemas.profile import (
    BioUpdateRequest,
    InterestsUpdateRequest,
    PhotoUploadResponse,
    ProfileResponse,
)
from app.schemas.report import ReportRequest, ReportResponse
from app.schemas.trust import (
    TrustExplanationResponse,
    TrustReasonResponse,
    TrustScoreResponse,
)

__all__ = [
    # error envelope
    "ErrorCode",
    "ErrorDetail",
    "ErrorEnvelope",
    "FieldError",
    # exceptions + handler registration
    "AppError",
    "AuthError",
    "AuthorizationError",
    "ConflictError",
    "NotFoundError",
    "PolicyViolationError",
    "RateLimitedError",
    "TimeoutAppError",
    "ValidationAppError",
    "register_exception_handlers",
    # auth
    "RegisterRequest",
    "RegisterResponse",
    "VerifyOtpRequest",
    "VerifyOtpResponse",
    "ResendOtpRequest",
    "ResendOtpResponse",
    "LoginRequest",
    "LoginResponse",
    # profile
    "BioUpdateRequest",
    "InterestsUpdateRequest",
    "PhotoUploadResponse",
    "ProfileResponse",
    "ACCEPTED_PHOTO_CONTENT_TYPES",
    "MAX_PHOTO_BYTES",
    # message
    "MessageSendRequest",
    "MessageResponse",
    # trust
    "TrustScoreResponse",
    "TrustReasonResponse",
    "TrustExplanationResponse",
    # report
    "ReportRequest",
    "ReportResponse",
    # admin
    "ReportResolutionRequest",
    "ReportResolutionResponse",
    "ReportDecision",
    "FlaggedUserResponse",
    "ScamAlertResponse",
]
