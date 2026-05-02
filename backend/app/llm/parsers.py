"""LLM response parsers for the Rubric Grading Engine.

This module is the *only* place where raw LLM response strings are
transformed into validated, typed Python objects.  Every LLM response
passes through here before any data is written to the database.

Design rules:
    - Parsing is fully deterministic — no I/O, no randomness.
    - Out-of-range scores are clamped and the anomaly is logged (never
      stored raw).
    - Missing criteria get a ``None`` score, ``confidence="low"``, and
      ``needs_review=True`` — they are never silently dropped.
    - Short / empty justifications fall back to ``FALLBACK_JUSTIFICATION``
      and are flagged for teacher review.
    - ``summary_feedback`` falls back to a safe placeholder if blank.

Test coverage target: ≥ 95 % (fully deterministic logic).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.exceptions import LLMParseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_JUSTIFICATION_LENGTH: int = 20
FALLBACK_JUSTIFICATION: str = "No justification provided."
FALLBACK_SUMMARY: str = "No summary feedback provided."
FALLBACK_FEEDBACK: str = "No feedback note provided."
VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})

# ---------------------------------------------------------------------------
# Input descriptors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriterionInfo:
    """Minimal criterion data needed for response validation.

    Attributes:
        criterion_id: UUID string matching the rubric snapshot.
        min_score: Minimum valid integer score for this criterion.
        max_score: Maximum valid integer score for this criterion.
    """

    criterion_id: str
    min_score: int
    max_score: int


# ---------------------------------------------------------------------------
# Grading response
# ---------------------------------------------------------------------------


@dataclass
class ParsedCriterionScore:
    """Validated score for a single criterion.

    Attributes:
        criterion_id: UUID string.
        score: Clamped integer score, or ``None`` if the LLM omitted the
            criterion entirely.
        justification: Non-empty justification string (may be the fallback).
        confidence: One of ``"high"``, ``"medium"``, ``"low"``.
        ai_feedback: Per-criterion student-facing feedback note.  Empty string
            when the LLM response did not include the field (e.g. v1 responses).
        score_clamped: ``True`` when the raw LLM score was outside the valid
            range and was clamped.
        needs_review: ``True`` when any anomaly was detected — the teacher
            should review this score before locking the grade.
        raw_score: The integer score parsed from the LLM response, or
            ``None`` when the LLM returned an unparseable value.  When
            ``score_clamped`` is ``True``, this stores the original
            pre-clamp value used to populate the ``score_clamped`` audit
            log entry.
    """

    criterion_id: str
    score: int | None
    justification: str
    confidence: str
    ai_feedback: str = ""
    score_clamped: bool = False
    needs_review: bool = False
    raw_score: int | None = None


@dataclass
class ParsedGradingResponse:
    """Fully validated LLM grading response.

    Attributes:
        criterion_scores: One entry per criterion in the rubric snapshot.
        summary_feedback: Overall essay assessment paragraph.
    """

    criterion_scores: list[ParsedCriterionScore] = field(default_factory=list)
    summary_feedback: str = ""


def parse_grading_response(
    raw_content: str,
    criteria: list[CriterionInfo],
) -> ParsedGradingResponse:
    """Parse and validate a raw LLM grading response string.

    Applies the following normalization in order:
    1.  JSON decode — raises ``LLMParseError`` on failure.
    2.  Top-level structure check — must be an object with a
        ``criterion_scores`` list.  ``summary_feedback`` is optional.
    3.  For each criterion expected by the rubric snapshot:
        - Missing from response → ``score=None``, ``confidence="low"``,
          ``needs_review=True``.
        - Score outside ``[min_score, max_score]`` → clamp, lower
          ``confidence`` to ``"low"``, set ``score_clamped=True``,
          ``needs_review=True``, log warning.
        - Justification shorter than ``MIN_JUSTIFICATION_LENGTH`` or blank
          → replace with ``FALLBACK_JUSTIFICATION``, ``needs_review=True``.
        - Invalid ``confidence`` value → replace with ``"low"``.
    4.  Extra entries in the response (criterion IDs not in the rubric
        snapshot) are silently ignored.
    5.  ``summary_feedback`` blank or missing → replaced with
        ``FALLBACK_SUMMARY``.

    Args:
        raw_content: The raw string content from the LLM response.
        criteria: Criterion descriptors from the rubric snapshot.

    Returns:
        A ``ParsedGradingResponse`` with one entry per expected criterion.

    Raises:
        LLMParseError: If ``raw_content`` is not valid JSON or is missing
            the required ``criterion_scores`` field.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("LLM response is not valid JSON") from exc

    if not isinstance(data, dict):
        raise LLMParseError("LLM response must be a JSON object")

    if "criterion_scores" not in data:
        raise LLMParseError("LLM response missing required field: criterion_scores")

    if not isinstance(data["criterion_scores"], list):
        raise LLMParseError("criterion_scores must be a JSON array")

    # Build lookup from the returned list; ignore duplicate / unknown criterion IDs.
    returned: dict[str, dict[str, object]] = {}
    for item in data["criterion_scores"]:
        if isinstance(item, dict) and "criterion_id" in item:
            cid = str(item["criterion_id"])
            returned[cid] = item

    parsed_scores: list[ParsedCriterionScore] = []

    for info in criteria:
        item = returned.get(info.criterion_id)

        if item is None:
            # Criterion completely absent from LLM response.
            logger.warning(
                "LLM response missing criterion",
                extra={"criterion_id": info.criterion_id},
            )
            parsed_scores.append(
                ParsedCriterionScore(
                    criterion_id=info.criterion_id,
                    score=None,
                    justification=FALLBACK_JUSTIFICATION,
                    confidence="low",
                    ai_feedback="",
                    needs_review=True,
                )
            )
            continue

        # --- Score validation / clamping ---
        score_clamped = False
        needs_review = False
        pre_clamp_score: int | None = None

        try:
            raw_score = item.get("score")
            if isinstance(raw_score, (int, float, str)):
                score: int = int(raw_score)
                pre_clamp_score = score  # Record before any clamping
            else:
                raise TypeError("non-numeric score type")
        except (TypeError, ValueError):
            # Unparse-able score — clamp to minimum.
            score = info.min_score
            score_clamped = True
            needs_review = True

        if score < info.min_score:
            score = info.min_score
            score_clamped = True
        elif score > info.max_score:
            score = info.max_score
            score_clamped = True

        if score_clamped:
            logger.warning(
                "LLM returned out-of-range score, clamped",
                extra={
                    "criterion_id": info.criterion_id,
                    "raw_score": raw_score,
                    "clamped_to": score,
                },
            )
            needs_review = True

        # --- Justification validation ---
        raw_just = item.get("justification", "")
        justification = str(raw_just) if raw_just else ""
        if len(justification.strip()) < MIN_JUSTIFICATION_LENGTH:
            logger.warning(
                "LLM returned short or empty justification",
                extra={"criterion_id": info.criterion_id},
            )
            justification = FALLBACK_JUSTIFICATION
            needs_review = True

        # --- Confidence validation ---
        confidence = str(item.get("confidence", "low"))
        if confidence not in VALID_CONFIDENCE:
            confidence = "low"

        # Any clamped score also lowers confidence.
        if score_clamped:
            confidence = "low"

        # --- Per-criterion feedback note (v2+) ---
        # When the ``feedback`` key is present in the response (grading-v2),
        # use its value or fall back to the placeholder.  When the key is
        # absent entirely (grading-v1 responses), keep an empty string so
        # callers can distinguish "no feedback requested" from "empty feedback".
        # Use an explicit key-presence check so that `"feedback": null` in a v2
        # response is treated as a missing/blank value (→ FALLBACK_FEEDBACK)
        # rather than as a v1 "field absent" response (→ "").
        if "feedback" in item:
            feedback_raw = item["feedback"]
            ai_feedback = str(feedback_raw).strip() if feedback_raw else ""
            if not ai_feedback:
                ai_feedback = FALLBACK_FEEDBACK
        else:
            ai_feedback = ""

        parsed_scores.append(
            ParsedCriterionScore(
                criterion_id=info.criterion_id,
                score=score,
                justification=justification,
                confidence=confidence,
                ai_feedback=ai_feedback,
                score_clamped=score_clamped,
                needs_review=needs_review,
                raw_score=pre_clamp_score,
            )
        )

    # --- Summary feedback ---
    raw_summary = data.get("summary_feedback", "")
    summary_feedback = str(raw_summary).strip() if raw_summary else ""
    if not summary_feedback:
        summary_feedback = FALLBACK_SUMMARY

    return ParsedGradingResponse(
        criterion_scores=parsed_scores,
        summary_feedback=summary_feedback,
    )


