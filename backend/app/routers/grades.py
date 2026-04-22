"""Grades router — grade read, edit, and lock endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints (``essay_grade_router``, prefix ``/essays``):
  GET   /essays/{essayId}/grade              — fetch grade with all criterion scores

Endpoints (``grades_router``, prefix ``/grades``):
  PATCH /grades/{gradeId}/feedback           — update overall summary feedback
  PATCH /grades/{gradeId}/criteria/{criterionId} — override a criterion score or feedback
  POST  /grades/{gradeId}/lock               — lock grade (no further edits allowed)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.grade import PatchCriterionRequest, PatchFeedbackRequest
from app.services.grade import (
    get_grade_audit_log,
    get_grade_for_essay,
    lock_grade,
    override_criterion,
    update_grade_feedback,
)

#: Router for essay-scoped grade retrieval.
essay_grade_router = APIRouter(prefix="/essays", tags=["grades"])

#: Router for grade-level edit and lock operations.
grades_router = APIRouter(prefix="/grades", tags=["grades"])


# ---------------------------------------------------------------------------
# GET /essays/{essayId}/grade
# ---------------------------------------------------------------------------


@essay_grade_router.get(
    "/{essay_id}/grade",
    summary="Get the current grade for an essay with all criterion scores",
)
async def get_essay_grade_endpoint(
    essay_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the current grade for an essay including all criterion scores.

    Response body: ``{"data": GradeResponse}``

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay or its grade does not exist.
    """
    grade_response = await get_grade_for_essay(
        db=db,
        essay_id=essay_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": grade_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /grades/{gradeId}/feedback
# ---------------------------------------------------------------------------


@grades_router.patch(
    "/{grade_id}/feedback",
    summary="Update the summary feedback for a grade",
)
async def patch_grade_feedback_endpoint(
    grade_id: uuid.UUID,
    body: PatchFeedbackRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update the teacher-edited summary feedback text for a grade.

    Writes a ``feedback_edited`` audit log entry with before/after values.

    Response body: ``{"data": GradeResponse}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade does not exist.
    Returns 409 if the grade is locked.
    """
    grade_response = await update_grade_feedback(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
        summary_feedback=body.summary_feedback,
    )
    return JSONResponse(
        status_code=200,
        content={"data": grade_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /grades/{gradeId}/criteria/{criterionId}
# ---------------------------------------------------------------------------


@grades_router.patch(
    "/{grade_id}/criteria/{criterion_score_id}",
    summary="Override a criterion score or feedback",
)
async def patch_criterion_score_endpoint(
    grade_id: uuid.UUID,
    criterion_score_id: uuid.UUID,
    body: PatchCriterionRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Override the teacher score and/or feedback for a specific criterion.

    At least one of ``teacher_score`` or ``teacher_feedback`` must be provided.
    Writes a ``score_override`` audit log entry with before/after values.

    Response body: ``{"data": GradeResponse}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade or criterion score does not exist.
    Returns 409 if the grade is locked.
    Returns 422 if neither field is provided.
    """
    grade_response = await override_criterion(
        db=db,
        grade_id=grade_id,
        criterion_score_id=criterion_score_id,
        teacher_id=teacher.id,
        teacher_score=body.teacher_score,
        teacher_feedback=body.teacher_feedback,
    )
    return JSONResponse(
        status_code=200,
        content={"data": grade_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /grades/{gradeId}/lock
# ---------------------------------------------------------------------------


@grades_router.post(
    "/{grade_id}/lock",
    status_code=200,
    summary="Lock a grade so no further edits are allowed",
)
async def lock_grade_endpoint(
    grade_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Lock a grade as final.

    Sets ``is_locked=True`` and records a ``grade_locked`` audit log entry.
    Locking an already-locked grade is idempotent and succeeds without error.

    Response body: ``{"data": GradeResponse}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade does not exist.
    """
    grade_response = await lock_grade(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": grade_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /grades/{gradeId}/audit
# ---------------------------------------------------------------------------


@grades_router.get(
    "/{grade_id}/audit",
    summary="Get the audit log for a grade",
)
async def get_grade_audit_endpoint(
    grade_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the full change history for a grade in chronological order.

    Includes all audit entries for the grade itself and its criterion scores
    (e.g. ``feedback_edited``, ``score_override``, ``grade_locked``,
    ``score_clamped``).  Each entry includes timestamp, actor (teacher_id),
    entity type/id, action, and before/after values.

    No student PII is included — only entity IDs appear in the response.

    Response body: ``{"data": [AuditLogEntryResponse, ...]}``

    Returns 403 if the grade belongs to a different teacher.
    Returns 404 if the grade does not exist.
    """
    entries = await get_grade_audit_log(
        db=db,
        grade_id=grade_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": [e.model_dump(mode="json") for e in entries]},
    )
