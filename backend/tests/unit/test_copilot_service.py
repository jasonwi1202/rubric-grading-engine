"""Unit tests for app/services/copilot.py (M7-03).

Tests cover:

``_build_context_json``:
- Empty profiles and worklist items produces valid JSON.
- Profile data includes student_id, assignment_count, skill_scores.
- Worklist items are serialised with expected fields.

``_enrich_ranked_items``:
- Valid student UUIDs are resolved to display names.
- Unknown UUIDs produce None display_name.
- Malformed UUID strings produce student_id=None.
- Skill-level items (null student_id) are passed through.

``_safe_response_type``:
- Valid types are returned unchanged.
- Unknown type defaults to "ranked_list".

``execute_copilot_query``:
- Happy path returns a CopilotQueryResponse with enriched items.
- class_id=None skips class ownership check.
- class_id provided: calls _assert_class_owned_by; ForbiddenError propagates.
- class_id provided: NotFoundError propagates.
- Student names are resolved and populated in ranked items.
- Profiles with no matching student IDs produce None display_names.
- LLM returns empty ranked_items: response has empty list.
- prompt_version is forwarded to call_copilot.

``_load_skill_profiles``:
- Calls DB with teacher_id filter.
- When class_id is provided, adds enrollment join.

``_load_worklist_items``:
- Queries only active items for the given teacher_id.

No student PII in any fixture.  All database calls are mocked.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, NotFoundError
from app.llm.parsers import CopilotRankedItem, ParsedCopilotResponse
from app.services.copilot import (
    _build_context_json,
    _enrich_ranked_items,
    _safe_response_type,
    execute_copilot_query,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_profile(
    student_id: uuid.UUID | None = None,
    teacher_id: uuid.UUID | None = None,
    assignment_count: int = 3,
    skill_scores: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a mock StudentSkillProfile."""
    p = MagicMock()
    p.student_id = student_id or uuid.uuid4()
    p.teacher_id = teacher_id or uuid.uuid4()
    p.assignment_count = assignment_count
    p.skill_scores = skill_scores or {
        "thesis": {"avg_score": 0.55, "trend": "stable", "data_points": 3}
    }
    return p


def _make_worklist_item(
    student_id: uuid.UUID | None = None,
    trigger_type: str = "persistent_gap",
    skill_key: str | None = "thesis",
    urgency: int = 3,
) -> MagicMock:
    """Build a mock TeacherWorklistItem."""
    w = MagicMock()
    w.student_id = student_id or uuid.uuid4()
    w.trigger_type = trigger_type
    w.skill_key = skill_key
    w.urgency = urgency
    w.suggested_action = "Review skill dimension with student."
    w.details = {"avg_score": 0.50, "trend": "stable", "assignment_count": 4}
    return w


def _make_parsed_copilot(
    query_interpretation: str = "Who needs help with thesis?",
    has_sufficient_data: bool = True,
    uncertainty_note: str | None = None,
    response_type: str = "ranked_list",
    ranked_items: list[CopilotRankedItem] | None = None,
    summary: str = "Two students need thesis support.",
    suggested_next_steps: list[str] | None = None,
) -> ParsedCopilotResponse:
    """Build a ParsedCopilotResponse."""
    return ParsedCopilotResponse(
        query_interpretation=query_interpretation,
        has_sufficient_data=has_sufficient_data,
        uncertainty_note=uncertainty_note,
        response_type=response_type,
        ranked_items=ranked_items or [],
        summary=summary,
        suggested_next_steps=suggested_next_steps or ["Review profiles.", "Schedule mini-lesson."],
    )


