"""Students router — student detail and update endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
Student PII (names) is never logged — only entity IDs appear in log output.

Endpoints:
  GET   /students/{studentId}  — get student detail
  PATCH /students/{studentId}  — update student name or external ID
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.student import PatchStudentRequest, StudentResponse
from app.services.student import get_student, update_student

router = APIRouter(prefix="/students", tags=["students"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _student_response(student: object) -> StudentResponse:
    return StudentResponse.model_validate(student)


# ---------------------------------------------------------------------------
# GET /students/{studentId}
# ---------------------------------------------------------------------------


@router.get(
    "/{student_id}",
    summary="Get student detail",
)
async def get_student_endpoint(
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single student owned by the authenticated teacher.

    Returns 404 if the student does not exist.
    Returns 403 if the student belongs to a different teacher.
    """
    student = await get_student(db, teacher.id, student_id)
    return JSONResponse(
        status_code=200,
        content={"data": _student_response(student).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /students/{studentId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{student_id}",
    summary="Update student name or external ID",
)
async def patch_student_endpoint(
    student_id: uuid.UUID,
    payload: PatchStudentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update a student record.

    Only fields explicitly included in the request body are updated.
    To explicitly clear ``external_id``, send ``"external_id": null``.

    Returns 403 if the student belongs to a different teacher.
    Returns 404 if the student does not exist.
    """
    fields_set = payload.model_fields_set
    student = await update_student(
        db,
        teacher.id,
        student_id,
        full_name=payload.full_name if "full_name" in fields_set else None,
        external_id=payload.external_id
        if "external_id" in fields_set and payload.external_id is not None
        else None,
        clear_external_id="external_id" in fields_set and payload.external_id is None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _student_response(student).model_dump(mode="json")},
    )
