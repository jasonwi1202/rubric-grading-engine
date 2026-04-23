"""Integrity provider abstraction for academic-integrity checks (M4.5/M4.6).

Implements the ``IntegrityProvider`` interface and two concrete providers:

* :class:`InternalProvider` — wraps the cross-submission similarity logic from
  :mod:`app.services.embedding` (M4.4).  Active when
  ``INTEGRITY_PROVIDER=internal`` (the default).

* :class:`OriginalityAiProvider` — calls the Originality.ai REST API using
  ``INTEGRITY_API_KEY`` from settings.  Active when
  ``INTEGRITY_PROVIDER=originality_ai``.

The active provider is selected by :func:`get_provider`, which reads
``settings.integrity_provider``.  If a third-party provider encounters a
network error, :func:`run_integrity_check` automatically falls back to
:class:`InternalProvider` and logs a warning.

API helper functions (M4.6):
- :func:`get_integrity_report_for_essay` — fetch the latest IntegrityReport
  for an essay, scoped to the authenticated teacher.
- :func:`update_integrity_report_status` — update the teacher review status
  on an IntegrityReport (``reviewed_clear`` or ``flagged``).

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output (no student PII).
- ``teacher_id`` is always included in DB queries (tenant isolation).
"""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus
from app.schemas.integrity import IntegrityReportResponse, IntegritySummaryResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class IntegrityResult:
    """Normalised result returned by any :class:`IntegrityProvider`.

    Attributes:
        provider: Short name of the provider that produced this result
            (e.g. ``"internal"``, ``"originality_ai"``).
        ai_likelihood: Probability [0.0, 1.0] that the text was AI-generated,
            or ``None`` when the provider does not surface this signal.
        similarity_score: Similarity score [0.0, 1.0] vs. known sources, or
            ``None`` when the provider does not surface this signal.
        flagged_passages: Provider-specific list of passage excerpts that
            triggered the check.  May be empty.
    """

    provider: str
    ai_likelihood: float | None = None
    similarity_score: float | None = None
    flagged_passages: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class IntegrityProvider(ABC):
    """Abstract base for all integrity-check providers.

    Subclasses implement :meth:`check` which performs the actual check and
    returns a normalised :class:`IntegrityResult`.  The provider name returned
    in the result is used as ``IntegrityReport.provider`` when the report is
    persisted.
    """

    @abstractmethod
    async def check(
        self,
        db: AsyncSession,
        essay_version_id: uuid.UUID,
        assignment_id: uuid.UUID,
        teacher_id: uuid.UUID,
        essay_text: str,
    ) -> IntegrityResult:
        """Run the integrity check and return a normalised result.

        Args:
            db: Async database session.
            essay_version_id: UUID of the ``EssayVersion`` being checked.
            assignment_id: UUID of the parent assignment (for cross-submission
                scope).
            teacher_id: The owning teacher's UUID (tenant isolation).
            essay_text: The plain-text content of the essay.

        Returns:
            A populated :class:`IntegrityResult`.
        """


# ---------------------------------------------------------------------------
# InternalProvider
# ---------------------------------------------------------------------------


class InternalProvider(IntegrityProvider):
    """Internal cross-submission similarity using pgvector embeddings (M4.4).

    Delegates to :func:`app.services.embedding.compute_and_store_embedding`
    and :func:`app.services.embedding.flag_similar_essays`.

    The similarity score stored on the returned :class:`IntegrityResult` is
    the *maximum* similarity found across all flagged pairs, or ``None`` when
    no similar pairs were found.
    """

    async def check(
        self,
        db: AsyncSession,
        essay_version_id: uuid.UUID,
        assignment_id: uuid.UUID,
        teacher_id: uuid.UUID,
        essay_text: str,
    ) -> IntegrityResult:
        from app.services.embedding import (  # noqa: PLC0415 — lazy import
            compute_and_store_embedding,
            flag_similar_essays,
        )

        embedding = await compute_and_store_embedding(
            db=db,
            essay_version_id=essay_version_id,
            teacher_id=teacher_id,
        )

        # Run similarity scan in a fresh session so the embedding commit is
        # visible to the cosine-similarity query.
        async with AsyncSessionLocal() as fresh_db:
            flagged_count = await flag_similar_essays(
                db=fresh_db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                embedding=embedding,
            )

        logger.info(
            "InternalProvider check complete",
            extra={
                "essay_version_id": str(essay_version_id),
                "flagged_count": flagged_count,
            },
        )

        # Retrieve the highest similarity score written by flag_similar_essays
        # to surface on the IntegrityResult.
        similarity_score: float | None = None
        if flagged_count:
            result = await db.execute(
                select(IntegrityReport.similarity_score)
                .where(
                    IntegrityReport.essay_version_id == essay_version_id,
                    IntegrityReport.provider == "internal",
                    IntegrityReport.teacher_id == teacher_id,
                )
                .order_by(IntegrityReport.similarity_score.desc())
                .limit(1)
            )
            similarity_score = result.scalar_one_or_none()

        return IntegrityResult(
            provider="internal",
            similarity_score=similarity_score,
        )


