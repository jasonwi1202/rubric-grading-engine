"""Pydantic schemas for the PDF batch export endpoints.

No student PII is collected, processed, or stored in these schemas.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel


class TriggerExportResponse(BaseModel):
    """Response for POST /assignments/{id}/export (202 Accepted)."""

    task_id: str
    assignment_id: uuid.UUID
    status: str = "pending"


class ExportStatusResponse(BaseModel):
    """Response for GET /exports/{taskId}/status."""

    task_id: str
    status: Literal["pending", "processing", "complete", "failed"]
    total: int
    complete: int
    error: str | None = None


class ExportDownloadResponse(BaseModel):
    """Response for GET /exports/{taskId}/download."""

    url: str
    expires_in_seconds: int
