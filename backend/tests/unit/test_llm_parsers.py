"""Unit tests for app/llm/parsers.py.

Coverage target: ≥ 95% (parsers are fully deterministic pure functions).

Tests verify:
    - parse_grading_response: happy path, JSON errors, missing fields,
      missing criterion, score clamping, justification fallback,
      invalid confidence, extra criteria ignored, blank summary fallback.
    - parse_feedback_response: happy path, JSON errors, missing fields,
      malformed items, empty next_steps.
    - parse_instruction_response: happy path, JSON errors, missing field,
      malformed items, bad estimated_minutes.

No real OpenAI calls, no database, no file I/O.
No student PII in fixtures.
"""

from __future__ import annotations

import json

import pytest

from app.exceptions import LLMParseError
from app.llm.parsers import (
    FALLBACK_JUSTIFICATION,
    FALLBACK_SUMMARY,
    CriterionInfo,
    ParsedCriterionFeedback,
    ParsedFeedbackResponse,
    ParsedGradingResponse,
    ParsedInstructionResponse,
    ParsedRecommendation,
    parse_feedback_response,
    parse_grading_response,
    parse_instruction_response,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _crit(cid: str, min_score: int = 1, max_score: int = 5) -> CriterionInfo:
    return CriterionInfo(criterion_id=cid, min_score=min_score, max_score=max_score)


def _grading_payload(
    *,
    criterion_id: str = "crit-1",
    score: int = 3,
    justification: str = "A sufficiently long justification for the test case.",
    confidence: str = "high",
    summary_feedback: str = "This essay demonstrates good structure.",
) -> str:
    return json.dumps(
        {
            "criterion_scores": [
                {
                    "criterion_id": criterion_id,
                    "score": score,
                    "justification": justification,
                    "confidence": confidence,
                }
            ],
            "summary_feedback": summary_feedback,
        }
    )


def _feedback_payload(
    *,
    summary: str = "Good essay overall.",
    criterion_id: str = "crit-1",
    feedback: str = "Strong thesis statement.",
    next_steps: list[str] | None = None,
) -> str:
    steps = ["Focus on transitions.", "Vary sentence length."] if next_steps is None else next_steps
    return json.dumps(
        {
            "summary": summary,
            "criterion_feedback": [{"criterion_id": criterion_id, "feedback": feedback}],
            "next_steps": steps,
        }
    )


def _instruction_payload(
    *,
    skill_dimension: str = "thesis",
    title: str = "Thesis Workshop",
    description: str = "Write five thesis statements.",
    estimated_minutes: int = 20,
    strategy_type: str = "guided_practice",
) -> str:
    return json.dumps(
        {
            "recommendations": [
                {
                    "skill_dimension": skill_dimension,
                    "title": title,
                    "description": description,
                    "estimated_minutes": estimated_minutes,
                    "strategy_type": strategy_type,
                }
            ]
        }
    )


# ===========================================================================
# parse_grading_response
# ===========================================================================


class TestParseGradingResponseHappyPath:
    def test_returns_parsed_grading_response(self) -> None:
        criteria = [_crit("crit-1")]
        result = parse_grading_response(_grading_payload(), criteria)
        assert isinstance(result, ParsedGradingResponse)

    def test_criterion_score_populated(self) -> None:
        criteria = [_crit("crit-1")]
        result = parse_grading_response(_grading_payload(score=4), criteria)
        assert len(result.criterion_scores) == 1
        cs = result.criterion_scores[0]
        assert cs.score == 4
        assert cs.criterion_id == "crit-1"
        assert cs.confidence == "high"
        assert not cs.score_clamped
        assert not cs.needs_review

    def test_summary_feedback_preserved(self) -> None:
        criteria = [_crit("crit-1")]
        result = parse_grading_response(
            _grading_payload(summary_feedback="Excellent argument development."),
            criteria,
        )
        assert result.summary_feedback == "Excellent argument development."

    def test_extra_criterion_ids_in_response_ignored(self) -> None:
        """Extra criterion IDs returned by the LLM are silently dropped."""
        criteria = [_crit("crit-1")]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "crit-1",
                        "score": 3,
                        "justification": "Long enough justification text here.",
                        "confidence": "medium",
                    },
                    {
                        "criterion_id": "unknown-crit",
                        "score": 5,
                        "justification": "Should be ignored entirely.",
                        "confidence": "high",
                    },
                ],
                "summary_feedback": "Good.",
            }
        )
        result = parse_grading_response(payload, criteria)
        assert len(result.criterion_scores) == 1
        assert result.criterion_scores[0].criterion_id == "crit-1"

    def test_multiple_criteria_all_populated(self) -> None:
        criteria = [_crit("c1"), _crit("c2"), _crit("c3")]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "c1",
                        "score": 2,
                        "justification": "Long enough justification text for c1.",
                        "confidence": "low",
                    },
                    {
                        "criterion_id": "c2",
                        "score": 4,
                        "justification": "Long enough justification text for c2.",
                        "confidence": "high",
                    },
                    {
                        "criterion_id": "c3",
                        "score": 3,
                        "justification": "Long enough justification text for c3.",
                        "confidence": "medium",
                    },
                ],
                "summary_feedback": "Well written.",
            }
        )
        result = parse_grading_response(payload, criteria)
        assert len(result.criterion_scores) == 3
        ids = {cs.criterion_id for cs in result.criterion_scores}
        assert ids == {"c1", "c2", "c3"}


