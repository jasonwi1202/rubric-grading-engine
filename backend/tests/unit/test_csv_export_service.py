"""Unit tests for app/services/csv_export.py.

All database calls are mocked — no real PostgreSQL.
No student PII in any fixture.

Coverage:
- _extract_criteria: ordering by display_order, missing display_order fallback.
- _build_csv: header row, data rows, criterion column ordering, missing scores.
- export_grades_csv: happy path (multiple locked grades), no locked grades
  (header-only CSV), cross-teacher access returns ForbiddenError,
  assignment not found returns NotFoundError, audit log entry is written.
"""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.services.csv_export import _build_csv, _extract_criteria, export_grades_csv

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_criterion(
    criterion_id: uuid.UUID | None = None,
    name: str = "Criterion",
    display_order: int = 1,
    min_score: int = 1,
    max_score: int = 5,
) -> dict:
    return {
        "id": str(criterion_id or _make_uuid()),
        "name": name,
        "display_order": display_order,
        "min_score": min_score,
        "max_score": max_score,
        "weight": 50.0,
    }


def _make_assignment_mock(criteria: list[dict]) -> MagicMock:
    a = MagicMock()
    a.id = _make_uuid()
    a.rubric_snapshot = {"criteria": criteria}
    return a


def _make_grade_row(
    grade_id: uuid.UUID | None = None,
    total_score: Decimal = Decimal("8"),
    student_id: uuid.UUID | None = None,
    full_name: str = "Student A",
) -> MagicMock:
    """Simulate a SQLAlchemy named-tuple row returned by the joined query."""
    row = MagicMock()
    row.id = grade_id or _make_uuid()
    row.total_score = total_score
    row.student_id = student_id or _make_uuid()
    row.full_name = full_name
    return row


def _make_criterion_score(
    grade_id: uuid.UUID,
    rubric_criterion_id: uuid.UUID,
    final_score: int = 4,
) -> MagicMock:
    cs = MagicMock()
    cs.grade_id = grade_id
    cs.rubric_criterion_id = rubric_criterion_id
    cs.final_score = final_score
    cs.created_at = MagicMock()
    return cs


def _scalars_mock(items: list) -> MagicMock:
    result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all = MagicMock(return_value=items)
    result.scalars = MagicMock(return_value=scalars_obj)
    return result


def _all_mock(items: list) -> MagicMock:
    result = MagicMock()
    result.all = MagicMock(return_value=items)
    return result


# ---------------------------------------------------------------------------
# Tests — _extract_criteria
# ---------------------------------------------------------------------------


class TestExtractCriteria:
    """Tests for the _extract_criteria helper."""

    def test_sorts_by_display_order(self) -> None:
        c1 = _make_criterion(name="First", display_order=1)
        c2 = _make_criterion(name="Second", display_order=2)
        c3 = _make_criterion(name="Third", display_order=3)
        snapshot = {"criteria": [c3, c1, c2]}

        result = _extract_criteria(snapshot)

        assert [c["name"] for c in result] == ["First", "Second", "Third"]

    def test_missing_display_order_falls_back_to_zero(self) -> None:
        c_no_order = {"id": str(_make_uuid()), "name": "NoOrder"}
        c_ordered = _make_criterion(name="Ordered", display_order=1)
        snapshot = {"criteria": [c_ordered, c_no_order]}

        result = _extract_criteria(snapshot)

        # c_no_order sorts before c_ordered because 0 < 1.
        assert result[0]["name"] == "NoOrder"
        assert result[1]["name"] == "Ordered"

    def test_empty_criteria_returns_empty_list(self) -> None:
        result = _extract_criteria({"criteria": []})
        assert result == []

    def test_missing_criteria_key_returns_empty_list(self) -> None:
        result = _extract_criteria({})
        assert result == []


# ---------------------------------------------------------------------------
# Tests — _build_csv
# ---------------------------------------------------------------------------


