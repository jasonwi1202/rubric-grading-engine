"""Classes router — class CRUD and enrollment endpoints.

All endpoints require a valid JWT (``get_current_teacher`` dependency).
Student PII (names) is never logged — only entity IDs appear in log output.

Endpoints:
  GET    /classes                                       — list teacher's classes (filterable)
  POST   /classes                                       — create a new class
  GET    /classes/{classId}                             — get class detail
  PATCH  /classes/{classId}                             — update class name, subject, grade level, academic year
  POST   /classes/{classId}/archive                     — archive the class (soft)
  GET    /classes/{classId}/assignments                 — list assignments for a class
  POST   /classes/{classId}/assignments                 — create a new assignment
  GET    /classes/{classId}/students                    — list enrolled students
  POST   /classes/{classId}/students                    — enroll a new or existing student
  POST   /classes/{classId}/students/import             — parse CSV and return import diff
  POST   /classes/{classId}/students/import/confirm     — commit a previously reviewed import
  DELETE /classes/{classId}/students/{studentId}        — soft-remove a student from the class
  GET    /classes/{classId}/insights                    — class-level skill averages, distributions, and common issues
  GET    /classes/{classId}/groups                      — current auto-generated skill-gap groups with student lists and stability status
  PATCH  /classes/{classId}/groups/{groupId}            — manually adjust student membership of a skill-gap group
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse, Response

from app.db.session import AsyncSession, get_db
from app.dependencies import get_current_teacher
from app.exceptions import ValidationError as DomainValidationError
from app.models.user import User
from app.schemas.assignment import (
    AssignmentListItemResponse,
    AssignmentResponse,
    CreateAssignmentRequest,
)
from app.schemas.class_ import ClassResponse, CreateClassRequest, PatchClassRequest
from app.schemas.instruction_recommendation import (
    GenerateGroupRecommendationRequest,
    recommendation_response_from_orm,
)
from app.schemas.roster_import import (
    DiffRowResponse,
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportDiffResponse,
    ImportRowStatus,
)
from app.schemas.student import EnrolledStudentResponse, EnrollStudentRequest, StudentResponse
from app.schemas.student_group import PatchGroupMembersRequest
from app.services.assignment import (
    create_assignment,
    list_assignments,
)
from app.services.auto_grouping import list_class_groups, update_group_members
from app.services.class_ import (
    archive_class,
    create_class,
    get_class,
    list_classes,
    update_class,
)
from app.services.class_insights import get_class_insights
from app.services.instruction_recommendation import generate_group_recommendations
from app.services.roster_import import (
    CsvParseResult,
    ParsedRow,
    build_import_diff,
    commit_roster_import,
    parse_csv_roster,
)
from app.services.student import (
    enroll_student,
    list_enrolled_students,
    remove_enrollment,
)

router = APIRouter(prefix="/classes", tags=["classes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _class_response(class_obj: object) -> ClassResponse:
    """Build a ClassResponse from a Class ORM instance."""
    return ClassResponse.model_validate(class_obj)


# ---------------------------------------------------------------------------
# GET /classes
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List the authenticated teacher's classes",
)
async def list_classes_endpoint(
    academic_year: str | None = Query(default=None),
    is_archived: bool | None = Query(default=None),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all classes for the authenticated teacher.

    Supports optional query filters:
    - ``academic_year``: filter by academic year string (e.g. ``"2025-26"``)
    - ``is_archived``: ``true`` or ``false`` to filter by archive status
    """
    classes = await list_classes(
        db,
        teacher_id=teacher.id,
        academic_year=academic_year,
        is_archived=is_archived,
    )
    response_items = [_class_response(c).model_dump(mode="json") for c in classes]
    return JSONResponse(
        status_code=200,
        content={"data": response_items},
    )


