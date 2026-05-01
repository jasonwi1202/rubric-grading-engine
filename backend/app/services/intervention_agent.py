"""Intervention agent service (M7-01).

Proactively scans teacher-scoped student profiles on a schedule, detects
persistent gaps, regressions, and non-response patterns, and creates
:class:`~app.models.intervention_recommendation.InterventionRecommendation`
records for the teacher to review.

Public API:
  - ``scan_teacher_for_interventions``   — scan one teacher's profiles and
                                           insert new recommendations.
  - ``list_interventions``               — return recommendations for a teacher
                                           (optionally filtered by status).
  - ``approve_intervention``             — teacher approves; status → 'approved'
                                           + audit log.
  - ``dismiss_intervention``             — teacher dismisses; status → 'dismissed'
                                           + audit log.

Signal detection:
  Three trigger types are detected, reusing the same thresholds as the
  worklist service (M6-04) to keep signal semantics consistent:

  1. **regression**     — A skill dimension is trending downward
                          (``trend == 'declining'``).  Urgency 4.
  2. **persistent_gap** — A skill dimension is chronically below 0.60 across
                          ≥ 2 assignments with a non-improving trend.  Urgency 3.
  3. **non_responder**  — Detected when a student skill profile shows evidence
                          of stagnation (avg_score < 0.60 + stable trend +
                          assignment_count ≥ 3 and data_points ≥ 3 without
                          improvement).  Urgency 4.
                          Note: the full non-responder check (based on actual
                          resubmission deltas) lives in the worklist service and
                          requires per-assignment score sequences.  The
                          intervention agent uses a profile-level proxy: a skill
                          that is persistently below threshold with a stable
                          trend and many data points signals a student who has
                          received repeated feedback but has not improved.

Idempotency:
  Before inserting a recommendation, the service checks whether a
  'pending_review' record already exists for the same
  (teacher_id, student_id, trigger_type, skill_key) tuple.  If one exists,
  the new scan is skipped for that signal so that rescheduled runs do not
  accumulate duplicate pending items.

Tenant isolation:
  Every function accepts ``teacher_id`` and includes it in every query.  No
  cross-teacher data is ever loaded or written.

FERPA:
  No student PII (names, essay content, raw scores) is written to log
  statements.  Only entity IDs (``teacher_id``, ``student_id``,
  ``recommendation_id``) appear in log lines.

Audit log:
  - ``intervention_recommendation.created`` — emitted for each new
    recommendation inserted by the scan.
  - ``intervention_recommendation.approved`` — emitted when the teacher approves.
  - ``intervention_recommendation.dismissed`` — emitted when the teacher dismisses.
  All audit entries use entity IDs only — no student PII.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models.audit_log import AuditLog
from app.models.intervention_recommendation import InterventionRecommendation
from app.models.student_skill_profile import StudentSkillProfile
from app.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal thresholds (mirrors worklist service — keep in sync)
# ---------------------------------------------------------------------------

#: Normalised avg_score below which a skill is considered underperforming.
_GAP_SCORE_THRESHOLD: float = 0.60

#: Minimum number of locked assignments before a persistent_gap or
#: non_responder signal is eligible.
_GAP_MIN_ASSIGNMENTS: int = 2

#: Minimum number of per-skill data_points before a non_responder proxy fires.
_NON_RESPONDER_MIN_DATA_POINTS: int = 3

#: Urgency values (must match worklist service).
_URGENCY_REGRESSION: int = 4
_URGENCY_NON_RESPONDER: int = 4
_URGENCY_PERSISTENT_GAP: int = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rowcount(result: Any) -> int:
    """Return the rowcount from a SQLAlchemy CursorResult returned by an UPDATE."""
    return cast("CursorResult[Any]", result).rowcount


def _trigger_reason(trigger_type: str, skill_key: str | None, details: dict[str, Any]) -> str:
    """Build a short human-readable trigger reason sentence."""
    skill_label = skill_key.replace("_", " ") if skill_key else ""
    avg = details.get("avg_score")
    avg_str = f"{avg:.0%}" if isinstance(avg, float) else "below threshold"
    match trigger_type:
        case "regression":
            return (
                f"Skill '{skill_label}' is trending downward "
                f"(current average: {avg_str})."
            )
        case "persistent_gap":
            count = details.get("assignment_count", 0)
            return (
                f"Skill '{skill_label}' has been below {int(_GAP_SCORE_THRESHOLD * 100)}% "
                f"across {count} assignment(s) with no improving trend."
            )
        case "non_responder":
            count = details.get("data_points", 0)
            return (
                f"Student's '{skill_label}' skill has remained below threshold "
                f"across {count} scoring event(s) despite ongoing feedback."
            )
        case _:
            return "A student signal was detected that requires teacher attention."


def _evidence_summary(trigger_type: str, skill_key: str | None, details: dict[str, Any]) -> str:
    """Build a detailed evidence description for the teacher."""
    avg = details.get("avg_score")
    trend = details.get("trend", "unknown")
    avg_str = f"{avg:.0%}" if isinstance(avg, float) else "N/A"
    match trigger_type:
        case "regression":
            return (
                f"Average normalised score for '{skill_key}': {avg_str}. "
                f"Trend: {trend}. "
                "The most recent assignments scored lower than earlier ones."
            )
        case "persistent_gap":
            count = details.get("assignment_count", 0)
            return (
                f"Average normalised score for '{skill_key}': {avg_str}. "
                f"Trend: {trend}. "
                f"Below {int(_GAP_SCORE_THRESHOLD * 100)}% threshold across {count} assignment(s)."
            )
        case "non_responder":
            data_pts = details.get("data_points", 0)
            return (
                f"Average normalised score for '{skill_key}': {avg_str}. "
                f"Trend: {trend}. "
                f"Score has remained stagnant across {data_pts} scoring event(s)."
            )
        case _:
            return "See student skill profile for details."


def _suggested_action(trigger_type: str, skill_key: str | None) -> str:
    """Return a concrete, teacher-actionable suggestion for a trigger type."""
    skill_label = skill_key.replace("_", " ") if skill_key else "the identified skill"
    match trigger_type:
        case "regression":
            return (
                f"Review the recent decline in {skill_label} with this student "
                f"and identify what changed."
            )
        case "persistent_gap":
            return f"Assign a targeted practice exercise focused on {skill_label}."
        case "non_responder":
            return (
                "Schedule a 1:1 check-in to understand why written feedback "
                "has not translated to improvement."
            )
        case _:
            return "Follow up with this student."


def _detect_signals(
    profile: StudentSkillProfile,
) -> list[dict[str, Any]]:
    """Detect intervention signals from a student skill profile.

    Returns a list of signal dicts with keys:
      ``trigger_type``, ``skill_key``, ``urgency``, ``details``.

    Implements three trigger types using profile-level data only:

    1. **regression** — skill trend == 'declining'.
    2. **persistent_gap** — avg_score < threshold, assignment_count ≥ minimum,
       trend not improving.
    3. **non_responder** — avg_score < threshold, trend == 'stable',
       data_points ≥ minimum (proxy: no improvement despite many assessments).
    """
    signals: list[dict[str, Any]] = []
    skill_scores: dict[str, Any] = profile.skill_scores or {}
    assignment_count: int = profile.assignment_count or 0

    for skill_key, entry in sorted(skill_scores.items()):
        if not isinstance(entry, dict):
            continue
        avg_score = entry.get("avg_score")
        trend = entry.get("trend", "stable")
        data_points = entry.get("data_points", 0)
        if not isinstance(avg_score, (int, float)):
            continue
        avg_score = float(avg_score)

        # --- regression ---
        if trend == "declining":
            signals.append(
                {
                    "trigger_type": "regression",
                    "skill_key": skill_key,
                    "urgency": _URGENCY_REGRESSION,
                    "details": {
                        "avg_score": avg_score,
                        "trend": trend,
                        "assignment_count": assignment_count,
                    },
                }
            )

        # --- persistent_gap ---
        if (
            avg_score < _GAP_SCORE_THRESHOLD
            and assignment_count >= _GAP_MIN_ASSIGNMENTS
            and trend != "improving"
            and trend != "declining"  # declining already captured above
        ):
            signals.append(
                {
                    "trigger_type": "persistent_gap",
                    "skill_key": skill_key,
                    "urgency": _URGENCY_PERSISTENT_GAP,
                    "details": {
                        "avg_score": avg_score,
                        "trend": trend,
                        "assignment_count": assignment_count,
                    },
                }
            )

        # --- non_responder proxy ---
        if (
            avg_score < _GAP_SCORE_THRESHOLD
            and trend == "stable"
            and data_points >= _NON_RESPONDER_MIN_DATA_POINTS
            and assignment_count >= _GAP_MIN_ASSIGNMENTS
        ):
            signals.append(
                {
                    "trigger_type": "non_responder",
                    "skill_key": skill_key,
                    "urgency": _URGENCY_NON_RESPONDER,
                    "details": {
                        "avg_score": avg_score,
                        "trend": trend,
                        "data_points": data_points,
                        "assignment_count": assignment_count,
                    },
                }
            )

    return signals


async def _pending_signal_keys(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_id: uuid.UUID,
) -> set[tuple[str, str | None]]:
    """Return (trigger_type, skill_key) pairs that already have a pending review.

    Used to skip signals that are already waiting for the teacher's attention
    so that scheduled runs don't accumulate duplicate recommendations.
    """
    rows = await db.execute(
        select(
            InterventionRecommendation.trigger_type,
            InterventionRecommendation.skill_key,
        ).where(
            InterventionRecommendation.teacher_id == teacher_id,
            InterventionRecommendation.student_id == student_id,
            InterventionRecommendation.status == "pending_review",
        )
    )
    return {(r.trigger_type, r.skill_key) for r in rows}


async def _write_audit_log(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    entity_id: uuid.UUID,
    action: str,
    before_value: dict[str, object] | None = None,
    after_value: dict[str, object] | None = None,
) -> None:
    """Insert an audit log row for an intervention recommendation event."""
    db.add(
        AuditLog(
            teacher_id=teacher_id,
            entity_type="intervention_recommendation",
            entity_id=entity_id,
            action=action,
            before_value=before_value,
            after_value=after_value,
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def scan_teacher_for_interventions(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[InterventionRecommendation]:
    """Scan one teacher's student skill profiles and create new recommendations.

    For each student profile owned by *teacher_id*, detects regression,
    persistent_gap, and non_responder signals.  Skips any (student,
    trigger_type, skill_key) combination that already has a 'pending_review'
    recommendation (idempotency guard).  Inserts a new
    :class:`~app.models.intervention_recommendation.InterventionRecommendation`
    row and a corresponding audit log entry for each new signal.

    Tenant isolation: the query for profiles is filtered by ``teacher_id`` so
    no cross-teacher data is ever loaded.

    FERPA: only entity IDs appear in log lines.

    Args:
        db: Active ``AsyncSession`` with the RLS tenant context already set.
        teacher_id: UUID of the teacher whose students are being scanned.

    Returns:
        List of newly inserted :class:`InterventionRecommendation` rows.
    """
    # Load all skill profiles for this teacher.
    profile_rows = await db.execute(
        select(StudentSkillProfile).where(
            StudentSkillProfile.teacher_id == teacher_id,
        )
    )
    profiles = list(profile_rows.scalars())

    created: list[InterventionRecommendation] = []

    for profile in profiles:
        signals = _detect_signals(profile)
        if not signals:
            continue

        # Load pending signal keys once per student to avoid N+1 queries inside
        # the signal loop.
        pending_keys = await _pending_signal_keys(db, teacher_id, profile.student_id)

        for signal in signals:
            trigger_type: str = signal["trigger_type"]
            skill_key: str | None = signal["skill_key"]
            urgency: int = signal["urgency"]
            details: dict[str, Any] = signal["details"]

            # Skip if already pending for this (student, trigger, skill).
            if (trigger_type, skill_key) in pending_keys:
                continue

            reason = _trigger_reason(trigger_type, skill_key, details)
            evidence = _evidence_summary(trigger_type, skill_key, details)
            action = _suggested_action(trigger_type, skill_key)

            rec = InterventionRecommendation(
                id=uuid.uuid4(),
                teacher_id=teacher_id,
                student_id=profile.student_id,
                trigger_type=trigger_type,
                skill_key=skill_key,
                urgency=urgency,
                trigger_reason=reason,
                evidence_summary=evidence,
                suggested_action=action,
                details=details,
                status="pending_review",
            )
            db.add(rec)
            # Flush so the row has an ID before we audit-log it.
            await db.flush()

            await _write_audit_log(
                db=db,
                teacher_id=teacher_id,
                entity_id=rec.id,
                action="intervention_recommendation.created",
                after_value={
                    "student_id": str(profile.student_id),
                    "trigger_type": trigger_type,
                    "skill_key": skill_key,
                    "urgency": urgency,
                    "status": "pending_review",
                },
            )

            created.append(rec)
            # Add to pending_keys so subsequent signals in the same scan for
            # the same student don't duplicate (matches the DB after flush).
            pending_keys.add((trigger_type, skill_key))

            logger.info(
                "Intervention recommendation created",
                extra={
                    "teacher_id": str(teacher_id),
                    "student_id": str(profile.student_id),
                    "recommendation_id": str(rec.id),
                    "trigger_type": trigger_type,
                },
            )

    if created:
        await db.commit()
        for rec in created:
            await db.refresh(rec)
    return created


async def list_interventions(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    status: str | None = None,
) -> list[InterventionRecommendation]:
    """Return intervention recommendations for *teacher_id*.

    Args:
        db:         Active ``AsyncSession`` with RLS tenant context set.
        teacher_id: UUID of the authenticated teacher.
        status:     Optional lifecycle filter.  When ``None``, returns only
                    'pending_review' items.  Pass ``"all"`` to include
                    approved and dismissed items as well.

    Returns:
        List of :class:`InterventionRecommendation` rows, most urgent first,
        then newest-first within the same urgency.
    """
    q = select(InterventionRecommendation).where(
        InterventionRecommendation.teacher_id == teacher_id,
    )
    if status != "all":
        filter_status = status if status in {"approved", "dismissed"} else "pending_review"
        q = q.where(InterventionRecommendation.status == filter_status)

    q = q.order_by(
        InterventionRecommendation.urgency.desc(),
        InterventionRecommendation.created_at.desc(),
    )
    rows = await db.execute(q)
    return list(rows.scalars())


async def approve_intervention(
    db: AsyncSession,
    rec_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> InterventionRecommendation:
    """Teacher approves an intervention recommendation.

    Transitions the recommendation from 'pending_review' (or idempotently from
    'approved') to 'approved'.  Sets ``actioned_at`` and writes an audit log
    entry.

    Tenant isolation: the UPDATE is scoped to ``teacher_id`` so a cross-teacher
    ID is treated the same as a missing ID (returns 404 rather than 403 —
    matching the RLS pattern used by the worklist service to avoid leaking
    whether another teacher's resource exists).

    Raises:
        NotFoundError:  Recommendation not found or belongs to another teacher.
        ConflictError:  Recommendation is already dismissed.
    """
    # Load the recommendation (tenant-scoped via teacher_id).
    result = await db.execute(
        select(InterventionRecommendation).where(
            InterventionRecommendation.id == rec_id,
            InterventionRecommendation.teacher_id == teacher_id,
        )
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Intervention recommendation not found.")

    if rec.status == "dismissed":
        raise ConflictError("Cannot approve a dismissed recommendation.")

    if rec.status == "approved":
        # Idempotent: already approved.
        return rec

    before = {"status": rec.status}
    now = datetime.now(UTC)
    update_result = await db.execute(
        update(InterventionRecommendation)
        .where(
            InterventionRecommendation.id == rec_id,
            InterventionRecommendation.teacher_id == teacher_id,
            InterventionRecommendation.status == "pending_review",
        )
        .values(status="approved", actioned_at=now)
    )
    if _rowcount(update_result) == 0:
        # Race: another request already approved or dismissed.
        await db.refresh(rec)
        if rec.status == "dismissed":
            raise ConflictError("Cannot approve a dismissed recommendation.")
        # Already approved by concurrent request — idempotent.
        return rec

    await _write_audit_log(
        db=db,
        teacher_id=teacher_id,
        entity_id=rec_id,
        action="intervention_recommendation.approved",
        before_value=before,
        after_value={"status": "approved", "actioned_at": now.isoformat()},
    )
    await db.commit()
    await db.refresh(rec)

    logger.info(
        "Intervention recommendation approved",
        extra={
            "teacher_id": str(teacher_id),
            "recommendation_id": str(rec_id),
        },
    )
    return rec


async def dismiss_intervention(
    db: AsyncSession,
    rec_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> InterventionRecommendation:
    """Teacher dismisses an intervention recommendation.

    Transitions the recommendation from 'pending_review' (or idempotently from
    'dismissed') to 'dismissed'.  Sets ``actioned_at`` and writes an audit log
    entry.

    Tenant isolation: same RLS pattern as ``approve_intervention`` — cross-
    teacher IDs return 404, not 403.

    Raises:
        NotFoundError:  Recommendation not found or belongs to another teacher.
        ConflictError:  Recommendation is already approved.
    """
    result = await db.execute(
        select(InterventionRecommendation).where(
            InterventionRecommendation.id == rec_id,
            InterventionRecommendation.teacher_id == teacher_id,
        )
    )
    rec = result.scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Intervention recommendation not found.")

    if rec.status == "approved":
        raise ConflictError("Cannot dismiss an already-approved recommendation.")

    if rec.status == "dismissed":
        # Idempotent: already dismissed.
        return rec

    before = {"status": rec.status}
    now = datetime.now(UTC)
    update_result = await db.execute(
        update(InterventionRecommendation)
        .where(
            InterventionRecommendation.id == rec_id,
            InterventionRecommendation.teacher_id == teacher_id,
            InterventionRecommendation.status == "pending_review",
        )
        .values(status="dismissed", actioned_at=now)
    )
    if _rowcount(update_result) == 0:
        await db.refresh(rec)
        if rec.status == "approved":
            raise ConflictError("Cannot dismiss an already-approved recommendation.")
        return rec

    await _write_audit_log(
        db=db,
        teacher_id=teacher_id,
        entity_id=rec_id,
        action="intervention_recommendation.dismissed",
        before_value=before,
        after_value={"status": "dismissed", "actioned_at": now.isoformat()},
    )
    await db.commit()
    await db.refresh(rec)

    logger.info(
        "Intervention recommendation dismissed",
        extra={
            "teacher_id": str(teacher_id),
            "recommendation_id": str(rec_id),
        },
    )
    return rec


async def get_all_teacher_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Return all teacher UUIDs from the users table.

    This is an unscoped query (no tenant context required) because the
    ``users`` table does not have RLS enabled — it is not a tenant-scoped
    table.  Used by the scheduled scan task to iterate over all teachers.
    """
    rows = await db.execute(select(User.id).where(User.role == "teacher"))
    return list(rows.scalars())
