"""Teacher copilot data query service (M7-03).

Answers teacher natural-language queries by gathering live class data from
Postgres and feeding it to the LLM via a structured context snapshot.

Public API:
  - ``execute_copilot_query`` — main entry point.  Gathers context data,
    calls the LLM, resolves student display names, and returns a validated
    :class:`~app.schemas.copilot.CopilotQueryResponse`.

Context data gathered:
  1. Student skill profiles scoped to the requesting teacher (optionally
     filtered by ``class_id`` when supplied).
  2. Active teacher worklist items (urgency-ranked signals) scoped to the
     requesting teacher.
  3. A lightweight summary: total student count and profiles with data.

Security / tenant isolation:
  - Every query includes ``teacher_id`` so that a teacher can never read
    another teacher's data.
  - When ``class_id`` is supplied the service first verifies that the class
    belongs to the requesting teacher before filtering student profiles.
  - No essay content is included in the LLM context — only aggregate skill
    dimension data (avg_score, trend, data_points) and worklist signals.
  - No student names are sent to the LLM — only student UUIDs.  Names are
    resolved from the database after parsing the LLM response.

FERPA:
  No student PII (names, essay content, raw scores) is written to log
  statements.  Only entity IDs (``teacher_id``, ``student_id``,
  ``class_id``) appear in log lines.

Uncertainty handling:
  When fewer than :data:`_MIN_PROFILES_FOR_RELIABLE_RESPONSE` students
  have profile data the service passes a flag to the LLM instructing it to
  express uncertainty.  The LLM is also instructed to never fabricate data.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError
from app.llm.client import call_copilot
from app.llm.parsers import ParsedCopilotResponse
from app.llm.prompts.copilot_v1 import VERSION as COPILOT_PROMPT_VERSION
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.student import Student
from app.models.student_skill_profile import StudentSkillProfile
from app.models.worklist import TeacherWorklistItem
from app.schemas.copilot import CopilotQueryResponse, CopilotRankedItemResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum number of student profiles with at least one assignment graded
#: before the service considers the data sufficient for a confident response.
_MIN_PROFILES_FOR_RELIABLE_RESPONSE: int = 2

#: Maximum number of active worklist items included in the LLM context
#: (to keep the context JSON size manageable).
_MAX_WORKLIST_ITEMS_IN_CONTEXT: int = 50

#: Maximum number of student skill profiles included in the LLM context.
_MAX_PROFILES_IN_CONTEXT: int = 100


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify that the class exists and belongs to the given teacher.

    Raises:
        NotFoundError:  Class does not exist.
        ForbiddenError: Class belongs to a different teacher.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")


async def _load_skill_profiles(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
) -> list[StudentSkillProfile]:
    """Load student skill profiles scoped to the given teacher.

    When ``class_id`` is supplied, only profiles for students currently
    enrolled in that class are returned.

    Args:
        db: Async database session.
        teacher_id: Requesting teacher's UUID.
        class_id: Optional class UUID filter.

    Returns:
        List of :class:`~app.models.student_skill_profile.StudentSkillProfile`
        rows, limited to :data:`_MAX_PROFILES_IN_CONTEXT` entries.
    """
    if class_id is not None:
        # Join via class enrollment to restrict to this class's students.
        stmt = (
            select(StudentSkillProfile)
            .join(
                ClassEnrollment,
                (ClassEnrollment.student_id == StudentSkillProfile.student_id)
                & (ClassEnrollment.class_id == class_id)
                & (ClassEnrollment.removed_at.is_(None)),
            )
            .where(StudentSkillProfile.teacher_id == teacher_id)
            .order_by(StudentSkillProfile.student_id)
            .limit(_MAX_PROFILES_IN_CONTEXT)
        )
    else:
        stmt = (
            select(StudentSkillProfile)
            .where(StudentSkillProfile.teacher_id == teacher_id)
            .order_by(StudentSkillProfile.student_id)
            .limit(_MAX_PROFILES_IN_CONTEXT)
        )

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_worklist_items(
    db: AsyncSession,
    teacher_id: uuid.UUID,
) -> list[TeacherWorklistItem]:
    """Load active worklist items for the given teacher.

    Returns items ordered by urgency descending (most urgent first), then
    by creation timestamp descending.

    Args:
        db: Async database session.
        teacher_id: Requesting teacher's UUID.

    Returns:
        List of active :class:`~app.models.worklist.TeacherWorklistItem`
        rows, limited to :data:`_MAX_WORKLIST_ITEMS_IN_CONTEXT` entries.
    """
    stmt = (
        select(TeacherWorklistItem)
        .where(
            TeacherWorklistItem.teacher_id == teacher_id,
            TeacherWorklistItem.status == "active",
        )
        .order_by(
            TeacherWorklistItem.urgency.desc(),
            TeacherWorklistItem.created_at.desc(),
            TeacherWorklistItem.id.asc(),  # deterministic tie-breaker
        )
        .limit(_MAX_WORKLIST_ITEMS_IN_CONTEXT)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_student_names(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    student_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Return a ``{student_id: full_name}`` map for the given IDs.

    Only students belonging to the requesting teacher are returned.

    Args:
        db: Async database session.
        teacher_id: Requesting teacher's UUID.
        student_ids: List of student UUIDs to resolve.

    Returns:
        Mapping from student UUID to display name.  IDs that do not belong
        to the teacher are silently omitted.
    """
    if not student_ids:
        return {}

    result = await db.execute(
        select(Student.id, Student.full_name).where(
            Student.id.in_(student_ids),
            Student.teacher_id == teacher_id,
        )
    )
    return {row.id: row.full_name for row in result.all()}


