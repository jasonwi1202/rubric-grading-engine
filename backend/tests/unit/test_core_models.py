"""Unit tests for the core grading-domain ORM models added in M3.1.

Tests verify:
- All new models import without errors
- Each model declares the expected ``__tablename__``
- Each model's columns are registered in ``Base.metadata``
- Key column attributes (nullable, type family) match ``docs/architecture/data-model.md``

No database connection is required — SQLAlchemy populates metadata at import
time, so all assertions work against in-memory model definitions.
"""

from app.models.assignment import Assignment, AssignmentStatus
from app.models.base import Base
from app.models.class_ import Class
from app.models.class_enrollment import ClassEnrollment
from app.models.essay import Essay, EssayStatus, EssayVersion
from app.models.grade import ConfidenceLevel, CriterionScore, Grade, StrictnessLevel
from app.models.rubric import Rubric, RubricCriterion
from app.models.student import Student

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(model: type, name: str) -> object:
    """Return the Column object from Base.metadata for a given model + column name."""
    table = Base.metadata.tables[model.__tablename__]  # type: ignore[attr-defined]
    assert name in table.c, f"Column '{name}' not found in table '{model.__tablename__}'"
    return table.c[name]


def _is_nullable(model: type, name: str) -> bool:
    col = _col(model, name)
    return col.nullable  # type: ignore[union-attr]


def _type_name(model: type, name: str) -> str:
    col = _col(model, name)
    return type(col.type).__name__  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Class
# ---------------------------------------------------------------------------


