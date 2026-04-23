"""Rubric template service.

Business logic for rubric template operations:

- ``list_rubric_templates``      — list system templates + teacher's personal
                                   templates.
- ``save_rubric_as_template``    — copy a teacher's rubric as a personal
                                   template (``is_template=True``).

System templates have ``teacher_id IS NULL`` and ``is_template=True``.
Personal templates have ``teacher_id = <teacher_id>`` and ``is_template=True``.

No student PII is collected or processed here.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.models.rubric import Rubric, RubricCriterion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def list_rubric_templates(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[tuple[Rubric, int, bool]]:
    """Return system templates and the teacher's personal templates with criterion counts.

    Returns a list of (Rubric, criterion_count, is_system) tuples where
    ``is_system`` is True for templates with no teacher owner.

    Uses two queries (rubrics, then a COUNT GROUP BY) to avoid N+1 and avoid
    loading full criteria rows for the list view.
    System templates are returned first, then personal templates (both
    sub-groups ordered by name ascending).
    """
    rubric_result = await db.execute(
        select(Rubric)
        .where(
            Rubric.is_template.is_(True),
            Rubric.deleted_at.is_(None),
            # system templates (teacher_id IS NULL) OR this teacher's templates
            (Rubric.teacher_id.is_(None)) | (Rubric.teacher_id == teacher_id),
        )
        .order_by(
            # System templates first (teacher_id IS NULL sorts before any UUID),
            # then by name for stable ordering.
            Rubric.teacher_id.asc().nulls_first(),
            Rubric.name.asc(),
        )
    )
    rubrics = list(rubric_result.scalars().all())

    if not rubrics:
        return []

    rubric_ids = [r.id for r in rubrics]
    counts_rows = (
        await db.execute(
            select(
                RubricCriterion.rubric_id,
                func.count(RubricCriterion.id).label("cnt"),
            )
            .where(RubricCriterion.rubric_id.in_(rubric_ids))
            .group_by(RubricCriterion.rubric_id)
        )
    ).all()
    counts_by_rubric: dict[uuid.UUID, int] = {row.rubric_id: row.cnt for row in counts_rows}

    return [(r, counts_by_rubric.get(r.id, 0), r.teacher_id is None) for r in rubrics]


async def get_rubric_template(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    template_id: uuid.UUID,
) -> tuple[Rubric, list[RubricCriterion], bool]:
    """Return a single template with full criteria.

    System templates (``teacher_id IS NULL``) are accessible to any
    authenticated teacher.  Personal templates are only accessible to their
    owner.

    Returns (Rubric, criteria, is_system).

    Raises:
        NotFoundError: If the template does not exist or is soft-deleted.
        ForbiddenError: If a personal template belongs to a different teacher.
    """
    rubric_result = await db.execute(
        select(Rubric).where(
            Rubric.id == template_id,
            Rubric.is_template.is_(True),
            Rubric.deleted_at.is_(None),
        )
    )
    rubric = rubric_result.scalar_one_or_none()
    if rubric is None:
        raise NotFoundError("Template not found.")

    is_system = rubric.teacher_id is None
    if not is_system and rubric.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this template.")

    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_id == template_id)
        .order_by(RubricCriterion.display_order)
    )
    criteria = list(criteria_result.scalars().all())

    return rubric, criteria, is_system


async def save_rubric_as_template(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    rubric_id: uuid.UUID,
    name: str | None = None,
) -> tuple[Rubric, list[RubricCriterion]]:
    """Copy an existing rubric as a personal template owned by the teacher.

    The copy gets ``is_template=True`` and the same criteria as the source.
    If ``name`` is provided it overrides the source rubric's name.

    Raises:
        NotFoundError: If the source rubric does not exist or is soft-deleted.
        ForbiddenError: If the source rubric belongs to a different teacher.
    """
    # Verify ownership of the source rubric.
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

    # Load the full source rubric.
    source_result = await db.execute(
        select(Rubric).where(
            Rubric.id == rubric_id,
            Rubric.teacher_id == teacher_id,
            Rubric.deleted_at.is_(None),
        )
    )
    source_rubric = source_result.scalar_one_or_none()
    if source_rubric is None:
        raise NotFoundError("Rubric not found.")

    # Load the source criteria.
    criteria_result = await db.execute(
        select(RubricCriterion)
        .where(RubricCriterion.rubric_id == rubric_id)
        .order_by(RubricCriterion.display_order)
    )
    source_criteria = list(criteria_result.scalars().all())

    # Create the template rubric.
    template_rubric = Rubric(
        teacher_id=teacher_id,
        name=name if name is not None else source_rubric.name,
        description=source_rubric.description,
        is_template=True,
    )
    db.add(template_rubric)
    await db.flush()  # populate template_rubric.id

    # Copy criteria.
    new_criteria = [
        RubricCriterion(
            rubric_id=template_rubric.id,
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
    await db.refresh(template_rubric)

    logger.info(
        "Rubric saved as template",
        extra={
            "source_rubric_id": str(rubric_id),
            "template_rubric_id": str(template_rubric.id),
            "teacher_id": str(teacher_id),
        },
    )
    return template_rubric, new_criteria