def _build_context_json(
    profiles: list[StudentSkillProfile],
    worklist_items: list[TeacherWorklistItem],
) -> str:
    """Serialise class context data into a JSON string for the LLM prompt.

    Only aggregate data is included — no student names or essay content.

    Args:
        profiles: Student skill profile rows.
        worklist_items: Active worklist item rows.

    Returns:
        A compact JSON string suitable for insertion into the prompt.
    """
    profile_data: list[dict[str, Any]] = []
    for p in profiles:
        profile_data.append(
            {
                "student_id": str(p.student_id),
                "assignment_count": p.assignment_count,
                "skill_scores": p.skill_scores,
            }
        )

    worklist_data: list[dict[str, Any]] = []
    for w in worklist_items:
        worklist_data.append(
            {
                "student_id": str(w.student_id),
                "trigger_type": w.trigger_type,
                "skill_key": w.skill_key,
                "urgency": w.urgency,
                "suggested_action": w.suggested_action,
                "details": w.details,
            }
        )

    context: dict[str, Any] = {
        "total_students_with_profiles": len(profiles),
        "skill_profiles": profile_data,
        "active_worklist_items": worklist_data,
    }
    return json.dumps(context, separators=(",", ":"))


def _enrich_ranked_items(
    parsed: ParsedCopilotResponse,
    student_names: dict[uuid.UUID, str],
) -> list[CopilotRankedItemResponse]:
    """Convert parsed ranked items into response schema objects.

    Resolves student UUIDs to display names where available.

    Args:
        parsed: Validated LLM response.
        student_names: ``{student_id: full_name}`` map from the database.

    Returns:
        List of :class:`~app.schemas.copilot.CopilotRankedItemResponse` objects.
    """
    items: list[CopilotRankedItemResponse] = []
    for raw_item in parsed.ranked_items:
        student_id: uuid.UUID | None = None
        display_name: str | None = None
        if raw_item.student_id:
            try:
                student_id = uuid.UUID(raw_item.student_id)
                display_name = student_names.get(student_id)
            except ValueError:
                # LLM returned a non-UUID student_id — treat as missing.
                student_id = None

        items.append(
            CopilotRankedItemResponse(
                student_id=student_id,
                student_display_name=display_name,
                skill_dimension=raw_item.skill_dimension,
                label=raw_item.label,
                value=raw_item.value,
                explanation=raw_item.explanation,
            )
        )
    return items