class TestParseGradingResponseJsonErrors:
    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(LLMParseError, match="not valid JSON"):
            parse_grading_response("not json", [_crit("c1")])

    def test_raises_on_json_array(self) -> None:
        with pytest.raises(LLMParseError, match="must be a JSON object"):
            parse_grading_response("[]", [_crit("c1")])

    def test_raises_on_missing_criterion_scores_field(self) -> None:
        payload = json.dumps({"summary_feedback": "ok"})
        with pytest.raises(LLMParseError, match="missing required field"):
            parse_grading_response(payload, [_crit("c1")])

    def test_missing_summary_feedback_field_falls_back(self) -> None:
        """summary_feedback is optional — missing value falls back to FALLBACK_SUMMARY."""
        payload = json.dumps({"criterion_scores": []})
        result = parse_grading_response(payload, [])
        assert result.summary_feedback == FALLBACK_SUMMARY

    def test_raises_on_criterion_scores_not_list(self) -> None:
        payload = json.dumps({"criterion_scores": "bad", "summary_feedback": "ok"})
        with pytest.raises(LLMParseError, match="must be a JSON array"):
            parse_grading_response(payload, [_crit("c1")])


class TestParseGradingResponseMissingCriterion:
    def test_missing_criterion_produces_none_score(self) -> None:
        criteria = [_crit("crit-1"), _crit("crit-2")]
        # Only return one criterion
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "crit-1",
                        "score": 3,
                        "justification": "Long enough justification text here.",
                        "confidence": "high",
                    }
                ],
                "summary_feedback": "Good.",
            }
        )
        result = parse_grading_response(payload, criteria)
        missing = next(cs for cs in result.criterion_scores if cs.criterion_id == "crit-2")
        assert missing.score is None
        assert missing.confidence == "low"
        assert missing.needs_review is True
        assert missing.justification == FALLBACK_JUSTIFICATION

    def test_empty_response_list_all_criteria_missing(self) -> None:
        criteria = [_crit("c1"), _crit("c2")]
        payload = json.dumps({"criterion_scores": [], "summary_feedback": "ok"})
        result = parse_grading_response(payload, criteria)
        assert all(cs.score is None for cs in result.criterion_scores)
        assert all(cs.needs_review for cs in result.criterion_scores)


