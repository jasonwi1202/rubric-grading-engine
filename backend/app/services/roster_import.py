"""Roster import service.

Handles CSV parsing, duplicate detection (by external_id and fuzzy name
match), and batch student enrollment for the two-phase import flow:

  Phase 1 — ``parse_csv_roster`` + ``build_import_diff``:
      Parse the uploaded CSV and compare each row against the existing class
      roster.  Returns per-row status without writing to the database.

  Phase 2 — ``commit_roster_import``:
      Re-validate rows supplied by the teacher and write only the approved
      rows to the database.

No student PII (name, external_id) is written to any log statement.
Only entity IDs (class_id, student_id, teacher_id) appear in logs.
"""

from __future__ import annotations

import csv
import difflib
import io
import logging
import uuid
from dataclasses import dataclass
from dataclasses import field as dc_field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.student import Student
from app.schemas.roster_import import ImportRowStatus

logger = logging.getLogger(__name__)

# Maximum rows per CSV upload (enforced before building the diff).
MAX_IMPORT_ROWS: int = 200

# Maximum length for a student's full_name (mirrors the DB column constraint).
MAX_NAME_LENGTH: int = 255

# Maximum length for a student's external_id (mirrors the DB column constraint).
MAX_EXTERNAL_ID_LENGTH: int = 255

# Ratio threshold for difflib fuzzy name matching (0–1).
# Names with a similarity ratio >= this value are treated as potential
# duplicates of enrolled students.
FUZZY_MATCH_THRESHOLD: float = 0.85


# ---------------------------------------------------------------------------
# Internal data classes (not exposed via the API directly)
# ---------------------------------------------------------------------------


@dataclass
class ParsedRow:
    """A successfully parsed row from the uploaded CSV."""

    row_number: int
    full_name: str
    external_id: str | None


@dataclass
class DiffRow:
    """Analysis result for a single CSV row."""

    row_number: int
    full_name: str
    external_id: str | None
    status: ImportRowStatus
    message: str | None = None
    existing_student_id: uuid.UUID | None = None


@dataclass
class CsvParseResult:
    """Output of ``parse_csv_roster``."""

    rows: list[ParsedRow] = dc_field(default_factory=list)
    errors: list[DiffRow] = dc_field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def parse_csv_roster(content: bytes, *, max_rows: int = MAX_IMPORT_ROWS) -> CsvParseResult:
    """Parse CSV bytes into a list of ``ParsedRow`` items and row-level errors.

    Expected CSV columns (case-insensitive, whitespace-trimmed):
      - ``full_name``   — required
      - ``external_id`` — optional (LMS student ID)

    Raises:
        ValidationError: If the file cannot be decoded as UTF-8, the CSV has
            no header row, the required ``full_name`` column is absent, or the
            number of data rows exceeds ``max_rows``.
    """
    try:
        text = content.decode("utf-8-sig")  # "utf-8-sig" handles optional BOM
    except UnicodeDecodeError:
        raise ValidationError("CSV file must be UTF-8 encoded.", field="file") from None

    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise ValidationError("CSV file is empty or has no header row.", field="file")

    # Build a case-insensitive mapping of stripped header names.
    header_map: dict[str, str] = {h.strip().lower(): h for h in reader.fieldnames if h}

    if "full_name" not in header_map:
        raise ValidationError(
            "CSV must contain a 'full_name' column.",
            field="file",
        )

    full_name_col = header_map["full_name"]
    external_id_col: str | None = header_map.get("external_id")

    result = CsvParseResult()
    row_number = 0

    for row in reader:
        row_number += 1

        if row_number > max_rows:
            raise ValidationError(
                f"CSV exceeds the maximum of {max_rows} rows per import.",
                field="file",
            )

        raw_name = (row.get(full_name_col) or "").strip()
        raw_ext_id = (row.get(external_id_col) or "").strip() if external_id_col else ""

        if not raw_name:
            result.errors.append(
                DiffRow(
                    row_number=row_number,
                    full_name="",
                    external_id=None,
                    status=ImportRowStatus.ERROR,
                    message="Row is missing a required full_name value.",
                )
            )
            continue

        if len(raw_name) > MAX_NAME_LENGTH:
            result.errors.append(
                DiffRow(
                    row_number=row_number,
                    full_name=raw_name[:MAX_NAME_LENGTH],
                    external_id=None,
                    status=ImportRowStatus.ERROR,
                    message=f"full_name exceeds the {MAX_NAME_LENGTH}-character limit.",
                )
            )
            continue

        if raw_ext_id and len(raw_ext_id) > MAX_EXTERNAL_ID_LENGTH:
            result.errors.append(
                DiffRow(
                    row_number=row_number,
                    full_name=raw_name,
                    external_id=raw_ext_id[:MAX_EXTERNAL_ID_LENGTH],
                    status=ImportRowStatus.ERROR,
                    message=f"external_id exceeds the {MAX_EXTERNAL_ID_LENGTH}-character limit.",
                )
            )
            continue

        result.rows.append(
            ParsedRow(
                row_number=row_number,
                full_name=raw_name,
                external_id=raw_ext_id or None,
            )
        )

    return result


