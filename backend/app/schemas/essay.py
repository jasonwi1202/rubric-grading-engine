"""Pydantic schemas for essay upload and response.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.essay import EssayStatus

AutoAssignStatus = Literal["assigned", "ambiguous", "unassigned"]


class EssayVersionResponse(BaseModel):
    """A single essay version within an essay response."""

    id: uuid.UUID
    version_number: int
    word_count: int
    file_storage_key: str | None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class EssayUploadItemResponse(BaseModel):
    """Response for a single essay after upload ingestion."""

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID | None
    status: EssayStatus
    word_count: int
    file_storage_key: str | None
    submitted_at: datetime
    #: Outcome of the auto-assignment attempt.
    #:  ``"assigned"``  — matched and assigned to a student.
    #:  ``"ambiguous"`` — multiple candidates; held for manual review.
    #:  ``"unassigned"`` — no match found; held for manual review.
    #: ``None`` when the caller supplied an explicit ``student_id`` (no
    #: roster search was performed) or the field is not available.
    auto_assign_status: AutoAssignStatus | None = None

    model_config = {"from_attributes": True}


class EssayListItemResponse(BaseModel):
    """Response for a single essay in the assignment essay list.

    Returned by ``GET /assignments/{id}/essays`` and
    ``PATCH /essays/{essayId}``.

    ``auto_assign_status`` is derived from the current ``student_id``:
    - ``"assigned"``   — the essay has a student assigned.
    - ``"unassigned"`` — the essay has no student yet (includes formerly
      ambiguous essays; the original ambiguous state is not preserved after
      upload).
    """

    essay_id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID | None
    student_name: str | None
    status: EssayStatus
    word_count: int
    submitted_at: datetime
    auto_assign_status: AutoAssignStatus | None = None

    model_config = {"from_attributes": True}


class AssignEssayRequest(BaseModel):
    """Request body for ``PATCH /essays/{essayId}``.

    The ``student_id`` must belong to the authenticated teacher and be
    actively enrolled in the assignment's class.
    """

    student_id: uuid.UUID
