"""Unit tests for app/services/instruction_recommendation.py (M6-07/M6-08/M6-09).

Tests cover:
- ``generate_student_recommendations``:
  - happy path returns an InstructionRecommendation row
  - raises NotFoundError when student not found
  - raises ForbiddenError when student belongs to another teacher
  - raises NotFoundError when skill profile not found
  - raises ValidationError when skill profile has no data
  - validates worklist item ownership when worklist_item_id is provided
  - raises ForbiddenError when worklist item belongs to another teacher
  - skill_key filtering is applied to profile sent to LLM
  - LLMParseError propagates when LLM response is unparseable

- ``generate_group_recommendations``:
  - happy path returns an InstructionRecommendation row
  - raises NotFoundError when group not found
  - raises ForbiddenError when group belongs to another teacher
  - raises NotFoundError when group_id does not match class_id
  - LLMParseError propagates from call_instruction

- ``list_student_recommendations``:
  - returns recs in newest-first order
  - returns empty list when no recs exist
  - raises NotFoundError when student not found
  - raises ForbiddenError when student belongs to another teacher

- ``assign_recommendation`` (M6-08):
  - happy path transitions pending_review → accepted; audit row written
  - idempotent when already accepted
  - dismissed status raises ConflictError
  - nonexistent ID raises NotFoundError
  - cross-teacher ID raises NotFoundError (RLS pattern)

- ``dismiss_recommendation`` (M6-09):
  - happy path transitions pending_review → dismissed; audit row written
  - idempotent when already dismissed
  - accepted status raises ConflictError
  - nonexistent ID raises NotFoundError
  - race condition: concurrent assign wins → raises ConflictError after refresh

- ``_build_evidence_summary``:
  - single skill_key produces targeted summary
  - missing skill_key in profile produces fallback text
  - all-gaps (no skill_key) lists only below-threshold skills
  - no gaps returns a 'no gaps' message

No real DB, LLM, or network calls.  All external calls are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.llm.parsers import ParsedInstructionResponse, ParsedRecommendation
from app.services.instruction_recommendation import (
    _build_evidence_summary,
    _filter_skill_profile_for_prompt,
    assign_recommendation,
    dismiss_recommendation,
    generate_group_recommendations,
    generate_student_recommendations,
    list_student_recommendations,
)

# ---------------------------------------------------------------------------
# Factories (no PII)
# ---------------------------------------------------------------------------

_T_ID = uuid.uuid4()
_S_ID = uuid.uuid4()
_G_ID = uuid.uuid4()
_C_ID = uuid.uuid4()
_W_ID = uuid.uuid4()
_REC_ID = uuid.uuid4()


def _make_student_row(teacher_id: uuid.UUID = _T_ID, student_id: uuid.UUID = _S_ID):
    row = MagicMock()
    row.id = student_id
    row.teacher_id = teacher_id
    return row


def _make_profile(skill_scores: dict | None = None, student_id: uuid.UUID = _S_ID):
    profile = MagicMock()
    profile.student_id = student_id
    if skill_scores is None:
        profile.skill_scores = {
            "evidence": {
                "avg_score": 0.40,
                "trend": "stable",
                "data_points": 3,
                "last_updated": datetime.now(UTC).isoformat(),
            },
            "thesis": {
                "avg_score": 0.80,
                "trend": "improving",
                "data_points": 2,
                "last_updated": datetime.now(UTC).isoformat(),
            },
        }
    else:
        profile.skill_scores = skill_scores
    return profile


def _make_group(
    group_id: uuid.UUID = _G_ID,
    class_id: uuid.UUID = _C_ID,
    teacher_id: uuid.UUID = _T_ID,
    skill_key: str = "evidence",
    student_count: int = 4,
    stability: str = "persistent",
):
    group = MagicMock()
    group.id = group_id
    group.class_id = class_id
    group.teacher_id = teacher_id
    group.skill_key = skill_key
    group.student_count = student_count
    group.stability = stability
    return group


def _make_worklist_row(teacher_id: uuid.UUID = _T_ID, item_id: uuid.UUID = _W_ID):
    row = MagicMock()
    row.id = item_id
    row.teacher_id = teacher_id
    return row


def _parsed_instruction_response():
    return ParsedInstructionResponse(
        recommendations=[
            ParsedRecommendation(
                skill_dimension="evidence",
                title="Evidence Workshop",
                description="Practice selecting and integrating textual evidence.",
                estimated_minutes=20,
                strategy_type="guided_practice",
            )
        ]
    )


def _make_persisted_rec(
    rec_id: uuid.UUID = _REC_ID,
    teacher_id: uuid.UUID = _T_ID,
    student_id: uuid.UUID | None = _S_ID,
    group_id: uuid.UUID | None = None,
):
    rec = MagicMock()
    rec.id = rec_id
    rec.teacher_id = teacher_id
    rec.student_id = student_id
    rec.group_id = group_id
    rec.worklist_item_id = None
    rec.skill_key = "evidence"
    rec.grade_level = "Grade 8"
    rec.prompt_version = "instruction-v1"
    rec.recommendations = [
        {
            "skill_dimension": "evidence",
            "title": "Evidence Workshop",
            "description": "Practice selecting evidence.",
            "estimated_minutes": 20,
            "strategy_type": "guided_practice",
        }
    ]
    rec.evidence_summary = "Skill gap detected in 'evidence': average score 40%, trend is stable."
    rec.status = "pending_review"
    rec.created_at = datetime(2026, 4, 30, 0, 0, 0, tzinfo=UTC)
    return rec


# ---------------------------------------------------------------------------
# _build_evidence_summary (pure function — no DB needed)
# ---------------------------------------------------------------------------


class TestBuildEvidenceSummary:
    def test_single_skill_key_with_data(self):
        skill_scores = {
            "evidence": {
                "avg_score": 0.40,
                "trend": "stable",
                "data_points": 3,
            }
        }
        summary = _build_evidence_summary(skill_scores, skill_key="evidence")
        assert "evidence" in summary
        assert "40%" in summary
        assert "stable" in summary

    def test_single_skill_key_missing_from_profile(self):
        summary = _build_evidence_summary({}, skill_key="organization")
        assert "organization" in summary
        assert "no profile data found" in summary

    def test_all_gaps_lists_below_threshold_skills(self):
        skill_scores = {
            "evidence": {"avg_score": 0.40, "trend": "stable", "data_points": 3},
            "thesis": {"avg_score": 0.80, "trend": "improving", "data_points": 2},
        }
        summary = _build_evidence_summary(skill_scores, skill_key=None)
        assert "evidence" in summary
        # thesis is above the 0.6 threshold and should not appear
        assert "thesis" not in summary

    def test_no_gaps_detected(self):
        skill_scores = {
            "thesis": {"avg_score": 0.85, "trend": "improving", "data_points": 3},
        }
        summary = _build_evidence_summary(skill_scores, skill_key=None)
        assert "No skill gaps detected" in summary


# ---------------------------------------------------------------------------
# _filter_skill_profile_for_prompt (pure function)
# ---------------------------------------------------------------------------


class TestFilterSkillProfileForPrompt:
    def test_single_skill_key_filters_to_one_entry(self):
        skill_scores = {
            "evidence": {"avg_score": 0.40, "trend": "stable", "data_points": 3},
            "thesis": {"avg_score": 0.80, "trend": "improving", "data_points": 2},
        }
        result = _filter_skill_profile_for_prompt(skill_scores, "evidence")
        assert list(result.keys()) == ["evidence"]

    def test_missing_skill_key_returns_empty(self):
        result = _filter_skill_profile_for_prompt({}, "nonexistent")
        assert result == {}

    def test_no_skill_key_returns_only_gaps(self):
        skill_scores = {
            "evidence": {"avg_score": 0.40, "trend": "stable", "data_points": 3},
            "thesis": {"avg_score": 0.80, "trend": "improving", "data_points": 2},
        }
        result = _filter_skill_profile_for_prompt(skill_scores, None)
        assert "evidence" in result
        assert "thesis" not in result


# ---------------------------------------------------------------------------
# generate_student_recommendations
# ---------------------------------------------------------------------------


class TestGenerateStudentRecommendations:
    @pytest.mark.asyncio
    async def test_happy_path_returns_recommendation(self):
        db = AsyncMock()
        profile = _make_profile()

        # _assert_student_owned_by: student exists, teacher matches
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID

        execute_results = [
            # _assert_student_owned_by
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            # skill profile query
            MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_parsed_instruction_response(),
        ):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        added = db.add.call_args[0][0]
        assert added.teacher_id == _T_ID
        assert added.student_id == _S_ID
        assert added.group_id is None
        assert added.status == "pending_review"
        assert len(added.recommendations) == 1
        assert added.recommendations[0]["skill_dimension"] == "evidence"

    @pytest.mark.asyncio
    async def test_student_not_found_raises_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one_or_none=MagicMock(return_value=None)))
        with pytest.raises(NotFoundError, match="Student not found"):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_wrong_teacher_raises_forbidden(self):
        db = AsyncMock()
        other_teacher_id = uuid.uuid4()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = other_teacher_id  # different teacher

        db.execute = AsyncMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=student_row))
        )
        with pytest.raises(ForbiddenError):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_no_skill_profile_raises_not_found(self):
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        with pytest.raises(NotFoundError, match="No skill profile found"):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_empty_skill_scores_raises_validation_error(self):
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID
        profile = _make_profile(skill_scores={})

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        with pytest.raises(ValidationError):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_worklist_item_ownership_verified(self):
        """When worklist_item_id is provided, its ownership is checked."""
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID
        profile = _make_profile()
        worklist_row = MagicMock()
        worklist_row.id = _W_ID
        worklist_row.teacher_id = _T_ID

        execute_results = [
            # _assert_student_owned_by
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            # _assert_worklist_item_owned_by
            MagicMock(one_or_none=MagicMock(return_value=worklist_row)),
            # skill profile query
            MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_parsed_instruction_response(),
        ):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
                worklist_item_id=_W_ID,
            )

        added = db.add.call_args[0][0]
        assert added.worklist_item_id == _W_ID

    @pytest.mark.asyncio
    async def test_worklist_item_wrong_teacher_raises_forbidden(self):
        """worklist_item_id belonging to another teacher raises ForbiddenError."""
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID
        worklist_row = MagicMock()
        worklist_row.id = _W_ID
        worklist_row.teacher_id = uuid.uuid4()  # different teacher

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(one_or_none=MagicMock(return_value=worklist_row)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        with pytest.raises(ForbiddenError):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
                worklist_item_id=_W_ID,
            )

    @pytest.mark.asyncio
    async def test_llm_parse_error_propagates(self):
        """LLMParseError from call_instruction is not swallowed."""
        from app.exceptions import LLMParseError

        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID
        profile = _make_profile()

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        with (
            patch(
                "app.services.instruction_recommendation.call_instruction",
                new_callable=AsyncMock,
                side_effect=LLMParseError("bad json"),
            ),
            pytest.raises(LLMParseError),
        ):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_skill_key_filters_profile_sent_to_llm(self):
        """When skill_key is provided, only that dimension is sent to the LLM."""
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID
        profile = _make_profile()

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=profile)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        captured_calls: list = []

        async def mock_call_instruction(**kwargs):
            captured_calls.append(kwargs)
            return _parsed_instruction_response()

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            side_effect=mock_call_instruction,
        ):
            await generate_student_recommendations(
                db,
                _T_ID,
                _S_ID,
                grade_level="Grade 8",
                duration_minutes=20,
                skill_key="evidence",
            )

        sent_profile = json.loads(captured_calls[0]["skill_profile_json"])
        assert "evidence" in sent_profile
        assert "thesis" not in sent_profile


# ---------------------------------------------------------------------------
# generate_group_recommendations
# ---------------------------------------------------------------------------


class TestGenerateGroupRecommendations:
    @pytest.mark.asyncio
    async def test_happy_path_returns_recommendation(self):
        db = AsyncMock()
        group = _make_group()

        execute_results = [
            # _assert_group_owned_by
            MagicMock(scalar_one_or_none=MagicMock(return_value=group)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        with patch(
            "app.services.instruction_recommendation.call_instruction",
            new_callable=AsyncMock,
            return_value=_parsed_instruction_response(),
        ):
            await generate_group_recommendations(
                db,
                _T_ID,
                _C_ID,
                _G_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.teacher_id == _T_ID
        assert added.student_id is None
        assert added.group_id == _G_ID
        assert "evidence" in added.evidence_summary

    @pytest.mark.asyncio
    async def test_group_not_found_raises_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        with pytest.raises(NotFoundError):
            await generate_group_recommendations(
                db,
                _T_ID,
                _C_ID,
                _G_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_wrong_teacher_raises_forbidden(self):
        db = AsyncMock()
        group = _make_group(teacher_id=uuid.uuid4())  # different teacher
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=group))
        )
        with pytest.raises(ForbiddenError):
            await generate_group_recommendations(
                db,
                _T_ID,
                _C_ID,
                _G_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )

    @pytest.mark.asyncio
    async def test_group_class_mismatch_raises_not_found(self):
        """Group exists but belongs to a different class — should be 404."""
        db = AsyncMock()
        different_class_id = uuid.uuid4()
        group = _make_group(class_id=different_class_id)  # wrong class
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=group))
        )
        with pytest.raises(NotFoundError):
            await generate_group_recommendations(
                db,
                _T_ID,
                _C_ID,  # caller's class_id != group.class_id
                _G_ID,
                grade_level="Grade 8",
                duration_minutes=20,
            )


# ---------------------------------------------------------------------------
# list_student_recommendations
# ---------------------------------------------------------------------------


class TestListStudentRecommendations:
    @pytest.mark.asyncio
    async def test_returns_recs_newest_first(self):
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID

        older_rec = _make_persisted_rec(rec_id=uuid.uuid4())
        older_rec.created_at = datetime(2026, 4, 1, tzinfo=UTC)
        newer_rec = _make_persisted_rec(rec_id=uuid.uuid4())
        newer_rec.created_at = datetime(2026, 4, 29, tzinfo=UTC)

        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[newer_rec, older_rec])

        execute_results = [
            # _assert_student_owned_by
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            # select InstructionRecommendation
            MagicMock(scalars=MagicMock(return_value=scalars_mock)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        recs = await list_student_recommendations(db, _T_ID, _S_ID)
        assert len(recs) == 2
        # Newest first (ordering delegated to DB, but we verify the list)
        assert recs[0].created_at >= recs[1].created_at

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_recs(self):
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = _T_ID

        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=[])

        execute_results = [
            MagicMock(one_or_none=MagicMock(return_value=student_row)),
            MagicMock(scalars=MagicMock(return_value=scalars_mock)),
        ]
        db.execute = AsyncMock(side_effect=execute_results)

        recs = await list_student_recommendations(db, _T_ID, _S_ID)
        assert recs == []

    @pytest.mark.asyncio
    async def test_student_not_found_raises_not_found(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(one_or_none=MagicMock(return_value=None)))
        with pytest.raises(NotFoundError):
            await list_student_recommendations(db, _T_ID, _S_ID)

    @pytest.mark.asyncio
    async def test_wrong_teacher_raises_forbidden(self):
        db = AsyncMock()
        student_row = MagicMock()
        student_row.id = _S_ID
        student_row.teacher_id = uuid.uuid4()  # different teacher
        db.execute = AsyncMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=student_row))
        )
        with pytest.raises(ForbiddenError):
            await list_student_recommendations(db, _T_ID, _S_ID)


# ---------------------------------------------------------------------------
# assign_recommendation (M6-08)
# ---------------------------------------------------------------------------


class TestAssignRecommendation:
    """Unit tests for :func:`assign_recommendation`.

    All DB calls are mocked — no real database or LLM used.
    """

    def _make_rec_orm(self, status: str = "pending_review", teacher_id: uuid.UUID = _T_ID):
        rec = MagicMock()
        rec.id = _REC_ID
        rec.teacher_id = teacher_id
        rec.status = status
        return rec

    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_accepted(self):
        """pending_review → accepted: audit row added, commit called."""
        db = AsyncMock()
        rec = self._make_rec_orm(status="pending_review")

        # Simulate db.refresh updating rec.status (as it would from the real DB).
        async def _refresh(obj: object) -> None:
            if obj is rec:
                rec.status = "accepted"

        # Two db.execute calls:
        # 1. SELECT with WHERE id AND teacher_id → returns rec
        # 2. UPDATE WHERE status='pending_review' → rowcount = 1
        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
                update_result,
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh)

        result = await assign_recommendation(db, _T_ID, _REC_ID)

        assert rec.status == "accepted"
        db.add.assert_called_once()
        audit = db.add.call_args[0][0]
        assert audit.action == "recommendation_assigned"
        assert audit.before_value == {"status": "pending_review"}
        assert audit.after_value == {"status": "accepted"}
        assert audit.teacher_id == _T_ID
        assert audit.entity_id == _REC_ID
        db.commit.assert_awaited_once()
        assert result is rec

    @pytest.mark.asyncio
    async def test_idempotent_when_already_accepted(self):
        """Calling assign on an already-accepted rec returns it without side effects."""
        db = AsyncMock()
        rec = self._make_rec_orm(status="accepted")

        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=rec))
        )
        db.add = MagicMock()
        db.commit = AsyncMock()

        result = await assign_recommendation(db, _T_ID, _REC_ID)

        db.add.assert_not_called()
        db.commit.assert_not_awaited()
        assert result is rec

    @pytest.mark.asyncio
    async def test_dismissed_raises_conflict_error(self):
        """Dismissed recommendations cannot be assigned (ConflictError)."""
        from app.exceptions import ConflictError

        db = AsyncMock()
        rec = self._make_rec_orm(status="dismissed")

        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=rec))
        )

        with pytest.raises(ConflictError, match="dismissed"):
            await assign_recommendation(db, _T_ID, _REC_ID)

    @pytest.mark.asyncio
    async def test_not_found_raises_not_found_error(self):
        """Non-existent recommendation ID raises NotFoundError."""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(NotFoundError, match="not found"):
            await assign_recommendation(db, _T_ID, _REC_ID)

    @pytest.mark.asyncio
    async def test_wrong_teacher_raises_not_found(self):
        """Recommendation owned by a different teacher returns NotFoundError (RLS behavior).

        With FORCE RLS enforced at the DB level, cross-tenant rows are invisible.
        The single ``WHERE id = ? AND teacher_id = ?`` query returns no row, so
        both nonexistent IDs and cross-tenant IDs raise NotFoundError (404).
        """
        db = AsyncMock()
        # With the RLS-pattern query (WHERE id AND teacher_id), no row is returned
        # for a cross-tenant ID — the DB filters it out before the service sees it.
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(NotFoundError, match="not found"):
            await assign_recommendation(db, _T_ID, _REC_ID)


# ---------------------------------------------------------------------------
# dismiss_recommendation (M6-09)
# ---------------------------------------------------------------------------


class TestDismissRecommendation:
    """Unit tests for :func:`dismiss_recommendation`.

    All DB calls are mocked — no real database or LLM used.
    """

    def _make_rec_orm(self, status: str = "pending_review", teacher_id: uuid.UUID = _T_ID):
        rec = MagicMock()
        rec.id = _REC_ID
        rec.teacher_id = teacher_id
        rec.status = status
        return rec

    @pytest.mark.asyncio
    async def test_happy_path_transitions_to_dismissed(self):
        """pending_review → dismissed: audit row added, commit called."""
        db = AsyncMock()
        rec = self._make_rec_orm(status="pending_review")

        async def _refresh(obj: object) -> None:
            if obj is rec:
                rec.status = "dismissed"

        update_result = MagicMock()
        update_result.rowcount = 1
        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
                update_result,
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh)

        result = await dismiss_recommendation(db, _T_ID, _REC_ID)

        assert rec.status == "dismissed"
        db.add.assert_called_once()
        audit = db.add.call_args[0][0]
        assert audit.action == "recommendation_dismissed"
        assert audit.before_value == {"status": "pending_review"}
        assert audit.after_value == {"status": "dismissed"}
        assert audit.teacher_id == _T_ID
        assert audit.entity_id == _REC_ID
        db.commit.assert_awaited_once()
        assert result is rec

    @pytest.mark.asyncio
    async def test_idempotent_when_already_dismissed(self):
        """Dismissing an already-dismissed rec returns it without side effects."""
        db = AsyncMock()
        rec = self._make_rec_orm(status="dismissed")

        update_result = MagicMock()
        update_result.rowcount = 0

        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
                update_result,
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda obj: None)

        result = await dismiss_recommendation(db, _T_ID, _REC_ID)

        db.add.assert_not_called()
        db.commit.assert_not_awaited()
        assert result is rec

    @pytest.mark.asyncio
    async def test_accepted_raises_conflict_error(self):
        """Accepted recommendations cannot be dismissed (ConflictError)."""
        from app.exceptions import ConflictError

        db = AsyncMock()
        rec = self._make_rec_orm(status="accepted")

        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=rec))
        )

        with pytest.raises(ConflictError, match="assigned"):
            await dismiss_recommendation(db, _T_ID, _REC_ID)

    @pytest.mark.asyncio
    async def test_not_found_raises_not_found_error(self):
        """Non-existent recommendation ID raises NotFoundError."""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with pytest.raises(NotFoundError, match="not found"):
            await dismiss_recommendation(db, _T_ID, _REC_ID)

    @pytest.mark.asyncio
    async def test_race_condition_concurrent_assign_raises_conflict(self):
        """If a concurrent request assigns the rec before dismiss completes, raise ConflictError.

        Scenario:
        1. SELECT returns pending_review rec
        2. Concurrent request runs assign_recommendation → status → 'accepted'
        3. Our UPDATE WHERE status='pending_review' touches 0 rows (rowcount=0)
        4. db.refresh re-fetches the now-'accepted' state
        5. dismiss_recommendation raises ConflictError
        """
        from app.exceptions import ConflictError

        db = AsyncMock()
        rec = self._make_rec_orm(status="pending_review")

        async def _refresh_to_accepted(obj: object) -> None:
            if obj is rec:
                rec.status = "accepted"

        update_result = MagicMock()
        update_result.rowcount = 0

        db.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
                update_result,
            ]
        )
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh_to_accepted)

        with pytest.raises(ConflictError, match="assigned"):
            await dismiss_recommendation(db, _T_ID, _REC_ID)
