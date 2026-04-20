"""Classes router — class CRUD and enrollment endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
Student PII (names) is never logged — only entity IDs appear in log output.

Endpoints:
  GET    /classes                              — list teacher's classes (filterable)
  POST   /classes                              — create a new class
  GET    /classes/{classId}                    — get class detail
  PATCH  /classes/{classId}                    — update class name, subject, grade level, academic year
  POST   /classes/{classId}/archive            — archive the class (soft)
  GET    /classes/{classId}/students           — list enrolled students
  POST   /classes/{classId}/students           — enroll a new or existing student
  DELETE /classes/{classId}/students/{studentId} — soft-remove a student from the class
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.class_ import ClassResponse, CreateClassRequest, PatchClassRequest
from app.schemas.student import EnrolledStudentResponse, EnrollStudentRequest, StudentResponse
from app.services.class_ import (
    archive_class,
    create_class,
    get_class,
    list_classes,
    update_class,
)
from app.services.student import (
    enroll_student,
    list_enrolled_students,
    remove_enrollment,
)

router = APIRouter(prefix="/classes", tags=["classes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _class_response(class_obj: object) -> ClassResponse:
    """Build a ClassResponse from a Class ORM instance."""
    return ClassResponse.model_validate(class_obj)


# ---------------------------------------------------------------------------
# GET /classes
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List the authenticated teacher's classes",
)
async def list_classes_endpoint(
    academic_year: str | None = Query(default=None),
    is_archived: bool | None = Query(default=None),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all classes for the authenticated teacher.

    Supports optional query filters:
    - ``academic_year``: filter by academic year string (e.g. ``"2025-26"``)
    - ``is_archived``: ``true`` or ``false`` to filter by archive status
    """
    classes = await list_classes(
        db,
        teacher_id=teacher.id,
        academic_year=academic_year,
        is_archived=is_archived,
    )
    response_items = [_class_response(c).model_dump(mode="json") for c in classes]
    return JSONResponse(
        status_code=200,
        content={"data": response_items},
    )


# ---------------------------------------------------------------------------
# POST /classes
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Create a new class",
)
async def create_class_endpoint(
    payload: CreateClassRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a class owned by the authenticated teacher."""
    new_class = await create_class(
        db,
        teacher_id=teacher.id,
        name=payload.name,
        subject=payload.subject,
        grade_level=payload.grade_level,
        academic_year=payload.academic_year,
    )
    return JSONResponse(
        status_code=201,
        content={"data": _class_response(new_class).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}",
    summary="Get class detail",
)
async def get_class_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single class.

    Returns 404 if the class does not exist.
    Returns 403 if the class belongs to a different teacher.
    """
    class_obj = await get_class(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /classes/{classId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{class_id}",
    summary="Update class metadata",
)
async def patch_class_endpoint(
    class_id: uuid.UUID,
    payload: PatchClassRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update a class.

    Only fields explicitly included in the request body are updated.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    fields_set = payload.model_fields_set
    class_obj = await update_class(
        db,
        teacher_id=teacher.id,
        class_id=class_id,
        name=payload.name if "name" in fields_set else None,
        subject=payload.subject if "subject" in fields_set else None,
        grade_level=payload.grade_level if "grade_level" in fields_set else None,
        academic_year=payload.academic_year if "academic_year" in fields_set else None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /classes/{classId}/archive
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/archive",
    summary="Archive a class",
)
async def archive_class_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Archive a class by setting ``is_archived=True``.

    This is a soft operation — the class is not deleted.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    class_obj = await archive_class(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}/students
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/students",
    summary="List enrolled students in a class",
)
async def list_enrolled_students_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all actively enrolled students for a class.

    Returns 404 if the class does not exist.
    Returns 403 if the class belongs to a different teacher.
    """
    pairs = await list_enrolled_students(db, teacher.id, class_id)
    items = [
        EnrolledStudentResponse(
            enrollment_id=enrollment.id,
            enrolled_at=enrollment.enrolled_at,
            student=StudentResponse.model_validate(student),
        ).model_dump(mode="json")
        for enrollment, student in pairs
    ]
    return JSONResponse(status_code=200, content={"data": items})


# ---------------------------------------------------------------------------
# POST /classes/{classId}/students
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/students",
    status_code=201,
    summary="Enrol a new or existing student in a class",
)
async def enroll_student_endpoint(
    class_id: uuid.UUID,
    payload: EnrollStudentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Enrol a student in a class.

    Provide ``student_id`` to enroll an existing student, or ``full_name``
    (and optionally ``external_id``) to create a new student and enroll them.

    Returns 409 if the student is already enrolled.
    Returns 403 if the class or student belongs to a different teacher.
    Returns 404 if the class or referenced student does not exist.
    """
    enrollment, student = await enroll_student(
        db,
        teacher.id,
        class_id,
        student_id=payload.student_id,
        full_name=payload.full_name,
        external_id=payload.external_id,
    )
    response_data = EnrolledStudentResponse(
        enrollment_id=enrollment.id,
        enrolled_at=enrollment.enrolled_at,
        student=StudentResponse.model_validate(student),
    ).model_dump(mode="json")
    return JSONResponse(status_code=201, content={"data": response_data})


# ---------------------------------------------------------------------------
# DELETE /classes/{classId}/students/{studentId}
# ---------------------------------------------------------------------------


@router.delete(
    "/{class_id}/students/{student_id}",
    status_code=204,
    summary="Soft-remove a student from a class",
)
async def remove_enrollment_endpoint(
    class_id: uuid.UUID,
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a student from a class by setting ``removed_at``.

    This is a soft operation — the student record and all assignment history
    are preserved.

    Returns 404 if the class, student, or active enrollment does not exist.
    Returns 403 if the class or student belongs to a different teacher.
    """
    await remove_enrollment(db, teacher.id, class_id, student_id)
