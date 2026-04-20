"""Classes router — class CRUD endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or processed here.

Endpoints:
  GET    /classes                   — list teacher's classes (filterable)
  POST   /classes                   — create a new class
  GET    /classes/{classId}         — get class detail
  PATCH  /classes/{classId}         — update class name, subject, grade level, academic year
  POST   /classes/{classId}/archive — archive the class (soft)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.class_ import ClassResponse, CreateClassRequest, PatchClassRequest
from app.services.class_ import (
    archive_class,
    create_class,
    get_class,
    list_classes,
    update_class,
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
    class_obj = await update_class(
        db,
        teacher_id=teacher.id,
        class_id=class_id,
        name=payload.name,
        subject=payload.subject,
        grade_level=payload.grade_level,
        academic_year=payload.academic_year,
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
