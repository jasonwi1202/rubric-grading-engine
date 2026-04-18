"""Rubric service.

Business logic for rubric CRUD operations:

- ``list_rubrics``     — list all non-deleted rubrics for a teacher.
- ``create_rubric``    — create a rubric with criteria, validating weight sum.
- ``get_rubric``       — fetch a single rubric with criteria (tenant-scoped).
- ``update_rubric``    — update rubric metadata and/or replace criteria.
- ``delete_rubric``    — soft-delete a rubric (blocked if in use by an open assignment).
- ``duplicate_rubric`` — copy a rubric as a new draft owned by the same teacher.
- ``build_rubric_snapshot`` — produce the JSONB snapshot for assignment creation.

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError, RubricInUseError, RubricWeightInvalidError
from app.models.assignment import Assignment, AssignmentStatus
from app.models.class_ import Class
from app.models.rubric import Rubric, RubricCriterion
from app.schemas.rubric import RubricCriterionRequest

logger = logging.getLogger(__name__)

_WEIGHT_SUM_EXACT = Decimal("100.00")

# Assignment statuses that block rubric deletion.
_BLOCKING_STATUSES = frozenset(
    {
        AssignmentStatus.open,
        AssignmentStatus.grading,
        AssignmentStatus.review,
    }
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_weight_sum(criteria: list[RubricCriterionRequest]) -> None:
    """Raise RubricWeightInvalidError if criterion weights do not sum to exactly 100.

    Each weight is quantized to two decimal places (matching the Numeric(5,2)
    column) before summing so that floating-point artefacts cannot cause a
    valid rubric to be rejected.
    """
    two_dp = Decimal("0.01")
    total = sum(c.weight.quantize(two_dp) for c in criteria)
    if total != _WEIGHT_SUM_EXACT:
        raise RubricWeightInvalidError(
            f"Criterion weights must sum to 100. Got {total}.",
            field="criteria",
        )


async def _get_rubric_owned_by(
    db: AsyncSession,
    rubric_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> Rubric:
    """Fetch a non-deleted rubric, raising NotFoundError or ForbiddenError.

    Uses a two-step query: first verify existence and ownership (selecting only
    the columns needed to decide 404 vs 403) so that cross-tenant requests do
    not load full rubric metadata.  Only when the caller is the owner is the
    full row fetched.
    """
    ownership_result = await db.execute(
        select(Rubric.id, Rubric.teacher_id).where(
            Rubric.id == rubric_id,
            Rubric.deleted_at.is_(None),
        )
    )
    ownership_row = ownership_result.one_or_none()
    if ownership_row is None:
        raise NotFoundError("Rubric not found.")
    if ownership_row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this rubric.")

    rubric_result = await db.execute(
        select(Rubric).where(Rubric.id == rubric_id, Rubric.deleted_at.is_(None))
    )
    rubric = rubric_result.scalar_one_or_none()
    if rubric is None:
        # Extremely unlikely TOCTOU window — treat as not found.
        raise NotFoundError("Rubric not found.")
    return rubric


async def _get_criteria_for_rubric(
    db: AsyncSession,
    rubric_id: uuid.UUID,
) -> list[RubricCriterion]:
    """Return all criteria for a rubric, ordered by display_order."""
    result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_id == rubric_id)
        .order_by(RubricCriterion.display_order)
    )
    return list(result.scalars().all())


def _build_criteria_orm(
    rubric_id: uuid.UUID,
    criteria_requests: list[RubricCriterionRequest],
) -> list[RubricCriterion]:
    """Create RubricCriterion ORM instances from request objects."""
    return [
        RubricCriterion(
            rubric_id=rubric_id,
            name=c.name,
            description=c.description,
            weight=c.weight,
            min_score=c.min_score,
            max_score=c.max_score,
            display_order=i,
            anchor_descriptions=c.anchor_descriptions,
        )
        for i, c in enumerate(criteria_requests)
    ]


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_rubrics(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[tuple[Rubric, list[RubricCriterion]]]:
    """List all non-deleted rubrics for a teacher, with their criteria.

    Uses two queries (rubrics, then all criteria in one batch) to avoid N+1.
    Rubrics are returned newest-first.
    """
    rubric_result = await db.execute(
        select(Rubric)
        .where(Rubric.teacher_id == teacher_id, Rubric.deleted_at.is_(None))
        .order_by(Rubric.created_at.desc())
    )
    rubrics = list(rubric_result.scalars().all())

    if not rubrics:
        return []

    rubric_ids = [r.id for r in rubrics]
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_id.in_(rubric_ids))
        .order_by(RubricCriterion.rubric_id, RubricCriterion.display_order)
    )
    all_criteria = list(criteria_result.scalars().all())

    # Group criteria by rubric_id.
    criteria_by_rubric: dict[uuid.UUID, list[RubricCriterion]] = {}
    for c in all_criteria:
        criteria_by_rubric.setdefault(c.rubric_id, []).append(c)

    return [(r, criteria_by_rubric.get(r.id, [])) for r in rubrics]


async def create_rubric(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    name: str,
    description: str | None,
    criteria_requests: list[RubricCriterionRequest],
) -> tuple[Rubric, list[RubricCriterion]]:
    """Create a rubric with its criteria after validating the weight sum.

    Raises:
        RubricWeightInvalidError: If criterion weights do not sum to 100.
    """
    _validate_weight_sum(criteria_requests)

    rubric = Rubric(
        teacher_id=teacher_id,
        name=name,
        description=description,
    )
    db.add(rubric)
    await db.flush()  # populate rubric.id

    criteria = _build_criteria_orm(rubric.id, criteria_requests)
    for criterion in criteria:
        db.add(criterion)

    await db.commit()
    await db.refresh(rubric)

    logger.info(
        "Rubric created",
        extra={"rubric_id": str(rubric.id), "teacher_id": str(teacher_id)},
    )
    return rubric, criteria


async def get_rubric(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    rubric_id: uuid.UUID,
) -> tuple[Rubric, list[RubricCriterion]]:
    """Fetch a rubric with its criteria (tenant-scoped).

    Raises:
        NotFoundError: If the rubric does not exist or is soft-deleted.
        ForbiddenError: If the rubric belongs to a different teacher.
    """
    rubric = await _get_rubric_owned_by(db, rubric_id, teacher_id)
    criteria = await _get_criteria_for_rubric(db, rubric.id)
    return rubric, criteria


async def update_rubric(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    rubric_id: uuid.UUID,
    name: str | None,
    description: str | None,
    update_description: bool,
    criteria_requests: list[RubricCriterionRequest] | None,
) -> tuple[Rubric, list[RubricCriterion]]:
    """Update a rubric's metadata and/or replace its criteria.

    - ``name``: if not None, update the rubric name.
    - ``description`` / ``update_description``: if ``update_description`` is
      True, set ``description`` (which may be None to clear it).
    - ``criteria_requests``: if not None, replace all existing criteria.
      The new set must pass weight-sum validation.

    Raises:
        NotFoundError: If the rubric does not exist or is soft-deleted.
        ForbiddenError: If the rubric belongs to a different teacher.
        RubricWeightInvalidError: If new criteria weights do not sum to 100.
    """
    rubric = await _get_rubric_owned_by(db, rubric_id, teacher_id)

    if criteria_requests is not None:
        _validate_weight_sum(criteria_requests)

    if name is not None:
        rubric.name = name

    if update_description:
        rubric.description = description

    if criteria_requests is not None:
        # Delete all existing criteria and replace with the new set.
        existing = await _get_criteria_for_rubric(db, rubric.id)
        for c in existing:
            await db.delete(c)
        await db.flush()

        new_criteria = _build_criteria_orm(rubric.id, criteria_requests)
        for criterion in new_criteria:
            db.add(criterion)
        criteria: list[RubricCriterion] = new_criteria
    else:
        criteria = await _get_criteria_for_rubric(db, rubric.id)

    await db.commit()
    await db.refresh(rubric)

    logger.info(
        "Rubric updated",
        extra={"rubric_id": str(rubric_id), "teacher_id": str(teacher_id)},
    )
    return rubric, criteria


async def delete_rubric(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    rubric_id: uuid.UUID,
) -> None:
    """Soft-delete a rubric by setting ``deleted_at`` to now.

    Raises:
        NotFoundError: If the rubric does not exist or is already soft-deleted.
        ForbiddenError: If the rubric belongs to a different teacher.
        RubricInUseError: If the rubric is referenced by an open assignment.
    """
    rubric = await _get_rubric_owned_by(db, rubric_id, teacher_id)

    # Block deletion if any assignment owned by this teacher uses this rubric
    # and is still in an "open" state.  The join through Class enforces that
    # only assignments belonging to the authenticated teacher are counted.
    in_use_result = await db.execute(
        select(func.count(Assignment.id))
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.rubric_id == rubric_id,
            Assignment.status.in_(list(_BLOCKING_STATUSES)),
            Class.teacher_id == teacher_id,
        )
    )
    in_use_count: int = in_use_result.scalar_one()
    if in_use_count > 0:
        raise RubricInUseError(
            "Rubric is in use by one or more open assignments and cannot be deleted."
        )

    rubric.deleted_at = datetime.now(UTC)
    await db.commit()

    logger.info(
        "Rubric soft-deleted",
        extra={"rubric_id": str(rubric_id), "teacher_id": str(teacher_id)},
    )


async def duplicate_rubric(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    rubric_id: uuid.UUID,
) -> tuple[Rubric, list[RubricCriterion]]:
    """Duplicate a rubric as a new draft owned by the same teacher.

    The duplicate gets a ``"Copy of …"`` name prefix and ``is_template=False``.

    Raises:
        NotFoundError: If the rubric does not exist or is soft-deleted.
        ForbiddenError: If the rubric belongs to a different teacher.
    """
    source_rubric, source_criteria = await get_rubric(db, teacher_id, rubric_id)

    new_rubric = Rubric(
        teacher_id=teacher_id,
        name=f"Copy of {source_rubric.name}",
        description=source_rubric.description,
        is_template=False,
    )
    db.add(new_rubric)
    await db.flush()  # populate new_rubric.id

    new_criteria = [
        RubricCriterion(
            rubric_id=new_rubric.id,
            name=c.name,
            description=c.description,
            weight=c.weight,
            min_score=c.min_score,
            max_score=c.max_score,
            display_order=c.display_order,
            anchor_descriptions=c.anchor_descriptions,
        )
        for c in source_criteria
    ]
    for criterion in new_criteria:
        db.add(criterion)

    await db.commit()
    await db.refresh(new_rubric)

    logger.info(
        "Rubric duplicated",
        extra={
            "source_rubric_id": str(rubric_id),
            "new_rubric_id": str(new_rubric.id),
            "teacher_id": str(teacher_id),
        },
    )
    return new_rubric, new_criteria


def build_rubric_snapshot(
    rubric: Rubric,
    criteria: list[RubricCriterion],
) -> dict[str, object]:
    """Build the JSONB snapshot of a rubric for embedding in an Assignment.

    The snapshot is written at assignment-creation time and is immutable
    thereafter.  Grading always reads ``assignment.rubric_snapshot``, never
    the live rubric or criteria rows.
    """
    return {
        "id": str(rubric.id),
        "name": rubric.name,
        "description": rubric.description,
        "criteria": [
            {
                "id": str(c.id),
                "name": c.name,
                "description": c.description,
                "weight": float(c.weight),
                "min_score": c.min_score,
                "max_score": c.max_score,
                "display_order": c.display_order,
                "anchor_descriptions": c.anchor_descriptions,
            }
            for c in criteria
        ],
    }