class TestBuildCsv:
    """Tests for the _build_csv helper."""

    def test_header_row_contains_expected_columns(self) -> None:
        criterion_id = _make_uuid()
        criteria = [_make_criterion(criterion_id=criterion_id, name="Writing Quality")]
        csv_content = _build_csv(criteria, [], {})

        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)
        assert header == ["student_id", "student_name", "Writing Quality", "weighted_total"]

    def test_data_row_maps_criterion_scores_by_id(self) -> None:
        criterion_id = _make_uuid()
        criteria = [_make_criterion(criterion_id=criterion_id, name="Argument")]
        grade_id = _make_uuid()
        row = _make_grade_row(grade_id=grade_id, total_score=Decimal("4"), full_name="Student B")
        grade_score_map = {grade_id: {str(criterion_id): 4}}

        csv_content = _build_csv(criteria, [row], grade_score_map)
        reader = csv.reader(io.StringIO(csv_content))
        next(reader)  # skip header
        data = next(reader)

        assert data[0] == str(row.student_id)
        assert data[1] == "Student B"
        assert data[2] == "4"
        assert data[3] == "4"

    def test_missing_criterion_score_uses_empty_string(self) -> None:
        criterion_id = _make_uuid()
        criteria = [_make_criterion(criterion_id=criterion_id, name="Evidence")]
        grade_id = _make_uuid()
        row = _make_grade_row(grade_id=grade_id)
        # grade_score_map is empty — no score recorded for this criterion.
        grade_score_map: dict = {}

        csv_content = _build_csv(criteria, [row], grade_score_map)
        reader = csv.reader(io.StringIO(csv_content))
        next(reader)  # skip header
        data = next(reader)

        assert data[2] == ""

    def test_criterion_columns_in_display_order(self) -> None:
        id_a = _make_uuid()
        id_b = _make_uuid()
        # Criteria deliberately supplied in reverse order to _build_csv.
        # The caller is responsible for pre-sorting; _build_csv preserves order.
        criteria = [
            _make_criterion(criterion_id=id_a, name="Alpha", display_order=1),
            _make_criterion(criterion_id=id_b, name="Beta", display_order=2),
        ]
        csv_content = _build_csv(criteria, [], {})
        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)

        assert header[2] == "Alpha"
        assert header[3] == "Beta"

    def test_no_locked_grades_produces_header_only(self) -> None:
        criteria = [_make_criterion(name="Criterion X")]
        csv_content = _build_csv(criteria, [], {})

        lines = [line for line in csv_content.splitlines() if line]
        # Only the header line.
        assert len(lines) == 1

    def test_student_id_none_renders_as_empty_string(self) -> None:
        criteria = [_make_criterion(name="Style")]
        grade_id = _make_uuid()
        row = _make_grade_row(grade_id=grade_id)
        row.student_id = None

        csv_content = _build_csv(criteria, [row], {})
        reader = csv.reader(io.StringIO(csv_content))
        next(reader)  # skip header
        data = next(reader)

        assert data[0] == ""

    def test_multiple_rows_in_output(self) -> None:
        criterion_id = _make_uuid()
        criteria = [_make_criterion(criterion_id=criterion_id, name="Structure")]
        gid1, gid2 = _make_uuid(), _make_uuid()
        row1 = _make_grade_row(grade_id=gid1, total_score=Decimal("3"), full_name="Student C")
        row2 = _make_grade_row(grade_id=gid2, total_score=Decimal("5"), full_name="Student D")
        score_map = {
            gid1: {str(criterion_id): 3},
            gid2: {str(criterion_id): 5},
        }

        csv_content = _build_csv(criteria, [row1, row2], score_map)
        rows = list(csv.reader(io.StringIO(csv_content)))

        assert len(rows) == 3  # header + 2 data rows
        assert rows[1][1] == "Student C"
        assert rows[2][1] == "Student D"


# ---------------------------------------------------------------------------
# Tests — export_grades_csv (service integration with mocked DB)
# ---------------------------------------------------------------------------


class TestExportGradesCsv:
    """Tests for the export_grades_csv service function."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_valid_csv(self) -> None:
        """Returns a CSV with header and one data row for a locked grade."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()
        criterion_id = _make_uuid()
        grade_id = _make_uuid()

        assignment = _make_assignment_mock(
            [_make_criterion(criterion_id=criterion_id, name="Thesis", display_order=1)]
        )

        row = _make_grade_row(grade_id=grade_id, total_score=Decimal("4"), full_name="Student E")
        cs = _make_criterion_score(
            grade_id=grade_id,
            rubric_criterion_id=criterion_id,
            final_score=4,
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.csv_export.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            db.execute = AsyncMock(
                side_effect=[
                    _all_mock([row]),  # locked grades query
                    _scalars_mock([cs]),  # criterion scores query
                ]
            )
            csv_content = await export_grades_csv(db, assignment_id, teacher_id)

        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)
        assert "Thesis" in header
        data = next(reader)
        assert data[1] == "Student E"
        assert data[2] == "4"  # criterion score
        assert data[-1] == "4"  # weighted_total

        # Audit log entry must have been inserted.
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_locked_grades_returns_header_only(self) -> None:
        """Returns a header-only CSV when no grades are locked."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()
        criterion_id = _make_uuid()

        assignment = _make_assignment_mock(
            [_make_criterion(criterion_id=criterion_id, name="Evidence", display_order=1)]
        )

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.csv_export.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            db.execute = AsyncMock(return_value=_all_mock([]))
            csv_content = await export_grades_csv(db, assignment_id, teacher_id)

        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader)
        assert header == ["student_id", "student_name", "Evidence", "weighted_total"]
        # No data rows.
        with pytest.raises(StopIteration):
            next(reader)

        # Audit log entry must still be written even for an empty export.
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_assignment_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when the assignment does not exist."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()

        db = AsyncMock()

        with (
            patch(
                "app.services.csv_export.get_assignment",
                new=AsyncMock(side_effect=NotFoundError("Assignment not found.")),
            ),
            pytest.raises(NotFoundError),
        ):
            await export_grades_csv(db, assignment_id, teacher_id)

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when the assignment belongs to another teacher."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()

        db = AsyncMock()

        with (
            patch(
                "app.services.csv_export.get_assignment",
                new=AsyncMock(
                    side_effect=ForbiddenError("You do not have access to this assignment.")
                ),
            ),
            pytest.raises(ForbiddenError),
        ):
            await export_grades_csv(db, assignment_id, teacher_id)

    @pytest.mark.asyncio
    async def test_audit_log_written_with_correct_format(self) -> None:
        """The audit log entry records format='csv' in after_value."""
        teacher_id = _make_uuid()
        assignment_id = _make_uuid()

        assignment = _make_assignment_mock([])

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.csv_export.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            db.execute = AsyncMock(return_value=_all_mock([]))
            await export_grades_csv(db, assignment_id, teacher_id)

        # Inspect the AuditLog object passed to db.add().
        call_args = db.add.call_args
        audit_obj = call_args.args[0]
        assert audit_obj.action == "export_requested"
        assert audit_obj.entity_type == "export"
        assert audit_obj.after_value["format"] == "csv"
        assert audit_obj.after_value["assignment_id"] == str(assignment_id)
        assert audit_obj.teacher_id == teacher_id