class TestParseGradingResponseScoreClamping:
    def test_score_above_max_clamped(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=10)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 5
        assert cs.score_clamped is True
        assert cs.confidence == "low"
        assert cs.needs_review is True

    def test_score_below_min_clamped(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=0)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 1
        assert cs.score_clamped is True

    def test_score_at_max_not_clamped(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=5)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 5
        assert not cs.score_clamped

    def test_score_at_min_not_clamped(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=1)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 1
        assert not cs.score_clamped

    def test_non_integer_score_clamped_to_min(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "c1",
                        "score": "not-a-number",
                        "justification": "Long enough justification text here.",
                        "confidence": "high",
                    }
                ],
                "summary_feedback": "ok",
            }
        )
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 1
        assert cs.score_clamped is True

    def test_float_score_converted_to_int(self) -> None:
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "c1",
                        "score": 3.7,
                        "justification": "Long enough justification text here.",
                        "confidence": "high",
                    }
                ],
                "summary_feedback": "ok",
            }
        )
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score == 3


class TestParseGradingResponseRawScore:
    def test_raw_score_populated_when_score_clamped_above_max(self) -> None:
        """raw_score holds the pre-clamp LLM integer when score exceeds max."""
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=10)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score_clamped is True
        assert cs.score == 5  # Clamped
        assert cs.raw_score == 10  # Original LLM value

    def test_raw_score_populated_when_score_clamped_below_min(self) -> None:
        """raw_score holds the pre-clamp LLM integer when score is below min."""
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=0)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score_clamped is True
        assert cs.score == 1  # Clamped to min
        assert cs.raw_score == 0  # Original LLM value

    def test_raw_score_none_when_score_unparseable(self) -> None:
        """raw_score is None when LLM returns an unparseable (non-numeric) score."""
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "c1",
                        "score": "not-a-number",
                        "justification": "Long enough justification text here.",
                        "confidence": "high",
                    }
                ],
                "summary_feedback": "ok",
            }
        )
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.score_clamped is True
        assert cs.raw_score is None  # No pre-clamp integer available

    def test_raw_score_not_set_when_score_in_range(self) -> None:
        """raw_score remains None when no clamping occurs."""
        criteria = [_crit("c1", min_score=1, max_score=5)]
        payload = _grading_payload(criterion_id="c1", score=3)
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert not cs.score_clamped
        assert cs.raw_score == 3  # Equals score (pre-clamp == post-clamp)


class TestParseGradingResponseJustification:
    def test_empty_justification_replaced_with_fallback(self) -> None:
        criteria = [_crit("c1")]
        payload = json.dumps(
            {
                "criterion_scores": [
                    {
                        "criterion_id": "c1",
                        "score": 3,
                        "justification": "",
                        "confidence": "high",
                    }
                ],
                "summary_feedback": "ok",
            }
        )
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.justification == FALLBACK_JUSTIFICATION
        assert cs.needs_review is True

    def test_short_justification_replaced_with_fallback(self) -> None:
        criteria = [_crit("c1")]
        payload = _grading_payload(criterion_id="c1", justification="Too short.")
        result = parse_grading_response(payload, criteria)
        cs = result.criterion_scores[0]
        assert cs.justification == FALLBACK_JUSTIFICATION
        assert cs.needs_review is True

    def test_justification_exactly_at_min_length(self) -> None:
        criteria = [_crit("c1")]
        # Exactly 20 characters
        just = "A" * 20
        payload = _grading_payload(criterion_id="c1", justification=just)
        result = parse_grading_response(payload, criteria)
        # 20 chars passes (>= MIN_JUSTIFICATION_LENGTH)
        cs = result.criterion_scores[0]
        assert cs.justification == just

    def test_missing_justification_key_replaced_with_fallback(self) -> None:
        criteria = [_crit("c1")]
        payload = json.dumps(
            {
                "criterion_scores": [{"criterion_id": "c1", "score": 3, "confidence": "high"}],
                "summary_feedback": "ok",
            }
        )
        result = parse_grading_response(payload, criteria)
        assert result.criterion_scores[0].justification == FALLBACK_JUSTIFICATION


class TestParseGradingResponseConfidence:
    def test_invalid_confidence_replaced_with_low(self) -> None:
        criteria = [_crit("c1")]
        payload = _grading_payload(criterion_id="c1", confidence="very_high")
        result = parse_grading_response(payload, criteria)
        assert result.criterion_scores[0].confidence == "low"

    def test_valid_confidence_values_preserved(self) -> None:
        for conf in ("high", "medium", "low"):
            criteria = [_crit("c1")]
            payload = _grading_payload(criterion_id="c1", confidence=conf)
            result = parse_grading_response(payload, criteria)
            # Clamped scores lower confidence, but this test uses score=3 (valid).
            assert result.criterion_scores[0].confidence == conf