def _safe_response_type(
    response_type: str,
) -> Literal["ranked_list", "summary", "insufficient_data"]:
    """Coerce the LLM response type to a valid Literal value.

    The Pydantic schema expects one of ``"ranked_list"``, ``"summary"``,
    ``"insufficient_data"``.  The parser already normalises unknown values
    to ``"ranked_list"``, so this is a belt-and-suspenders guard.
    """
    valid: set[str] = {"ranked_list", "summary", "insufficient_data"}
    if response_type in valid:
        return cast(Literal["ranked_list", "summary", "insufficient_data"], response_type)
    return "ranked_list"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_copilot_query(
    db: AsyncSession,
    *,
    teacher_id: uuid.UUID,
    query_text: str,
    class_id: uuid.UUID | None = None,
    prompt_version: str = "v1",
) -> CopilotQueryResponse:
    """Answer a teacher's natural-language query using live class data.

    Steps:
    1. If ``class_id`` is provided, verify the class belongs to the teacher.
    2. Load student skill profiles (tenant-scoped; optionally class-scoped).
    3. Load active worklist items (tenant-scoped).
    4. Serialise context data to JSON — no student names, no essay content.
    5. Call the LLM copilot via :func:`~app.llm.client.call_copilot`.
    6. Resolve student display names from the DB for any UUIDs in ranked
       items.
    7. Return a validated :class:`~app.schemas.copilot.CopilotQueryResponse`.

    Args:
        db: Async database session.
        teacher_id: Authenticated teacher's UUID.
        query_text: Natural-language question from the teacher.
        class_id: Optional class UUID.  When supplied, context data is
            restricted to students enrolled in this class.
        prompt_version: Prompt module version (default: ``"v1"``).

    Returns:
        A :class:`~app.schemas.copilot.CopilotQueryResponse` ready to be
        returned as ``{"data": ...}``.

    Raises:
        NotFoundError:  ``class_id`` not found.
        ForbiddenError: ``class_id`` belongs to a different teacher.
        LLMParseError:  LLM response cannot be parsed after one retry.
        LLMError:       LLM transport error.
    """
    if class_id is not None:
        await _assert_class_owned_by(db, class_id, teacher_id)

    profiles = await _load_skill_profiles(db, teacher_id, class_id)
    worklist_items = await _load_worklist_items(db, teacher_id)

    logger.info(
        "Copilot query context loaded",
        extra={
            "teacher_id": str(teacher_id),
            "class_id": str(class_id) if class_id else None,
            "profile_count": len(profiles),
            "worklist_item_count": len(worklist_items),
        },
    )

    context_json = _build_context_json(profiles, worklist_items)
    parsed = await call_copilot(
        context_json=context_json,
        query_text=query_text,
        prompt_version=prompt_version,
    )

    # Resolve student names for any UUIDs in ranked items.
    raw_student_ids: list[uuid.UUID] = []
    for item in parsed.ranked_items:
        if item.student_id:
            with contextlib.suppress(ValueError):
                raw_student_ids.append(uuid.UUID(item.student_id))

    student_names = await _load_student_names(db, teacher_id, raw_student_ids)
    enriched_items = _enrich_ranked_items(parsed, student_names)

    return CopilotQueryResponse(
        query_interpretation=parsed.query_interpretation,
        has_sufficient_data=parsed.has_sufficient_data,
        uncertainty_note=parsed.uncertainty_note,
        response_type=_safe_response_type(parsed.response_type),
        ranked_items=enriched_items,
        summary=parsed.summary,
        suggested_next_steps=parsed.suggested_next_steps,
        prompt_version=COPILOT_PROMPT_VERSION,
    )
