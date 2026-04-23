"""Unit tests for the IntegrityReport ORM model added in M4.3.

Tests verify:
- Model imports without errors
- ``__tablename__`` is ``integrity_reports``
- All expected columns are present in ``Base.metadata``
- Key column attributes (nullable, type family) match the acceptance criteria
- ``IntegrityReportStatus`` enum has the correct values
- Migration revision chain is wired correctly
"""

import importlib

from app.models.base import Base
from app.models.integrity_report import IntegrityReport, IntegrityReportStatus

# ---------------------------------------------------------------------------
# Helpers (mirrors pattern in test_core_models.py)
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
# IntegrityReport
# ---------------------------------------------------------------------------


class TestIntegrityReportModel:
    def test_tablename(self) -> None:
        assert IntegrityReport.__tablename__ == "integrity_reports"

    def test_expected_columns_present(self) -> None:
        table = Base.metadata.tables["integrity_reports"]
        expected = {
            "id",
            "essay_version_id",
            "teacher_id",
            "provider",
            "ai_likelihood",
            "similarity_score",
            "flagged_passages",
            "status",
            "created_at",
            "updated_at",
        }
        assert expected <= set(table.c.keys()), (
            f"Missing columns: {expected - set(table.c.keys())}"
        )

    def test_id_is_uuid(self) -> None:
        assert _type_name(IntegrityReport, "id") == "UUID"

    def test_essay_version_id_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "essay_version_id")

    def test_teacher_id_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "teacher_id")

    def test_provider_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "provider")

    def test_provider_is_string(self) -> None:
        assert _type_name(IntegrityReport, "provider") == "String"

    def test_ai_likelihood_nullable(self) -> None:
        assert _is_nullable(IntegrityReport, "ai_likelihood")

    def test_ai_likelihood_is_float(self) -> None:
        assert _type_name(IntegrityReport, "ai_likelihood") == "Float"

    def test_similarity_score_nullable(self) -> None:
        assert _is_nullable(IntegrityReport, "similarity_score")

    def test_similarity_score_is_float(self) -> None:
        assert _type_name(IntegrityReport, "similarity_score") == "Float"

    def test_flagged_passages_nullable(self) -> None:
        assert _is_nullable(IntegrityReport, "flagged_passages")

    def test_flagged_passages_is_jsonb(self) -> None:
        assert _type_name(IntegrityReport, "flagged_passages") == "JSONB"

    def test_status_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "status")

    def test_created_at_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "created_at")

    def test_updated_at_not_nullable(self) -> None:
        assert not _is_nullable(IntegrityReport, "updated_at")

    def test_integrity_report_status_enum_values(self) -> None:
        values = {s.value for s in IntegrityReportStatus}
        assert values == {"pending", "reviewed_clear", "flagged"}

    def test_model_has_essay_version_relationship(self) -> None:
        """IntegrityReport must declare a relationship to EssayVersion."""
        from sqlalchemy.orm import RelationshipProperty

        mapper = IntegrityReport.__mapper__  # type: ignore[attr-defined]
        assert "essay_version" in mapper.relationships
        rel: RelationshipProperty = mapper.relationships["essay_version"]
        assert rel.mapper.class_.__name__ == "EssayVersion"


# ---------------------------------------------------------------------------
# Migration revision chain
# ---------------------------------------------------------------------------


class TestMigrationRevisionChain:
    """Verify that 013_integrity_report is wired correctly in the Alembic chain."""

    def test_revision_id(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_013_integrity_report_create_integrity_reports_table"
        )
        assert mod.revision == "013_integrity_report"

    def test_down_revision_points_to_012(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_013_integrity_report_create_integrity_reports_table"
        )
        assert mod.down_revision == "012_confidence_scoring"

    def test_upgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_013_integrity_report_create_integrity_reports_table"
        )
        assert callable(mod.upgrade)

    def test_downgrade_callable(self) -> None:
        mod = importlib.import_module(
            "app.db.migrations.versions"
            ".20260423_013_integrity_report_create_integrity_reports_table"
        )
        assert callable(mod.downgrade)