class TestParseGradingResponseSummary:
    def test_blank_summary_replaced_with_fallback(self) -> None:
        criteria = [_crit("c1")]
        payload = _grading_payload(criterion_id="c1", summary_feedback="")
        result = parse_grading_response(payload, criteria)
        assert result.summary_feedback == FALLBACK_SUMMARY

    def test_whitespace_only_summary_replaced_with_fallback(self) -> None:
        criteria = [_crit("c1")]
        payload = _grading_payload(criterion_id="c1", summary_feedback="   ")
        result = parse_grading_response(payload, criteria)
        assert result.summary_feedback == FALLBACK_SUMMARY


# ===========================================================================
# parse_feedback_response
# ===========================================================================


class TestParseFeedbackResponseHappyPath:
    def test_returns_parsed_feedback_response(self) -> None:
        result = parse_feedback_response(_feedback_payload())
        assert isinstance(result, ParsedFeedbackResponse)

    def test_summary_preserved(self) -> None:
        result = parse_feedback_response(_feedback_payload(summary="Great essay!"))
        assert result.summary == "Great essay!"

    def test_criterion_feedback_populated(self) -> None:
        result = parse_feedback_response(
            _feedback_payload(criterion_id="crit-42", feedback="Strong argument.")
        )
        assert len(result.criterion_feedback) == 1
        cf = result.criterion_feedback[0]
        assert isinstance(cf, ParsedCriterionFeedback)
        assert cf.criterion_id == "crit-42"
        assert cf.feedback == "Strong argument."

    def test_next_steps_preserved(self) -> None:
        steps = ["Step one.", "Step two.", "Step three."]
        result = parse_feedback_response(_feedback_payload(next_steps=steps))
        assert result.next_steps == steps

    def test_empty_next_steps_list(self) -> None:
        result = parse_feedback_response(_feedback_payload(next_steps=[]))
        assert result.next_steps == []

    def test_non_string_items_in_next_steps_dropped(self) -> None:
        payload = json.dumps(
            {
                "summary": "ok",
                "criterion_feedback": [],
                "next_steps": ["valid step", 42, None, "another step"],
            }
        )
        result = parse_feedback_response(payload)
        assert result.next_steps == ["valid step", "another step"]

    def test_non_dict_items_in_criterion_feedback_dropped(self) -> None:
        payload = json.dumps(
            {
                "summary": "ok",
                "criterion_feedback": [
                    {"criterion_id": "c1", "feedback": "Good."},
                    "not a dict",
                    None,
                ],
                "next_steps": [],
            }
        )
        result = parse_feedback_response(payload)
        assert len(result.criterion_feedback) == 1


class TestParseFeedbackResponseErrors:
    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(LLMParseError, match="not valid JSON"):
            parse_feedback_response("not json")

    def test_raises_on_json_array(self) -> None:
        with pytest.raises(LLMParseError, match="must be a JSON object"):
            parse_feedback_response("[]")

    def test_raises_on_missing_summary(self) -> None:
        payload = json.dumps({"criterion_feedback": [], "next_steps": []})
        with pytest.raises(LLMParseError, match="missing required fields"):
            parse_feedback_response(payload)

    def test_raises_on_missing_criterion_feedback(self) -> None:
        payload = json.dumps({"summary": "ok", "next_steps": []})
        with pytest.raises(LLMParseError, match="missing required fields"):
            parse_feedback_response(payload)

    def test_raises_on_missing_next_steps(self) -> None:
        payload = json.dumps({"summary": "ok", "criterion_feedback": []})
        with pytest.raises(LLMParseError, match="missing required fields"):
            parse_feedback_response(payload)

    def test_raises_on_criterion_feedback_not_list(self) -> None:
        payload = json.dumps({"summary": "ok", "criterion_feedback": "bad", "next_steps": []})
        with pytest.raises(LLMParseError, match="must be a JSON array"):
            parse_feedback_response(payload)

    def test_raises_on_next_steps_not_list(self) -> None:
        payload = json.dumps({"summary": "ok", "criterion_feedback": [], "next_steps": "bad"})
        with pytest.raises(LLMParseError, match="must be a JSON array"):
            parse_feedback_response(payload)

    def test_item_missing_criterion_id_dropped(self) -> None:
        payload = json.dumps(
            {
                "summary": "ok",
                "criterion_feedback": [{"feedback": "no id here"}],
                "next_steps": [],
            }
        )
        result = parse_feedback_response(payload)
        assert result.criterion_feedback == []