class TestClassModel:
    def test_tablename(self) -> None:
        assert Class.__tablename__ == "classes"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["classes"]
        expected = {
            "id",
            "teacher_id",
            "name",
            "subject",
            "grade_level",
            "academic_year",
            "is_archived",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_is_archived_not_nullable(self) -> None:
        assert not _is_nullable(Class, "is_archived")

    def test_teacher_id_not_nullable(self) -> None:
        assert not _is_nullable(Class, "teacher_id")

    def test_created_at_not_nullable(self) -> None:
        assert not _is_nullable(Class, "created_at")


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


class TestStudentModel:
    def test_tablename(self) -> None:
        assert Student.__tablename__ == "students"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["students"]
        expected = {"id", "teacher_id", "full_name", "external_id", "created_at"}
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_external_id_nullable(self) -> None:
        assert _is_nullable(Student, "external_id")

    def test_teacher_id_not_nullable(self) -> None:
        assert not _is_nullable(Student, "teacher_id")

    def test_full_name_is_string(self) -> None:
        assert _type_name(Student, "full_name") == "String"


# ---------------------------------------------------------------------------
# ClassEnrollment
# ---------------------------------------------------------------------------


class TestClassEnrollmentModel:
    def test_tablename(self) -> None:
        assert ClassEnrollment.__tablename__ == "class_enrollments"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["class_enrollments"]
        expected = {"id", "class_id", "student_id", "enrolled_at", "removed_at"}
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_removed_at_nullable(self) -> None:
        assert _is_nullable(ClassEnrollment, "removed_at")

    def test_class_id_not_nullable(self) -> None:
        assert not _is_nullable(ClassEnrollment, "class_id")

    def test_no_full_unique_constraint_on_enrollment(self) -> None:
        """The full (class_id, student_id) unique constraint must NOT be on the ORM
        model because the real constraint is a partial index WHERE removed_at IS NULL,
        which cannot be expressed via SQLAlchemy UniqueConstraint.
        Presence of a full unique constraint would incorrectly prevent re-enrollment
        after removal.
        """
        table = Base.metadata.tables["class_enrollments"]
        for uq in table.constraints:
            if hasattr(uq, "columns"):
                col_names = {c.name for c in uq.columns}
                assert col_names != {"class_id", "student_id"}, (
                    "Found a full UniqueConstraint on (class_id, student_id) — "
                    "must be a migration-level partial index instead."
                )


# ---------------------------------------------------------------------------
# Rubric + RubricCriterion
# ---------------------------------------------------------------------------


class TestRubricModel:
    def test_tablename(self) -> None:
        assert Rubric.__tablename__ == "rubrics"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["rubrics"]
        expected = {
            "id",
            "teacher_id",
            "name",
            "description",
            "is_template",
            "created_at",
            "updated_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_description_nullable(self) -> None:
        assert _is_nullable(Rubric, "description")

    def test_is_template_not_nullable(self) -> None:
        assert not _is_nullable(Rubric, "is_template")


class TestRubricCriterionModel:
    def test_tablename(self) -> None:
        assert RubricCriterion.__tablename__ == "rubric_criteria"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["rubric_criteria"]
        expected = {
            "id",
            "rubric_id",
            "name",
            "description",
            "weight",
            "min_score",
            "max_score",
            "display_order",
            "anchor_descriptions",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_anchor_descriptions_nullable(self) -> None:
        assert _is_nullable(RubricCriterion, "anchor_descriptions")

    def test_weight_is_numeric(self) -> None:
        assert _type_name(RubricCriterion, "weight") == "Numeric"

    def test_anchor_descriptions_is_jsonb(self) -> None:
        assert _type_name(RubricCriterion, "anchor_descriptions") == "JSONB"


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


class TestAssignmentModel:
    def test_tablename(self) -> None:
        assert Assignment.__tablename__ == "assignments"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["assignments"]
        expected = {
            "id",
            "class_id",
            "rubric_id",
            "rubric_snapshot",
            "title",
            "prompt",
            "due_date",
            "status",
            "resubmission_enabled",
            "resubmission_limit",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_rubric_snapshot_not_nullable(self) -> None:
        assert not _is_nullable(Assignment, "rubric_snapshot")

    def test_rubric_snapshot_is_jsonb(self) -> None:
        assert _type_name(Assignment, "rubric_snapshot") == "JSONB"

    def test_prompt_nullable(self) -> None:
        assert _is_nullable(Assignment, "prompt")

    def test_due_date_nullable(self) -> None:
        assert _is_nullable(Assignment, "due_date")

    def test_resubmission_limit_nullable(self) -> None:
        assert _is_nullable(Assignment, "resubmission_limit")

    def test_assignment_status_enum_values(self) -> None:
        values = {s.value for s in AssignmentStatus}
        assert values == {"draft", "open", "grading", "review", "complete", "returned"}


# ---------------------------------------------------------------------------
# Essay + EssayVersion
# ---------------------------------------------------------------------------


class TestEssayModel:
    def test_tablename(self) -> None:
        assert Essay.__tablename__ == "essays"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["essays"]
        expected = {
            "id",
            "assignment_id",
            "student_id",
            "status",
            "submitted_at",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_student_id_nullable(self) -> None:
        """student_id is nullable until the uploaded file is assigned to a student."""
        assert _is_nullable(Essay, "student_id")

    def test_submitted_at_nullable(self) -> None:
        assert _is_nullable(Essay, "submitted_at")

    def test_essay_status_enum_values(self) -> None:
        values = {s.value for s in EssayStatus}
        assert values == {
            "unassigned",
            "queued",
            "grading",
            "graded",
            "reviewed",
            "locked",
            "returned",
        }


class TestEssayVersionModel:
    def test_tablename(self) -> None:
        assert EssayVersion.__tablename__ == "essay_versions"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["essay_versions"]
        expected = {
            "id",
            "essay_id",
            "version_number",
            "content",
            "file_storage_key",
            "word_count",
            "submitted_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_file_storage_key_nullable(self) -> None:
        assert _is_nullable(EssayVersion, "file_storage_key")

    def test_content_not_nullable(self) -> None:
        assert not _is_nullable(EssayVersion, "content")

    def test_version_number_is_integer(self) -> None:
        assert _type_name(EssayVersion, "version_number") == "Integer"


# ---------------------------------------------------------------------------
# Grade + CriterionScore
# ---------------------------------------------------------------------------


class TestGradeModel:
    def test_tablename(self) -> None:
        assert Grade.__tablename__ == "grades"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["grades"]
        expected = {
            "id",
            "essay_version_id",
            "total_score",
            "max_possible_score",
            "summary_feedback",
            "summary_feedback_edited",
            "strictness",
            "ai_model",
            "prompt_version",
            "is_locked",
            "locked_at",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_summary_feedback_edited_nullable(self) -> None:
        assert _is_nullable(Grade, "summary_feedback_edited")

    def test_locked_at_nullable(self) -> None:
        assert _is_nullable(Grade, "locked_at")

    def test_is_locked_not_nullable(self) -> None:
        assert not _is_nullable(Grade, "is_locked")

    def test_prompt_version_present(self) -> None:
        """prompt_version must exist — required by LLM audit trail spec."""
        assert not _is_nullable(Grade, "prompt_version")

    def test_strictness_level_enum_values(self) -> None:
        values = {s.value for s in StrictnessLevel}
        assert values == {"lenient", "balanced", "strict"}


class TestCriterionScoreModel:
    def test_tablename(self) -> None:
        assert CriterionScore.__tablename__ == "criterion_scores"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["criterion_scores"]
        expected = {
            "id",
            "grade_id",
            "rubric_criterion_id",
            "ai_score",
            "teacher_score",
            "final_score",
            "ai_justification",
            "teacher_feedback",
            "confidence",
            "created_at",
        }
        assert expected <= set(table.c.keys()), f"Missing columns: {expected - set(table.c.keys())}"

    def test_teacher_score_nullable(self) -> None:
        """teacher_score is only set if the teacher overrides the AI score."""
        assert _is_nullable(CriterionScore, "teacher_score")

    def test_teacher_feedback_nullable(self) -> None:
        assert _is_nullable(CriterionScore, "teacher_feedback")

    def test_final_score_not_nullable(self) -> None:
        assert not _is_nullable(CriterionScore, "final_score")

    def test_confidence_level_enum_values(self) -> None:
        values = {c.value for c in ConfidenceLevel}
        assert values == {"high", "medium", "low"}


# ---------------------------------------------------------------------------
# Migration revision chain
# ---------------------------------------------------------------------------


class TestMigrationRevisionChain:
    """Verify that 006_core_schema is wired correctly in the Alembic chain."""

    def test_revision_id(self) -> None:
        import importlib

        mod = importlib.import_module(
            "app.db.migrations.versions.20260418_006_core_schema_create_core_schema"
        )
        assert mod.revision == "006_core_schema"

    def test_down_revision_points_to_005(self) -> None:
        import importlib

        mod = importlib.import_module(
            "app.db.migrations.versions.20260418_006_core_schema_create_core_schema"
        )
        assert mod.down_revision == "005_users_onboarding"

    def test_upgrade_callable(self) -> None:
        import importlib

        mod = importlib.import_module(
            "app.db.migrations.versions.20260418_006_core_schema_create_core_schema"
        )
        assert callable(mod.upgrade)

    def test_downgrade_callable(self) -> None:
        import importlib

        mod = importlib.import_module(
            "app.db.migrations.versions.20260418_006_core_schema_create_core_schema"
        )
        assert callable(mod.downgrade)
