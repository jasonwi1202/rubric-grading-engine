"""Resubmission comparison service (M6-11).

Computes and persists a :class:`~app.models.revision_comparison.RevisionComparison`
record after a resubmitted essay version has been graded.

Responsibilities:
    - Compute criterion-level score deltas (revised minus base).
    - Detect low-effort revisions using text-similarity heuristics.
    - Optionally call the LLM to assess whether prior feedback was addressed.
    - Persist the :class:`RevisionComparison` row.
    - Expose a read function for the ``GET /essays/{id}/revision-comparison``
      endpoint.

Security invariants:
    - Essay content is NEVER logged at any level.
    - Only entity IDs appear in log output.
    - LLM call places the revised essay text in the user role only.
    - Tenant isolation is enforced in all public read functions.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.llm.client import call_revision_comparison
from app.models.assignment import Assignment
from app.models.class_ import Class
from app.models.essay import Essay, EssayVersion
from app.models.grade import CriterionScore, Grade
from app.models.revision_comparison import RevisionComparison

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Low-effort heuristics — thresholds
# ---------------------------------------------------------------------------

#: Jaccard similarity of word sets above this threshold → flagged as low-effort.
_SIMILARITY_THRESHOLD: float = 0.95

#: Word-count change smaller than this fraction of the base word count → flagged.
_WORD_COUNT_DELTA_FRACTION: float = 0.02

#: Absolute word-count change smaller than this value → flagged (guards against
#: very short essays where the fraction threshold alone is too loose).
_WORD_COUNT_DELTA_ABS: int = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity of the word bags of two texts.

    Jaccard similarity = |A ∩ B| / |A ∪ B| where A and B are the sets of
    (lowercased) words in each text.  Returns 1.0 when both texts are empty
    (they are trivially identical — no words in either set differ) or when
    they are identical in vocabulary.

    Args:
        text_a: First plain-text string.
        text_b: Second plain-text string.

    Returns:
        A float in [0.0, 1.0].  1.0 means identical word sets; 0.0 means
        completely disjoint sets.
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a and not words_b:
        return 1.0
    union = words_a | words_b
    intersection = words_a & words_b
    return len(intersection) / len(union)


def _detect_low_effort(
    base_content: str,
    revised_content: str,
    base_word_count: int,
    revised_word_count: int,
) -> tuple[bool, list[str]]:
    """Apply heuristics to determine whether a revision is low-effort.

    Heuristics (any one is sufficient to flag):
        1. Word-count change is negligible: absolute delta < ``_WORD_COUNT_DELTA_ABS``
           AND relative delta < ``_WORD_COUNT_DELTA_FRACTION`` of the base count.
        2. Word-set Jaccard similarity exceeds ``_SIMILARITY_THRESHOLD``.

    Args:
        base_content: Plain-text content of the base (previous) version.
        revised_content: Plain-text content of the revised version.
        base_word_count: Stored word count of the base version.
        revised_word_count: Stored word count of the revised version.

    Returns:
        A tuple ``(is_low_effort, reasons)`` where ``reasons`` is a list of
        human-readable strings (empty list when not flagged).
    """
    reasons: list[str] = []

    word_delta_abs = abs(revised_word_count - base_word_count)
    word_delta_frac = (
        word_delta_abs / base_word_count if base_word_count > 0 else 0.0
    )
    if word_delta_abs < _WORD_COUNT_DELTA_ABS and word_delta_frac < _WORD_COUNT_DELTA_FRACTION:
        reasons.append(
            f"Word count changed by only {word_delta_abs} words "
            f"({word_delta_frac * 100:.1f}% of the original)."
        )

    similarity = _jaccard_similarity(base_content, revised_content)
    if similarity >= _SIMILARITY_THRESHOLD:
        reasons.append(
            f"Text similarity is very high ({similarity * 100:.1f}%), "
            "suggesting minimal substantive changes."
        )

    return bool(reasons), reasons


def _build_feedback_items(
    criterion_scores: list[CriterionScore],
) -> list[dict[str, str]]:
    """Build the feedback items list for the revision LLM prompt.

    Filters out criterion scores with no ``ai_feedback`` (empty or None).

    Args:
        criterion_scores: CriterionScore ORM objects from the base grade.

    Returns:
        A list of ``{criterion_id, feedback}`` dicts ready for JSON encoding.
    """
    items = []
    for cs in criterion_scores:
        feedback = cs.ai_feedback or ""
        if feedback.strip():
            items.append(
                {
                    "criterion_id": str(cs.rubric_criterion_id),
                    "feedback": feedback.strip(),
                }
            )
    return items


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def compute_revision_comparison(
    db: AsyncSession,
    *,
    essay_id: uuid.UUID,
    base_version_id: uuid.UUID,
    revised_version_id: uuid.UUID,
    base_grade_id: uuid.UUID,
    revised_grade_id: uuid.UUID,
) -> RevisionComparison:
    """Compute and persist a RevisionComparison for a newly graded resubmission.

    This function is called from the grading service immediately after a
    resubmission (version > 1) has been graded.  It:

    1. Loads the base and revised EssayVersion objects.
    2. Loads the base and revised Grade + CriterionScore records.
    3. Computes total_score_delta and per-criterion score deltas.
    4. Applies low-effort heuristics.
    5. Calls the LLM (best-effort) to assess feedback-addressed status.
    6. Persists and returns the RevisionComparison row.

    The LLM step is best-effort: if it fails, ``feedback_addressed`` is stored
    as ``None`` and the rest of the comparison is still persisted.

    Args:
        db: Async database session (must already be within an active session).
        essay_id: UUID of the parent Essay.
        base_version_id: UUID of the previous EssayVersion.
        revised_version_id: UUID of the just-graded EssayVersion.
        base_grade_id: UUID of the Grade for the base version.
        revised_grade_id: UUID of the Grade for the revised version.

    Returns:
        The committed :class:`RevisionComparison` instance.

    Security notes:
        - No essay content is logged.
        - Only entity IDs appear in log output.
    """
    # ------------------------------------------------------------------
    # 1. Load essay versions.
    # ------------------------------------------------------------------
    ver_result = await db.execute(
        select(EssayVersion).where(
            EssayVersion.id.in_([base_version_id, revised_version_id])
        )
    )
    versions_by_id: dict[uuid.UUID, EssayVersion] = {
        v.id: v for v in ver_result.scalars().all()
    }
    base_version = versions_by_id.get(base_version_id)
    revised_version = versions_by_id.get(revised_version_id)

    if base_version is None or revised_version is None:
        logger.warning(
            "Could not load essay versions for revision comparison",
            extra={"essay_id": str(essay_id)},
        )
        raise NotFoundError("Essay version(s) not found for revision comparison.")

    # ------------------------------------------------------------------
    # 2. Load grades and criterion scores.
    # ------------------------------------------------------------------
    grades_result = await db.execute(
        select(Grade).where(Grade.id.in_([base_grade_id, revised_grade_id]))
    )
    grades_by_id: dict[uuid.UUID, Grade] = {
        g.id: g for g in grades_result.scalars().all()
    }
    base_grade = grades_by_id.get(base_grade_id)
    revised_grade = grades_by_id.get(revised_grade_id)

    if base_grade is None or revised_grade is None:
        logger.warning(
            "Could not load grades for revision comparison",
            extra={"essay_id": str(essay_id)},
        )
        raise NotFoundError("Grade(s) not found for revision comparison.")

    base_scores_result = await db.execute(
        select(CriterionScore).where(CriterionScore.grade_id == base_grade_id)
    )
    base_criterion_scores: list[CriterionScore] = base_scores_result.scalars().all()

    revised_scores_result = await db.execute(
        select(CriterionScore).where(CriterionScore.grade_id == revised_grade_id)
    )
    revised_criterion_scores: list[CriterionScore] = revised_scores_result.scalars().all()

    # ------------------------------------------------------------------
    # 3. Compute score deltas.
    # ------------------------------------------------------------------
    total_score_delta = float(
        Decimal(str(revised_grade.total_score)) - Decimal(str(base_grade.total_score))
    )

    # Build lookup for revised scores by criterion ID.
    revised_by_criterion: dict[uuid.UUID, CriterionScore] = {
        cs.rubric_criterion_id: cs for cs in revised_criterion_scores
    }

    criterion_deltas: list[dict[str, Any]] = []
    for base_cs in base_criterion_scores:
        revised_cs = revised_by_criterion.get(base_cs.rubric_criterion_id)
        if revised_cs is None:
            logger.warning(
                "Revised grade missing criterion score; using 0 for delta calculation",
                extra={
                    "essay_id": str(essay_id),
                    "criterion_id": str(base_cs.rubric_criterion_id),
                },
            )
        revised_score = revised_cs.final_score if revised_cs is not None else 0
        criterion_deltas.append(
            {
                "criterion_id": str(base_cs.rubric_criterion_id),
                "base_score": base_cs.final_score,
                "revised_score": revised_score,
                "delta": revised_score - base_cs.final_score,
            }
        )

    # ------------------------------------------------------------------
    # 4. Low-effort heuristics.
    # ------------------------------------------------------------------
    is_low_effort, low_effort_reasons = _detect_low_effort(
        base_content=base_version.content,
        revised_content=revised_version.content,
        base_word_count=base_version.word_count,
        revised_word_count=revised_version.word_count,
    )

    # ------------------------------------------------------------------
    # 5. LLM feedback-addressed detection (best-effort).
    # ------------------------------------------------------------------
    feedback_addressed: list[dict[str, Any]] | None = None
    feedback_items = _build_feedback_items(base_criterion_scores)

    if feedback_items:
        try:
            feedback_items_json = json.dumps(feedback_items)
            revision_response = await call_revision_comparison(
                feedback_items_json=feedback_items_json,
                revised_essay_text=revised_version.content,
            )
            # Build an O(1) lookup so the list comprehension below is O(N+M)
            # rather than the O(N*M) linear search that next(...) would produce.
            feedback_by_criterion_id: dict[str, str] = {
                item["criterion_id"]: item["feedback"] for item in feedback_items
            }
            feedback_addressed = [
                {
                    "criterion_id": assessment.criterion_id,
                    "feedback_given": feedback_by_criterion_id.get(assessment.criterion_id, ""),
                    "addressed": assessment.addressed,
                    "detail": assessment.detail,
                }
                for assessment in revision_response.criterion_assessments
            ]
            logger.info(
                "Revision feedback-addressed LLM analysis complete",
                extra={"essay_id": str(essay_id)},
            )
        except Exception as exc:
            # Best-effort: LLM failure must not prevent the comparison from
            # being stored.  feedback_addressed stays None.
            logger.warning(
                "Revision feedback-addressed LLM analysis failed; storing comparison without it",
                extra={"essay_id": str(essay_id), "error_type": type(exc).__name__},
            )
    else:
        logger.info(
            "No criterion feedback available for feedback-addressed analysis; skipping LLM call",
            extra={"essay_id": str(essay_id)},
        )

    # ------------------------------------------------------------------
    # 6. Persist the RevisionComparison row.
    # ------------------------------------------------------------------
    comparison = RevisionComparison(
        essay_id=essay_id,
        base_version_id=base_version_id,
        revised_version_id=revised_version_id,
        base_grade_id=base_grade_id,
        revised_grade_id=revised_grade_id,
        total_score_delta=total_score_delta,
        criterion_deltas=criterion_deltas,
        is_low_effort=is_low_effort,
        low_effort_reasons=low_effort_reasons,
        feedback_addressed=feedback_addressed,
    )
    db.add(comparison)
    await db.commit()
    await db.refresh(comparison)

    logger.info(
        "Revision comparison persisted",
        extra={
            "essay_id": str(essay_id),
            "comparison_id": str(comparison.id),
            "is_low_effort": is_low_effort,
        },
    )
    return comparison


async def get_revision_comparison(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> RevisionComparison:
    """Load the most recent RevisionComparison for an essay.

    Enforces tenant isolation via an Assignment → Class → teacher_id JOIN.

    Args:
        db: Async database session.
        essay_id: UUID of the essay whose comparison to retrieve.
        teacher_id: UUID of the authenticated teacher (tenant scope).

    Returns:
        The most recently created :class:`RevisionComparison` for the essay.

    Raises:
        NotFoundError: Essay does not exist or has no revision comparison.
        ForbiddenError: Essay belongs to a different teacher.
    """
    # Verify essay existence and tenant ownership.
    essay_result = await db.execute(
        select(Essay)
        .join(Assignment, Essay.assignment_id == Assignment.id)
        .join(Class, Assignment.class_id == Class.id)
        .where(Essay.id == essay_id, Class.teacher_id == teacher_id)
    )
    essay = essay_result.scalar_one_or_none()
    if essay is None:
        exists_result = await db.execute(select(Essay.id).where(Essay.id == essay_id))
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Essay not found.")
        raise ForbiddenError("You do not have access to this essay.")

    # Load the most recent comparison.
    comparison_result = await db.execute(
        select(RevisionComparison)
        .where(RevisionComparison.essay_id == essay_id)
        .order_by(RevisionComparison.created_at.desc())
        .limit(1)
    )
    comparison = comparison_result.scalar_one_or_none()
    if comparison is None:
        raise NotFoundError("No revision comparison found for this essay.")

    return comparison