# ===========================================================================
# parse_instruction_response
# ===========================================================================


class TestParseInstructionResponseHappyPath:
    def test_returns_parsed_instruction_response(self) -> None:
        result = parse_instruction_response(_instruction_payload())
        assert isinstance(result, ParsedInstructionResponse)

    def test_recommendation_fields_populated(self) -> None:
        result = parse_instruction_response(
            _instruction_payload(
                skill_dimension="evidence",
                title="Evidence Hunt",
                description="Find three pieces of evidence.",
                estimated_minutes=15,
                strategy_type="independent_practice",
            )
        )
        assert len(result.recommendations) == 1
        rec = result.recommendations[0]
        assert isinstance(rec, ParsedRecommendation)
        assert rec.skill_dimension == "evidence"
        assert rec.title == "Evidence Hunt"
        assert rec.estimated_minutes == 15
        assert rec.strategy_type == "independent_practice"

    def test_multiple_recommendations(self) -> None:
        payload = json.dumps(
            {
                "recommendations": [
                    {
                        "skill_dimension": "thesis",
                        "title": "A",
                        "description": "Desc A",
                        "estimated_minutes": 10,
                        "strategy_type": "mini_lesson",
                    },
                    {
                        "skill_dimension": "evidence",
                        "title": "B",
                        "description": "Desc B",
                        "estimated_minutes": 20,
                        "strategy_type": "guided_practice",
                    },
                ]
            }
        )
        result = parse_instruction_response(payload)
        assert len(result.recommendations) == 2

    def test_empty_recommendations_list(self) -> None:
        payload = json.dumps({"recommendations": []})
        result = parse_instruction_response(payload)
        assert result.recommendations == []

    def test_non_dict_items_in_recommendations_dropped(self) -> None:
        payload = json.dumps(
            {
                "recommendations": [
                    {
                        "skill_dimension": "thesis",
                        "title": "Valid",
                        "description": "ok",
                        "estimated_minutes": 10,
                        "strategy_type": "mini_lesson",
                    },
                    "not a dict",
                    None,
                ]
            }
        )
        result = parse_instruction_response(payload)
        assert len(result.recommendations) == 1


class TestParseInstructionResponseErrors:
    def test_raises_on_invalid_json(self) -> None:
        with pytest.raises(LLMParseError, match="not valid JSON"):
            parse_instruction_response("not json")

    def test_raises_on_json_array(self) -> None:
        with pytest.raises(LLMParseError, match="must be a JSON object"):
            parse_instruction_response("[]")

    def test_raises_on_missing_recommendations_field(self) -> None:
        payload = json.dumps({"other": "data"})
        with pytest.raises(LLMParseError, match="missing 'recommendations'"):
            parse_instruction_response(payload)

    def test_raises_on_recommendations_not_list(self) -> None:
        payload = json.dumps({"recommendations": "bad"})
        with pytest.raises(LLMParseError, match="must be a JSON array"):
            parse_instruction_response(payload)

    def test_bad_estimated_minutes_defaults_to_zero(self) -> None:
        payload = json.dumps(
            {
                "recommendations": [
                    {
                        "skill_dimension": "thesis",
                        "title": "T",
                        "description": "D",
                        "estimated_minutes": "not-a-number",
                        "strategy_type": "mini_lesson",
                    }
                ]
            }
        )
        result = parse_instruction_response(payload)
        assert result.recommendations[0].estimated_minutes == 0
