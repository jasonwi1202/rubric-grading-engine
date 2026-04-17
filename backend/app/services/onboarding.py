"""Onboarding service.

Business logic for the teacher onboarding wizard:

* ``get_onboarding_status`` — determine the teacher's current wizard step and
  whether onboarding has been marked complete.
* ``complete_onboarding``   — mark ``users.onboarding_complete = True``.

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger(__name__)


async def get_onboarding_status(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> tuple[int, bool]:
    """Return the teacher's current onboarding step and completion flag.

    The step is determined as follows:
    - Step 1 (create class): returned when ``onboarding_complete`` is False
      and no classes exist (M3 table not yet available — defaults to step 1).
    - Step 2 (create rubric): returned when classes exist but no rubrics.
    - ``completed = True``: returned when ``onboarding_complete = True``.

    Until the M3 classes/rubrics tables are implemented, ``step`` defaults
    to 1 for all teachers with ``onboarding_complete = False``.

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID.

    Returns:
        Tuple of (step: int, completed: bool).

    Raises:
        NotFoundError: Teacher record not found.
    """
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == teacher_id))
    teacher = result.scalar_one_or_none()

    if teacher is None:
        raise NotFoundError("Teacher account not found.")

    if teacher.onboarding_complete:
        return 2, True

    # Default step 1 until M3 class/rubric tables allow more granular checks.
    return 1, False


async def complete_onboarding(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> User:
    """Mark the teacher's onboarding as complete.

    Sets ``users.onboarding_complete = True`` and persists the change.

    Args:
        db: Async database session.
        teacher_id: The authenticated teacher's UUID.

    Returns:
        The updated ``User`` ORM instance.

    Raises:
        NotFoundError: Teacher record not found.
    """
    from app.models.user import User

    result = await db.execute(select(User).where(User.id == teacher_id))
    teacher = result.scalar_one_or_none()

    if teacher is None:
        raise NotFoundError("Teacher account not found.")

    teacher.onboarding_complete = True
    await db.commit()
    await db.refresh(teacher)

    logger.info("Onboarding marked complete", extra={"user_id": str(teacher_id)})
    return teacher
