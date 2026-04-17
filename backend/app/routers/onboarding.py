"""Onboarding router — wizard status and completion endpoints.

Both endpoints require a valid JWT (``get_current_teacher`` dependency).

GET  /onboarding/status  — returns the teacher's current wizard step and
                           completion flag, plus ``trial_ends_at``.
POST /onboarding/complete — marks ``users.onboarding_complete = True``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.onboarding import OnboardingCompleteResponse, OnboardingStatusResponse
from app.services.onboarding import complete_onboarding, get_onboarding_step

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ---------------------------------------------------------------------------
# GET /onboarding/status
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    summary="Get the authenticated teacher's onboarding status",
)
async def get_status(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the current wizard step and completion flag for the teacher.

    - ``step``: 1 (create class) or 2 (create rubric).
    - ``completed``: True once ``POST /onboarding/complete`` has been called.
    - ``trial_ends_at``: ISO-8601 timestamp or null.

    Requires a valid JWT Bearer token.
    """
    # Use the already-loaded teacher object to avoid an extra DB round-trip.
    step, completed = get_onboarding_step(teacher)
    response_data = OnboardingStatusResponse(
        step=step,
        completed=completed,
        trial_ends_at=teacher.trial_ends_at,
    )
    return JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /onboarding/complete
# ---------------------------------------------------------------------------


@router.post(
    "/complete",
    summary="Mark the teacher's onboarding wizard as complete",
)
async def mark_complete(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Set ``users.onboarding_complete = True`` for the authenticated teacher.

    Idempotent -- calling this multiple times has the same effect.

    Requires a valid JWT Bearer token.
    """
    await complete_onboarding(db, teacher.id)
    response_data = OnboardingCompleteResponse(message="Onboarding marked as complete.")
    return JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )
