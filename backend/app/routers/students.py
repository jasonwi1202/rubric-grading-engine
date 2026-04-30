"""Students router — student detail and update endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
Student PII (names) is never logged — only entity IDs appear in log output.

Endpoints:
  GET   /students/{studentId}                    — get student detail with embedded skill profile
  GET   /students/{studentId}/history            — get all locked graded assignments (newest-first)
  PATCH /students/{studentId}                    — update student name, external ID, or teacher notes
  POST  /students/{studentId}/recommendations    — generate instruction recommendations from profile
  GET   /students/{studentId}/recommendations    — list persisted recommendation sets
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.models.student import Student
from app.models.student_skill_profile import StudentSkillProfile
from app.models.user import User
from app.schemas.instruction_recommendation import (
    GenerateStudentRecommendationRequest,
    recommendation_response_from_orm,
)
from app.schemas.student import (
    AssignmentHistoryItemResponse,
    PatchStudentRequest,
    SkillProfileResponse,
    StudentResponse,
    StudentWithProfileResponse,
)
from app.services.instruction_recommendation import (
    generate_student_recommendations,
    list_student_recommendations,
)
from app.services.student import (
    get_student_history,
    get_student_with_profile,
    update_student,
)

router = APIRouter(prefix="/students", tags=["students"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _student_response(student: object) -> StudentResponse:
    return StudentResponse.model_validate(student)


def _student_with_profile_response(
    student: Student,
    profile: StudentSkillProfile | None,
) -> StudentWithProfileResponse:
    return StudentWithProfileResponse(
        id=student.id,
        teacher_id=student.teacher_id,
        full_name=student.full_name,
        external_id=student.external_id,
        teacher_notes=student.teacher_notes,
        created_at=student.created_at,
        skill_profile=SkillProfileResponse.model_validate(profile) if profile is not None else None,
    )


# ---------------------------------------------------------------------------
# GET /students/{studentId}
# ---------------------------------------------------------------------------


@router.get(
    "/{student_id}",
    summary="Get student detail with embedded skill profile",
)
async def get_student_endpoint(
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a student with an optionally embedded skill profile.

    ``skill_profile`` is ``null`` when the student has no locked grades yet.

    Returns 404 if the student does not exist.
    Returns 403 if the student belongs to a different teacher.
    """
    student, profile = await get_student_with_profile(db, teacher.id, student_id)
    return JSONResponse(
        status_code=200,
        content={"data": _student_with_profile_response(student, profile).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /students/{studentId}/history
# ---------------------------------------------------------------------------


@router.get(
    "/{student_id}/history",
    summary="Get student assignment history",
)
async def get_student_history_endpoint(
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all locked graded assignments for a student, newest-first.

    Returns 404 if the student does not exist.
    Returns 403 if the student belongs to a different teacher.
    """
    rows = await get_student_history(db, teacher.id, student_id)
    items = [
        AssignmentHistoryItemResponse(
            assignment_id=row.assignment_id,
            assignment_title=row.assignment_title,
            class_id=row.class_id,
            grade_id=row.grade_id,
            essay_id=row.essay_id,
            total_score=row.total_score,
            max_possible_score=row.max_possible_score,
            locked_at=row.locked_at,
        ).model_dump(mode="json")
        for row in rows
    ]
    return JSONResponse(status_code=200, content={"data": items})


# ---------------------------------------------------------------------------
# PATCH /students/{studentId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{student_id}",
    summary="Update student name, external ID, or teacher notes",
)
async def patch_student_endpoint(
    student_id: uuid.UUID,
    payload: PatchStudentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update a student record.

    Only fields explicitly included in the request body are updated.
    To explicitly clear ``external_id``, send ``"external_id": null``.
    To set or update ``teacher_notes``, send the new text.
    To explicitly clear ``teacher_notes``, send ``"teacher_notes": null``.

    Returns 403 if the student belongs to a different teacher.
    Returns 404 if the student does not exist.
    """
    fields_set = payload.model_fields_set
    student = await update_student(
        db,
        teacher.id,
        student_id,
        full_name=payload.full_name if "full_name" in fields_set else None,
        external_id=payload.external_id
        if "external_id" in fields_set and payload.external_id is not None
        else None,
        clear_external_id="external_id" in fields_set and payload.external_id is None,
        teacher_notes=payload.teacher_notes
        if "teacher_notes" in fields_set and payload.teacher_notes is not None
        else None,
        clear_teacher_notes="teacher_notes" in fields_set and payload.teacher_notes is None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _student_response(student).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /students/{studentId}/recommendations
# ---------------------------------------------------------------------------


@router.post(
    "/{student_id}/recommendations",
    status_code=201,
    summary="Generate instruction recommendations from a student's skill profile",
)
async def generate_student_recommendations_endpoint(
    student_id: uuid.UUID,
    payload: GenerateStudentRecommendationRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate AI-powered instruction recommendations for a student's skill gaps.

    Reads the student's skill profile, calls the LLM with aggregate skill data
    only (no essay content), validates the response, and persists the result.

    The teacher can optionally specify a single ``skill_key`` to target one
    dimension, or omit it to address all detected gaps.  Setting
    ``worklist_item_id`` links the generated recommendations to the worklist
    item that prompted the action.

    Returns 201 with the persisted recommendation set.
    Returns 404 if the student or their skill profile does not exist.
    Returns 403 if the student belongs to a different teacher.
    Returns 422 if the student has no skill profile data yet.
    Returns 503 if the LLM service is temporarily unavailable.
    """
    rec = await generate_student_recommendations(
        db,
        teacher.id,
        student_id,
        grade_level=payload.grade_level,
        duration_minutes=payload.duration_minutes,
        skill_key=payload.skill_key,
        worklist_item_id=payload.worklist_item_id,
    )
    return JSONResponse(
        status_code=201,
        content={"data": recommendation_response_from_orm(rec).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /students/{studentId}/recommendations
# ---------------------------------------------------------------------------


@router.get(
    "/{student_id}/recommendations",
    summary="List persisted instruction recommendation sets for a student",
)
async def list_student_recommendations_endpoint(
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all persisted instruction recommendation sets for a student, newest-first.

    Returns 404 if the student does not exist.
    Returns 403 if the student belongs to a different teacher.
    """
    recs = await list_student_recommendations(db, teacher.id, student_id)
    return JSONResponse(
        status_code=200,
        content={"data": [recommendation_response_from_orm(r).model_dump(mode="json") for r in recs]},
    )
