"""Grading service.

Core AI grading pipeline for a single essay:

0. Validate ``strictness`` — raise ``ValidationError`` if invalid
1. Load the Essay and verify tenant ownership (teacher_id)
2. Load the latest EssayVersion (the text to grade)
3. Load the Assignment and read the immutable ``rubric_snapshot``
4. Extract ``CriterionInfo`` objects from the snapshot
5. Update essay status → ``grading`` and commit (externally visible)
6. Call the LLM via :func:`app.llm.client.call_grading`
7. Write :class:`Grade` and :class:`CriterionScore` records
8. Log ``score_clamped`` audit entries for any clamped scores
9. Update essay status → ``graded`` and commit

Security invariants:
- Essay content is NEVER logged at any level.
- Only entity IDs appear in log output (no student PII).
- Grading always reads ``assignment.rubric_snapshot`` — the live rubric
  rows are never queried during grading.
- LLM response is validated before any database write.
- Scores are clamped server-side and the anomaly is audit-logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.llm.client import CriterionInfo, call_grading
from app.models.assignment import Assignment
from app.models.audit_log import AuditLog
from app.models.class_ import Class
from app.models.essay import Essay, EssayStatus, EssayVersion
from app.models.grade import ConfidenceLevel, CriterionScore, Grade, StrictnessLevel

logger = logging.getLogger(__name__)


async def grade_essay(
    db: AsyncSession,
    essay_id: uuid.UUID,
    teacher_id: uuid.UUID,
    strictness: str,
) -> Grade:
    """Grade the latest version of an essay against the assignment's rubric snapshot.

    Loads the Essay (scoped to *teacher_id*), fetches the latest
    :class:`EssayVersion`, reads the assignment's immutable
    ``rubric_snapshot``, calls the LLM, writes :class:`Grade` and
    :class:`CriterionScore` records, logs ``score_clamped`` audit entries for
    any clamped scores, and updates the essay status to ``graded``.

    Args:
        db: Async database session.
        essay_id: UUID of the :class:`Essay` to grade.
        teacher_id: UUID of the owning teacher (enforces tenant isolation).
        strictness: Grading strictness — one of ``"lenient"``,
            ``"balanced"``, ``"strict"``.

    Returns:
        The newly created and committed :class:`Grade` record.

    Raises:
        NotFoundError: Essay, essay version, or assignment not found.
        ForbiddenError: Essay belongs to a different teacher.
        ValidationError: ``strictness`` is not a recognised value.
        LLMError: LLM call failed after all retries.
        LLMParseError: LLM response could not be parsed after retries.
    """
    # ------------------------------------------------------------------
    # 0. Validate strictness early — raise a structured domain error
    #    rather than letting StrictnessLevel(strictness) raise a bare
    #    ValueError that would surface as an unhandled 500.
    # ------------------------------------------------------------------
    try:
        strictness_level = StrictnessLevel(strictness)
    except ValueError as exc:
        valid = ", ".join(f'"{v.value}"' for v in StrictnessLevel)
        raise ValidationError(
            f"Invalid strictness value: {strictness!r}. Must be one of: {valid}",
            field="strictness",
        ) from exc

    # ------------------------------------------------------------------
    # 1. Load Essay — single tenant-scoped query.
    # ------------------------------------------------------------------
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
        # Distinguish 404 (essay doesn't exist) from 403 (wrong teacher).
        exists_result = await db.execute(select(Essay.id).where(Essay.id == essay_id))
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Essay not found.")
        raise ForbiddenError("You do not have access to this essay.")

    # ------------------------------------------------------------------
    # 2. Load the latest EssayVersion.
    # ------------------------------------------------------------------
    version_result = await db.execute(
        select(EssayVersion)
        .where(EssayVersion.essay_id == essay_id)
        .order_by(EssayVersion.version_number.desc())
        .limit(1)
    )
    essay_version = version_result.scalar_one_or_none()
    if essay_version is None:
        raise NotFoundError("No essay version found for this essay.")

    # ------------------------------------------------------------------
    # 3. Load the Assignment — tenant-scoped via Class join.
    # ------------------------------------------------------------------
    assignment_result = await db.execute(
        select(Assignment)
        .join(Class, Assignment.class_id == Class.id)
        .where(
            Assignment.id == essay.assignment_id,
            Class.teacher_id == teacher_id,
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        raise NotFoundError("Assignment not found.")

    # ------------------------------------------------------------------
    # 4. Extract criteria from the immutable rubric snapshot.
    #    Grading NEVER reads the live rubric or rubric_criteria rows.
    #    cast() narrows the JSONB column (typed as dict[str, object]) to
    #    dict[str, Any] so downstream attribute access is type-safe.
    # ------------------------------------------------------------------
    snapshot = cast(dict[str, Any], assignment.rubric_snapshot)
    criteria_data = cast(list[dict[str, Any]], snapshot.get("criteria", []))

    criteria: list[CriterionInfo] = [
        CriterionInfo(
            criterion_id=str(c["id"]),
            min_score=int(str(c["min_score"])),
            max_score=int(str(c["max_score"])),
        )
        for c in criteria_data
    ]

    rubric_json: str = json.dumps(snapshot)

    # ------------------------------------------------------------------
    # 5. Update essay status → grading and persist it before the LLM
    #    call so other transactions can observe the in-progress state
    #    and duplicate enqueues can be detected early.
    # ------------------------------------------------------------------
    essay.status = EssayStatus.grading
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("Could not update essay grading status.") from exc

    # ------------------------------------------------------------------
    # 6. Call the LLM.
    #    Essay text is passed as a positional argument to call_grading,
    #    which places it in the user role — NEVER in the system prompt.
    # ------------------------------------------------------------------
    prompt_version = settings.grading_prompt_version
    grading_response = await call_grading(
        rubric_json=rubric_json,
        strictness=strictness,
        essay_text=essay_version.content,
        criteria=criteria,
        prompt_version=prompt_version,
    )

    # ------------------------------------------------------------------
    # 7. Compute aggregate scores.
    #    Criteria with score=None (missing criterion) contribute 0 to
    #    total_score, consistent with ai_score=0 written for those rows.
    # ------------------------------------------------------------------
    total_score = Decimal(
        sum(cs.score if cs.score is not None else 0 for cs in grading_response.criterion_scores)
    )
    max_possible_score = Decimal(sum(int(str(c["max_score"])) for c in criteria_data))

    # ------------------------------------------------------------------
    # 8. Write Grade record.
    # ------------------------------------------------------------------
    grade = Grade(
        essay_version_id=essay_version.id,
        total_score=total_score,
        max_possible_score=max_possible_score,
        summary_feedback=grading_response.summary_feedback,
        strictness=strictness_level,
        ai_model=settings.openai_grading_model,
        prompt_version=f"grading-{prompt_version}",
        is_locked=False,
    )
    db.add(grade)
    await db.flush()  # Populate grade.id before writing criterion scores.

    # ------------------------------------------------------------------
    # 9. Write CriterionScore records; audit-log score_clamped events.
    # ------------------------------------------------------------------
    for cs in grading_response.criterion_scores:
        ai_score = cs.score if cs.score is not None else 0
        criterion_uuid = uuid.UUID(cs.criterion_id)
        # Generate the CriterionScore PK client-side before construction so
        # it can be used as entity_id in the audit log entry at the same time —
        # SQLAlchemy's column default is applied during flush, not at object
        # creation, so we cannot rely on criterion_score.id being populated
        # until after the session is flushed.
        criterion_score_id = uuid.uuid4()

        criterion_score = CriterionScore(
            id=criterion_score_id,
            grade_id=grade.id,
            rubric_criterion_id=criterion_uuid,
            ai_score=ai_score,
            teacher_score=None,
            final_score=ai_score,
            ai_justification=cs.justification,
            confidence=ConfidenceLevel(cs.confidence),
        )
        db.add(criterion_score)

        if cs.score_clamped:
            # Log the clamping event to the audit log.
            # teacher_id is None — this is a system-generated event.
            # entity_id points at the CriterionScore row so audit queries
            # can reliably join back to the exact score record.
            # raw_score may be None when the LLM returned an unparseable
            # value (e.g. a string that wasn't numeric); the JSONB column
            # accepts null, and the absence of raw_score is itself
            # informative.
            audit_entry = AuditLog(
                teacher_id=None,
                entity_type="criterion_score",
                entity_id=criterion_score_id,
                action="score_clamped",
                before_value={
                    "criterion_id": cs.criterion_id,
                    "raw_score": cs.raw_score,
                },
                after_value={
                    "criterion_id": cs.criterion_id,
                    "clamped_score": ai_score,
                },
            )
            db.add(audit_entry)

    # ------------------------------------------------------------------
    # 10. Update essay status → graded and commit.
    #     IntegrityError on commit means the essay version was already
    #     graded (unique constraint on Grade.essay_version_id) — surface
    #     as ConflictError so the task/caller gets a recoverable failure
    #     instead of a generic 500.
    # ------------------------------------------------------------------
    essay.status = EssayStatus.graded
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("This essay version has already been graded.") from exc
    await db.refresh(grade)

    logger.info(
        "Essay graded successfully",
        extra={"essay_id": str(essay_id), "grade_id": str(grade.id)},
    )
    return grade
