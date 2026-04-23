"""Integrity provider abstraction for academic-integrity checks (M4.5).

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

Security invariants:
- No essay content is logged at any level.
- Only entity IDs appear in log output (no student PII).
- ``teacher_id`` is always included in DB queries (tenant isolation).
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.exceptions import ForbiddenError, NotFoundError
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus

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
        # Verify essay version exists and is owned by the requesting teacher
        # before spending an API credit (tenant isolation).
        ownership_result = await db.execute(
            select(EssayVersion.id)
            .join(Essay, EssayVersion.essay_id == Essay.id)
            .join(Assignment, Essay.assignment_id == Assignment.id)
            .join(Class, Assignment.class_id == Class.id)
            .where(EssayVersion.id == essay_version_id, Class.teacher_id == teacher_id)
        )
        if ownership_result.scalar_one_or_none() is None:
            exists_result = await db.execute(
                select(EssayVersion.id).where(EssayVersion.id == essay_version_id)
            )
            if exists_result.scalar_one_or_none() is None:
                raise NotFoundError("EssayVersion not found.")
            raise ForbiddenError("You do not have access to this essay version.")

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
                data: dict[str, Any] = response.json()

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

        # Write the IntegrityReport for this provider.
        # Convert empty list to None so the JSONB column stores NULL rather than [].
        report = IntegrityReport(
            essay_version_id=essay_version_id,
            teacher_id=teacher_id,
            provider="originality_ai",
            ai_likelihood=ai_likelihood,
            similarity_score=similarity_score,
            flagged_passages=flagged_passages if flagged_passages else None,
            status=IntegrityReportStatus.pending,
        )
        db.add(report)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise

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
