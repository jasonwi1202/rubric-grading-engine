"""Assignment service.

Business logic for assignment CRUD operations:

- ``list_assignments``  — list assignments for a class (tenant-scoped).
- ``create_assignment`` — create an assignment, snapshot the rubric at creation time.
- ``get_assignment``    — fetch a single assignment (tenant-scoped).
- ``update_assignment`` — update title, prompt, due_date, and/or advance status.

State machine (forward-only):
    draft → open → grading → review → complete → returned

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, InvalidStateTransitionError, NotFoundError
from app.models.assignment import Assignment, AssignmentStatus
from app.models.class_ import Class
from app.models.rubric import Rubric, RubricCriterion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

# Maps each status to the single valid next status (forward-only).
_VALID_TRANSITIONS: dict[AssignmentStatus, AssignmentStatus] = {
    AssignmentStatus.draft: AssignmentStatus.open,
    AssignmentStatus.open: AssignmentStatus.grading,
    AssignmentStatus.grading: AssignmentStatus.review,
    AssignmentStatus.review: AssignmentStatus.complete,
    AssignmentStatus.complete: AssignmentStatus.returned,
}


def _validate_transition(current: AssignmentStatus, target: AssignmentStatus) -> None:
    """Raise InvalidStateTransitionError if the transition is not allowed.

    Only forward transitions defined in ``_VALID_TRANSITIONS`` are permitted.
    Attempting to set the same status or transition backward raises the error.
    """
    allowed_next = _VALID_TRANSITIONS.get(current)
    if target == current:
        # No-op transitions are also disallowed — the teacher must provide a
        # meaningful status update.
        raise InvalidStateTransitionError(
            f"Assignment is already in '{current}' status.",
            field="status",
        )
    if allowed_next is None or target != allowed_next:
        raise InvalidStateTransitionError(
            f"Cannot transition from '{current}' to '{target}'. "
            f"Only '{allowed_next}' is valid from '{current}'."
            if allowed_next
            else f"Assignment is in terminal status '{current}' and cannot be advanced.",
            field="status",
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Class:
    """Fetch a class row, enforcing tenant ownership.

    Raises NotFoundError if the class does not exist.
    Raises ForbiddenError if it belongs to a different teacher.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")
    # Return the full Class row.
    full = await db.execute(
        select(Class).where(Class.id == class_id, Class.teacher_id == teacher_id)
    )
    cls = full.scalar_one_or_none()
    if cls is None:
        raise NotFoundError("Class not found.")
    return cls


async def _get_assignment_owned_by(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Assignment:
    """Fetch an assignment, enforcing tenant ownership via the class join.

    Raises NotFoundError if the assignment does not exist.
    Raises ForbiddenError if it belongs to a different teacher.
    """
    # Two-step ownership check: first verify existence and ownership using a
    # lightweight join (id columns only), then load the full row.
    ownership_result = await db.execute(
        select(Assignment.id, Class.teacher_id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Assignment.id == assignment_id)
    )
    ownership_row = ownership_result.one_or_none()
    if ownership_row is None:
        raise NotFoundError("Assignment not found.")
    if ownership_row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this assignment.")

    result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == assignment_id,
            Class.teacher_id == teacher_id,
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    return assignment


def _build_snapshot(rubric: Rubric, criteria: list[RubricCriterion]) -> dict:
    """Build the immutable JSONB rubric snapshot for an assignment.

    Called once at assignment-creation time.  Grading always reads this
    snapshot; editing the live rubric later has no effect.
    """
    from app.services.rubric import build_rubric_snapshot

    return build_rubric_snapshot(rubric, criteria)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_assignments(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
) -> list[Assignment]:
    """List all assignments for a class (tenant-scoped).

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    await _get_class_owned_by(db, class_id, teacher_id)

    result = await db.execute(
        select(Assignment)
        .where(Assignment.class_id == class_id)
        .order_by(Assignment.created_at.desc())
    )
    return list(result.scalars().all())


async def create_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    rubric_id: uuid.UUID,
    title: str,
    prompt: str | None,
    due_date: date | None,
) -> Assignment:
    """Create an assignment, writing an immutable rubric snapshot at creation time.

    The rubric snapshot is taken from the live rubric at the moment of creation.
    Any subsequent edits to the rubric will NOT affect this assignment or its grades.

    Raises:
        NotFoundError: If the class or rubric does not exist.
        ForbiddenError: If the class or rubric belongs to a different teacher.
    """
    await _get_class_owned_by(db, class_id, teacher_id)

    # Verify the rubric exists and belongs to this teacher.
    rubric_ownership = await db.execute(
        select(Rubric.id, Rubric.teacher_id).where(
            Rubric.id == rubric_id,
            Rubric.deleted_at.is_(None),
        )
    )
    rubric_row = rubric_ownership.one_or_none()
    if rubric_row is None:
        raise NotFoundError("Rubric not found.")
    if rubric_row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this rubric.")

    # Load the full rubric and its criteria to build the snapshot.
    rubric_result = await db.execute(select(Rubric).where(Rubric.id == rubric_id))
    rubric = rubric_result.scalar_one()

    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_id == rubric_id)
        .order_by(RubricCriterion.display_order)
    )
    criteria = list(criteria_result.scalars().all())

    snapshot = _build_snapshot(rubric, criteria)

    assignment = Assignment(
        class_id=class_id,
        rubric_id=rubric_id,
        rubric_snapshot=snapshot,
        title=title,
        prompt=prompt,
        due_date=due_date,
        status=AssignmentStatus.draft,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    logger.info(
        "Assignment created",
        extra={
            "assignment_id": str(assignment.id),
            "class_id": str(class_id),
            "teacher_id": str(teacher_id),
        },
    )
    return assignment


async def get_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> Assignment:
    """Fetch a single assignment (tenant-scoped).

    Raises:
        NotFoundError: If the assignment does not exist.
        ForbiddenError: If the assignment belongs to a different teacher.
    """
    return await _get_assignment_owned_by(db, assignment_id, teacher_id)


async def update_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
    title: str | None,
    prompt: str | None,
    update_prompt: bool,
    due_date: date | None,
    update_due_date: bool,
    status: AssignmentStatus | None,
) -> Assignment:
    """Partially update an assignment.

    - ``title``: if not None, update the title.
    - ``prompt`` / ``update_prompt``: if ``update_prompt`` is True, set prompt
      (may be None to clear it).
    - ``due_date`` / ``update_due_date``: if ``update_due_date`` is True, set
      due_date (may be None to clear it).
    - ``status``: if not None, attempt a state-machine transition.

    Raises:
        NotFoundError: If the assignment does not exist.
        ForbiddenError: If the assignment belongs to a different teacher.
        InvalidStateTransitionError: If the status transition is not allowed.
    """
    assignment = await _get_assignment_owned_by(db, assignment_id, teacher_id)

    if status is not None:
        _validate_transition(assignment.status, status)
        assignment.status = status

    if title is not None:
        assignment.title = title

    if update_prompt:
        assignment.prompt = prompt

    if update_due_date:
        assignment.due_date = due_date

    await db.commit()
    await db.refresh(assignment)

    logger.info(
        "Assignment updated",
        extra={
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
        },
    )
    return assignment
