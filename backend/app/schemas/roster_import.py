"""Pydantic schemas for the CSV roster import endpoints.

No essay content or grade values appear here.  ``full_name`` and
``external_id`` are required for roster management and appear in responses;
they must never be written to log statements.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class ImportRowStatus(StrEnum):
    """Per-row classification returned by the import diff endpoint."""

    NEW = "new"
    UPDATED = "updated"  # student record found by external_id but not enrolled here
    SKIPPED = "skipped"  # already enrolled or flagged as potential duplicate
    ERROR = "error"  # row-level parse / validation error


class DiffRowResponse(BaseModel):
    """Status of a single CSV row as determined by the import diff analysis."""

    row_number: int
    full_name: str
    external_id: str | None
    status: ImportRowStatus
    message: str | None
    # Populated for UPDATED and SKIPPED (external_id match) rows.
    existing_student_id: uuid.UUID | None


class ImportDiffResponse(BaseModel):
    """Response body from POST /classes/{id}/students/import.

    Contains per-row analysis and aggregate counts.  No students are written
    to the database until the teacher calls the confirm endpoint.
    """

    rows: list[DiffRowResponse]
    new_count: int
    updated_count: int
    skipped_count: int
    error_count: int


class ImportRowInput(BaseModel):
    """A single row the teacher wishes to include in the confirmed import.

    The teacher sends back only the rows they want committed — they can omit
    any rows that were flagged as SKIPPED or ERROR in the diff response.
    """

    row_number: int = Field(ge=1)
    full_name: str = Field(min_length=1, max_length=255)
    external_id: str | None = Field(default=None, max_length=255)


class ImportConfirmRequest(BaseModel):
    """Request body for POST /classes/{id}/students/import/confirm.

    ``rows`` contains the subset of parsed rows the teacher approves for
    import.  The server re-validates each row before writing to the database.
    """

    rows: list[ImportRowInput] = Field(min_length=1)


class ImportConfirmResponse(BaseModel):
    """Response body from POST /classes/{id}/students/import/confirm."""

    created: int
    updated: int
    skipped: int