# ---------------------------------------------------------------------------
# Feedback response
# ---------------------------------------------------------------------------


@dataclass
class ParsedCriterionFeedback:
    """Student-facing feedback for a single criterion.

    Attributes:
        criterion_id: UUID string.
        feedback: Actionable feedback text.
    """

    criterion_id: str
    feedback: str


@dataclass
class ParsedFeedbackResponse:
    """Fully validated LLM feedback generation response.

    Attributes:
        summary: Overall feedback paragraph.
        criterion_feedback: Per-criterion feedback entries.
        next_steps: Actionable next-step recommendations.
    """

    summary: str = ""
    criterion_feedback: list[ParsedCriterionFeedback] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


def parse_feedback_response(raw_content: str) -> ParsedFeedbackResponse:
    """Parse and validate a raw LLM feedback generation response.

    Args:
        raw_content: The raw string content from the LLM response.

    Returns:
        A ``ParsedFeedbackResponse``.

    Raises:
        LLMParseError: If ``raw_content`` is not valid JSON or is missing
            required fields.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("LLM feedback response is not valid JSON") from exc

    if not isinstance(data, dict):
        raise LLMParseError("LLM feedback response must be a JSON object")

    required = {"summary", "criterion_feedback", "next_steps"}
    missing = required - data.keys()
    if missing:
        raise LLMParseError(
            f"LLM feedback response missing required fields: {', '.join(sorted(missing))}"
        )

    if not isinstance(data["criterion_feedback"], list):
        raise LLMParseError("criterion_feedback must be a JSON array")

    if not isinstance(data["next_steps"], list):
        raise LLMParseError("next_steps must be a JSON array")

    criterion_feedback: list[ParsedCriterionFeedback] = []
    for item in data["criterion_feedback"]:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("criterion_id", ""))
        fb = str(item.get("feedback", "")).strip()
        if cid:
            criterion_feedback.append(ParsedCriterionFeedback(criterion_id=cid, feedback=fb))

    next_steps: list[str] = [
        str(s).strip() for s in data["next_steps"] if isinstance(s, str) and str(s).strip()
    ]

    summary = str(data.get("summary", "")).strip()

    return ParsedFeedbackResponse(
        summary=summary,
        criterion_feedback=criterion_feedback,
        next_steps=next_steps,
    )


# ---------------------------------------------------------------------------
# Instruction recommendations response
# ---------------------------------------------------------------------------


@dataclass
class ParsedRecommendation:
    """A single instruction recommendation.

    Attributes:
        skill_dimension: Canonical skill dimension (e.g. ``"thesis"``).
        title: Short activity title.
        description: Specific, actionable description.
        estimated_minutes: Target duration in minutes.
        strategy_type: Instructional strategy label.
    """

    skill_dimension: str
    title: str
    description: str
    estimated_minutes: int
    strategy_type: str


@dataclass
class ParsedInstructionResponse:
    """Fully validated LLM instruction recommendations response.

    Attributes:
        recommendations: List of recommended activities.
    """

    recommendations: list[ParsedRecommendation] = field(default_factory=list)


def parse_instruction_response(raw_content: str) -> ParsedInstructionResponse:
    """Parse and validate a raw LLM instruction recommendations response.

    Args:
        raw_content: The raw string content from the LLM response.

    Returns:
        A ``ParsedInstructionResponse``.

    Raises:
        LLMParseError: If ``raw_content`` is not valid JSON or missing the
            ``recommendations`` field.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("LLM instruction response is not valid JSON") from exc

    if not isinstance(data, dict):
        raise LLMParseError("LLM instruction response must be a JSON object")

    if "recommendations" not in data:
        raise LLMParseError("LLM instruction response missing 'recommendations' field")

    if not isinstance(data["recommendations"], list):
        raise LLMParseError("recommendations must be a JSON array")

    recommendations: list[ParsedRecommendation] = []
    for item in data["recommendations"]:
        if not isinstance(item, dict):
            continue
        try:
            estimated_minutes = int(item.get("estimated_minutes", 0))
        except (TypeError, ValueError):
            estimated_minutes = 0

        recommendations.append(
            ParsedRecommendation(
                skill_dimension=str(item.get("skill_dimension", "")).strip(),
                title=str(item.get("title", "")).strip(),
                description=str(item.get("description", "")).strip(),
                estimated_minutes=estimated_minutes,
                strategy_type=str(item.get("strategy_type", "")).strip(),
            )
        )

    return ParsedInstructionResponse(recommendations=recommendations)