# ---------------------------------------------------------------------------
# OriginalityAiProvider
# ---------------------------------------------------------------------------

_ORIGINALITY_AI_SCAN_URL = "https://api.originality.ai/api/v1/scan/ai"


class OriginalityAiProvider(IntegrityProvider):
    """Calls the Originality.ai REST API to detect AI-generated content.

    Reads ``INTEGRITY_API_KEY`` from ``settings.integrity_api_key``.

    API contract (POST /api/v1/scan/ai):
    - Request body: ``{"content": "<essay text>", "aiModelVersion": "1"}``
    - Headers: ``X-OAI-API-KEY: <key>``
    - Response (success): ``{"ai_likelihood": <float 0-1>, "score": {...}}``

    On a network error (``httpx.TransportError`` or ``httpx.TimeoutException``),
    raises :class:`IntegrityProviderUnavailableError` so the caller can fall
    back to the internal provider.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.integrity_api_key or ""

    async def check(
        self,
        db: AsyncSession,
        essay_version_id: uuid.UUID,
        assignment_id: uuid.UUID,
        teacher_id: uuid.UUID,
        essay_text: str,
    ) -> IntegrityResult:
        # Verify essay version exists under the provided assignment and is owned
        # by the requesting teacher before spending an API credit (tenant
        # isolation).
        ownership_result = await db.execute(
            select(EssayVersion.id)
            .join(Essay, EssayVersion.essay_id == Essay.id)
            .join(Assignment, Essay.assignment_id == Assignment.id)
            .join(Class, Assignment.class_id == Class.id)
            .where(
                EssayVersion.id == essay_version_id,
                Essay.assignment_id == assignment_id,
                Class.teacher_id == teacher_id,
            )
        )
        if ownership_result.scalar_one_or_none() is None:
            exists_result = await db.execute(
                select(EssayVersion.id)
                .join(Essay, EssayVersion.essay_id == Essay.id)
                .where(
                    EssayVersion.id == essay_version_id,
                    Essay.assignment_id == assignment_id,
                )
            )
            if exists_result.scalar_one_or_none() is None:
                raise NotFoundError("EssayVersion not found.")
            raise ForbiddenError("You do not have access to this essay version.")

        # Idempotency guard: if a report for this version already exists, return
        # it immediately without spending an API credit.
        idempotency_check = await db.execute(
            select(IntegrityReport)
            .where(
                IntegrityReport.essay_version_id == essay_version_id,
                IntegrityReport.provider == "originality_ai",
                IntegrityReport.teacher_id == teacher_id,
            )
        )
        existing = idempotency_check.scalar_one_or_none()
        if existing is not None:
            logger.info(
                "OriginalityAiProvider: existing report found — skipping API call",
                extra={"essay_version_id": str(essay_version_id)},
            )
            return IntegrityResult(
                provider="originality_ai",
                ai_likelihood=existing.ai_likelihood,
                similarity_score=existing.similarity_score,
                flagged_passages=existing.flagged_passages or [],
            )

        ai_likelihood: float | None = None
        similarity_score: float | None = None
        flagged_passages: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    _ORIGINALITY_AI_SCAN_URL,
                    headers={"X-OAI-API-KEY": self._api_key},
                    json={"content": essay_text, "aiModelVersion": "1"},
                )
                response.raise_for_status()
                try:
                    raw_data = response.json()
                except (json.JSONDecodeError, ValueError):
                    logger.warning(
                        "OriginalityAiProvider: could not decode JSON from response",
                        extra={"essay_version_id": str(essay_version_id)},
                    )
                    raise IntegrityProviderUnavailableError(
                        "Originality.ai returned invalid JSON"
                    ) from None
                if not isinstance(raw_data, dict):
                    logger.warning(
                        "OriginalityAiProvider: unexpected response type (not a JSON object)",
                        extra={"essay_version_id": str(essay_version_id)},
                    )
                    raise IntegrityProviderUnavailableError(
                        "Originality.ai returned unexpected response type"
                    )
                data: dict[str, Any] = raw_data

        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning(
                "OriginalityAiProvider network error — provider unavailable",
                extra={
                    "essay_version_id": str(essay_version_id),
                    "error_type": type(exc).__name__,
                },
            )
            raise IntegrityProviderUnavailableError(
                "Originality.ai is unavailable"
            ) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code >= 500 or status_code == 429:
                logger.warning(
                    "OriginalityAiProvider HTTP error — provider unavailable",
                    extra={
                        "essay_version_id": str(essay_version_id),
                        "error_type": type(exc).__name__,
                        "status_code": status_code,
                    },
                )
                raise IntegrityProviderUnavailableError(
                    "Originality.ai is unavailable"
                ) from exc
            raise

        # Normalise response fields; ignore unrecognised keys gracefully.
        raw_score = data.get("score", {})
        if isinstance(raw_score, dict):
            ai_raw = raw_score.get("ai")
            if ai_raw is not None:
                try:
                    ai_likelihood = max(0.0, min(1.0, float(ai_raw)))
                except (TypeError, ValueError):
                    logger.warning(
                        "OriginalityAiProvider: could not parse 'score.ai' from response",
                        extra={"essay_version_id": str(essay_version_id)},
                    )

        # Top-level ai_likelihood field (fallback for some API versions).
        if ai_likelihood is None:
            top_level = data.get("ai_likelihood")
            if top_level is not None:
                try:
                    ai_likelihood = max(0.0, min(1.0, float(top_level)))
                except (TypeError, ValueError):
                    logger.warning(
                        "OriginalityAiProvider: could not parse 'ai_likelihood' from response",
                        extra={"essay_version_id": str(essay_version_id)},
                    )

        sentences = data.get("sentences")
        if isinstance(sentences, list):
            for s in sentences:
                if not isinstance(s, dict):
                    continue
                prob = s.get("generated_prob")
                # Only flag when probability is a valid numeric value above threshold.
                if isinstance(prob, (int, float)) and prob >= settings.integrity_ai_likelihood_threshold:
                    flagged_passages.append(
                        {
                            "text": s.get("sentence", ""),
                            "ai_probability": prob,
                        }
                    )

        # Write the IntegrityReport atomically.  The unique constraint on
        # (essay_version_id, provider) means a concurrent duplicate insert is
        # silently skipped (ON CONFLICT DO NOTHING) rather than raising a DB
        # error or creating a duplicate row.
        stmt = (
            pg_insert(IntegrityReport)
            .values(
                id=uuid.uuid4(),
                essay_version_id=essay_version_id,
                teacher_id=teacher_id,
                provider="originality_ai",
                ai_likelihood=ai_likelihood,
                similarity_score=similarity_score,
                flagged_passages=flagged_passages if flagged_passages else None,
                status=IntegrityReportStatus.pending,
            )
            .on_conflict_do_nothing(
                index_elements=["essay_version_id", "provider"]
            )
            .returning(IntegrityReport.id)
        )
        insert_result = await db.execute(stmt)
        was_inserted = insert_result.scalar_one_or_none() is not None

        try:
            await db.commit()
        except IntegrityError:
            # FK violation: the essay version was deleted between the ownership
            # check and this commit.  Translate to a domain exception so callers
            # get a deterministic error instead of a raw SQLAlchemy exception.
            await db.rollback()
            raise ConflictError(
                "Could not save integrity report — the essay version may have been deleted."
            ) from None

        if not was_inserted:
            # Race condition: a concurrent worker already committed the row.
            # Query for the existing report and return it without re-spending a
            # credit.
            logger.info(
                "OriginalityAiProvider: concurrent insert detected — returning existing report",
                extra={"essay_version_id": str(essay_version_id)},
            )
            re_select = await db.execute(
                select(IntegrityReport).where(
                    IntegrityReport.essay_version_id == essay_version_id,
                    IntegrityReport.provider == "originality_ai",
                    IntegrityReport.teacher_id == teacher_id,
                )
            )
            existing = re_select.scalar_one_or_none()
            if existing is not None:
                return IntegrityResult(
                    provider="originality_ai",
                    ai_likelihood=existing.ai_likelihood,
                    similarity_score=existing.similarity_score,
                    flagged_passages=existing.flagged_passages or [],
                )
            raise ConflictError(
                # Extremely unlikely: the ON CONFLICT DO NOTHING triggered (meaning
                # another worker committed the row), but our re-select found nothing
                # — the row was deleted between the two operations.  Surface a
                # deterministic domain error rather than returning an unexpected None.
                "Could not retrieve integrity report after concurrent write."
            )

        logger.info(
            "OriginalityAiProvider check complete",
            extra={"essay_version_id": str(essay_version_id)},
        )

        return IntegrityResult(
            provider="originality_ai",
            ai_likelihood=ai_likelihood,
            similarity_score=similarity_score,
            flagged_passages=flagged_passages,
        )


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class IntegrityProviderUnavailableError(Exception):
    """Raised by a third-party provider when it cannot be reached.

    Callers should fall back to :class:`InternalProvider` on this error.
    """


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[str, type[IntegrityProvider]] = {
    "internal": InternalProvider,
    "originality_ai": OriginalityAiProvider,
}


def get_provider() -> IntegrityProvider:
    """Return the active :class:`IntegrityProvider` based on settings.

    Reads ``settings.integrity_provider`` (env var ``INTEGRITY_PROVIDER``).
    Falls back to :class:`InternalProvider` for unrecognised values.

    Returns:
        An instantiated :class:`IntegrityProvider`.
    """
    provider_name = (settings.integrity_provider or "internal").lower()
    provider_cls = _PROVIDER_MAP.get(provider_name, InternalProvider)
    return provider_cls()


# ---------------------------------------------------------------------------
# Public run helper (with fallback)
# ---------------------------------------------------------------------------


async def run_integrity_check(
    db: AsyncSession,
    essay_version_id: uuid.UUID,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
    essay_text: str,
    *,
    provider: IntegrityProvider | None = None,
) -> IntegrityResult:
    """Run the integrity check using the configured provider.

    If the active provider is unavailable (raises
    :class:`IntegrityProviderUnavailableError`), this function automatically
    falls back to :class:`InternalProvider` and logs a warning.

    Args:
        db: Async database session.
        essay_version_id: UUID of the ``EssayVersion`` being checked.
        assignment_id: UUID of the parent assignment.
        teacher_id: The owning teacher's UUID.
        essay_text: Plain-text essay content.
        provider: Optional override for the active provider (used in tests).

    Returns:
        A populated :class:`IntegrityResult` from whichever provider ran.
    """
    active_provider = provider or get_provider()

    try:
        return await active_provider.check(
            db=db,
            essay_version_id=essay_version_id,
            assignment_id=assignment_id,
            teacher_id=teacher_id,
            essay_text=essay_text,
        )
    except IntegrityProviderUnavailableError:
        if isinstance(active_provider, InternalProvider):
            # Internal provider itself should never raise this error; re-raise
            # to surface unexpected states.
            raise

        logger.warning(
            "Third-party integrity provider unavailable — falling back to internal",
            extra={
                "essay_version_id": str(essay_version_id),
                "provider": type(active_provider).__name__,
            },
        )

        fallback = InternalProvider()
        return await fallback.check(
            db=db,
            essay_version_id=essay_version_id,
            assignment_id=assignment_id,
            teacher_id=teacher_id,
            essay_text=essay_text,
        )


# ---------------------------------------------------------------------------
# API helpers (M4.6)
# ---------------------------------------------------------------------------


async def get_integrity_report_for_essay(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> IntegrityReportResponse:
    """Return the latest IntegrityReport for an essay, tenant-scoped.

    The report is looked up via the most-recently created IntegrityReport whose
    ``essay_version_id`` matches the essay's current (latest) version.  If the
    essay has multiple versions, only the latest version's report is returned.

    Args:
        db: Async database session.
        essay_id: UUID of the Essay (not the EssayVersion).
        teacher_id: The requesting teacher's UUID (tenant isolation).

    Returns:
        A populated :class:`IntegrityReportResponse`.

    Raises:
        NotFoundError: The essay does not exist or has no integrity report.
        ForbiddenError: The essay belongs to a different teacher.
    """
    # Verify essay exists and is owned by this teacher.
    essay_result = await db.execute(
        select(Essay)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Essay.id == essay_id,
            Class.teacher_id == teacher_id,
        )
    )
    essay = essay_result.scalar_one_or_none()
    if essay is None:
        # Distinguish between not found vs. forbidden.
        exists_result = await db.execute(
            select(Essay.id).where(Essay.id == essay_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Essay not found.")
        raise ForbiddenError("You do not have access to this essay.")

    # Fetch the latest IntegrityReport for the latest version of this essay,
    # scoped to the teacher.  First resolve the highest-numbered EssayVersion
    # to avoid returning a report for an older version even if its report was
    # created more recently.
    version_result = await db.execute(
        select(EssayVersion.id)
        .where(EssayVersion.essay_id == essay_id)
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    latest_version_id = version_result.scalar_one_or_none()
    if latest_version_id is None:
        raise NotFoundError("No integrity report found for this essay.")

    report_result = await db.execute(
        select(IntegrityReport)
        .where(
            IntegrityReport.essay_version_id == latest_version_id,
            IntegrityReport.teacher_id == teacher_id,
        )
        .order_by(IntegrityReport.created_at.desc())
        .limit(1)
    )
    report = report_result.scalar_one_or_none()
    if report is None:
        raise NotFoundError("No integrity report found for this essay.")

    return IntegrityReportResponse(
        id=report.id,
        essay_id=essay.id,
        essay_version_id=report.essay_version_id,
        provider=report.provider,
        ai_likelihood=report.ai_likelihood,
        similarity_score=report.similarity_score,
        flagged_passages=report.flagged_passages or [],
        status=report.status,
        reviewed_at=report.reviewed_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def update_integrity_report_status(
    db: AsyncSession,
    report_id: uuid.UUID,
    teacher_id: uuid.UUID,
    status: IntegrityReportStatus,
) -> IntegrityReportResponse:
    """Update the teacher review status on an IntegrityReport.

    Only ``reviewed_clear`` and ``flagged`` are valid teacher-action statuses.
    Setting a report back to ``pending`` is not allowed.

    Args:
        db: Async database session.
        report_id: UUID of the IntegrityReport to update.
        teacher_id: The requesting teacher's UUID (tenant isolation).
        status: The new status — must be ``reviewed_clear`` or ``flagged``.

    Returns:
        Updated :class:`IntegrityReportResponse`.

    Raises:
        NotFoundError: The report does not exist.
        ForbiddenError: The report belongs to a different teacher.
        ValidationError: The requested status is not a valid teacher action.
    """
    allowed = {IntegrityReportStatus.reviewed_clear, IntegrityReportStatus.flagged}
    if status not in allowed:
        raise ValidationError(
            f"Status must be one of: {', '.join(s.value for s in allowed)}.",
            field="status",
        )

    # Load and authorise.
    report_result = await db.execute(
        select(IntegrityReport).where(IntegrityReport.id == report_id)
    )
    report = report_result.scalar_one_or_none()
    if report is None:
        raise NotFoundError("Integrity report not found.")
    if report.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this integrity report.")

    report.status = status
    report.reviewed_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(report)

    # Resolve essay_id via the report's essay version so the response includes it.
    version_result = await db.execute(
        select(EssayVersion.essay_id).where(EssayVersion.id == report.essay_version_id)
    )
    essay_id = version_result.scalar_one()

    logger.info(
        "Integrity report status updated",
        extra={"report_id": str(report_id), "status": status.value},
    )

    return IntegrityReportResponse(
        id=report.id,
        essay_id=essay_id,
        essay_version_id=report.essay_version_id,
        provider=report.provider,
        ai_likelihood=report.ai_likelihood,
        similarity_score=report.similarity_score,
        flagged_passages=report.flagged_passages or [],
        status=report.status,
        reviewed_at=report.reviewed_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def get_integrity_summary_for_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> IntegritySummaryResponse:
    """Return aggregate integrity signal counts for all essays in an assignment.

    Counts how many integrity reports are in each status (``flagged``,
    ``reviewed_clear``, ``pending``) so the teacher can see the class-level
    picture at a glance on the assignment overview page.

    The query is tenant-scoped: only reports for essays owned by *teacher_id*
    are included.

    Args:
        db: Async database session.
        assignment_id: UUID of the assignment to summarise.
        teacher_id: The requesting teacher's UUID (tenant isolation).

    Returns:
        A populated :class:`IntegritySummaryResponse`.

    Raises:
        NotFoundError: The assignment does not exist.
        ForbiddenError: The assignment belongs to a different teacher.
    """
    # Verify the assignment exists and is owned by this teacher.
    assignment_result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == assignment_id,
            Class.teacher_id == teacher_id,
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        exists_result = await db.execute(
            select(Assignment.id).where(Assignment.id == assignment_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Assignment not found.")
        raise ForbiddenError("You do not have access to this assignment.")

    # Count integrity report statuses per essay, using only the latest version of
    # each essay and the most-recently-created report for that version.  This
    # avoids double-counting essays that have been resubmitted (multiple
    # EssayVersions) or that have reports from multiple providers.

    # Step 1 — for each essay in the assignment, find the highest version_number.
    max_version_subq = (
        select(
            EssayVersion.essay_id,
            func.max(EssayVersion.version_number).label("max_version"),
        )
        .join(Essay, EssayVersion.essay_id == Essay.id)
        .where(Essay.assignment_id == assignment_id)
        .group_by(EssayVersion.essay_id)
        .subquery("max_versions")
    )

    # Step 2 — resolve (essay_id, max_version) → essay_version_id.
    latest_versions_subq = (
        select(EssayVersion.id.label("version_id"))
        .join(
            max_version_subq,
            (EssayVersion.essay_id == max_version_subq.c.essay_id)
            & (EssayVersion.version_number == max_version_subq.c.max_version),
        )
        .subquery("latest_versions")
    )

    # Step 3 — for each of those latest versions, find the max created_at report
    # (scoped to the requesting teacher), giving one report per essay.
    latest_report_subq = (
        select(
            IntegrityReport.essay_version_id,
            func.max(IntegrityReport.created_at).label("max_created_at"),
        )
        .where(
            IntegrityReport.essay_version_id.in_(
                select(latest_versions_subq.c.version_id)
            ),
            IntegrityReport.teacher_id == teacher_id,
        )
        .group_by(IntegrityReport.essay_version_id)
        .subquery("latest_reports")
    )

    # Step 4 — count those deduplicated reports by status.
    rows = await db.execute(
        select(IntegrityReport.status, func.count(IntegrityReport.id).label("cnt"))
        .join(
            latest_report_subq,
            (IntegrityReport.essay_version_id == latest_report_subq.c.essay_version_id)
            & (IntegrityReport.created_at == latest_report_subq.c.max_created_at),
        )
        .where(IntegrityReport.teacher_id == teacher_id)
        .group_by(IntegrityReport.status)
    )
    counts: dict[IntegrityReportStatus, int] = {row.status: row.cnt for row in rows}

    flagged = counts.get(IntegrityReportStatus.flagged, 0)
    reviewed_clear = counts.get(IntegrityReportStatus.reviewed_clear, 0)
    pending = counts.get(IntegrityReportStatus.pending, 0)

    return IntegritySummaryResponse(
        assignment_id=assignment_id,
        flagged=flagged,
        reviewed_clear=reviewed_clear,
        pending=pending,
        total=flagged + reviewed_clear + pending,
    )
