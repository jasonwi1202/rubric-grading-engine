"""Comment bank router — reusable feedback comment CRUD endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
Comment ``text`` is free-form user input and must be treated as potentially
sensitive, including possible student PII.  Do not log or echo comment text
beyond the intended authenticated API response.

Endpoints:
  GET    /comment-bank              — list teacher's saved comments
  POST   /comment-bank              — save a feedback snippet
  DELETE /comment-bank/{id}         — remove a saved comment
  GET    /comment-bank/suggestions  — fuzzy-match suggestions for a query
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.comment_bank import (
    CommentBankEntryResponse,
    CommentBankSuggestionResponse,
    CreateCommentBankEntryRequest,
)
from app.services.comment_bank import (
    create_comment,
    delete_comment,
    list_comments,
    suggest_comments,
)

router = APIRouter(prefix="/comment-bank", tags=["comment-bank"])


# ---------------------------------------------------------------------------
# GET /comment-bank
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List the authenticated teacher's saved comments",
)
async def list_comments_endpoint(
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all saved feedback comments for the authenticated teacher."""
    entries = await list_comments(db, teacher.id)
    items = [
        CommentBankEntryResponse(
            id=entry.id,
            text=entry.text,
            created_at=entry.created_at,
        )
        for entry in entries
    ]
    return JSONResponse(
        status_code=200,
        content={"data": [item.model_dump(mode="json") for item in items]},
    )


# ---------------------------------------------------------------------------
# POST /comment-bank
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Save a new feedback comment",
)
async def create_comment_endpoint(
    payload: CreateCommentBankEntryRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Save a reusable feedback snippet to the teacher's comment bank."""
    entry = await create_comment(db, teacher.id, payload.text)
    response_data = CommentBankEntryResponse(
        id=entry.id,
        text=entry.text,
        created_at=entry.created_at,
    )
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# DELETE /comment-bank/{id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{comment_id}",
    status_code=204,
    summary="Remove a saved comment",
)
async def delete_comment_endpoint(
    comment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a saved feedback comment.

    Returns 404 if the comment does not exist.
    Returns 403 if the comment belongs to a different teacher.
    """
    await delete_comment(db, teacher.id, comment_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /comment-bank/suggestions
# ---------------------------------------------------------------------------


@router.get(
    "/suggestions",
    summary="Get fuzzy-match comment suggestions for a query",
)
async def suggestions_endpoint(
    q: str = Query(min_length=1, max_length=500, description="Text to match against"),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return saved comments that fuzzy-match the supplied query string.

    Suggestions are advisory only — the teacher explicitly selects which
    comment (if any) to apply.  The ``score`` field (0.0–1.0) indicates
    match strength.
    """
    results = await suggest_comments(db, teacher.id, q)
    items = [
        CommentBankSuggestionResponse(
            id=entry.id,
            text=entry.text,
            score=round(score, 4),
            created_at=entry.created_at,
        )
        for entry, score in results
    ]
    return JSONResponse(
        status_code=200,
        content={"data": [item.model_dump(mode="json") for item in items]},
    )
