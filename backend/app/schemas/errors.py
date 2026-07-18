"""Application exceptions and the global exception handlers.

The backend surfaces every failure through a single error envelope
(``{error:{code,message,fields[]}}``) so clients get consistent, safe
feedback (Req 16.1, 16.2). This module provides:

* :class:`AppError` and a small hierarchy of typed subclasses that services
  and routers raise to signal a specific, expected failure category
  (auth, authorization, not-found, conflict, policy violation, rate limited,
  timeout). Each carries its own client-facing message and HTTP status.
* :func:`register_exception_handlers`, wired into the app factory, which
  converts three sources of failure into the envelope:
    - FastAPI/Pydantic ``RequestValidationError`` -> a ``validation`` error
      naming every invalid field and the reason it failed (Req 16.1);
    - any raised :class:`AppError` -> its declared code/message/status;
    - any *other* uncaught exception -> a generic ``internal_error`` with no
      internal details leaked (Req 16.2).

Because all write-path requests run inside the transactional session
dependency (``app.db.get_session``), an exception rolls the transaction back
before these handlers format the response, so no partial write survives a
failure (Req 16.2).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorCode, ErrorDetail, ErrorEnvelope, FieldError

# Generic, non-revealing messages. These never include internal details such
# as stack traces, exception types, SQL, or configuration values (Req 16.2).
_GENERIC_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION: "The request contains invalid input.",
    ErrorCode.AUTH: "Authentication is required or the credentials are invalid.",
    ErrorCode.AUTHORIZATION: "You are not authorized to perform this action.",
    ErrorCode.NOT_FOUND: "The requested resource was not found.",
    ErrorCode.CONFLICT: "The request conflicts with the current state.",
    ErrorCode.POLICY_VIOLATION: "The request violates platform policy.",
    ErrorCode.RATE_LIMITED: "Too many requests. Please try again later.",
    ErrorCode.SEND_FAILURE: "The message could not be sent. Please try again.",
    ErrorCode.TIMEOUT: "The request timed out. Please try again.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred. Please try again.",
}

# Default HTTP status for each error code.
_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION: 422,
    ErrorCode.AUTH: 401,
    ErrorCode.AUTHORIZATION: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.POLICY_VIOLATION: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.INTERNAL_ERROR: 500,
}

# Map raw HTTP status codes (e.g. from Starlette HTTPException raised by the
# framework for unknown routes or auth guards) back to an error code so those
# responses share the envelope too.
_CODE_BY_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION,
    401: ErrorCode.AUTH,
    403: ErrorCode.AUTHORIZATION,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION,
    429: ErrorCode.RATE_LIMITED,
    504: ErrorCode.TIMEOUT,
}


class AppError(Exception):
    """Base class for expected, categorized application failures.

    Subclasses fix a :class:`ErrorCode` and an HTTP status; callers may pass a
    custom (still generic) ``message`` and, for validation-style failures, a
    list of :class:`FieldError` entries. Raising an ``AppError`` from a service
    or router yields the error envelope with the declared code and status.
    """

    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        fields: list[FieldError] | None = None,
    ) -> None:
        self.message = message or _GENERIC_MESSAGES[self.code]
        self.fields = fields or []
        super().__init__(self.message)

    def to_envelope(self) -> ErrorEnvelope:
        """Render this error as the standard error envelope."""
        return ErrorEnvelope(
            error=ErrorDetail(
                code=self.code, message=self.message, fields=self.fields
            )
        )


class ValidationAppError(AppError):
    """A request failed validation (Req 16.1)."""

    code = ErrorCode.VALIDATION
    status_code = 422


class AuthError(AppError):
    """Authentication is missing or invalid (Req 3.3, 3.6)."""

    code = ErrorCode.AUTH
    status_code = 401


class AuthorizationError(AppError):
    """The caller lacks permission for the action (Req 11.1)."""

    code = ErrorCode.AUTHORIZATION
    status_code = 403


class NotFoundError(AppError):
    """A referenced resource does not exist (Req 6.4, 12.4)."""

    code = ErrorCode.NOT_FOUND
    status_code = 404


class ConflictError(AppError):
    """The request conflicts with existing state (Req 1.2, 12.6)."""

    code = ErrorCode.CONFLICT
    status_code = 409


class PolicyViolationError(AppError):
    """Content violates platform policy (Req 7.2)."""

    code = ErrorCode.POLICY_VIOLATION
    status_code = 422


class RateLimitedError(AppError):
    """A rate/throttle limit was reached (Req 2.8)."""

    code = ErrorCode.RATE_LIMITED
    status_code = 429


class TimeoutAppError(AppError):
    """An operation exceeded its time budget (Req 16.6)."""

    code = ErrorCode.TIMEOUT
    status_code = 504


def _field_name_from_loc(loc: tuple[object, ...]) -> str:
    """Turn a Pydantic error location tuple into a readable field name.

    The first element is usually the request part (``body``/``query``/
    ``path``); it is dropped so the name reflects the field the client sent.
    Nested locations are joined with dots and list indices are kept.
    """
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path", "header", "cookie"):
        parts = parts[1:]
    if not parts:
        return "body"
    return ".".join(str(p) for p in parts)


def _envelope_response(status_code: int, detail: ErrorDetail) -> JSONResponse:
    """Serialize an :class:`ErrorDetail` into a JSON envelope response."""
    return JSONResponse(
        status_code=status_code,
        content=ErrorEnvelope(error=detail).model_dump(mode="json"),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the global handlers that render the error envelope.

    Registered on the app factory so every route shares identical error
    semantics regardless of which layer raised the failure.
    """

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Build one FieldError per invalid field, naming the field and the
        # reason it failed, so the client can correct each one (Req 16.1).
        field_errors = [
            FieldError(
                field=_field_name_from_loc(tuple(err.get("loc", ()))),
                reason=str(err.get("msg", "Invalid value")),
            )
            for err in exc.errors()
        ]
        detail = ErrorDetail(
            code=ErrorCode.VALIDATION,
            message=_GENERIC_MESSAGES[ErrorCode.VALIDATION],
            fields=field_errors,
        )
        return _envelope_response(_STATUS_BY_CODE[ErrorCode.VALIDATION], detail)

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _envelope_response(exc.status_code, exc.to_envelope().error)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        # Ignore the framework-provided detail string and use a generic message
        # so no internal specifics leak into the response (Req 16.2).
        detail = ErrorDetail(code=code, message=_GENERIC_MESSAGES[code])
        return _envelope_response(exc.status_code, detail)

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Any exception that is not an AppError is unexpected: respond with a
        # generic internal_error carrying no internal detail (Req 16.2). The
        # transactional session dependency has already rolled back, so no
        # partial write survives.
        detail = ErrorDetail(
            code=ErrorCode.INTERNAL_ERROR,
            message=_GENERIC_MESSAGES[ErrorCode.INTERNAL_ERROR],
        )
        return _envelope_response(_STATUS_BY_CODE[ErrorCode.INTERNAL_ERROR], detail)
