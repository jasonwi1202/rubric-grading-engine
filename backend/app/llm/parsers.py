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

        parsed_scores.append(
            ParsedCriterionScore(
                criterion_id=info.criterion_id,
                score=score,
                justification=justification,
                confidence=confidence,
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
