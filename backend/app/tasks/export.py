"""Export Celery task — PDF batch export for a full assignment.

The :func:`export_assignment` task is enqueued by
``POST /assignments/{id}/export``.  It:

1. Updates Redis status to ``processing``.
2. Loads all essays with status ``locked`` and their locked grades, scoped to
   the authenticated teacher (tenant isolation enforced in the query).
3. Generates a per-student PDF feedback report using :func:`_build_student_pdf`.
4. Packages all PDFs into a ZIP archive (in memory).
5. Uploads the ZIP to S3 under ``exports/{assignment_id}/{task_id}.zip``.
6. Updates Redis status to ``complete`` and stores the S3 key.

Security invariants:
- No student PII is logged at any level — only entity IDs
  (``student_id``, ``grade_id``, ``essay_id``) appear in log output.
- S3 object keys are never logged or included in exception messages.
- Teacher ownership is validated inside the task via an explicit
  ``teacher_id`` filter on every database query.
- PDF filenames inside the ZIP use ``student_id`` (a UUID), not student names.
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
import zipfile

from app.db.session import AsyncSessionLocal
from app.storage.s3 import StorageError, upload_file
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)

# S3 key prefix for export ZIPs.
_EXPORT_S3_PREFIX = "exports"

# Redis key prefix — must match the constant in app.services.export.
_EXPORT_KEY_PREFIX = "export:"

# Redis TTL for export records: 1 hour.
_EXPORT_TTL_SECONDS = 3600


# ---------------------------------------------------------------------------
# PDF generation helper
# ---------------------------------------------------------------------------


def _build_student_pdf(
    student_id: str,
    assignment_title: str,
    summary_feedback: str,
    criterion_items: list[dict[str, object]],
) -> bytes:
    """Generate a PDF feedback report for a single student.

    Uses ``fpdf2`` for PDF generation.  All text is encoded as UTF-8.

    Args:
        student_id: UUID string of the student (used in header — not name).
        assignment_title: Title of the assignment.
        summary_feedback: Overall teacher/AI feedback text.
        criterion_items: List of dicts with keys ``name``, ``final_score``,
            ``max_score``, and optional ``feedback``.

    Returns:
        Raw PDF bytes.
    """
    from fpdf import FPDF  # noqa: PLC0415 — optional dep, lazy import

    pdf = FPDF()
    pdf.add_page()

    # Assignment title
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, assignment_title)
    pdf.ln(3)

    # Student identifier (UUID — not name, to avoid PII in generated files)
    pdf.set_font("Helvetica", "I", 11)
    pdf.cell(0, 8, f"Student ID: {student_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Summary feedback
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Summary Feedback", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 7, summary_feedback)
    pdf.ln(4)

    # Per-criterion scores and feedback
    if criterion_items:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, "Criterion Scores", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        for item in criterion_items:
            name = str(item.get("name", ""))
            final_score = item.get("final_score", 0)
            max_score = item.get("max_score", 0)
            feedback = item.get("feedback")

            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, f"{name}  ({final_score}/{max_score})", new_x="LMARGIN", new_y="NEXT")
            if feedback:
                pdf.set_font("Helvetica", size=10)
                pdf.multi_cell(0, 6, str(feedback))
            pdf.ln(2)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_export(
    assignment_id: str,
    teacher_id: str,
    task_id: str,
) -> None:
    """Async implementation of the export task."""
    from redis.asyncio import Redis  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from app.config import settings  # noqa: PLC0415
    from app.models.assignment import Assignment  # noqa: PLC0415
    from app.models.class_ import Class  # noqa: PLC0415
    from app.models.essay import Essay, EssayStatus, EssayVersion  # noqa: PLC0415
    from app.models.grade import CriterionScore, Grade  # noqa: PLC0415
    from app.models.student import Student  # noqa: PLC0415

    assignment_uuid = uuid.UUID(assignment_id)
    teacher_uuid = uuid.UUID(teacher_id)

    redis_key = f"{_EXPORT_KEY_PREFIX}{task_id}"
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[type-arg]

    try:
        # Mark as processing so poll endpoints return an accurate status.
        await redis.hset(redis_key, "status", "processing")

        async with AsyncSessionLocal() as db:
            # 1. Load assignment — tenant-scoped, verifies teacher owns it.
            assignment_result = await db.execute(
                select(Assignment)
                .join(Class, Assignment.class_id == Class.id)
                .where(
                    Assignment.id == assignment_uuid,
                    Class.teacher_id == teacher_uuid,
                )
            )
            assignment = assignment_result.scalar_one_or_none()

            if assignment is None:
                logger.error(
                    "Export task: assignment not found or forbidden",
                    extra={"assignment_id": assignment_id},
                )
                await redis.hset(
                    redis_key,
                    mapping={"status": "failed", "error": "ASSIGNMENT_NOT_FOUND"},
                )
                return

            # Build a lookup map from rubric criterion UUID → criterion metadata
            # from the immutable snapshot (never query live rubric during export).
            snapshot_criteria: dict[str, dict[str, object]] = {}
            snapshot = assignment.rubric_snapshot
            for c in snapshot.get("criteria", []):  # type: ignore[union-attr]
                cid = str(c.get("id", ""))  # type: ignore[union-attr]
                snapshot_criteria[cid] = c  # type: ignore[assignment]

            # 2. Load all locked essays with student IDs — tenant-scoped.
            essays_result = await db.execute(
                select(Essay, Student.id.label("student_uuid"))
                .join(Assignment, Essay.assignment_id == Assignment.id)
                .join(Class, Assignment.class_id == Class.id)
                .outerjoin(Student, Essay.student_id == Student.id)
                .where(
                    Essay.assignment_id == assignment_uuid,
                    Essay.status == EssayStatus.locked,
                    Class.teacher_id == teacher_uuid,
                )
            )
            essays_rows = essays_result.all()

            if not essays_rows:
                logger.warning(
                    "Export task: no locked essays found",
                    extra={"assignment_id": assignment_id},
                )
                await redis.hset(
                    redis_key,
                    mapping={"status": "failed", "error": "NO_LOCKED_GRADES"},
                )
                return

            # total = essays found with locked status at query time.
            total = len(essays_rows)
            await redis.hset(redis_key, "total", str(total))

            # 3. Load grades for locked essays — join Essay → EssayVersion → Grade.
            essay_ids = [essay.id for essay, _ in essays_rows]
            grades_result = await db.execute(
                select(EssayVersion, Grade)
                .join(Grade, Grade.essay_version_id == EssayVersion.id)
                .where(
                    EssayVersion.essay_id.in_(essay_ids),
                    Grade.is_locked == True,  # noqa: E712 — SQLAlchemy requires ==
                )
            )
            grade_rows = grades_result.all()

            # Build a lookup: essay_id → (grade, essay_version)
            grade_by_essay: dict[uuid.UUID, tuple[EssayVersion, Grade]] = {}
            for ev, grade in grade_rows:
                grade_by_essay[ev.essay_id] = (ev, grade)

            # 4. Load criterion scores for all grades in one query.
            grade_ids = [grade.id for _, grade in grade_by_essay.values()]
            scores_result = await db.execute(
                select(CriterionScore).where(CriterionScore.grade_id.in_(grade_ids))
            )
            scores_by_grade: dict[uuid.UUID, list[CriterionScore]] = {}
            for score in scores_result.scalars():
                scores_by_grade.setdefault(score.grade_id, []).append(score)

            # 5. Generate PDFs and package into ZIP.
            zip_buffer = io.BytesIO()
            # completed counts PDFs written successfully; skipped tracks unprocessable essays.
            completed = 0
            skipped = 0

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for essay, student_uuid_val in essays_rows:
                    essay_id = essay.id

                    if student_uuid_val is None:
                        # Essay has no enrolled student — log and skip rather than silently
                        # using a surrogate identifier that could cause confusion.
                        logger.warning(
                            "Export task: locked essay has no associated student — skipping",
                            extra={"essay_id": str(essay_id)},
                        )
                        skipped += 1
                        continue

                    student_id_str = str(student_uuid_val)

                    grade_pair = grade_by_essay.get(essay_id)
                    if grade_pair is None:
                        # Essay is locked but no locked grade record found — skip.
                        logger.warning(
                            "Export task: locked essay has no locked grade — skipping",
                            extra={"essay_id": str(essay_id)},
                        )
                        skipped += 1
                        continue

                    _ev, grade = grade_pair
                    summary = (
                        grade.summary_feedback_edited
                        if grade.summary_feedback_edited
                        else grade.summary_feedback
                    )

                    # Build per-criterion items for the PDF.
                    criterion_items: list[dict[str, object]] = []
                    for score in scores_by_grade.get(grade.id, []):
                        crit_id = str(score.rubric_criterion_id)
                        crit_meta = snapshot_criteria.get(crit_id, {})
                        feedback = score.teacher_feedback or score.ai_feedback
                        criterion_items.append(
                            {
                                "name": crit_meta.get("name", crit_id),
                                "final_score": score.final_score,
                                "max_score": crit_meta.get("max_score", "?"),
                                "feedback": feedback,
                            }
                        )

                    try:
                        pdf_bytes = _build_student_pdf(
                            student_id=student_id_str,
                            assignment_title=assignment.title,
                            summary_feedback=summary,
                            criterion_items=criterion_items,
                        )
                    except Exception as pdf_exc:
                        logger.error(
                            "Export task: PDF generation failed for essay",
                            extra={
                                "essay_id": str(essay_id),
                                "grade_id": str(grade.id),
                                "error_type": type(pdf_exc).__name__,
                            },
                        )
                        raise

                    # Filename uses student_id (UUID) — not student name (PII).
                    pdf_filename = f"{student_id_str}.pdf"
                    zf.writestr(pdf_filename, pdf_bytes)
                    completed += 1
                    await redis.hset(redis_key, "complete", str(completed))

            if skipped > 0:
                logger.warning(
                    "Export task: some essays were skipped",
                    extra={"assignment_id": assignment_id, "skipped": skipped},
                )

            # 6. Upload ZIP to S3.
            zip_bytes = zip_buffer.getvalue()
            s3_key = f"{_EXPORT_S3_PREFIX}/{assignment_id}/{task_id}.zip"

            try:
                upload_file(s3_key, zip_bytes, "application/zip")
            except StorageError as exc:
                logger.error(
                    "Export task: S3 upload failed",
                    extra={"assignment_id": assignment_id, "error_type": type(exc).__name__},
                )
                await redis.hset(
                    redis_key,
                    mapping={"status": "failed", "error": "S3_UPLOAD_FAILED"},
                )
                return

            # 7. Mark complete and store the S3 key for the download endpoint.
            await redis.hset(
                redis_key,
                mapping={"status": "complete", "s3_key": s3_key},
            )
            # Refresh TTL so the record survives long enough to download.
            await redis.expire(redis_key, _EXPORT_TTL_SECONDS)

            logger.info(
                "Export task complete",
                extra={
                    "assignment_id": assignment_id,
                    "task_id": task_id,
                    "total": completed,
                },
            )

    except Exception as exc:
        logger.error(
            "Export task failed with unrecoverable error",
            extra={"assignment_id": assignment_id, "error_type": type(exc).__name__},
        )
        try:
            await redis.hset(
                redis_key,
                mapping={"status": "failed", "error": "INTERNAL_ERROR"},
            )
        except Exception as redis_exc:
            logger.warning(
                "Export task: failed to update Redis status after error",
                extra={"error_type": type(redis_exc).__name__},
            )
        raise
    finally:
        await redis.aclose()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.export.export_assignment",
    bind=True,
    max_retries=3,
)
def export_assignment(
    self: object,
    assignment_id: str,
    teacher_id: str,
    task_id: str,
) -> str:
    """Generate per-student PDF feedback exports for an assignment.

    Loads all locked grades, generates one PDF per student, packages them
    as a ZIP, and uploads the archive to S3.  The S3 key is written to Redis
    so the download endpoint can generate a pre-signed URL.

    Args:
        assignment_id: UUID string of the assignment to export.
        teacher_id: UUID string of the owning teacher.  Used for tenant
            isolation — every database query is scoped to this teacher.
        task_id: UUID string that uniquely identifies this export run.
            Used as the Redis key suffix and the S3 object key component.

    Returns:
        The S3 object key of the uploaded ZIP.

    Raises:
        Exception: Re-raised after updating Redis status to ``failed`` so
            Celery marks the task as ``FAILURE``.
    """
    try:
        asyncio.run(_run_export(assignment_id, teacher_id, task_id))
    except Exception as exc:
        attempt = self.request.retries  # type: ignore[attr-defined]
        if attempt < self.max_retries:  # type: ignore[attr-defined]
            logger.warning(
                "Export task failed — will retry",
                extra={
                    "assignment_id": assignment_id,
                    "error_type": type(exc).__name__,
                    "attempt": attempt,
                },
            )
            raise self.retry(exc=exc, countdown=2**attempt) from exc  # type: ignore[attr-defined]

        logger.error(
            "Export task failed — retries exhausted",
            extra={"assignment_id": assignment_id, "error_type": type(exc).__name__},
        )
        raise

    return f"{_EXPORT_S3_PREFIX}/{assignment_id}/{task_id}.zip"
