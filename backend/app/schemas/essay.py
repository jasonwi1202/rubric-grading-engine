"""Pydantic schemas for essay upload and response.

No student PII is collected, processed, or stored here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


# ---------------------------------------------------------------------------
# Browser compose — M5-09
# ---------------------------------------------------------------------------

#: Maximum allowed character length for browser-composed essay content.
_MAX_COMPOSE_CONTENT_LENGTH = 500_000


class ComposeEssayRequest(BaseModel):
    """Request body for ``POST /assignments/{assignmentId}/essays/compose``.

    Creates an empty essay version ready for in-browser composition.
    The ``student_id`` is optional — callers may assign the student later via
    ``PATCH /essays/{essayId}``.
    """

    student_id: uuid.UUID | None = None


class ComposeEssayResponse(BaseModel):
    """Response for ``POST /assignments/{assignmentId}/essays/compose``."""

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID | None
    status: EssayStatus
    current_content: str
    word_count: int

    model_config = {"from_attributes": True}


class WriteSnapshotRequest(BaseModel):
    """Request body for ``POST /essays/{essayId}/snapshots``.

    Sent by the browser writing interface on each autosave tick.
    ``html_content`` is the raw innerHTML of the contentEditable editor.
    ``word_count`` is pre-computed by the client (strip tags, split on
    whitespace) so the server does not need to parse HTML.
    """

    html_content: str = Field(
        max_length=_MAX_COMPOSE_CONTENT_LENGTH,
        description="Raw HTML from the browser rich-text editor.",
    )
    word_count: int = Field(ge=0, description="Pre-computed word count (tags stripped).")


class WriteSnapshotResponse(BaseModel):
    """Response for ``POST /essays/{essayId}/snapshots``."""

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    snapshot_count: int
    word_count: int
    saved_at: datetime

    model_config = {"from_attributes": True}


class SnapshotItem(BaseModel):
    """Metadata for a single writing-process snapshot (no HTML returned in list)."""

    seq: int
    ts: str
    word_count: int


class GetSnapshotsResponse(BaseModel):
    """Response for ``GET /essays/{essayId}/snapshots``.

    Returns the current editor content (HTML) and snapshot metadata list so
    the browser can restore the editor state after a refresh/navigation.
    The full ``html_content`` of individual snapshots is not returned here;
    it is stored server-side and will be used by writing-process visibility
    features (M5-10, M5-11).
    """

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    current_content: str
    word_count: int
    snapshots: list[SnapshotItem]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Composition timeline / process signals — M5-10
# ---------------------------------------------------------------------------


class SessionSegmentResponse(BaseModel):
    """One contiguous writing session derived from the snapshot history."""

    session_index: int
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    snapshot_count: int
    word_count_start: int
    word_count_end: int
    words_added: int


class PasteEventResponse(BaseModel):
    """A snapshot step where a large word-count jump was detected."""

    snapshot_seq: int
    occurred_at: datetime
    words_before: int
    words_after: int
    words_added: int
    session_index: int


class RapidCompletionEventResponse(BaseModel):
    """A session that brought the essay near-complete in a short time."""

    session_index: int
    duration_seconds: float
    words_at_start: int
    words_at_end: int
    completion_fraction: float


class ProcessSignalsResponse(BaseModel):
    """Response for ``GET /essays/{essayId}/process-signals``.

    Carries the full composition timeline analysis: session segments,
    detected events, and summary metrics.

    When ``has_process_data`` is ``False`` the essay was submitted as a file
    upload (no writing-process data was captured) and all list fields are
    empty with numeric metrics set to zero.
    """

    essay_id: uuid.UUID
    essay_version_id: uuid.UUID
    has_process_data: bool
    session_count: int
    sessions: list[SessionSegmentResponse]
    inter_session_gaps_seconds: list[float]
    active_writing_seconds: float
    total_elapsed_seconds: float
    paste_events: list[PasteEventResponse]
    rapid_completion_events: list[RapidCompletionEventResponse]
    computed_at: datetime
