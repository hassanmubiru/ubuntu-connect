"""Shared router dependencies: the JWT auth guard and the admin role guard.

Every protected route depends on :func:`get_current_user`, which validates the
bearer JWT on the request and resolves it to a :class:`User`. A missing,
malformed, expired, or tampered token — or a token whose subject no longer
exists — is rejected with an authentication error (Req 3.6). Admin-only routes
additionally depend on :func:`require_admin`, which rejects any non-admin
caller with an authorization error (Req 11.1).

The guards read the JWT secret from :class:`app.config.Config` (sourced from
the environment, Req 15.4) and resolve the user through the injected
:class:`UserRepository`, so no route handler touches a session or the token
format directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Config
from app.models.user import User
from app.repositories.dependencies import UserRepositoryDep
from app.repositories.user_repository import UserRepository
from app.schemas.errors import AuthError, AuthorizationError
from app.services.auth_service import decode_access_token

# ``auto_error=False`` so a missing/blank Authorization header yields ``None``
# and we raise our own envelope-formatted AuthError (401) rather than the
# library default (403). This keeps every rejection path uniform (Req 3.6).
_bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
]


def _jwt_secret() -> str:
    """Return the configured JWT secret (env-sourced, Req 15.4)."""
    return Config.from_env().jwt_secret


def get_current_user(
    credentials: BearerCredentials,
    users: UserRepositoryDep,
) -> User:
    """Resolve the authenticated user from the request's bearer JWT (Req 3.6).

    Raises :class:`AuthError` when the token is absent, invalid, expired, or
    points at a user that no longer exists.
    """
    if credentials is None or not credentials.credentials:
        raise AuthError()

    user_id = decode_access_token(credentials.credentials, _jwt_secret())
    user = users.get_by_id(user_id)
    if user is None:
        raise AuthError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(current_user: CurrentUser) -> User:
    """Require the authenticated user to be an administrator (Req 11.1).

    Rejects a non-admin caller with an authorization error while leaving
    authentication failures to :func:`get_current_user`.
    """
    if not current_user.is_admin:
        raise AuthorizationError()
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]


def build_auth_service_dependency(users: UserRepository):  # pragma: no cover
    """Placeholder kept intentionally unused; see ``app.routers.auth``.

    The auth service is constructed in the auth router where the request-scoped
    repository is available; this module only houses the guard dependencies.
    """
    raise NotImplementedError
