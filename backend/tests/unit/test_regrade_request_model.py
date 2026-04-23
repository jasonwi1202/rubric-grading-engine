"""Unit tests for the RegradeRequest ORM model added in M4.7.

Tests verify:
- Model imports without errors
- ``__tablename__`` is ``regrade_requests``
- All expected columns are present in ``Base.metadata``
- Key column attributes (nullable, type family) match the acceptance criteria
- ``RegradeRequestStatus`` enum has the correct values
- Relationships to ``Grade`` and ``CriterionScore`` are declared
- Migration revision chain is wired correctly
"""

import importlib

import app.models.grade  # noqa: F401 — ensures Grade/CriterionScore are registered so relationship targets resolve
from app.models.base import Base
from app.models.regrade_request import RegradeRequest, RegradeRequestStatus

# ---------------------------------------------------------------------------
# Helpers (mirrors pattern in test_core_models.py and test_integrity_report_model.py)
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
# RegradeRequest
# ---------------------------------------------------------------------------


class TestRegradeRequestModel:
    def test_tablename(self) -> None:
        assert RegradeRequest.__tablename__ == "regrade_requests"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["regrade_requests"]
        expected = {
            "id",
            "grade_id",
            "criterion_score_id",
            "teacher_id",
            "dispute_text",
            "status",
            "resolution_note",
            "resolved_at",
            "created_at",
        }
        assert expected <= set(table.c.keys()), (
            f"Missing columns: {expected - set(table.c.keys())}"
        )

    def test_id_is_uuid(self) -> None:
        assert _type_name(RegradeRequest, "id") == "UUID"

    def test_grade_id_not_nullable(self) -> None:
        assert not _is_nullable(RegradeRequest, "grade_id")

    def test_grade_id_is_uuid(self) -> None:
        assert _type_name(RegradeRequest, "grade_id") == "UUID"

    def test_criterion_score_id_nullable(self) -> None:
        """criterion_score_id is nullable — a request may target the whole grade."""
        assert _is_nullable(RegradeRequest, "criterion_score_id")

    def test_criterion_score_id_is_uuid(self) -> None:
        assert _type_name(RegradeRequest, "criterion_score_id") == "UUID"

    def test_teacher_id_not_nullable(self) -> None:
        assert not _is_nullable(RegradeRequest, "teacher_id")

    def test_teacher_id_is_uuid(self) -> None:
        assert _type_name(RegradeRequest, "teacher_id") == "UUID"

    def test_dispute_text_not_nullable(self) -> None:
        assert not _is_nullable(RegradeRequest, "dispute_text")

    def test_dispute_text_is_text(self) -> None:
        assert _type_name(RegradeRequest, "dispute_text") == "Text"

    def test_status_not_nullable(self) -> None:
        assert not _is_nullable(RegradeRequest, "status")

    def test_resolution_note_nullable(self) -> None:
        assert _is_nullable(RegradeRequest, "resolution_note")

    def test_resolution_note_is_text(self) -> None:
        assert _type_name(RegradeRequest, "resolution_note") == "Text"

    def test_resolved_at_nullable(self) -> None:
        assert _is_nullable(RegradeRequest, "resolved_at")

    def test_created_at_not_nullable(self) -> None:
        assert not _is_nullable(RegradeRequest, "created_at")

    def test_regrade_request_status_enum_values(self) -> None:
        values = {s.value for s in RegradeRequestStatus}
        assert values == {"open", "approved", "denied"}

    def test_model_has_grade_relationship(self) -> None:
        """RegradeRequest must declare a relationship to Grade."""
        from sqlalchemy.orm import RelationshipProperty

        mapper = RegradeRequest.__mapper__
        assert "grade" in mapper.relationships
        rel: RelationshipProperty[object] = mapper.relationships["grade"]
        assert rel.mapper.class_.__name__ == "Grade"

    def test_model_has_criterion_score_relationship(self) -> None:
        """RegradeRequest must declare a relationship to CriterionScore."""
        from sqlalchemy.orm import RelationshipProperty

        mapper = RegradeRequest.__mapper__
        assert "criterion_score" in mapper.relationships
        rel: RelationshipProperty[object] = mapper.relationships["criterion_score"]
        assert rel.mapper.class_.__name__ == "CriterionScore"


# ---------------------------------------------------------------------------
# Migration revision chain
# ---------------------------------------------------------------------------


class TestMigrationRevisionChain:
    """Verify that 017_regrade_request is wired correctly in the Alembic chain."""

    def test_revision_id(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_017_regrade_request_create_regrade_requests_table"
        )
        assert mod.revision == "017_regrade_request"

    def test_down_revision_points_to_016(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_017_regrade_request_create_regrade_requests_table"
        )
        assert mod.down_revision == "016_integrity_report_reviewed_at"

    def test_upgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_017_regrade_request_create_regrade_requests_table"
        )
        assert callable(mod.upgrade)

    def test_downgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_017_regrade_request_create_regrade_requests_table"
        )
        assert callable(mod.downgrade)
