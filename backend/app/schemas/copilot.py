"""Pydantic schemas for the teacher copilot data query layer (M7-03).

No student PII is logged.  Student IDs appear in response bodies only,
never in log lines.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CopilotQueryRequest(BaseModel):
    """Request body for ``POST /copilot/query``.

    Attributes:
        query: The teacher's natural-language question (1–500 chars).
        class_id: Optional class UUID to scope the context data.  When
            omitted the service aggregates across all of the teacher's
            classes.
    """

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Natural-language question from the teacher.",
    )
    class_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional class UUID.  When provided, context data is restricted "
            "to students enrolled in this class."
        ),
    )


class CopilotRankedItemResponse(BaseModel):
    """One ranked item surfaced by the copilot.

    Attributes:
        student_id: Student UUID, or ``None`` for skill-level items.
        student_display_name: Resolved student name for display.  ``None``
            for skill-level items or when the student record cannot be found.
        skill_dimension: Canonical skill dimension (e.g. ``"thesis"``), or
            ``None`` for student-level items.
        label: Short descriptive label.
        value: Normalised score / signal strength in ``[0.0, 1.0]``, or
            ``None`` when not applicable.
        explanation: Evidence-grounded explanation for this item's ranking.
    """

    student_id: uuid.UUID | None = None
    student_display_name: str | None = None
    skill_dimension: str | None = None
    label: str
    value: float | None = None
    explanation: str


class CopilotQueryResponse(BaseModel):
    """Response body for ``POST /copilot/query``.

    Attributes:
        query_interpretation: One sentence summarising what the LLM
            understood the teacher to be asking.
        has_sufficient_data: ``False`` when the class data is too sparse
            to produce a reliable answer.
        uncertainty_note: Human-readable explanation of data gaps, or
            ``None`` when data is sufficient.
        response_type: One of ``"ranked_list"``, ``"summary"``, or
            ``"insufficient_data"``.
        ranked_items: Ranked list of students or skill dimensions most
            relevant to the query.  May be empty.
        summary: 2–3 sentence overall answer to the teacher's question.
        suggested_next_steps: Actionable follow-up steps for the teacher.
        prompt_version: The versioned prompt module used to generate this
            response (e.g. ``"copilot-v1"``).
    """

    query_interpretation: str
    has_sufficient_data: bool
    uncertainty_note: str | None = None
    response_type: Literal["ranked_list", "summary", "insufficient_data"]
    ranked_items: list[CopilotRankedItemResponse] = Field(default_factory=list)
    summary: str
    suggested_next_steps: list[str] = Field(default_factory=list)
    prompt_version: str
