"""Rubrics router — rubric CRUD endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or processed here.

Endpoints:
  GET    /rubrics                   — list teacher's rubrics
  POST   /rubrics                   — create a new rubric
  GET    /rubrics/{rubricId}        — get rubric with all criteria
  PATCH  /rubrics/{rubricId}        — update rubric metadata or criteria
  DELETE /rubrics/{rubricId}        — soft-delete rubric (blocked if in use)
  POST   /rubrics/{rubricId}/duplicate — duplicate rubric as a new draft
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.rubric import (
    CreateRubricRequest,
    PatchRubricRequest,
    RubricCriterionResponse,
    RubricListItemResponse,
    RubricResponse,
)
from app.services.rubric import (
    create_rubric,
    delete_rubric,
    duplicate_rubric,
    get_rubric,
    list_rubrics,
    update_rubric,
)

router = APIRouter(prefix="/rubrics", tags=["rubrics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rubric_response(rubric_tuple: tuple) -> RubricResponse:  # type: ignore[type-arg]
    """Build a RubricResponse from a (Rubric, list[RubricCriterion]) tuple."""
    rubric, criteria = rubric_tuple
    return RubricResponse(
        id=rubric.id,
        name=rubric.name,
        description=rubric.description,
        is_template=rubric.is_template,
        created_at=rubric.created_at,
        updated_at=rubric.updated_at,
        criteria=[
            RubricCriterionResponse(
                id=c.id,
                name=c.name,
                description=c.description,
                weight=float(c.weight),
                min_score=c.min_score,
                max_score=c.max_score,
                display_order=c.display_order,
                anchor_descriptions=c.anchor_descriptions,
            )
            for c in criteria
        ],
    )


# ---------------------------------------------------------------------------
# GET /rubrics
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List the authenticated teacher's rubrics",
)
async def list_rubrics_endpoint(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all non-deleted rubrics for the authenticated teacher.

    Each item includes a ``criterion_count`` field.  For full criterion
    details use ``GET /rubrics/{rubricId}``.
    """
    items = await list_rubrics(db, teacher.id)
    response_items = [
        RubricListItemResponse(
            id=rubric.id,
            name=rubric.name,
            description=rubric.description,
            is_template=rubric.is_template,
            created_at=rubric.created_at,
            updated_at=rubric.updated_at,
            criterion_count=len(criteria),
        )
        for rubric, criteria in items
    ]
    return JSONResponse(
        status_code=200,
        content={"data": [item.model_dump(mode="json") for item in response_items]},
    )


# ---------------------------------------------------------------------------
# POST /rubrics
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Create a new rubric",
)
async def create_rubric_endpoint(
    payload: CreateRubricRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a rubric with the supplied criteria.

    The sum of all criterion weights must equal 100 — returns 422 otherwise.
    """
    rubric, criteria = await create_rubric(
        db,
        teacher_id=teacher.id,
        name=payload.name,
        description=payload.description,
        criteria_requests=payload.criteria,
    )
    response_data = _rubric_response((rubric, criteria))
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /rubrics/{rubricId}
# ---------------------------------------------------------------------------


@router.get(
    "/{rubric_id}",
    summary="Get a rubric with all criteria",
)
async def get_rubric_endpoint(
    rubric_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single rubric with its full criteria list.

    Returns 404 if the rubric does not exist or has been soft-deleted.
    Returns 403 if the rubric belongs to a different teacher.
    """
    rubric, criteria = await get_rubric(db, teacher.id, rubric_id)
    response_data = _rubric_response((rubric, criteria))
    return JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /rubrics/{rubricId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{rubric_id}",
    summary="Update rubric metadata or criteria",
)
async def patch_rubric_endpoint(
    rubric_id: uuid.UUID,
    payload: PatchRubricRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update a rubric.

    - ``name``: if provided and non-null, update the rubric name.
    - ``description``: if explicitly included in the body, update (or clear) it.
    - ``criteria``: if provided, replace all criteria.  The new set must pass
      weight-sum validation (must sum to 100).

    Returns 403 if the rubric belongs to a different teacher.
    Returns 422 if updated criteria weights do not sum to 100.
    """
    fields_set = payload.model_fields_set
    rubric, criteria = await update_rubric(
        db,
        teacher_id=teacher.id,
        rubric_id=rubric_id,
        name=payload.name,
        description=payload.description,
        update_description="description" in fields_set,
        criteria_requests=payload.criteria,
    )
    response_data = _rubric_response((rubric, criteria))
    return JSONResponse(
        status_code=200,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# DELETE /rubrics/{rubricId}
# ---------------------------------------------------------------------------


@router.delete(
    "/{rubric_id}",
    status_code=204,
    summary="Soft-delete a rubric",
)
async def delete_rubric_endpoint(
    rubric_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Soft-delete a rubric by setting its ``deleted_at`` timestamp.

    Blocked (returns 409) if the rubric is in use by an open assignment.
    Returns 403 if the rubric belongs to a different teacher.
    Returns 404 if the rubric does not exist or is already deleted.
    """
    await delete_rubric(db, teacher.id, rubric_id)
    return JSONResponse(status_code=204, content=None)


# ---------------------------------------------------------------------------
# POST /rubrics/{rubricId}/duplicate
# ---------------------------------------------------------------------------


@router.post(
    "/{rubric_id}/duplicate",
    status_code=201,
    summary="Duplicate a rubric as a new draft",
)
async def duplicate_rubric_endpoint(
    rubric_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a copy of the rubric with a ``"Copy of …"`` name prefix.

    The duplicate is not a template (``is_template=False``).

    Returns 403 if the rubric belongs to a different teacher.
    Returns 404 if the rubric does not exist or is soft-deleted.
    """
    rubric, criteria = await duplicate_rubric(db, teacher.id, rubric_id)
    response_data = _rubric_response((rubric, criteria))
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )
