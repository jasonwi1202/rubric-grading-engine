"""Unit tests for app/services/grading.py.

All database and LLM calls are mocked — no real PostgreSQL, no real OpenAI.
No student PII in any fixture.

Coverage:
- Happy path: grade written, criterion scores written, essay status updated.
- score_clamped: audit log entry written when parser flags clamping.
- Missing criterion (score=None): written with ai_score=0.
- Not found / forbidden: raises NotFoundError / ForbiddenError.
- LLMError propagates without writing any DB records.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, LLMError, LLMParseError, NotFoundError
from app.llm.parsers import ParsedCriterionScore, ParsedGradingResponse
from app.models.essay import EssayStatus
from app.services.grading import grade_essay

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_essay(
    essay_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    status: EssayStatus = EssayStatus.queued,
) -> MagicMock:
    essay = MagicMock()
    essay.id = essay_id or _make_uuid()
    essay.assignment_id = assignment_id or _make_uuid()
    essay.status = status
    return essay


def _make_essay_version(
    essay_id: uuid.UUID,
    version_number: int = 1,
    content: str = "This is the student essay text for testing.",
) -> MagicMock:
    ev = MagicMock()
    ev.id = _make_uuid()
    ev.essay_id = essay_id
    ev.version_number = version_number
    ev.content = content
    return ev


def _make_assignment(
    assignment_id: uuid.UUID | None = None,
    rubric_snapshot: dict | None = None,
) -> MagicMock:
    crit_id = str(_make_uuid())
    a = MagicMock()
    a.id = assignment_id or _make_uuid()
    a.rubric_snapshot = rubric_snapshot or {
        "id": str(_make_uuid()),
        "name": "Test Rubric",
        "criteria": [
            {
                "id": crit_id,
                "name": "Thesis",
                "description": "Argument quality",
                "weight": 100.0,
                "min_score": 1,
                "max_score": 5,
                "display_order": 0,
                "anchor_descriptions": None,
            }
        ],
    }
    return a


def _make_grading_response(
    criterion_id: str,
    score: int = 3,
    score_clamped: bool = False,
    needs_review: bool = False,
    confidence: str = "high",
) -> ParsedGradingResponse:
    return ParsedGradingResponse(
        criterion_scores=[
            ParsedCriterionScore(
                criterion_id=criterion_id,
                score=score,
                justification="A sufficiently long justification string for testing purposes.",
                confidence=confidence,
                score_clamped=score_clamped,
                needs_review=needs_review,
            )
        ],
        summary_feedback="Good essay with clear structure and argumentation.",
    )


def _make_db_mock(
    essay: MagicMock | None = None,
    essay_exists: bool = True,
    essay_version: MagicMock | None = None,
    assignment: MagicMock | None = None,
) -> AsyncMock:
    """Build a minimal AsyncSession mock that returns the provided ORM objects."""
    db = AsyncMock()
    db.add = MagicMock()  # synchronous — must NOT be AsyncMock

    def _scalar_one_or_none_for(result_mock: MagicMock, value: object) -> None:
        result_mock.scalar_one_or_none = MagicMock(return_value=value)

    # We have up to 4 execute() calls in grade_essay:
    # 1. Load essay (tenant-scoped join)
    # 2. [only if essay is None] existence check
    # 3. Load latest EssayVersion
    # 4. Load assignment (tenant-scoped join)

    results: list[MagicMock] = []

    if essay is not None:
        # execute #1 — essay found via tenant-scoped join
        r1 = MagicMock()
        r1.scalar_one_or_none = MagicMock(return_value=essay)
        results.append(r1)
    elif essay_exists:
        # execute #1 — tenant-scoped join returns None (wrong teacher)
        r1 = MagicMock()
        r1.scalar_one_or_none = MagicMock(return_value=None)
        results.append(r1)
        # execute #2 — existence check returns a UUID (essay exists, different teacher)
        r2 = MagicMock()
        r2.scalar_one_or_none = MagicMock(return_value=_make_uuid())
        results.append(r2)
    else:
        # execute #1 — tenant-scoped join returns None
        r1 = MagicMock()
        r1.scalar_one_or_none = MagicMock(return_value=None)
        results.append(r1)
        # execute #2 — existence check returns None (essay doesn't exist)
        r2 = MagicMock()
        r2.scalar_one_or_none = MagicMock(return_value=None)
        results.append(r2)

    if essay is not None:
        # execute #3 — essay version
        r3 = MagicMock()
        r3.scalar_one_or_none = MagicMock(return_value=essay_version)
        results.append(r3)
        # execute #4 — assignment
        r4 = MagicMock()
        r4.scalar_one_or_none = MagicMock(return_value=assignment)
        results.append(r4)

    db.execute = AsyncMock(side_effect=results)
    return db


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestGradeEssayHappyPath:
    @pytest.mark.asyncio
    async def test_returns_grade_record(self) -> None:
        """grade_essay returns the created Grade record on success."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        grading_resp = _make_grading_response(criterion_id=criterion_id, score=4)

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        # db.add called at least twice (Grade + CriterionScore)
        assert db.add.call_count >= 2
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_essay_status_set_to_graded(self) -> None:
        """Essay status is updated to EssayStatus.graded after grading."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        grading_resp = _make_grading_response(criterion_id=criterion_id, score=3)

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        assert essay.status == EssayStatus.graded

    @pytest.mark.asyncio
    async def test_grade_prompt_version_stored(self) -> None:
        """Grade.prompt_version is set to 'grading-{version}'."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        grading_resp = _make_grading_response(criterion_id=criterion_id, score=3)

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with (
            patch("app.services.grading.call_grading", return_value=grading_resp),
            patch("app.services.grading.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v1"
            mock_settings.openai_grading_model = "gpt-4o"
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.grade import Grade as GradeModel

        grade_objs = [o for o in added_objects if isinstance(o, GradeModel)]
        assert len(grade_objs) == 1, "Expected exactly one Grade record to be added"
        assert grade_objs[0].prompt_version == "grading-v1"

    @pytest.mark.asyncio
    async def test_total_score_computed_correctly(self) -> None:
        """total_score sums criterion scores; max_possible_score sums max values."""
        teacher_id = _make_uuid()
        crit1_id = str(_make_uuid())
        crit2_id = str(_make_uuid())
        snapshot = {
            "id": str(_make_uuid()),
            "name": "Two-criterion Rubric",
            "criteria": [
                {
                    "id": crit1_id,
                    "name": "Thesis",
                    "description": "Argument",
                    "weight": 50.0,
                    "min_score": 1,
                    "max_score": 5,
                    "display_order": 0,
                    "anchor_descriptions": None,
                },
                {
                    "id": crit2_id,
                    "name": "Evidence",
                    "description": "Support",
                    "weight": 50.0,
                    "min_score": 1,
                    "max_score": 5,
                    "display_order": 1,
                    "anchor_descriptions": None,
                },
            ],
        }
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id, rubric_snapshot=snapshot)

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)

        grading_resp = ParsedGradingResponse(
            criterion_scores=[
                ParsedCriterionScore(
                    criterion_id=crit1_id,
                    score=4,
                    justification="A clear and specific justification meeting the minimum length.",
                    confidence="high",
                ),
                ParsedCriterionScore(
                    criterion_id=crit2_id,
                    score=3,
                    justification="Supporting evidence is adequate and relevant to the argument.",
                    confidence="medium",
                ),
            ],
            summary_feedback="Solid essay with well-developed arguments.",
        )

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.grade import Grade as GradeModel

        grade_objs = [o for o in added_objects if isinstance(o, GradeModel)]
        assert len(grade_objs) == 1
        assert grade_objs[0].total_score == Decimal("7")
        assert grade_objs[0].max_possible_score == Decimal("10")


# ---------------------------------------------------------------------------
# Tests — score_clamped audit log
# ---------------------------------------------------------------------------


class TestScoreClampedAuditLog:
    @pytest.mark.asyncio
    async def test_score_clamped_writes_audit_entry(self) -> None:
        """When parser flags score_clamped=True, an audit_log entry is written."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)

        grading_resp = _make_grading_response(
            criterion_id=criterion_id,
            score=1,
            score_clamped=True,
            needs_review=True,
            confidence="low",
        )

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 1, "Expected one score_clamped audit entry"
        entry = audit_entries[0]
        assert entry.action == "score_clamped"
        assert entry.entity_type == "criterion_score"
        assert entry.teacher_id is None  # System-generated event

    @pytest.mark.asyncio
    async def test_no_audit_entry_when_score_not_clamped(self) -> None:
        """No score_clamped audit entry is written when the score is in range."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        grading_resp = _make_grading_response(
            criterion_id=criterion_id,
            score=3,
            score_clamped=False,
        )

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 0, "No audit entry expected when score is not clamped"

    @pytest.mark.asyncio
    async def test_multiple_clamped_scores_each_get_audit_entry(self) -> None:
        """Each clamped criterion score gets its own audit log entry."""
        teacher_id = _make_uuid()
        crit1_id = str(_make_uuid())
        crit2_id = str(_make_uuid())
        snapshot = {
            "id": str(_make_uuid()),
            "name": "Multi-criterion Rubric",
            "criteria": [
                {
                    "id": crit1_id,
                    "name": "Thesis",
                    "description": "Argument",
                    "weight": 50.0,
                    "min_score": 1,
                    "max_score": 5,
                    "display_order": 0,
                    "anchor_descriptions": None,
                },
                {
                    "id": crit2_id,
                    "name": "Evidence",
                    "description": "Support",
                    "weight": 50.0,
                    "min_score": 1,
                    "max_score": 5,
                    "display_order": 1,
                    "anchor_descriptions": None,
                },
            ],
        }
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id, rubric_snapshot=snapshot)

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)

        grading_resp = ParsedGradingResponse(
            criterion_scores=[
                ParsedCriterionScore(
                    criterion_id=crit1_id,
                    score=1,
                    justification="A sufficiently long justification for the first criterion.",
                    confidence="low",
                    score_clamped=True,
                    needs_review=True,
                ),
                ParsedCriterionScore(
                    criterion_id=crit2_id,
                    score=5,
                    justification="A sufficiently long justification for the second criterion.",
                    confidence="low",
                    score_clamped=True,
                    needs_review=True,
                ),
            ],
            summary_feedback="Multiple scores were clamped during this grading.",
        )

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.audit_log import AuditLog as AuditLogModel

        audit_entries = [o for o in added_objects if isinstance(o, AuditLogModel)]
        assert len(audit_entries) == 2, (
            f"Expected 2 score_clamped entries, got {len(audit_entries)}"
        )


# ---------------------------------------------------------------------------
# Tests — not found / forbidden
# ---------------------------------------------------------------------------


class TestGradeEssayAccessControl:
    @pytest.mark.asyncio
    async def test_essay_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when the essay does not exist."""
        db = _make_db_mock(essay=None, essay_exists=False)
        with pytest.raises(NotFoundError):
            await grade_essay(db, _make_uuid(), _make_uuid(), "balanced")

    @pytest.mark.asyncio
    async def test_essay_wrong_teacher_raises_forbidden(self) -> None:
        """Raises ForbiddenError when the essay belongs to a different teacher."""
        # essay_exists=True means the essay exists but the teacher-scoped join returns None
        db = _make_db_mock(essay=None, essay_exists=True)
        with pytest.raises(ForbiddenError):
            await grade_essay(db, _make_uuid(), _make_uuid(), "balanced")

    @pytest.mark.asyncio
    async def test_essay_version_not_found_raises_not_found(self) -> None:
        """Raises NotFoundError when there is no EssayVersion for the essay."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        # Pass essay_version=None to simulate missing version
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        db = _make_db_mock(essay=essay, essay_version=None, assignment=assignment)

        with pytest.raises(NotFoundError, match="No essay version"):
            await grade_essay(db, essay.id, teacher_id, "balanced")


# ---------------------------------------------------------------------------
# Tests — LLM error propagation
# ---------------------------------------------------------------------------


class TestGradeEssayLLMErrors:
    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        """LLMError raised by call_grading propagates without writing DB records."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        db.add = MagicMock()

        with (
            patch(
                "app.services.grading.call_grading",
                side_effect=LLMError("LLM request timed out"),
            ),
            pytest.raises(LLMError),
        ):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.grade import Grade as GradeModel

        added_objs = [call.args[0] for call in db.add.call_args_list]
        grade_objs = [o for o in added_objs if isinstance(o, GradeModel)]
        assert len(grade_objs) == 0, "No Grade should be written when LLM fails"

    @pytest.mark.asyncio
    async def test_llm_parse_error_propagates(self) -> None:
        """LLMParseError raised by call_grading propagates without writing DB records."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)
        db.add = MagicMock()

        with (
            patch(
                "app.services.grading.call_grading",
                side_effect=LLMParseError("LLM response is not valid JSON"),
            ),
            pytest.raises(LLMParseError),
        ):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.grade import Grade as GradeModel

        added_objs = [call.args[0] for call in db.add.call_args_list]
        grade_objs = [o for o in added_objs if isinstance(o, GradeModel)]
        assert len(grade_objs) == 0, "No Grade should be written when LLM parse fails"


# ---------------------------------------------------------------------------
# Tests — missing criterion score (null score)
# ---------------------------------------------------------------------------


class TestGradeEssayMissingCriterion:
    @pytest.mark.asyncio
    async def test_missing_criterion_written_with_zero_ai_score(self) -> None:
        """When parser returns score=None for a criterion, ai_score=0 is stored."""
        teacher_id = _make_uuid()
        essay = _make_essay()
        essay_version = _make_essay_version(essay.id)
        assignment = _make_assignment(assignment_id=essay.assignment_id)
        criterion_id = assignment.rubric_snapshot["criteria"][0]["id"]

        db = _make_db_mock(essay=essay, essay_version=essay_version, assignment=assignment)

        grading_resp = ParsedGradingResponse(
            criterion_scores=[
                ParsedCriterionScore(
                    criterion_id=criterion_id,
                    score=None,  # Missing criterion
                    justification="No justification provided.",
                    confidence="low",
                    needs_review=True,
                )
            ],
            summary_feedback="The LLM did not score one of the criteria.",
        )

        added_objects: list[object] = []
        db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with patch("app.services.grading.call_grading", return_value=grading_resp):
            await grade_essay(db, essay.id, teacher_id, "balanced")

        from app.models.grade import CriterionScore as CriterionScoreModel

        cs_objs = [o for o in added_objects if isinstance(o, CriterionScoreModel)]
        assert len(cs_objs) == 1
        assert cs_objs[0].ai_score == 0
        assert cs_objs[0].final_score == 0

        # Verify that total_score includes the 0 contribution from the missing criterion.
        from app.models.grade import Grade as GradeModel

        grade_objs = [o for o in added_objects if isinstance(o, GradeModel)]
        assert len(grade_objs) == 1
        assert grade_objs[0].total_score == Decimal("0")
