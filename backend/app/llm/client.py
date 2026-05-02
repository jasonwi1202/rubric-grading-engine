"""LLM client for the Rubric Grading Engine.

All calls to the OpenAI API go through this module. Direct use of
``openai.chat.completions.create()`` elsewhere in the codebase is not
permitted.

Responsibilities:
    - Load the correct versioned prompt module.
    - Inject rubric / score / profile data into the system prompt.
    - Wrap essay text in ``<ESSAY_START>`` / ``<ESSAY_END>`` in the user turn.
    - Apply retry logic with exponential back-off on transport errors.
    - Retry *once* with a corrective user turn on JSON-parse failures.
    - Pass raw responses to ``app.llm.parsers`` for schema validation.
    - Never log essay content or raw LLM response bodies.

Security invariants (non-negotiable):
    - Essay text is ALWAYS placed in the ``user`` role — never in the
      system prompt.
    - Every grading / feedback system prompt contains the injection defence
      instruction.
    - See ``docs/architecture/security.md#1-prompt-injection-defense``.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import logging
import types

import openai

from app.config import settings
from app.exceptions import LLMError, LLMParseError, ValidationError
from app.llm.parsers import (
    CriterionInfo,
    ParsedCopilotResponse,
    ParsedCriterionScore,
    ParsedFeedbackResponse,
    ParsedGradingResponse,
    ParsedInstructionResponse,
    ParsedRevisionResponse,
    parse_copilot_response,
    parse_feedback_response,
    parse_grading_response,
    parse_instruction_response,
    parse_revision_response,
)

logger = logging.getLogger(__name__)


def _is_fake_mode() -> bool:
    """Return whether deterministic fake LLM outputs are enabled."""
    # Use an explicit identity check to avoid truthy MagicMock values when
    # tests patch `settings` partially.
    return getattr(settings, "llm_fake_mode", False) is True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_openai_client() -> openai.AsyncOpenAI:
    """Return a configured ``AsyncOpenAI`` client.

    The client is constructed on every call so that tests can safely patch
    ``settings.openai_api_key`` without needing to replace a module-level
    singleton.
    """
    return openai.AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=float(settings.llm_request_timeout_seconds),
        max_retries=0,  # Retry logic is handled by this module.
    )


def _load_prompt_module(prompt_type: str, version: str) -> types.ModuleType:
    """Dynamically load a versioned prompt module.

    Args:
        prompt_type: One of ``"grading"``, ``"feedback"``,
            ``"instruction"``.
        version: Version string, e.g. ``"v1"``.

    Returns:
        The imported prompt module.

    Raises:
        LLMError: If no module matching ``{prompt_type}_{version}`` exists
            under ``app.llm.prompts``.
    """
    module_name = f"app.llm.prompts.{prompt_type}_{version}"
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise LLMError(f"Prompt module not found: {module_name}") from exc


async def _chat_with_retry(
    client: openai.AsyncOpenAI,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Call ``chat.completions.create`` with exponential back-off.

    Only transport-level errors (timeouts, API errors) trigger retries here.
    JSON-parse failures are handled by the calling function.

    Args:
        client: Configured ``AsyncOpenAI`` instance.
        model: Model identifier.
        messages: Messages list for the API call.

    Returns:
        The raw string content of the first choice.

    Raises:
        LLMError: After all retry attempts are exhausted.
    """
    last_exc: LLMError | None = None
    max_attempts = settings.llm_max_retries + 1  # 1 initial + N retries

    for attempt in range(max_attempts):
        if attempt > 0:
            wait = 2**attempt
            logger.info(
                "Retrying LLM call after transport error",
                extra={"attempt": attempt, "wait_seconds": wait},
            )
            await asyncio.sleep(wait)

        try:
            # SDK stubs define separate overloads keyed on `stream`; passing a
            # plain dict for `response_format` (instead of a typed
            # `ResponseFormat`) does not match any single overload at the
            # type-checker level, but runtime behaviour is correct.  Switching
            # to the fully-typed SDK parameter objects would require importing
            # private SDK types that change across minor releases, so the
            # ignore is the stable choice.
            response = await client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""
        except openai.APITimeoutError as exc:
            logger.warning(
                "LLM request timed out",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            last_exc = LLMError("LLM request timed out")
        except openai.APIError as exc:
            logger.warning(
                "LLM API error",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            last_exc = LLMError("LLM API error")

    raise last_exc or LLMError("LLM call failed after retries")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _build_messages_with_tone(
    module: types.ModuleType,
    rubric_json: str,
    strictness: str,
    essay_text: str,
    tone: str,
    *,
    retry: bool = False,
) -> list[dict[str, str]]:
    """Build the messages list for a grading request, optionally with tone.

    Passes ``tone`` only when the prompt module's ``build_messages`` (or
    ``build_retry_messages``) accepts it — grading-v2+.  Falls back to the
    three-argument call (``rubric_json``, ``strictness``, ``essay_text``) for
    grading-v1 to preserve backwards compatibility.

    Args:
        module: The loaded prompt module (e.g. ``grading_v1`` or ``grading_v2``).
        rubric_json: JSON-encoded rubric snapshot.
        strictness: Grading strictness level.
        essay_text: Raw student essay text.
        tone: Feedback tone string.
        retry: When ``True``, calls ``build_retry_messages`` instead of
            ``build_messages``.

    Returns:
        Messages list suitable for OpenAI chat completions.
    """
    import inspect  # noqa: PLC0415

    builder = module.build_retry_messages if retry else module.build_messages
    sig = inspect.signature(builder)
    if "tone" in sig.parameters:
        return builder(rubric_json, strictness, essay_text, tone)  # type: ignore[no-any-return]
    return builder(rubric_json, strictness, essay_text)  # type: ignore[no-any-return]


async def call_grading(
    *,
    rubric_json: str,
    strictness: str,
    essay_text: str,
    criteria: list[CriterionInfo],
    tone: str = "direct",
    prompt_version: str | None = None,
) -> ParsedGradingResponse:
    """Grade an essay against a rubric.

    Essay text is always placed in the ``user`` role.  The system prompt
    (built by the versioned prompt module) never contains essay content.

    Args:
        rubric_json: JSON-encoded rubric snapshot (criteria + score ranges).
        strictness: One of ``"lenient"``, ``"balanced"``, ``"strict"``.
        essay_text: Raw student essay text.
        criteria: Criterion descriptors used to validate / clamp the
            response.  Must match the criteria in ``rubric_json``.
        tone: Feedback tone injected into the system prompt — one of
            ``"encouraging"``, ``"direct"``, ``"academic"``.  Defaults to
            ``"direct"``.  Passed to the prompt module's ``build_messages``
            if the module accepts a ``tone`` keyword argument (v2+).
        prompt_version: Override the active version from
            ``settings.grading_prompt_version``.  Defaults to the setting.

    Returns:
        A validated ``ParsedGradingResponse``.

    Raises:
        LLMParseError: If the response cannot be parsed after one corrective
            retry.
        LLMError: On timeout or unrecoverable API failure.
    """

    if _is_fake_mode():
        fake_scores = []
        for info in criteria:
            midpoint = int((info.min_score + info.max_score) / 2)
            fake_scores.append(
                ParsedCriterionScore(
                    criterion_id=info.criterion_id,
                    score=midpoint,
                    justification=(
                        "Deterministic test justification generated in fake LLM mode. "
                        "Teacher should still review before locking."
                    ),
                    confidence="high",
                    ai_feedback="Deterministic test feedback.",
                    score_clamped=False,
                    needs_review=False,
                    raw_score=midpoint,
                )
            )
        return ParsedGradingResponse(
            criterion_scores=fake_scores,
            summary_feedback="Deterministic test summary feedback.",
        )

    version = prompt_version or settings.grading_prompt_version
    module = _load_prompt_module("grading", version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages = _build_messages_with_tone(module, rubric_json, strictness, essay_text, tone)
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_grading_response(raw, criteria)
    except LLMParseError:
        logger.warning(
            "LLM grading parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages = _build_messages_with_tone(
            module, rubric_json, strictness, essay_text, tone, retry=True
        )
        retry_raw = await _chat_with_retry(client, model, retry_messages)
        # Let LLMParseError propagate on the second failure.
        return parse_grading_response(retry_raw, criteria)


async def call_feedback(
    *,
    approved_scores_json: str,
    tone: str,
    essay_text: str,
    prompt_version: str = "v1",
) -> ParsedFeedbackResponse:
    """Generate student-facing written feedback from a locked grade.

    Must only be called after a teacher has reviewed and locked the grade.

    Essay text is always placed in the ``user`` role.

    Args:
        approved_scores_json: JSON-encoded criterion scores approved by the
            teacher.
        tone: One of ``"encouraging"``, ``"neutral"``, ``"direct"``.
        essay_text: Raw student essay text.
        prompt_version: Prompt version to use (default: ``"v1"``).

    Returns:
        A validated ``ParsedFeedbackResponse``.

    Raises:
        LLMParseError: If the response cannot be parsed after one retry.
        LLMError: On timeout or unrecoverable API failure.
    """
    module = _load_prompt_module("feedback", prompt_version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages: list[dict[str, str]] = module.build_messages(approved_scores_json, tone, essay_text)
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_feedback_response(raw)
    except LLMParseError:
        logger.warning(
            "LLM feedback parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages = module.build_retry_messages(approved_scores_json, tone, essay_text)
        retry_raw = await _chat_with_retry(client, model, retry_messages)
        return parse_feedback_response(retry_raw)


async def call_instruction(
    *,
    skill_profile_json: str,
    grade_level: str,
    duration_minutes: int,
    prompt_version: str = "v1",
) -> ParsedInstructionResponse:
    """Generate instruction recommendations from a student skill profile.

    No essay content is used — only aggregate performance data.

    Args:
        skill_profile_json: JSON-encoded student skill profile.
        grade_level: Grade level descriptor, e.g. ``"Grade 8"``.
        duration_minutes: Target activity duration in minutes.
        prompt_version: Prompt version to use (default: ``"v1"``).

    Returns:
        A validated ``ParsedInstructionResponse``.

    Raises:
        LLMParseError: If the response cannot be parsed after one retry.
        LLMError: On timeout or unrecoverable API failure.
    """
    module = _load_prompt_module("instruction", prompt_version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages: list[dict[str, str]] = module.build_messages(
        skill_profile_json, grade_level, duration_minutes
    )
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_instruction_response(raw)
    except LLMParseError:
        logger.warning(
            "LLM instruction parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages = module.build_retry_messages(
            skill_profile_json, grade_level, duration_minutes
        )
        retry_raw = await _chat_with_retry(client, model, retry_messages)
        return parse_instruction_response(retry_raw)


async def call_embedding(text: str) -> list[float]:
    """Generate a text embedding vector using the configured OpenAI model.

    The embedding is computed via ``openai.AsyncOpenAI.embeddings.create``.
    Transport-level errors (timeouts, API errors, connection errors, rate
    limits) are retried with exponential back-off up to
    ``settings.llm_max_retries`` times before raising
    :exc:`~app.exceptions.LLMError`.  The retry logic mirrors
    :func:`_chat_with_retry` — ``openai.APIError`` (the base class for all
    OpenAI API exceptions including ``APIConnectionError`` and
    ``RateLimitError``) is caught on every attempt.

    Args:
        text: The plain-text content to embed.  Must not be empty or
            whitespace-only.

    Returns:
        A ``list[float]`` of ``settings.openai_embedding_model`` dimensions
        (1 536 for ``text-embedding-3-small``).

    Raises:
        ValidationError: If ``text`` is empty or whitespace-only.
        LLMError: On timeout or unrecoverable API failure after all retries.

    Security note:
        The text argument is never logged — callers must not pass log-visible
        content and should use entity IDs in their own log calls instead.
    """
    if not text.strip():
        raise ValidationError("text must not be empty or whitespace-only")

    if _is_fake_mode():
        # Generate a stable pseudo-embedding with the expected 1,536 dims.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        base = [b / 255.0 for b in digest]
        repeated = (base * ((1536 // len(base)) + 1))[:1536]
        return repeated

    client = _get_openai_client()
    max_attempts = settings.llm_max_retries + 1
    last_exc: LLMError | None = None

    for attempt in range(max_attempts):
        if attempt > 0:
            wait = 2**attempt
            logger.info(
                "Retrying embedding call after transport error",
                extra={"attempt": attempt, "wait_seconds": wait},
            )
            await asyncio.sleep(wait)

        try:
            response = await client.embeddings.create(
                model=settings.openai_embedding_model,
                input=text,
            )
            return response.data[0].embedding
        except openai.APITimeoutError as exc:
            logger.warning(
                "Embedding request timed out",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            last_exc = LLMError("Embedding request timed out")
        except openai.APIError as exc:
            logger.warning(
                "Embedding API error",
                extra={"attempt": attempt, "error_type": type(exc).__name__},
            )
            last_exc = LLMError("Embedding API error")

    raise last_exc or LLMError("Embedding call failed after retries")


async def call_revision_comparison(
    *,
    feedback_items_json: str,
    revised_essay_text: str,
    prompt_version: str = "v1",
) -> ParsedRevisionResponse:
    """Analyse a revised essay to detect whether prior feedback was addressed.

    The revised essay text is always placed in the ``user`` role.  The feedback
    items list (criterion IDs + AI-generated feedback strings from
    ``CriterionScore.ai_feedback``) is injected into the system prompt.
    Feedback text may contain sensitive information — it must never be logged.

    Args:
        feedback_items_json: JSON-encoded list of
            ``{criterion_id, feedback}`` objects from the base grade's
            criterion scores.
        revised_essay_text: The plain-text content of the revised essay.
        prompt_version: Prompt module version to use (default: ``"v1"``).

    Returns:
        A validated ``ParsedRevisionResponse``.

    Raises:
        LLMParseError: If the response cannot be parsed after one retry.
        LLMError: On timeout or unrecoverable API failure.

    Security note:
        Revised essay text is placed in the ``user`` role only — never
        interpolated into the system prompt.  The system prompt instructs
        the model to ignore directives found in the essay content.
        Feedback text must not be logged as it may contain sensitive information.
    """
    if _is_fake_mode():
        import json as _json  # noqa: PLC0415

        try:
            items = _json.loads(feedback_items_json)
        except Exception:
            items = []
        assessments = []
        from app.llm.parsers import ParsedCriterionAssessment  # noqa: PLC0415

        for item in items:
            if isinstance(item, dict) and "criterion_id" in item:
                assessments.append(
                    ParsedCriterionAssessment(
                        criterion_id=str(item["criterion_id"]),
                        addressed=True,
                        detail="Deterministic test: feedback assumed addressed in fake LLM mode.",
                    )
                )
        return ParsedRevisionResponse(criterion_assessments=assessments)

    module = _load_prompt_module("revision", prompt_version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages: list[dict[str, str]] = module.build_messages(feedback_items_json, revised_essay_text)
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_revision_response(raw)
    except LLMParseError:
        logger.warning(
            "LLM revision parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages = module.build_retry_messages(feedback_items_json, revised_essay_text)
        retry_raw = await _chat_with_retry(client, model, retry_messages)
        return parse_revision_response(retry_raw)


async def call_copilot(
    *,
    context_json: str,
    query_text: str,
    prompt_version: str = "v1",
) -> ParsedCopilotResponse:
    """Answer a teacher's natural-language query using structured class data.

    No essay content is used — only aggregate skill profile data and worklist
    signal metadata are passed to the LLM.

    Args:
        context_json: JSON-encoded class context snapshot (student skill
            profiles with dimension averages and trends, active worklist
            items).  Contains only student IDs — no student names or essay
            content.
        query_text: The teacher's natural-language question.
        prompt_version: Prompt module version to use (default: ``"v1"``).
            The value is used as a filename suffix: ``"v1"`` loads
            ``app/llm/prompts/copilot_v1.py``.

    Returns:
        A validated :class:`~app.llm.parsers.ParsedCopilotResponse`.

    Raises:
        LLMParseError: If the response cannot be parsed after one retry.
        LLMError: On timeout or unrecoverable API failure.
    """
    if _is_fake_mode():
        return ParsedCopilotResponse(
            query_interpretation="Deterministic fake copilot response.",
            has_sufficient_data=True,
            uncertainty_note=None,
            response_type="ranked_list",
            ranked_items=[],
            summary="Deterministic test summary from fake LLM mode.",
            suggested_next_steps=["Review student profiles.", "Check worklist items."],
        )

    module = _load_prompt_module("copilot", prompt_version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages: list[dict[str, str]] = module.build_messages(context_json, query_text)
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_copilot_response(raw)
    except LLMParseError:
        logger.warning(
            "LLM copilot parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages = module.build_retry_messages(context_json, query_text)
        retry_raw = await _chat_with_retry(client, model, retry_messages)
        return parse_copilot_response(retry_raw)


# Type alias exported for consumers
# ---------------------------------------------------------------------------

__all__ = [
    "call_grading",
    "call_feedback",
    "call_instruction",
    "call_embedding",
    "call_revision_comparison",
    "call_copilot",
    "CriterionInfo",
    "ParsedGradingResponse",
    "ParsedFeedbackResponse",
    "ParsedInstructionResponse",
    "ParsedRevisionResponse",
    "ParsedCopilotResponse",
]