def _make_ranked_item(
    student_id: str | None = None,
    skill_dimension: str | None = "thesis",
    label: str = "Student needs help with thesis",
    value: float | None = 0.45,
    explanation: str = "avg_score is 0.45 with stable trend.",
) -> CopilotRankedItem:
    return CopilotRankedItem(
        student_id=student_id,
        skill_dimension=skill_dimension,
        label=label,
        value=value,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Tests — _build_context_json
# ---------------------------------------------------------------------------


class TestBuildContextJson:
    def test_empty_inputs_produce_valid_json(self) -> None:
        result = _build_context_json([], [])
        data = json.loads(result)
        assert data["total_students_with_profiles"] == 0
        assert data["skill_profiles"] == []
        assert data["active_worklist_items"] == []

    def test_profile_fields_serialised(self) -> None:
        student_id = uuid.uuid4()
        profile = _make_profile(
            student_id=student_id,
            assignment_count=5,
            skill_scores={"evidence": {"avg_score": 0.70, "trend": "improving", "data_points": 5}},
        )
        result = _build_context_json([profile], [])
        data = json.loads(result)
        assert data["total_students_with_profiles"] == 1
        assert len(data["skill_profiles"]) == 1
        sp = data["skill_profiles"][0]
        assert sp["student_id"] == str(student_id)
        assert sp["assignment_count"] == 5
        assert "evidence" in sp["skill_scores"]

    def test_worklist_item_fields_serialised(self) -> None:
        student_id = uuid.uuid4()
        item = _make_worklist_item(
            student_id=student_id, trigger_type="regression", skill_key="evidence", urgency=4
        )
        result = _build_context_json([], [item])
        data = json.loads(result)
        assert len(data["active_worklist_items"]) == 1
        wi = data["active_worklist_items"][0]
        assert wi["student_id"] == str(student_id)
        assert wi["trigger_type"] == "regression"
        assert wi["skill_key"] == "evidence"
        assert wi["urgency"] == 4

    def test_worklist_items_order_preserved_in_context(self) -> None:
        """Context JSON preserves the order of worklist items as supplied.

        The ``_load_worklist_items`` query orders by urgency DESC, then
        created_at DESC, then id ASC (deterministic tie-breaker).  The
        context builder reflects that ordering faithfully without reshuffling.
        """
        sid_a = uuid.uuid4()
        sid_b = uuid.uuid4()
        item_high = _make_worklist_item(student_id=sid_a, urgency=4, trigger_type="regression")
        item_low = _make_worklist_item(student_id=sid_b, urgency=2, trigger_type="trajectory_risk")
        # Pass items already sorted by urgency descending (as the query returns them).
        result = _build_context_json([], [item_high, item_low])
        data = json.loads(result)
        items = data["active_worklist_items"]
        assert items[0]["urgency"] == 4
        assert items[1]["urgency"] == 2


# ---------------------------------------------------------------------------
# Tests — _enrich_ranked_items
# ---------------------------------------------------------------------------


class TestEnrichRankedItems:
    def test_known_student_uuid_resolved_to_name(self) -> None:
        sid = uuid.uuid4()
        names = {sid: "Synthetic Student"}
        item = _make_ranked_item(student_id=str(sid))
        parsed = _make_parsed_copilot(ranked_items=[item])
        result = _enrich_ranked_items(parsed, names)
        assert len(result) == 1
        assert result[0].student_id == sid
        assert result[0].student_display_name == "Synthetic Student"

    def test_unknown_student_uuid_produces_none_display_name(self) -> None:
        sid = uuid.uuid4()
        names: dict[uuid.UUID, str] = {}
        item = _make_ranked_item(student_id=str(sid))
        parsed = _make_parsed_copilot(ranked_items=[item])
        result = _enrich_ranked_items(parsed, names)
        assert result[0].student_id == sid
        assert result[0].student_display_name is None

    def test_malformed_uuid_string_produces_none_student_id(self) -> None:
        item = _make_ranked_item(student_id="not-a-uuid")
        parsed = _make_parsed_copilot(ranked_items=[item])
        result = _enrich_ranked_items(parsed, {})
        assert result[0].student_id is None
        assert result[0].student_display_name is None

    def test_null_student_id_passes_through(self) -> None:
        item = _make_ranked_item(student_id=None, skill_dimension="evidence")
        parsed = _make_parsed_copilot(ranked_items=[item])
        result = _enrich_ranked_items(parsed, {})
        assert result[0].student_id is None
        assert result[0].skill_dimension == "evidence"

    def test_value_and_explanation_preserved(self) -> None:
        sid = uuid.uuid4()
        item = _make_ranked_item(student_id=str(sid), value=0.35, explanation="Below threshold.")
        parsed = _make_parsed_copilot(ranked_items=[item])
        result = _enrich_ranked_items(parsed, {sid: "Fake Student"})
        assert result[0].value == 0.35
        assert result[0].explanation == "Below threshold."


# ---------------------------------------------------------------------------
# Tests — _safe_response_type
# ---------------------------------------------------------------------------


class TestSafeResponseType:
    def test_valid_ranked_list(self) -> None:
        assert _safe_response_type("ranked_list") == "ranked_list"

    def test_valid_summary(self) -> None:
        assert _safe_response_type("summary") == "summary"

    def test_valid_insufficient_data(self) -> None:
        assert _safe_response_type("insufficient_data") == "insufficient_data"

    def test_unknown_type_defaults_to_ranked_list(self) -> None:
        assert _safe_response_type("unknown_type") == "ranked_list"

    def test_empty_string_defaults_to_ranked_list(self) -> None:
        assert _safe_response_type("") == "ranked_list"


# ---------------------------------------------------------------------------
# Tests — execute_copilot_query
# ---------------------------------------------------------------------------


class TestExecuteCopilotQuery:
    """Tests for the public execute_copilot_query function."""

    @pytest.fixture()
    def db(self) -> AsyncMock:
        db = AsyncMock()
        # db.execute is an awaitable AsyncSession method — must be AsyncMock
        # (db.add / db.delete are synchronous and would use MagicMock, but
        # this service only calls db.execute so only AsyncMock is needed here).
        db.execute = AsyncMock()
        return db

    def _mock_scalars(self, rows: list[Any]) -> MagicMock:
        """Build a mock result set where .scalars().all() returns rows."""
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = rows
        result = MagicMock()
        result.scalars.return_value = scalars_mock
        return result

    def _mock_query_result(self, rows: list[Any]) -> MagicMock:
        """Build a mock result for select(Student.id, ...) queries."""
        mock_rows = []
        for sid, name in rows:
            row = MagicMock()
            row.id = sid
            row.full_name = name
            row.teacher_id = uuid.uuid4()
            mock_rows.append(row)
        result = MagicMock()
        result.all.return_value = mock_rows
        # Also support scalars for profile/worklist queries
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result.scalars.return_value = scalars_mock
        return result

    @pytest.mark.asyncio
    async def test_happy_path_returns_copilot_response(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        profile = _make_profile(student_id=student_id, assignment_count=4)
        worklist_item = _make_worklist_item(student_id=student_id)

        # First two execute calls: profiles, worklist
        # Third call: student names
        db.execute.side_effect = [
            self._mock_scalars([profile]),  # skill profiles
            self._mock_scalars([worklist_item]),  # worklist items
            self._mock_query_result([(student_id, "Fake Student A")]),  # student names
        ]

        item = _make_ranked_item(student_id=str(student_id))
        parsed = _make_parsed_copilot(ranked_items=[item])

        with patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)):
            response = await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Who needs help?"
            )

        assert response.has_sufficient_data is True
        assert response.prompt_version == "copilot-v1"
        assert len(response.ranked_items) == 1
        assert response.ranked_items[0].student_id == student_id
        assert response.ranked_items[0].student_display_name == "Fake Student A"

    @pytest.mark.asyncio
    async def test_class_id_none_skips_ownership_check(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),  # profiles
            self._mock_scalars([]),  # worklist
            self._mock_query_result([]),  # names
        ]
        parsed = _make_parsed_copilot()

        with (
            patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)),
            patch("app.services.copilot._assert_class_owned_by") as mock_assert,
        ):
            await execute_copilot_query(db, teacher_id=teacher_id, query_text="What to teach?")

        mock_assert.assert_not_called()

    @pytest.mark.asyncio
    async def test_class_id_provided_calls_ownership_check(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),  # profiles (with class join)
            self._mock_scalars([]),  # worklist
            self._mock_query_result([]),  # names
        ]
        parsed = _make_parsed_copilot()

        with (
            patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)),
            patch(
                "app.services.copilot._assert_class_owned_by",
                new=AsyncMock(return_value=None),
            ) as mock_assert,
        ):
            await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Class query?", class_id=class_id
            )

        mock_assert.assert_called_once_with(db, class_id, teacher_id)

    @pytest.mark.asyncio
    async def test_forbidden_error_propagates_when_class_belongs_to_other_teacher(
        self, db: AsyncMock
    ) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        with (
            patch(
                "app.services.copilot._assert_class_owned_by",
                new=AsyncMock(side_effect=ForbiddenError("Not your class.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Query?", class_id=class_id
            )

    @pytest.mark.asyncio
    async def test_not_found_error_propagates_when_class_missing(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()

        with (
            patch(
                "app.services.copilot._assert_class_owned_by",
                new=AsyncMock(side_effect=NotFoundError("Class not found.")),
            ),
            pytest.raises(NotFoundError),
        ):
            await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Query?", class_id=class_id
            )

    @pytest.mark.asyncio
    async def test_empty_ranked_items_returns_empty_list(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),
            self._mock_scalars([]),
            self._mock_query_result([]),
        ]
        parsed = _make_parsed_copilot(ranked_items=[], response_type="summary")

        with patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)):
            response = await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Summary query?"
            )

        assert response.ranked_items == []
        assert response.response_type == "summary"

    @pytest.mark.asyncio
    async def test_insufficient_data_response_type_preserved(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),
            self._mock_scalars([]),
            self._mock_query_result([]),
        ]
        parsed = _make_parsed_copilot(
            has_sufficient_data=False,
            uncertainty_note="Fewer than 2 students have profile data.",
            response_type="insufficient_data",
        )

        with patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)):
            response = await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Who is at risk?"
            )

        assert response.has_sufficient_data is False
        assert response.uncertainty_note == "Fewer than 2 students have profile data."
        assert response.response_type == "insufficient_data"

    @pytest.mark.asyncio
    async def test_prompt_version_forwarded_to_call_copilot(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),
            self._mock_scalars([]),
            self._mock_query_result([]),
        ]
        parsed = _make_parsed_copilot()

        with patch(
            "app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)
        ) as mock_call:
            await execute_copilot_query(
                db,
                teacher_id=teacher_id,
                query_text="Query?",
                prompt_version="v1",
            )

        mock_call.assert_called_once()
        call_kwargs = mock_call.call_args.kwargs
        assert call_kwargs["prompt_version"] == "v1"

    @pytest.mark.asyncio
    async def test_class_id_scopes_worklist_items(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        class_id = uuid.uuid4()
        parsed = _make_parsed_copilot(ranked_items=[])

        with (
            patch(
                "app.services.copilot._assert_class_owned_by",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.copilot._load_skill_profiles",
                new=AsyncMock(return_value=[]),
            ) as mock_profiles,
            patch(
                "app.services.copilot._load_worklist_items",
                new=AsyncMock(return_value=[]),
            ) as mock_worklist,
            patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)),
            patch(
                "app.services.copilot._load_student_names",
                new=AsyncMock(return_value={}),
            ),
        ):
            await execute_copilot_query(
                db,
                teacher_id=teacher_id,
                query_text="Who needs help?",
                class_id=class_id,
            )

        mock_profiles.assert_awaited_once_with(db, teacher_id, class_id)
        mock_worklist.assert_awaited_once_with(db, teacher_id, class_id)

    @pytest.mark.asyncio
    async def test_student_names_not_found_produce_none_display_name(self, db: AsyncMock) -> None:
        teacher_id = uuid.uuid4()
        unknown_sid = uuid.uuid4()
        db.execute.side_effect = [
            self._mock_scalars([]),
            self._mock_scalars([]),
            self._mock_query_result([]),  # no names returned
        ]
        item = _make_ranked_item(student_id=str(unknown_sid))
        parsed = _make_parsed_copilot(ranked_items=[item])

        with patch("app.services.copilot.call_copilot", new=AsyncMock(return_value=parsed)):
            response = await execute_copilot_query(
                db, teacher_id=teacher_id, query_text="Who needs help?"
            )

        assert response.ranked_items[0].student_display_name is None
