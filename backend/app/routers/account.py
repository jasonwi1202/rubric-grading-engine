"""Account router — account-level information endpoints.

GET /account/trial — returns the authenticated teacher's trial status.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or processed here.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.account import TrialStatusResponse

router = APIRouter(prefix="/account", tags=["account"])


# ---------------------------------------------------------------------------
# GET /account/trial
# ---------------------------------------------------------------------------


@router.get(
    "/trial",
    summary="Get the authenticated teacher's trial status",
)
async def get_trial_status(
    teacher: User = Depends(get_current_teacher),
) -> JSONResponse:
    """Return the trial expiry timestamp, active flag, and days remaining.

    - ``trial_ends_at``: ISO-8601 timestamp or null.
    - ``is_active``: True while the trial has not yet expired.
    - ``days_remaining``: Full calendar days remaining; null if no expiry set.

    Requires a valid JWT Bearer token.
    """
    trial_ends_at = teacher.trial_ends_at
    now = datetime.now(UTC)

    if trial_ends_at is None:
        is_active = True
        days_remaining = None
    else:
        delta_seconds = (trial_ends_at - now).total_seconds()
        days_remaining = math.floor(delta_seconds / 86400)
        is_active = delta_seconds > 0

    response_data = TrialStatusResponse(
        trial_ends_at=trial_ends_at,
        is_active=is_active,
        days_remaining=days_remaining,
    )
    return JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )
