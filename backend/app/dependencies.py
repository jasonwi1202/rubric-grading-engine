"""Shared FastAPI dependencies.

Re-usable Depends() callables for the application.  Import from this module
rather than duplicating logic across routers.

Currently provides:
- ``get_current_teacher`` — validate JWT Bearer token and return the
  authenticated User.  Use this on every protected endpoint.
- ``get_current_teacher_optional`` — like the above but returns ``None``
  instead of raising when no valid token is present.  Used internally by the
  logout endpoint for audit logging.
- ``get_db_for_teacher`` — combines ``get_current_teacher`` + ``get_db`` and
  calls ``set_tenant_context`` so PostgreSQL RLS policies are activated for
  the authenticated teacher.  Use this instead of bare ``get_db`` in any
  router that queries tenant-scoped tables.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, set_tenant_context
from app.exceptions import UnauthorizedError, ValidationError
from app.services.auth import decode_access_token

if TYPE_CHECKING:
    from app.models.user import User

# HTTPBearer scheme — raises 403 automatically when the header is absent.
# ``auto_error=False`` lets us return a more informative 401 ourselves.
_bearer = HTTPBearer(auto_error=False)


async def get_current_teacher(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate the ``Authorization: Bearer <token>`` header and return the
    authenticated teacher.

    Raises:
        UnauthorizedError: Bearer header is absent, token is malformed/expired,
            wrong type, or references a deleted / unverified account — maps to
            HTTP 401.  Returning 401 for all these cases ensures the frontend
            silent-refresh cycle fires instead of stranding the session.
    """
    if credentials is None:
        raise UnauthorizedError("Authentication required.")

    try:
        payload = decode_access_token(credentials.credentials)
    except ValidationError as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc

    # Reject tokens that are not access tokens (e.g. future refresh-JWT types).
    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type.")

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise UnauthorizedError("Invalid token payload.")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise UnauthorizedError("Invalid token payload.") from exc

    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()

    if db_user is None:
        raise UnauthorizedError("Account not found.")

    if not db_user.email_verified:
        raise UnauthorizedError("Email address is not verified.")

    return db_user


async def get_current_teacher_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID | None:
    """Extract the authenticated teacher's UUID without raising on failure.

    Returns ``None`` if the Authorization header is absent, the scheme is
    not ``Bearer``, or the token is malformed/expired/wrong-type.  Does not
    perform a database lookup — only decodes the JWT claim.  Used by the
    logout endpoint for best-effort audit logging.
    """
    auth_header = request.headers.get("Authorization", "")
    # HTTP auth schemes are case-insensitive (RFC 7235 §2.1).
    if not auth_header.lower().startswith("bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_access_token(token)
    except ValidationError:
        return None

    # Only accept access tokens — reject refresh tokens or unknown types.
    if payload.get("type") != "access":
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None

    try:
        return uuid.UUID(sub)
    except ValueError:
        return None


async def get_db_for_teacher(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield an authenticated, tenant-context-activated ``AsyncSession``.

    Combines authentication and RLS activation in a single dependency:
    1. Validates the JWT and resolves the teacher (via ``get_current_teacher``).
    2. Calls ``set_tenant_context`` so the PostgreSQL RLS policies for the
       authenticated teacher become active for all queries in this session.

    FastAPI caches ``get_db`` within a request, so the ``db`` instance here
    is the same session used by ``get_current_teacher``.  Calling
    ``set_tenant_context`` here therefore activates RLS for all queries
    issued by the route handler (and any service functions it calls).

    Usage::

        @router.get("/classes")
        async def list_classes(
            teacher: User = Depends(get_current_teacher),
            db: AsyncSession = Depends(get_db_for_teacher),
        ) -> ...:
            ...
    """
    await set_tenant_context(db, teacher.id)
    yield db