# ---------------------------------------------------------------------------
# Revision comparison response (M6-11)
# ---------------------------------------------------------------------------


@dataclass
class ParsedCriterionAssessment:
    """Assessment of whether a single criterion's feedback was addressed.

    Attributes:
        criterion_id: UUID string matching the rubric criterion.
        addressed: ``True`` when the revision meaningfully addresses the
            feedback given on the prior submission.
        detail: One-sentence explanation from the LLM.
    """

    criterion_id: str
    addressed: bool
    detail: str


@dataclass
class ParsedRevisionResponse:
    """Fully validated LLM revision comparison response.

    Attributes:
        criterion_assessments: Per-criterion addressed/not-addressed judgments.
    """

    criterion_assessments: list[ParsedCriterionAssessment] = field(default_factory=list)


def parse_revision_response(raw_content: str) -> ParsedRevisionResponse:
    """Parse and validate a raw LLM revision comparison response.

    Args:
        raw_content: The raw string content from the LLM response.

    Returns:
        A ``ParsedRevisionResponse``.

    Raises:
        LLMParseError: If ``raw_content`` is not valid JSON or is missing
            the required ``criterion_assessments`` field.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("LLM revision response is not valid JSON") from exc

    if not isinstance(data, dict):
        raise LLMParseError("LLM revision response must be a JSON object")

    if "criterion_assessments" not in data:
        raise LLMParseError("LLM revision response missing 'criterion_assessments' field")

    if not isinstance(data["criterion_assessments"], list):
        raise LLMParseError("criterion_assessments must be a JSON array")

    assessments: list[ParsedCriterionAssessment] = []
    for item in data["criterion_assessments"]:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("criterion_id", "")).strip()
        if not cid:
            continue
        addressed_raw = item.get("addressed", False)
        # Accept boolean or specific string values from the LLM.
        # For any other type (e.g., dict, list, int) default to False rather
        # than using bool() which would silently mark unexpected values as True.
        if isinstance(addressed_raw, bool):
            addressed = addressed_raw
        elif isinstance(addressed_raw, str):
            addressed = addressed_raw.lower() in {"true", "yes", "1"}
        else:
            addressed = False
        detail = str(item.get("detail", "")).strip() or "No detail provided."
        assessments.append(
            ParsedCriterionAssessment(
                criterion_id=cid,
                addressed=addressed,
                detail=detail,
            )
        )

    return ParsedRevisionResponse(criterion_assessments=assessments)


# ---------------------------------------------------------------------------
# Teacher copilot query response (M7-03)
# ---------------------------------------------------------------------------

#: Valid response type strings returned by the copilot LLM.
VALID_COPILOT_RESPONSE_TYPES: frozenset[str] = frozenset(
    {"ranked_list", "summary", "insufficient_data"}
)


@dataclass
class CopilotRankedItem:
    """One ranked item in a teacher copilot response.

    Attributes:
        student_id: Student UUID string, or ``None`` for skill-level items.
        skill_dimension: Canonical skill dimension name (e.g. ``"thesis"``),
            or ``None`` for student-level items.
        label: Short descriptive label for display in the teacher UI.
        value: Normalised score or signal strength in ``[0.0, 1.0]``, or
            ``None`` when no numeric value is applicable.
        explanation: Evidence-grounded explanation for this item's ranking.
    """

    student_id: str | None
    skill_dimension: str | None
    label: str
    value: float | None
    explanation: str


@dataclass
class ParsedCopilotResponse:
    """Fully validated LLM teacher copilot response.

    Attributes:
        query_interpretation: One-sentence summary of what the LLM
            understood the teacher to be asking.
        has_sufficient_data: ``False`` when data is too sparse to produce
            a reliable answer.
        uncertainty_note: Human-readable explanation of data gaps, or
            ``None`` when data is sufficient.
        response_type: One of ``"ranked_list"``, ``"summary"``, or
            ``"insufficient_data"``.
        ranked_items: Ordered list of ranked items (may be empty).
        summary: 2–3 sentence overall answer.
        suggested_next_steps: Actionable follow-up steps for the teacher.
    """

    query_interpretation: str
    has_sufficient_data: bool
    uncertainty_note: str | None
    response_type: str
    ranked_items: list[CopilotRankedItem] = field(default_factory=list)
    summary: str = ""
    suggested_next_steps: list[str] = field(default_factory=list)


def parse_copilot_response(raw_content: str) -> ParsedCopilotResponse:
    """Parse and validate a raw LLM teacher copilot response.

    Applies the following normalization:
    1. JSON decode — raises ``LLMParseError`` on failure.
    2. Top-level structure check — must be a JSON object with
       ``query_interpretation``, ``has_sufficient_data``,
       ``response_type``, ``ranked_items``, and ``summary``.
    3. ``response_type`` is normalised to ``"ranked_list"`` if the value
       returned by the LLM is not in :data:`VALID_COPILOT_RESPONSE_TYPES`.
    4. Each ranked item is coerced to a :class:`CopilotRankedItem`; items
       with invalid structure are silently skipped.
    5. ``value`` is clamped to ``[0.0, 1.0]`` when present; unparseable
       values are set to ``None``.
    6. At most 20 ranked items are kept (excess items are dropped).
    7. Blank ``summary`` falls back to a safe placeholder.

    Args:
        raw_content: The raw string content from the LLM response.

    Returns:
        A ``ParsedCopilotResponse``.

    Raises:
        LLMParseError: If ``raw_content`` is not valid JSON, is not a JSON
            object, or is missing required top-level fields.
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise LLMParseError("LLM copilot response is not valid JSON") from exc

    if not isinstance(data, dict):
        raise LLMParseError("LLM copilot response must be a JSON object")

    required = {
        "query_interpretation",
        "has_sufficient_data",
        "response_type",
        "ranked_items",
        "summary",
    }
    missing = required - data.keys()
    if missing:
        raise LLMParseError(
            f"LLM copilot response missing required fields: {', '.join(sorted(missing))}"
        )

    # --- query_interpretation ---
    query_interpretation = str(data.get("query_interpretation", "")).strip()
    if not query_interpretation:
        query_interpretation = "Query could not be interpreted."

    # --- has_sufficient_data ---
    raw_sufficient = data.get("has_sufficient_data")
    if isinstance(raw_sufficient, bool):
        has_sufficient_data = raw_sufficient
    elif isinstance(raw_sufficient, str):
        has_sufficient_data = raw_sufficient.lower() in {"true", "yes", "1"}
    else:
        has_sufficient_data = False

    # --- uncertainty_note ---
    raw_note = data.get("uncertainty_note")
    if raw_note is None or (isinstance(raw_note, str) and not raw_note.strip()):
        uncertainty_note: str | None = None
    else:
        uncertainty_note = str(raw_note).strip()

    # --- response_type ---
    response_type = str(data.get("response_type", "")).strip()
    if response_type not in VALID_COPILOT_RESPONSE_TYPES:
        logger.warning(
            "LLM copilot returned unknown response_type; normalising",
            extra={"response_type": response_type},
        )
        response_type = "ranked_list"

    # --- ranked_items ---
    raw_items = data.get("ranked_items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    ranked_items: list[CopilotRankedItem] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue

        # student_id — accept string or null
        raw_sid = item.get("student_id")
        student_id: str | None = str(raw_sid).strip() if raw_sid else None

        # skill_dimension — accept string or null
        raw_skill = item.get("skill_dimension")
        skill_dimension: str | None = str(raw_skill).strip() if raw_skill else None

        # label — required; skip item if blank
        label = str(item.get("label", "")).strip()
        if not label:
            continue

        # value — optional float clamped to [0.0, 1.0]
        raw_value = item.get("value")
        value: float | None = None
        if raw_value is not None:
            try:
                parsed_val = float(raw_value)
                value = max(0.0, min(1.0, parsed_val))
            except (TypeError, ValueError):
                value = None

        # explanation
        explanation = str(item.get("explanation", "")).strip() or "No explanation provided."

        ranked_items.append(
            CopilotRankedItem(
                student_id=student_id,
                skill_dimension=skill_dimension,
                label=label,
                value=value,
                explanation=explanation,
            )
        )

        if len(ranked_items) >= 20:
            break

    # --- summary ---
    summary = str(data.get("summary", "")).strip()
    if not summary:
        summary = "No summary available."

    # --- suggested_next_steps ---
    raw_steps = data.get("suggested_next_steps", [])
    if not isinstance(raw_steps, list):
        raw_steps = []
    suggested_next_steps: list[str] = [
        str(s).strip() for s in raw_steps if isinstance(s, str) and str(s).strip()
    ]

    return ParsedCopilotResponse(
        query_interpretation=query_interpretation,
        has_sufficient_data=has_sufficient_data,
        uncertainty_note=uncertainty_note,
        response_type=response_type,
        ranked_items=ranked_items,
        summary=summary,
        suggested_next_steps=suggested_next_steps,
    )
