"""Unit tests for app/services/resubmission.py (M6-11).

All database and LLM calls are mocked — no real PostgreSQL, no real OpenAI.
No student PII in any fixture.

Coverage:
- _jaccard_similarity: identical, disjoint, partial overlap, empty strings.
- _detect_low_effort: word-count-only flag, similarity-only flag, both, neither.
- _build_feedback_items: filters empty/None ai_feedback, preserves non-empty.
- compute_revision_comparison: happy path, LLM failure (best-effort), no
  feedback items (LLM skipped), base version/grade not found.
- parse_revision_response: valid JSON, missing field, malformed item.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.parsers import (
    ParsedCriterionAssessment,
    ParsedRevisionResponse,
    parse_revision_response,
)
from app.services.resubmission import (
    _build_feedback_items,
    _detect_low_effort,
    _jaccard_similarity,
    compute_revision_comparison,
)

# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_criterion_score(
    grade_id: uuid.UUID | None = None,
    criterion_id: uuid.UUID | None = None,
    ai_score: int = 3,
    final_score: int = 3,
    ai_feedback: str = "Good thesis statement, could improve evidence.",
) -> MagicMock:
    cs = MagicMock()
    cs.grade_id = grade_id or _make_uuid()
    cs.rubric_criterion_id = criterion_id or _make_uuid()
    cs.ai_score = ai_score
    cs.teacher_score = None
    cs.final_score = final_score
    cs.ai_feedback = ai_feedback
    return cs


def _make_grade(
    grade_id: uuid.UUID | None = None,
    version_id: uuid.UUID | None = None,
    total_score: Decimal = Decimal("3"),
    max_possible_score: Decimal = Decimal("5"),
) -> MagicMock:
    g = MagicMock()
    g.id = grade_id or _make_uuid()
    g.essay_version_id = version_id or _make_uuid()
    g.total_score = total_score
    g.max_possible_score = max_possible_score
    return g


def _make_essay_version(
    version_id: uuid.UUID | None = None,
    essay_id: uuid.UUID | None = None,
    version_number: int = 2,
    content: str = "This is a revised essay with substantially changed content.",
    word_count: int = 120,
) -> MagicMock:
    v = MagicMock()
    v.id = version_id or _make_uuid()
    v.essay_id = essay_id or _make_uuid()
    v.version_number = version_number
    v.content = content
    v.word_count = word_count
    return v


# ---------------------------------------------------------------------------
# Tests — _jaccard_similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical_texts_return_one(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        assert _jaccard_similarity(text, text) == 1.0

    def test_completely_disjoint_returns_zero(self) -> None:
        assert _jaccard_similarity("apple banana", "cherry date") == 0.0

    def test_partial_overlap(self) -> None:
        sim = _jaccard_similarity("apple banana cherry", "cherry date elderberry")
        # intersection = {cherry}, union = {apple, banana, cherry, date, elderberry}
        assert abs(sim - (1 / 5)) < 1e-9

    def test_both_empty_returns_one(self) -> None:
        assert _jaccard_similarity("", "") == 1.0

    def test_one_empty_returns_zero(self) -> None:
        # empty set against non-empty: intersection=0, union=non-empty → 0
        assert _jaccard_similarity("", "hello world") == 0.0

    def test_case_insensitive(self) -> None:
        assert _jaccard_similarity("Apple", "apple") == 1.0


# ---------------------------------------------------------------------------
# Tests — _detect_low_effort
# ---------------------------------------------------------------------------


class TestDetectLowEffort:
    def test_high_similarity_flags_low_effort(self) -> None:
        # Both texts use an identical vocabulary set (only repeated words added).
        # Jaccard similarity = |A∩B| / |A∪B| = 3/3 = 1.0 ≥ threshold.
        base = "apple banana cherry " * 30
        # Revised version only adds more repetitions of already-present words.
        revised = "apple banana cherry " * 31 + "apple "
        is_low, reasons = _detect_low_effort(base, revised, 90, 94)
        assert is_low
        assert any("similarity" in r.lower() for r in reasons)

    def test_negligible_word_count_flags_low_effort(self) -> None:
        base = "apple " * 100  # 100 words
        # Change only 1 word — delta = 1, fraction = 0.01 < threshold 0.02
        revised = "apple " * 99 + "banana "  # 100 words, 1 different
        is_low, reasons = _detect_low_effort(base, revised, 100, 100)
        # delta_abs = 0 < 5, fraction = 0 < 0.02 → word-count flag
        assert is_low
        assert any("word count" in r.lower() for r in reasons)

    def test_substantial_revision_not_flagged(self) -> None:
        base = "Simple base essay. " * 10
        revised = (
            "Completely rewritten with entirely new arguments and evidence. "
            "The student addressed every piece of feedback from the teacher. "
            "The conclusion now summarises the key points effectively. " * 5
        )
        is_low, reasons = _detect_low_effort(base, revised, 30, 80)
        assert not is_low
        assert reasons == []

    def test_flags_low_effort_when_word_count_delta_is_zero(self) -> None:
        base = "word " * 100
        revised = "different " * 80 + "word " * 20
        is_low, reasons = _detect_low_effort(base, revised, 100, 100)
        # Similarity: intersection={word}, union={word,different}=2 → 0.5
        # Word count: delta=0, fraction=0 — triggers word count flag
        # (delta_abs=0 < 5 AND fraction=0 < 0.02 → low effort)
        assert is_low  # word count flag triggers

    def test_both_heuristics_produce_two_reasons(self) -> None:
        # Identical short text → both similarity AND word count flag
        text = "same word " * 3
        is_low, reasons = _detect_low_effort(text, text, 6, 6)
        assert is_low
        assert len(reasons) >= 2


# ---------------------------------------------------------------------------
# Tests — _build_feedback_items
# ---------------------------------------------------------------------------


class TestBuildFeedbackItems:
    def test_filters_empty_ai_feedback(self) -> None:
        cs_with_feedback = _make_criterion_score(ai_feedback="Good thesis.")
        cs_empty = _make_criterion_score(ai_feedback="")
        cs_none = _make_criterion_score(ai_feedback=None)

        items = _build_feedback_items([cs_with_feedback, cs_empty, cs_none])
        assert len(items) == 1
        assert items[0]["feedback"] == "Good thesis."

    def test_includes_non_empty_ai_feedback(self) -> None:
        criterion_id = _make_uuid()
        cs = _make_criterion_score(
            criterion_id=criterion_id,
            ai_feedback="Add more evidence to support your claim.",
        )
        items = _build_feedback_items([cs])
        assert len(items) == 1
        assert items[0]["criterion_id"] == str(criterion_id)
        assert "evidence" in items[0]["feedback"]

    def test_whitespace_only_feedback_is_excluded(self) -> None:
        cs = _make_criterion_score(ai_feedback="   ")
        items = _build_feedback_items([cs])
        assert items == []

    def test_empty_list_returns_empty(self) -> None:
        assert _build_feedback_items([]) == []


# ---------------------------------------------------------------------------
# Tests — parse_revision_response
# ---------------------------------------------------------------------------


class TestParseRevisionResponse:
    def test_valid_response_parsed_correctly(self) -> None:
        cid = str(_make_uuid())
        raw = json.dumps(
            {
                "criterion_assessments": [
                    {
                        "criterion_id": cid,
                        "addressed": True,
                        "detail": "The student added specific evidence as requested.",
                    }
                ]
            }
        )
        result = parse_revision_response(raw)
        assert len(result.criterion_assessments) == 1
        assert result.criterion_assessments[0].criterion_id == cid
        assert result.criterion_assessments[0].addressed is True
        assert "evidence" in result.criterion_assessments[0].detail

    def test_missing_criterion_assessments_raises(self) -> None:
        from app.exceptions import LLMParseError

        raw = json.dumps({"something_else": []})
        with pytest.raises(LLMParseError, match="criterion_assessments"):
            parse_revision_response(raw)

    def test_invalid_json_raises(self) -> None:
        from app.exceptions import LLMParseError

        with pytest.raises(LLMParseError, match="not valid JSON"):
            parse_revision_response("not json")

    def test_non_object_root_raises(self) -> None:
        from app.exceptions import LLMParseError

        with pytest.raises(LLMParseError, match="JSON object"):
            parse_revision_response(json.dumps([{"criterion_id": "x"}]))

    def test_addressed_as_string_true(self) -> None:
        cid = str(_make_uuid())
        raw = json.dumps(
            {
                "criterion_assessments": [
                    {"criterion_id": cid, "addressed": "true", "detail": "Yes."}
                ]
            }
        )
        result = parse_revision_response(raw)
        assert result.criterion_assessments[0].addressed is True

    def test_addressed_as_string_false(self) -> None:
        cid = str(_make_uuid())
        raw = json.dumps(
            {
                "criterion_assessments": [
                    {"criterion_id": cid, "addressed": "false", "detail": "No."}
                ]
            }
        )
        result = parse_revision_response(raw)
        assert result.criterion_assessments[0].addressed is False

    def test_items_without_criterion_id_are_skipped(self) -> None:
        raw = json.dumps(
            {
                "criterion_assessments": [
                    {"addressed": True, "detail": "Missing ID."},
                    {"criterion_id": "  ", "addressed": False, "detail": "Empty ID."},
                ]
            }
        )
        result = parse_revision_response(raw)
        assert result.criterion_assessments == []

    def test_non_dict_items_are_skipped(self) -> None:
        raw = json.dumps({"criterion_assessments": ["not_a_dict", 42]})
        result = parse_revision_response(raw)
        assert result.criterion_assessments == []

    def test_multiple_assessments(self) -> None:
        cid1, cid2 = str(_make_uuid()), str(_make_uuid())
        raw = json.dumps(
            {
                "criterion_assessments": [
                    {"criterion_id": cid1, "addressed": True, "detail": "Yes."},
                    {"criterion_id": cid2, "addressed": False, "detail": "No."},
                ]
            }
        )
        result = parse_revision_response(raw)
        assert len(result.criterion_assessments) == 2
        assert result.criterion_assessments[0].criterion_id == cid1
        assert result.criterion_assessments[1].criterion_id == cid2


# ---------------------------------------------------------------------------
# Tests — compute_revision_comparison
# ---------------------------------------------------------------------------


def _make_db_for_comparison(
    base_version: MagicMock,
    revised_version: MagicMock,
    base_grade: MagicMock,
    revised_grade: MagicMock,
    base_criterion_scores: list[MagicMock],
    revised_criterion_scores: list[MagicMock],
) -> AsyncMock:
    """Build a minimal AsyncSession mock for compute_revision_comparison."""
    db = AsyncMock()
    db.add = MagicMock()

    # execute() calls in order:
    # 1. Load essay versions (IN clause → two rows)
    # 2. Load grades (IN clause → two rows)
    # 3. Load base criterion scores
    # 4. Load revised criterion scores

    r_versions = MagicMock()
    r_versions.scalars.return_value.all.return_value = [base_version, revised_version]

    r_grades = MagicMock()
    r_grades.scalars.return_value.all.return_value = [base_grade, revised_grade]

    r_base_cs = MagicMock()
    r_base_cs.scalars.return_value.all.return_value = base_criterion_scores

    r_revised_cs = MagicMock()
    r_revised_cs.scalars.return_value.all.return_value = revised_criterion_scores

    db.execute = AsyncMock(side_effect=[r_versions, r_grades, r_base_cs, r_revised_cs])
    return db


class TestComputeRevisionComparison:
    @pytest.mark.asyncio
    async def test_happy_path_delta_math(self) -> None:
        """Criterion deltas and total_score_delta are computed correctly."""
        essay_id = _make_uuid()
        criterion_id = _make_uuid()

        base_version = _make_essay_version(version_number=1, content="Original essay.", word_count=2)
        revised_version = _make_essay_version(
            version_number=2,
            content="Completely rewritten essay with much more evidence and detail. " * 5,
            word_count=50,
        )

        base_grade = _make_grade(total_score=Decimal("3"))
        revised_grade = _make_grade(total_score=Decimal("4"))

        base_cs = _make_criterion_score(
            grade_id=base_grade.id,
            criterion_id=criterion_id,
            final_score=3,
            ai_feedback="Improve thesis clarity.",
        )
        revised_cs = _make_criterion_score(
            grade_id=revised_grade.id,
            criterion_id=criterion_id,
            final_score=4,
            ai_feedback="Good improvement.",
        )

        db = _make_db_for_comparison(
            base_version=base_version,
            revised_version=revised_version,
            base_grade=base_grade,
            revised_grade=revised_grade,
            base_criterion_scores=[base_cs],
            revised_criterion_scores=[revised_cs],
        )

        fake_revision_response = ParsedRevisionResponse(
            criterion_assessments=[
                ParsedCriterionAssessment(
                    criterion_id=str(criterion_id),
                    addressed=True,
                    detail="Student added thesis clarity.",
                )
            ]
        )

        with patch(
            "app.services.resubmission.call_revision_comparison",
            new_callable=AsyncMock,
            return_value=fake_revision_response,
        ):
            comparison = await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=base_version.id,
                revised_version_id=revised_version.id,
                base_grade_id=base_grade.id,
                revised_grade_id=revised_grade.id,
            )

        # Delta math
        assert float(comparison.total_score_delta) == pytest.approx(1.0)
        assert len(comparison.criterion_deltas) == 1
        delta = comparison.criterion_deltas[0]
        assert delta["criterion_id"] == str(criterion_id)
        assert delta["base_score"] == 3
        assert delta["revised_score"] == 4
        assert delta["delta"] == 1

        # Feedback addressed
        assert comparison.feedback_addressed is not None
        assert len(comparison.feedback_addressed) == 1
        assert comparison.feedback_addressed[0]["addressed"] is True

    @pytest.mark.asyncio
    async def test_low_effort_flag_set_for_minimal_revision(self) -> None:
        """is_low_effort is True when word count and similarity indicate low effort."""
        essay_id = _make_uuid()
        criterion_id = _make_uuid()

        # Both versions have identical content — maximum low-effort signal.
        content = "This essay has not changed at all."
        base_version = _make_essay_version(version_number=1, content=content, word_count=7)
        revised_version = _make_essay_version(version_number=2, content=content, word_count=7)

        base_grade = _make_grade(total_score=Decimal("3"))
        revised_grade = _make_grade(total_score=Decimal("3"))

        base_cs = _make_criterion_score(
            grade_id=base_grade.id, criterion_id=criterion_id, final_score=3, ai_feedback=""
        )
        revised_cs = _make_criterion_score(
            grade_id=revised_grade.id, criterion_id=criterion_id, final_score=3, ai_feedback=""
        )

        db = _make_db_for_comparison(
            base_version=base_version,
            revised_version=revised_version,
            base_grade=base_grade,
            revised_grade=revised_grade,
            base_criterion_scores=[base_cs],
            revised_criterion_scores=[revised_cs],
        )

        with patch(
            "app.services.resubmission.call_revision_comparison",
            new_callable=AsyncMock,
        ):
            comparison = await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=base_version.id,
                revised_version_id=revised_version.id,
                base_grade_id=base_grade.id,
                revised_grade_id=revised_grade.id,
            )

        assert comparison.is_low_effort is True
        assert len(comparison.low_effort_reasons) > 0

    @pytest.mark.asyncio
    async def test_llm_failure_is_best_effort(self) -> None:
        """LLM failure during feedback-addressed analysis does not raise."""
        essay_id = _make_uuid()
        criterion_id = _make_uuid()

        base_version = _make_essay_version(
            version_number=1,
            content="Original essay about ecology.",
            word_count=4,
        )
        revised_version = _make_essay_version(
            version_number=2,
            content="Completely rewritten essay about ecology with extensive new research. " * 5,
            word_count=55,
        )

        base_grade = _make_grade(total_score=Decimal("2"))
        revised_grade = _make_grade(total_score=Decimal("3"))

        base_cs = _make_criterion_score(
            grade_id=base_grade.id,
            criterion_id=criterion_id,
            final_score=2,
            ai_feedback="Add more evidence.",
        )
        revised_cs = _make_criterion_score(
            grade_id=revised_grade.id,
            criterion_id=criterion_id,
            final_score=3,
            ai_feedback="",
        )

        db = _make_db_for_comparison(
            base_version=base_version,
            revised_version=revised_version,
            base_grade=base_grade,
            revised_grade=revised_grade,
            base_criterion_scores=[base_cs],
            revised_criterion_scores=[revised_cs],
        )

        with patch(
            "app.services.resubmission.call_revision_comparison",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unavailable"),
        ):
            # Should not raise — LLM failure is best-effort.
            comparison = await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=base_version.id,
                revised_version_id=revised_version.id,
                base_grade_id=base_grade.id,
                revised_grade_id=revised_grade.id,
            )

        # Grade still committed, feedback_addressed stored as None.
        assert comparison.feedback_addressed is None
        assert float(comparison.total_score_delta) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_no_feedback_items_skips_llm(self) -> None:
        """LLM is not called when all criterion scores have empty ai_feedback."""
        essay_id = _make_uuid()
        criterion_id = _make_uuid()

        base_version = _make_essay_version(
            version_number=1,
            content="Short base essay.",
            word_count=3,
        )
        revised_version = _make_essay_version(
            version_number=2,
            content="Revised essay that is substantially different and much longer with many new arguments. " * 4,
            word_count=70,
        )

        base_grade = _make_grade(total_score=Decimal("3"))
        revised_grade = _make_grade(total_score=Decimal("4"))

        # No ai_feedback on base criterion scores → LLM should be skipped.
        base_cs = _make_criterion_score(
            grade_id=base_grade.id, criterion_id=criterion_id, final_score=3, ai_feedback=""
        )
        revised_cs = _make_criterion_score(
            grade_id=revised_grade.id, criterion_id=criterion_id, final_score=4, ai_feedback=""
        )

        db = _make_db_for_comparison(
            base_version=base_version,
            revised_version=revised_version,
            base_grade=base_grade,
            revised_grade=revised_grade,
            base_criterion_scores=[base_cs],
            revised_criterion_scores=[revised_cs],
        )

        with patch(
            "app.services.resubmission.call_revision_comparison",
            new_callable=AsyncMock,
        ) as mock_llm:
            comparison = await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=base_version.id,
                revised_version_id=revised_version.id,
                base_grade_id=base_grade.id,
                revised_grade_id=revised_grade.id,
            )

        # LLM must NOT have been called.
        mock_llm.assert_not_called()
        assert comparison.feedback_addressed is None

    @pytest.mark.asyncio
    async def test_negative_delta_for_regression(self) -> None:
        """Negative total_score_delta is stored correctly when score regresses."""
        essay_id = _make_uuid()
        criterion_id = _make_uuid()

        base_version = _make_essay_version(version_number=1, content="A " * 50, word_count=50)
        revised_version = _make_essay_version(
            version_number=2, content="B " * 50, word_count=50
        )

        base_grade = _make_grade(total_score=Decimal("5"))
        revised_grade = _make_grade(total_score=Decimal("3"))

        base_cs = _make_criterion_score(
            grade_id=base_grade.id, criterion_id=criterion_id, final_score=5, ai_feedback=""
        )
        revised_cs = _make_criterion_score(
            grade_id=revised_grade.id, criterion_id=criterion_id, final_score=3, ai_feedback=""
        )

        db = _make_db_for_comparison(
            base_version=base_version,
            revised_version=revised_version,
            base_grade=base_grade,
            revised_grade=revised_grade,
            base_criterion_scores=[base_cs],
            revised_criterion_scores=[revised_cs],
        )

        with patch("app.services.resubmission.call_revision_comparison", new_callable=AsyncMock):
            comparison = await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=base_version.id,
                revised_version_id=revised_version.id,
                base_grade_id=base_grade.id,
                revised_grade_id=revised_grade.id,
            )

        assert float(comparison.total_score_delta) == pytest.approx(-2.0)
        assert comparison.criterion_deltas[0]["delta"] == -2

    @pytest.mark.asyncio
    async def test_raises_not_found_when_versions_missing(self) -> None:
        """NotFoundError is raised when essay versions cannot be loaded."""
        from app.exceptions import NotFoundError

        essay_id = _make_uuid()

        db = AsyncMock()
        db.add = MagicMock()

        r_versions = MagicMock()
        r_versions.scalars.return_value.all.return_value = []  # No versions found.
        db.execute = AsyncMock(return_value=r_versions)

        with pytest.raises(NotFoundError):
            await compute_revision_comparison(
                db,
                essay_id=essay_id,
                base_version_id=_make_uuid(),
                revised_version_id=_make_uuid(),
                base_grade_id=_make_uuid(),
                revised_grade_id=_make_uuid(),
            )
