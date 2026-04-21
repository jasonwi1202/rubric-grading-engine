"""Pydantic schemas for batch grading endpoints.

Covers:
  POST /assignments/{id}/grade          — trigger batch grading
  GET  /assignments/{id}/grading-status — read progress from Redis
  POST /essays/{id}/grade/retry         — retry a single failed essay

No student PII is collected or logged here; student names appear only in
response payloads (read from Redis cache) and are never written to logs.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

BatchGradingStatus = Literal["idle", "processing", "complete", "failed", "partial"]


class TriggerGradingRequest(BaseModel):
    """Request body for POST /assignments/{id}/grade."""

    #: Optional explicit list of essay UUIDs to grade.  When omitted, all
    #: essays with status ``queued`` in the assignment are included.
    essay_ids: list[uuid.UUID] | None = None
    strictness: str = Field(
        default="balanced",
        pattern=r"^(lenient|balanced|strict)$",
    )


class TriggerGradingResponse(BaseModel):
    """Response body for POST /assignments/{id}/grade (HTTP 202)."""

    enqueued: int
    assignment_id: uuid.UUID


class EssayProgressItem(BaseModel):
    """Per-essay progress entry within a GradingStatusResponse."""

    id: uuid.UUID
    #: ``queued`` | ``grading`` | ``complete`` | ``failed``
    status: str
    #: Student display name — ``None`` when the essay is not yet assigned.
    student_name: str | None = None
    #: Error code string — only present when ``status == "failed"``.
    error: str | None = None


class GradingStatusResponse(BaseModel):
    """Response body for GET /assignments/{id}/grading-status."""

    #: Overall batch status derived from counters.
    #: ``idle`` — no batch started yet (Redis key absent or expired).
    #: ``processing`` — tasks still in flight.
    #: ``complete`` — all essays graded successfully.
    #: ``failed`` — all essays failed.
    #: ``partial`` — some succeeded, some failed; all tasks finished.
    status: BatchGradingStatus
    total: int
    complete: int
    failed: int
    essays: list[EssayProgressItem]


class RetryGradingRequest(BaseModel):
    """Request body for POST /essays/{id}/grade/retry."""

    strictness: str = Field(
        default="balanced",
        pattern=r"^(lenient|balanced|strict)$",
    )
