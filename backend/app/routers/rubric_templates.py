"""Rubric templates router.

Endpoints:
  GET  /rubric-templates         — list system + teacher's personal templates
  POST /rubric-templates         — save a rubric as a personal template

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is collected or processed here.

System templates have ``is_system=True`` (``teacher_id IS NULL``).
Personal templates have ``is_system=False`` (``teacher_id = teacher.id``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.rubric import Rubric, RubricCriterion
from app.models.user import User
from app.schemas.rubric import (
    RubricCriterionResponse,
    RubricTemplateListItemResponse,
    RubricTemplateResponse,
    SaveRubricAsTemplateRequest,
)
from app.services.rubric_template import list_rubric_templates, save_rubric_as_template

router = APIRouter(prefix="/rubric-templates", tags=["rubric-templates"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _template_response(
    rubric: Rubric,
    criteria: list[RubricCriterion],
    is_system: bool,
) -> RubricTemplateResponse:
    return RubricTemplateResponse(
        id=rubric.id,
        name=rubric.name,
        description=rubric.description,
        is_system=is_system,
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
# GET /rubric-templates
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List system and personal rubric templates",
)
async def list_rubric_templates_endpoint(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all system templates and the authenticated teacher's personal templates.

    System templates (``is_system=true``) are returned first, then personal
    templates, both groups sorted by name.
    """
    items = await list_rubric_templates(db, teacher.id)
    response_items = [
        RubricTemplateListItemResponse(
            id=rubric.id,
            name=rubric.name,
            description=rubric.description,
            is_system=is_system,
            created_at=rubric.created_at,
            updated_at=rubric.updated_at,
            criterion_count=len(criteria),
        )
        for rubric, criteria, is_system in items
    ]
    return JSONResponse(
        status_code=200,
        content={"data": [item.model_dump(mode="json") for item in response_items]},
    )


# ---------------------------------------------------------------------------
# POST /rubric-templates
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Save a rubric as a personal template",
)
async def save_rubric_as_template_endpoint(
    payload: SaveRubricAsTemplateRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Copy an existing rubric as a personal template (``is_template=True``).

    Returns 404 if the source rubric does not exist or is soft-deleted.
    Returns 403 if the source rubric belongs to a different teacher.
    """
    rubric, criteria = await save_rubric_as_template(
        db,
        teacher_id=teacher.id,
        rubric_id=payload.rubric_id,
        name=payload.name,
    )
    response_data = _template_response(rubric, criteria, is_system=False)
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )
