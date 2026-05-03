"""Teacher copilot data query router (M7-03).

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints:
  POST /copilot/query — answer a teacher's natural-language query using
                        live class data.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.copilot import CopilotQueryRequest
from app.services.copilot import execute_copilot_query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/copilot", tags=["copilot"])


# ---------------------------------------------------------------------------
# POST /copilot/query
# ---------------------------------------------------------------------------


@router.post(
    "/query",
    summary="Answer a teacher's natural-language query using live class data",
)
async def copilot_query_endpoint(
    body: CopilotQueryRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Answer a teacher's natural-language question using live class data.

    The copilot gathers student skill profiles and active worklist signals
    scoped to the authenticated teacher, feeds them to the LLM, and returns
    a ranked, explainable response.

    Supports queries such as:
    - "Who is falling behind on thesis development?"
    - "What should I teach tomorrow based on this week's essays?"
    - "Which students haven't improved since my last feedback?"

    When class data is too sparse to produce a reliable response, the
    copilot expresses uncertainty and sets ``has_sufficient_data`` to
    ``false`` rather than fabricating conclusions.

    Request body:
    - ``query``: Natural-language question (1–500 characters).
    - ``class_id``: Optional class UUID to scope context data.

    Response body: ``{"data": CopilotQueryResponse}``

    Returns 404 if ``class_id`` is supplied and the class does not exist.
    Returns 403 if ``class_id`` belongs to a different teacher.
    Returns 503 on LLM transport failure.
    """
    logger.info(
        "Copilot query received",
        extra={
            "teacher_id": str(teacher.id),
            "class_id": str(body.class_id) if body.class_id else None,
        },
    )

    result = await execute_copilot_query(
        db,
        teacher_id=teacher.id,
        query_text=body.query,
        class_id=body.class_id,
    )

    return JSONResponse(
        status_code=200,
        content={"data": result.model_dump(mode="json")},
    )
