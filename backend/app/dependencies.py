"""Shared FastAPI dependencies.

Re-usable Depends() callables for the application.  Import from this module
rather than duplicating logic across routers.

Currently provides:
- ``get_current_teacher`` — validate JWT Bearer token and return the
  authenticated User.  Use this on every protected endpoint.
- ``get_current_teacher_optional`` — like the above but returns ``None``
  instead of raising when no valid token is present.  Used internally by the
  logout endpoint for audit logging.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.exceptions import ForbiddenError, ValidationError
from app.services.auth import decode_access_token

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)

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
        ForbiddenError: Bearer header is absent (401 via exception mapping in
            main.py — we map 403 to FORBIDDEN; callers that need 401 should
            use the StarletteHTTPException handler).
        ValidationError: Token is malformed, expired, or references a deleted
            / unverified account.
    """
    if credentials is None:
        raise ForbiddenError("Authentication required.")

    payload = decode_access_token(credentials.credentials)

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise ValidationError("Invalid token payload.", field="token")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise ValidationError("Invalid token payload.", field="token") from exc

    from app.models.user import User

    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()

    if db_user is None:
        raise ValidationError("Account not found.", field="token")

    if not db_user.email_verified:
        raise ValidationError("Email address is not verified.", field="token")

    return db_user


async def get_current_teacher_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID | None:
    """Extract the authenticated teacher's UUID without raising on failure.

    Returns ``None`` if the Authorization header is absent, malformed, or
    references an unknown account.  Used by the logout endpoint for
    best-effort audit logging.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer ") :]
    try:
        payload = decode_access_token(token)
    except (ValidationError, Exception):
        return None

    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None

    try:
        return uuid.UUID(sub)
    except ValueError:
        return None