# ---------------------------------------------------------------------------
# Duplicate detection / diff building
# ---------------------------------------------------------------------------


async def build_import_diff(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    rows: list[ParsedRow],
) -> list[DiffRow]:
    """Analyse parsed rows against the existing class roster.

    For each row:
    - **SKIPPED** — external_id already actively enrolled in this class, or a
      student with a similar name (fuzzy match) is already enrolled, or the
      same external_id appears earlier in the batch.
    - **UPDATED** — external_id matches an existing student record owned by
      this teacher but not currently enrolled in this class; the student will
      be enrolled (and their name updated if it differs).
    - **NEW**     — no match found; a new student record will be created and
      enrolled.

    No database writes are performed.

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    await _assert_class_owned_by(db, class_id, teacher_id)

    # Load all students currently actively enrolled in this class.
    enrolled_result = await db.execute(
        select(Student.id, Student.full_name, Student.external_id)
        .join(ClassEnrollment, ClassEnrollment.student_id == Student.id)
        .where(
            ClassEnrollment.class_id == class_id,
            ClassEnrollment.removed_at.is_(None),
            Student.teacher_id == teacher_id,
        )
    )
    enrolled_students = enrolled_result.all()

    # Collect only the external_ids present in this CSV so the cross-class
    # lookup query does not load every student owned by the teacher.
    csv_external_ids = {
        row.external_id
        for row in rows
        if row.external_id
    }

    # Load only matching student records owned by this teacher (for
    # external_id look-up across classes — to find students that exist but
    # are not yet enrolled).
    if csv_external_ids:
        all_result = await db.execute(
            select(Student.id, Student.full_name, Student.external_id).where(
                Student.teacher_id == teacher_id,
                Student.external_id.in_(csv_external_ids),
            )
        )
        all_teacher_students = all_result.all()
    else:
        all_teacher_students = []

    # Build look-up structures.
    enrolled_by_ext_id: dict[str, uuid.UUID] = {
        s.external_id: s.id for s in enrolled_students if s.external_id
    }
    enrolled_names_lower: list[tuple[str, uuid.UUID]] = [
        (s.full_name.lower(), s.id) for s in enrolled_students
    ]
    all_by_ext_id: dict[str, uuid.UUID] = {
        s.external_id: s.id for s in all_teacher_students if s.external_id
    }

    diff: list[DiffRow] = []
    # Track external_ids seen earlier in this batch to detect intra-batch
    # duplicates without requiring a separate pass.
    batch_ext_ids_seen: set[str] = set()

    for row in rows:
        # --- intra-batch external_id duplicate ---
        if row.external_id and row.external_id in batch_ext_ids_seen:
            diff.append(
                DiffRow(
                    row_number=row.row_number,
                    full_name=row.full_name,
                    external_id=row.external_id,
                    status=ImportRowStatus.SKIPPED,
                    message="Duplicate external ID in this CSV (an earlier row has the same ID).",
                )
            )
            continue

        if row.external_id:
            batch_ext_ids_seen.add(row.external_id)

        # --- already enrolled (external_id match) ---
        if row.external_id and row.external_id in enrolled_by_ext_id:
            diff.append(
                DiffRow(
                    row_number=row.row_number,
                    full_name=row.full_name,
                    external_id=row.external_id,
                    status=ImportRowStatus.SKIPPED,
                    message="A student with this external ID is already enrolled in this class.",
                    existing_student_id=enrolled_by_ext_id[row.external_id],
                )
            )
            continue

        # --- existing student record found by external_id (not enrolled here) ---
        if row.external_id and row.external_id in all_by_ext_id:
            diff.append(
                DiffRow(
                    row_number=row.row_number,
                    full_name=row.full_name,
                    external_id=row.external_id,
                    status=ImportRowStatus.UPDATED,
                    message=(
                        "An existing student record was matched by external ID; "
                        "they will be enrolled in this class."
                    ),
                    existing_student_id=all_by_ext_id[row.external_id],
                )
            )
            continue

        # --- fuzzy name match with currently enrolled student ---
        if _fuzzy_name_match(row.full_name, enrolled_names_lower):
            diff.append(
                DiffRow(
                    row_number=row.row_number,
                    full_name=row.full_name,
                    external_id=row.external_id,
                    status=ImportRowStatus.SKIPPED,
                    message="A student with a very similar name is already enrolled in this class.",
                )
            )
            continue

        # --- new student ---
        diff.append(
            DiffRow(
                row_number=row.row_number,
                full_name=row.full_name,
                external_id=row.external_id,
                status=ImportRowStatus.NEW,
                message=None,
            )
        )

    return diff


def _fuzzy_name_match(
    name: str,
    enrolled_names_lower: list[tuple[str, uuid.UUID]],
) -> bool:
    """Return True if *name* is similar to any enrolled student's name.

    Uses :class:`difflib.SequenceMatcher` with :data:`FUZZY_MATCH_THRESHOLD`
    as the minimum similarity ratio.  Comparison is case-insensitive.
    """
    name_lower = name.lower()
    for enrolled_lower, _ in enrolled_names_lower:
        ratio = difflib.SequenceMatcher(None, name_lower, enrolled_lower).ratio()
        if ratio >= FUZZY_MATCH_THRESHOLD:
            return True
    return False


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


async def commit_roster_import(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    rows: list[ParsedRow],
) -> dict[str, int]:
    """Re-analyse rows and write approved students to the database.

    Calls :func:`build_import_diff` to re-determine the status of each row
    against the current roster state, then:

    - **NEW**     → creates a new :class:`Student` record and enrols them.
    - **UPDATED** → enrols the existing student (updates name if it differs).
    - **SKIPPED** → no-op (already enrolled or duplicate).

    Returns a dict with ``created``, ``updated``, and ``skipped`` counts.

    Raises:
        NotFoundError: If the class does not exist.
        ForbiddenError: If the class belongs to a different teacher.
    """
    # build_import_diff validates class ownership and loads roster state.
    diff_rows = await build_import_diff(db, teacher_id, class_id, rows)

    created = 0
    updated = 0
    skipped = 0

    for diff_row in diff_rows:
        if diff_row.status == ImportRowStatus.NEW:
            student = Student(
                teacher_id=teacher_id,
                full_name=diff_row.full_name,
                external_id=diff_row.external_id,
            )
            db.add(student)
            await db.flush()  # assign student.id before creating enrollment

            enrollment = ClassEnrollment(
                class_id=class_id,
                student_id=student.id,
            )
            db.add(enrollment)
            created += 1

        elif diff_row.status == ImportRowStatus.UPDATED:
            # Enrol an existing student who is not yet in this class.
            if diff_row.existing_student_id is None:
                skipped += 1
                continue

            student_result = await db.execute(
                select(Student).where(
                    Student.id == diff_row.existing_student_id,
                    Student.teacher_id == teacher_id,
                )
            )
            student_obj = student_result.scalar_one_or_none()
            if student_obj is None:
                skipped += 1
                continue

            # Update name if it differs (the CSV is treated as the source of truth).
            if student_obj.full_name != diff_row.full_name:
                student_obj.full_name = diff_row.full_name

            enrollment = ClassEnrollment(
                class_id=class_id,
                student_id=student_obj.id,
            )
            db.add(enrollment)
            updated += 1

        else:
            # SKIPPED — do not write anything.
            skipped += 1

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning(
            "Roster import commit conflict",
            extra={
                "class_id": str(class_id),
                "teacher_id": str(teacher_id),
                "rows_created": created,
                "rows_updated": updated,
                "rows_skipped": skipped,
            },
        )
        raise ValidationError(
            "Roster import could not be completed because the class roster"
            " changed during import. Please retry."
        ) from exc

    logger.info(
        "Roster import committed",
        extra={
            "class_id": str(class_id),
            "teacher_id": str(teacher_id),
            "rows_created": created,
            "rows_updated": updated,
            "rows_skipped": skipped,
        },
    )

    return {"created": created, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _assert_class_owned_by(
    db: AsyncSession,
    class_id: uuid.UUID,
    teacher_id: uuid.UUID,
) -> None:
    """Verify class existence and ownership.

    Raises :exc:`NotFoundError` if the class does not exist; raises
    :exc:`ForbiddenError` if it belongs to a different teacher.
    """
    result = await db.execute(select(Class.id, Class.teacher_id).where(Class.id == class_id))
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("Class not found.")
    if row.teacher_id != teacher_id:
        raise ForbiddenError("You do not have access to this class.")
