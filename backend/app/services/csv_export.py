"""CSV grade export service.

Generates a synchronous CSV gradebook export for all locked grades in an
assignment.  Columns are: student_id, student_name, one column per rubric
criterion (ordered by ``display_order`` from the rubric snapshot), and
weighted_total.

Security invariants:
- Tenant isolation enforced: assignment is loaded via ``get_assignment``,
  which requires the authenticated teacher to own the assignment.
- The query that loads grades re-applies ``teacher_id`` via the class join
  so cross-teacher access cannot occur even if the ownership helper is bypassed.
- No student PII in any log statement — only entity IDs.
- An ``export_requested`` audit log entry (format: ``csv``) is written on
  every call — INSERT only, no UPDATE or DELETE on audit_logs.
- The rubric snapshot is always used for criterion metadata — never the live
  rubric rows.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.models.student import Student
from app.services.assignment import get_assignment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_criteria(rubric_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return criteria from a rubric snapshot sorted by display_order.

    Criteria with an explicit ``display_order`` are sorted by that value.
    Criteria without ``display_order`` retain their original relative order and
    are placed after explicitly ordered criteria, so the function is safe to
    call on snapshots created before ``display_order`` was populated.
    """
    criteria: list[dict[str, Any]] = rubric_snapshot.get("criteria", [])
    indexed_criteria = list(enumerate(criteria))
    sorted_criteria = sorted(
        indexed_criteria,
        key=lambda item: (
            item[1].get("display_order") is None,
            item[1].get("display_order", item[0]),
            item[0],
        ),
    )
    return [criterion for _, criterion in sorted_criteria]


def _build_csv(
    criteria: list[dict[str, Any]],
    grade_rows: Sequence[Any],
    grade_score_map: dict[uuid.UUID, dict[str, int]],
) -> str:
    """Render the CSV string from pre-loaded data.

    Args:
        criteria: List of criterion dicts from the rubric snapshot, in column order.
        grade_rows: ORM result rows with (id, total_score, student_id, full_name).
        grade_score_map: Maps grade_id → {rubric_criterion_id_str → final_score}.

    Returns:
        UTF-8 CSV string including header and data rows.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row.
    header = ["student_id", "student_name"] + [c["name"] for c in criteria] + ["weighted_total"]
    writer.writerow(header)

    # Data rows — one per locked grade.
    # Missing criterion scores are written as empty cells so LMS importers that
    # expect numeric columns do not receive a non-numeric sentinel like "N/A".
    for row in grade_rows:
        if not row.full_name:
            # A missing student name indicates the essay is unassigned; log the
            # grade_id so the issue can be investigated without exposing PII.
            logger.warning(
                "CSV export: locked grade has no associated student name",
                extra={"grade_id": str(row.id)},
            )
        criterion_cols = grade_score_map.get(row.id, {})
        data_row = (
            [str(row.student_id) if row.student_id else "", row.full_name or ""]
            + [criterion_cols.get(str(c["id"]), "") for c in criteria]
            + [str(row.total_score)]
        )
        writer.writerow(data_row)

    return output.getvalue()


def _write_audit(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> None:
    """Insert an ``export_requested`` audit log entry (INSERT-only, no await)."""
    audit = AuditLog(
        teacher_id=teacher_id,
        entity_type="export",
        entity_id=assignment_id,
        action="export_requested",
        before_value=None,
        after_value={
            "assignment_id": str(assignment_id),
            "format": "csv",
            "task_id": None,
        },
    )
    db.add(audit)


# ---------------------------------------------------------------------------
# Public service function
# ---------------------------------------------------------------------------


async def export_grades_csv(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> str:
    """Generate a CSV string of locked grades for the given assignment.

    Columns: ``student_id``, ``student_name``, one column per rubric criterion
    (in ``display_order`` order from the immutable rubric snapshot), then
    ``weighted_total``.

    Only grades where ``is_locked = True`` are included.  Essays not yet
    locked are silently excluded.  If no grades are locked, a CSV with only
    the header row is returned.

    Args:
        db: Async database session.
        assignment_id: UUID of the assignment to export.
        teacher_id: UUID of the authenticated teacher (enforces tenant isolation).

    Returns:
        A UTF-8 CSV string suitable for streaming as a file download.

    Raises:
        NotFoundError: Assignment does not exist.
        ForbiddenError: Assignment belongs to a different teacher.
    """
    # Validate ownership — raises NotFoundError / ForbiddenError as needed.
    assignment = await get_assignment(db, teacher_id, assignment_id)

    # Extract criteria from the immutable snapshot, ordered by display_order.
    criteria = _extract_criteria(assignment.rubric_snapshot)

    # Load all locked grades for this assignment with student info.
    # The query re-applies both assignment_id and teacher_id (via the class
    # join) so tenant isolation holds even independently of the ownership check
    # above.
    rows_result = await db.execute(
        select(
            Grade.id,
            Grade.total_score,
            Essay.student_id,
            Student.full_name,
        )
        .join(EssayVersion, Grade.essay_version_id == EssayVersion.id)
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .outerjoin(Student, Essay.student_id == Student.id)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == assignment_id,
            Class.teacher_id == teacher_id,
            Grade.is_locked.is_(True),
        )
        .order_by(Student.full_name)
    )
    grade_rows = rows_result.all()

    grade_score_map: dict[uuid.UUID, dict[str, int]] = {}

    if grade_rows:
        # Load criterion scores for all locked grades in a single query.
        grade_ids = [row.id for row in grade_rows]
        cs_result = await db.execute(
            select(CriterionScore)
            .where(CriterionScore.grade_id.in_(grade_ids))
            .order_by(CriterionScore.created_at)
        )
        for cs in cs_result.scalars().all():
            grade_score_map.setdefault(cs.grade_id, {})[str(cs.rubric_criterion_id)] = (
                cs.final_score
            )

    csv_content = _build_csv(criteria, grade_rows, grade_score_map)

    # Write audit log entry — INSERT only, no UPDATE/DELETE on audit_logs.
    _write_audit(db, teacher_id, assignment_id)
    await db.commit()

    logger.info(
        "CSV grade export generated",
        extra={
            "assignment_id": str(assignment_id),
            "teacher_id": str(teacher_id),
        },
    )
    return csv_content