# ---------------------------------------------------------------------------
# POST /classes
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    summary="Create a new class",
)
async def create_class_endpoint(
    payload: CreateClassRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create a class owned by the authenticated teacher."""
    new_class = await create_class(
        db,
        teacher_id=teacher.id,
        name=payload.name,
        subject=payload.subject,
        grade_level=payload.grade_level,
        academic_year=payload.academic_year,
    )
    return JSONResponse(
        status_code=201,
        content={"data": _class_response(new_class).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}",
    summary="Get class detail",
)
async def get_class_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return a single class.

    Returns 404 if the class does not exist.
    Returns 403 if the class belongs to a different teacher.
    """
    class_obj = await get_class(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /classes/{classId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{class_id}",
    summary="Update class metadata",
)
async def patch_class_endpoint(
    class_id: uuid.UUID,
    payload: PatchClassRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Partially update a class.

    Only fields explicitly included in the request body are updated.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    fields_set = payload.model_fields_set
    class_obj = await update_class(
        db,
        teacher_id=teacher.id,
        class_id=class_id,
        name=payload.name if "name" in fields_set else None,
        subject=payload.subject if "subject" in fields_set else None,
        grade_level=payload.grade_level if "grade_level" in fields_set else None,
        academic_year=payload.academic_year if "academic_year" in fields_set else None,
    )
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /classes/{classId}/archive
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/archive",
    summary="Archive a class",
)
async def archive_class_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Archive a class by setting ``is_archived=True``.

    This is a soft operation — the class is not deleted.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    class_obj = await archive_class(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": _class_response(class_obj).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}/assignments
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/assignments",
    summary="List assignments for a class",
)
async def list_assignments_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all assignments for the given class.

    Returns 404 if the class does not exist.
    Returns 403 if the class belongs to a different teacher.
    """
    assignments = await list_assignments(db, teacher_id=teacher.id, class_id=class_id)
    items = [
        AssignmentListItemResponse.model_validate(a).model_dump(mode="json") for a in assignments
    ]
    return JSONResponse(status_code=200, content={"data": items})


# ---------------------------------------------------------------------------
# POST /classes/{classId}/assignments
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/assignments",
    status_code=201,
    summary="Create a new assignment for a class",
)
async def create_assignment_endpoint(
    class_id: uuid.UUID,
    payload: CreateAssignmentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Create an assignment owned by the given class.

    The rubric is snapshotted at creation time — editing the rubric later has
    no effect on this assignment or its grades.

    Returns 404 if the class or rubric does not exist.
    Returns 403 if the class or rubric belongs to a different teacher.
    """
    assignment = await create_assignment(
        db,
        teacher_id=teacher.id,
        class_id=class_id,
        rubric_id=payload.rubric_id,
        title=payload.title,
        prompt=payload.prompt,
        due_date=payload.due_date,
        feedback_tone=payload.feedback_tone.value,
    )
    return JSONResponse(
        status_code=201,
        content={"data": AssignmentResponse.model_validate(assignment).model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}/students
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/students",
    summary="List enrolled students in a class",
)
async def list_enrolled_students_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return all actively enrolled students for a class.

    Returns 404 if the class does not exist.
    Returns 403 if the class belongs to a different teacher.
    """
    pairs = await list_enrolled_students(db, teacher.id, class_id)
    items = [
        EnrolledStudentResponse(
            enrollment_id=enrollment.id,
            enrolled_at=enrollment.enrolled_at,
            student=StudentResponse.model_validate(student),
        ).model_dump(mode="json")
        for enrollment, student in pairs
    ]
    return JSONResponse(status_code=200, content={"data": items})


# ---------------------------------------------------------------------------
# POST /classes/{classId}/students
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/students",
    status_code=201,
    summary="Enrol a new or existing student in a class",
)
async def enroll_student_endpoint(
    class_id: uuid.UUID,
    payload: EnrollStudentRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Enrol a student in a class.

    Provide ``student_id`` to enroll an existing student, or ``full_name``
    (and optionally ``external_id``) to create a new student and enroll them.

    Returns 409 if the student is already enrolled.
    Returns 403 if the class or student belongs to a different teacher.
    Returns 404 if the class or referenced student does not exist.
    """
    enrollment, student = await enroll_student(
        db,
        teacher.id,
        class_id,
        student_id=payload.student_id,
        full_name=payload.full_name,
        external_id=payload.external_id,
    )
    response_data = EnrolledStudentResponse(
        enrollment_id=enrollment.id,
        enrolled_at=enrollment.enrolled_at,
        student=StudentResponse.model_validate(student),
    ).model_dump(mode="json")
    return JSONResponse(status_code=201, content={"data": response_data})


# ---------------------------------------------------------------------------
# POST /classes/{classId}/students/import
# ---------------------------------------------------------------------------

# Maximum CSV file size accepted (bytes).  200 rows × ~200 bytes/row fits
# well under 1 MB; this limit prevents resource exhaustion from giant uploads.
_MAX_CSV_BYTES: int = 1 * 1024 * 1024  # 1 MB


@router.post(
    "/{class_id}/students/import",
    summary="Parse a CSV roster and return an import diff",
)
async def import_students_endpoint(
    class_id: uuid.UUID,
    file: UploadFile = File(
        ..., description="CSV file with full_name and optional external_id columns"
    ),
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Parse an uploaded CSV file and return a per-row import diff.

    The diff classifies each row as **new** (will be created), **updated**
    (existing student matched by external_id, will be enrolled), **skipped**
    (already enrolled or potential fuzzy-name duplicate), or **error** (row
    failed validation).

    No students are written to the database by this endpoint.  The teacher
    must review the diff and call POST .../import/confirm to commit.

    Returns 422 if:
    - The file cannot be decoded as UTF-8.
    - The CSV has no header row or is missing the required ``full_name`` column.
    - The CSV contains more than 200 data rows.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    raw = await file.read(_MAX_CSV_BYTES + 1)
    if len(raw) > _MAX_CSV_BYTES:
        raise DomainValidationError(
            f"CSV file is too large (maximum {_MAX_CSV_BYTES // 1024} KB).",
            field="file",
        )

    parse_result: CsvParseResult = parse_csv_roster(raw)

    # Build the diff for valid rows (may return empty list if all rows errored).
    diff_rows = await build_import_diff(db, teacher.id, class_id, parse_result.rows)

    # Merge parse errors (status=ERROR) with the diff rows, ordered by row number.
    all_rows = diff_rows + parse_result.errors
    all_rows.sort(key=lambda r: r.row_number)

    response_rows = [
        DiffRowResponse(
            row_number=r.row_number,
            full_name=r.full_name,
            external_id=r.external_id,
            status=r.status,
            message=r.message,
            existing_student_id=r.existing_student_id,
        )
        for r in all_rows
    ]

    diff_response = ImportDiffResponse(
        rows=response_rows,
        new_count=sum(1 for r in all_rows if r.status == ImportRowStatus.NEW),
        updated_count=sum(1 for r in all_rows if r.status == ImportRowStatus.UPDATED),
        skipped_count=sum(1 for r in all_rows if r.status == ImportRowStatus.SKIPPED),
        error_count=sum(1 for r in all_rows if r.status == ImportRowStatus.ERROR),
    )
    return JSONResponse(
        status_code=200,
        content={"data": diff_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /classes/{classId}/students/import/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/students/import/confirm",
    summary="Commit a reviewed CSV roster import",
)
async def confirm_import_endpoint(
    class_id: uuid.UUID,
    payload: ImportConfirmRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Commit the import rows that the teacher approved.

    Request-schema validation happens before this endpoint runs. If the
    payload is malformed (for example, ``rows`` is empty or a row has an
    invalid ``full_name``), FastAPI/Pydantic rejects the request with a 422
    response.

    After schema validation succeeds, the server re-validates each row
    against the current class roster before writing to the database. Rows
    that are already enrolled, or that fail this business-level
    re-validation, are silently skipped and do not cause the request to
    fail.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    rows_to_commit = [
        ParsedRow(
            row_number=r.row_number,
            full_name=r.full_name,
            external_id=r.external_id,
        )
        for r in payload.rows
    ]

    counts = await commit_roster_import(db, teacher.id, class_id, rows_to_commit)

    confirm_response = ImportConfirmResponse(
        created=counts["created"],
        updated=counts["updated"],
        skipped=counts["skipped"],
    )
    return JSONResponse(
        status_code=200,
        content={"data": confirm_response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# DELETE /classes/{classId}/students/{studentId}
# ---------------------------------------------------------------------------


@router.delete(
    "/{class_id}/students/{student_id}",
    status_code=204,
    summary="Soft-remove a student from a class",
)
async def remove_enrollment_endpoint(
    class_id: uuid.UUID,
    student_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a student from a class by setting ``removed_at``.

    This is a soft operation — the student record and all assignment history
    are preserved.

    Returns 404 if the class, student, or active enrollment does not exist.
    Returns 403 if the class or student belongs to a different teacher.
    """
    await remove_enrollment(db, teacher.id, class_id, student_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# GET /classes/{classId}/insights
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/insights",
    summary="Get class-level skill insights",
)
async def get_class_insights_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return aggregated skill averages, score distributions, and common issues
    for all locked grades across all assignments in the class.

    The response reflects only **locked** grades.  Unlocked (pending review)
    grades are excluded so the teacher sees a stable view of confirmed results.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    insights = await get_class_insights(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": insights.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# GET /classes/{classId}/groups
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/groups",
    summary="Get current auto-generated skill-gap groups for a class",
)
async def get_class_groups_endpoint(
    class_id: uuid.UUID,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return the current auto-generated skill-gap student groups for a class.

    Groups are computed by the auto-grouping Celery task (M6-01) and updated
    each time a grade is locked.  The response includes:

    - **students** — the list of students sharing the skill gap, with names
      and optional external IDs.  The ``students`` list is empty for 'exited'
      groups (skill gap was present in the last run but is no longer active).
    - **label** — human-readable description of the shared skill gap.
    - **stability** — one of:
        - ``'new'`` — first time this group appears for the class.
        - ``'persistent'`` — group existed in the previous computation.
        - ``'exited'`` — previously existed but no longer meets the minimum
          size threshold (students improved or the class is too small).

    Active groups (new/persistent) are returned first, sorted by label.
    Exited groups follow, also sorted by label.

    Returns an empty ``groups`` list when no groups have been computed yet.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class does not exist.
    """
    response = await list_class_groups(db, teacher.id, class_id)
    return JSONResponse(
        status_code=200,
        content={"data": response.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# PATCH /classes/{classId}/groups/{groupId}
# ---------------------------------------------------------------------------


@router.patch(
    "/{class_id}/groups/{group_id}",
    summary="Manually adjust student membership of a skill-gap group",
)
async def patch_class_group_endpoint(
    class_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: PatchGroupMembersRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Replace the student membership of a skill-gap group.

    Accepts a ``student_ids`` list that fully replaces the current group
    membership.  The update does **not** affect the underlying
    ``StudentSkillProfile`` data — it only adjusts which students are
    associated with this group record.

    Stability transitions:
    - If the list is empty, the group's ``stability`` becomes ``'exited'``.
    - If the group was previously ``'exited'`` and now receives students,
      its ``stability`` becomes ``'persistent'``.
    - Otherwise the existing stability value is preserved.

    Returns the updated group with resolved student names.

    Returns 403 if the class belongs to a different teacher.
    Returns 404 if the class or group does not exist.
    """
    updated = await update_group_members(
        db,
        teacher.id,
        class_id,
        group_id,
        payload.student_ids,
    )
    return JSONResponse(
        status_code=200,
        content={"data": updated.model_dump(mode="json")},
    )


# ---------------------------------------------------------------------------
# POST /classes/{classId}/groups/{groupId}/recommendations
# ---------------------------------------------------------------------------


@router.post(
    "/{class_id}/groups/{group_id}/recommendations",
    status_code=201,
    summary="Generate instruction recommendations for a class skill-gap group",
)
async def generate_group_recommendations_endpoint(
    class_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: GenerateGroupRecommendationRequest,
    teacher: User = Depends(get_current_teacher),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate AI-powered instruction recommendations targeting a class skill-gap group.

    Uses the group's shared skill gap as the generation context.  Only
    aggregate group metadata is sent to the LLM — no individual student essay
    content or PII.

    Returns 201 with the persisted recommendation set.
    Returns 404 if the class or group does not exist.
    Returns 403 if the class or group belongs to a different teacher.
    Returns 503 if the LLM service is temporarily unavailable.
    """
    rec = await generate_group_recommendations(
        db,
        teacher.id,
        class_id,
        group_id,
        grade_level=payload.grade_level,
        duration_minutes=payload.duration_minutes,
    )
    return JSONResponse(
        status_code=201,
        content={"data": recommendation_response_from_orm(rec).model_dump(mode="json")},
    )
