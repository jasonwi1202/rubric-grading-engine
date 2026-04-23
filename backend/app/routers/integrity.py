"""Integrity report router — read and status-update endpoints (M4.6).

All endpoints require a valid JWT (``get_current_teacher`` dependency).
No student PII is logged — only entity IDs appear in log output.

Endpoints (``essay_integrity_router``, prefix ``/essays``):
  GET   /essays/{essayId}/integrity                        — fetch latest integrity report

Endpoints (``assignment_integrity_router``, prefix ``/assignments``):
  GET   /assignments/{assignmentId}/integrity/summary      — class-level integrity counts

Endpoints (``integrity_reports_router``, prefix ``/integrity-reports``):
  PATCH /integrity-reports/{reportId}/status               — update review status
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.user import User
from app.schemas.integrity import (
    IntegrityReportResponse,
    IntegritySummaryResponse,
    PatchIntegrityStatusRequest,
)
from app.services.integrity import (
    get_integrity_report_for_essay,
    get_integrity_summary_for_assignment,
    update_integrity_report_status,
)

logger = logging.getLogger(__name__)

#: Router for essay-scoped integrity report retrieval.
essay_integrity_router = APIRouter(prefix="/essays", tags=["integrity"])

#: Router for assignment-scoped integrity summary.
assignment_integrity_router = APIRouter(prefix="/assignments", tags=["integrity"])

#: Router for integrity-report-level status updates.
integrity_reports_router = APIRouter(prefix="/integrity-reports", tags=["integrity"])


class _IntegrityReportResponseEnvelope(BaseModel):
    """Standard data envelope wrapping an IntegrityReportResponse."""

    data: IntegrityReportResponse


class _IntegritySummaryResponseEnvelope(BaseModel):
    """Standard data envelope wrapping an IntegritySummaryResponse."""

    data: IntegritySummaryResponse


# ---------------------------------------------------------------------------
# GET /essays/{essayId}/integrity
# ---------------------------------------------------------------------------


@essay_integrity_router.get(
    "/{essay_id}/integrity",
    summary="Get the latest integrity report for an essay",
    response_model=_IntegrityReportResponseEnvelope,
)
async def get_essay_integrity_endpoint(
    essay_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the latest integrity report for an essay.

    The report includes AI-likelihood score, similarity score, and any
    flagged passages detected by the configured integrity provider.

    All signals are informational — language is framed as potential signals,
    not definitive findings.

    Response body: ``{"data": IntegrityReportResponse}``

    Returns 403 if the essay belongs to a different teacher.
    Returns 404 if the essay does not exist or has no integrity report.
    """
    report = await get_integrity_report_for_essay(
        db=db,
        essay_id=essay_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": report.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /assignments/{assignmentId}/integrity/summary
# ---------------------------------------------------------------------------


@assignment_integrity_router.get(
    "/{assignment_id}/integrity/summary",
    summary="Get class-level integrity signal counts for an assignment",
    response_model=_IntegritySummaryResponseEnvelope,
)
async def get_assignment_integrity_summary_endpoint(
    assignment_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return aggregate integrity signal counts (flagged / clear / pending) for
    all essays in an assignment.

    Useful for the assignment overview page to surface a class-level integrity
    picture at a glance.

    Response body: ``{"data": IntegritySummaryResponse}``

    Returns 403 if the assignment belongs to a different teacher.
    Returns 404 if the assignment does not exist.
    """
    summary = await get_integrity_summary_for_assignment(
        db=db,
        assignment_id=assignment_id,
        teacher_id=teacher.id,
    )
    return JSONResponse(
        status_code=200,
        content={"data": summary.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /integrity-reports/{reportId}/status
# ---------------------------------------------------------------------------


@integrity_reports_router.patch(
    "/{report_id}/status",
    summary="Update the teacher review status of an integrity report",
    response_model=_IntegrityReportResponseEnvelope,
)
async def patch_integrity_status_endpoint(
    report_id: uuid.UUID,
    body: PatchIntegrityStatusRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update the review status of an integrity report.

    Accepted status values: ``reviewed_clear`` or ``flagged``.
    Setting the status back to ``pending`` is not allowed.

    Response body: ``{"data": IntegrityReportResponse}``

    Returns 403 if the report belongs to a different teacher.
    Returns 404 if the report does not exist.
    Returns 422 if the status value is not a valid teacher action.
    """
    report = await update_integrity_report_status(
        db=db,
        report_id=report_id,
        teacher_id=teacher.id,
        status=body.status,
    )
    return JSONResponse(
        status_code=200,
        content={"data": report.model_dump(mode="json")},
    )
