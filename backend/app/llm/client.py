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
import importlib
import logging
import types

import openai

from app.config import settings
from app.exceptions import LLMError, LLMParseError
from app.llm.parsers import (
    CriterionInfo,
    ParsedFeedbackResponse,
    ParsedGradingResponse,
    ParsedInstructionResponse,
    parse_feedback_response,
    parse_grading_response,
    parse_instruction_response,
)

logger = logging.getLogger(__name__)

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
            # type: ignore[call-overload] explanation: the SDK stubs define
            # separate overloads keyed on `stream`; passing a plain dict for
            # `response_format` (instead of a typed `ResponseFormat`) does not
            # match any single overload at the type-checker level, but the
            # runtime behaviour is correct.  Switching to the fully-typed SDK
            # parameter objects would require importing private SDK types that
            # change across minor releases, so the ignore is the stable choice.
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


async def call_grading(
    *,
    rubric_json: str,
    strictness: str,
    essay_text: str,
    criteria: list[CriterionInfo],
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
        prompt_version: Override the active version from
            ``settings.grading_prompt_version``.  Defaults to the setting.

    Returns:
        A validated ``ParsedGradingResponse``.

    Raises:
        LLMParseError: If the response cannot be parsed after one corrective
            retry.
        LLMError: On timeout or unrecoverable API failure.
    """
    version = prompt_version or settings.grading_prompt_version
    module = _load_prompt_module("grading", version)
    client = _get_openai_client()
    model = settings.openai_grading_model

    messages: list[dict[str, str]] = module.build_messages(rubric_json, strictness, essay_text)
    raw = await _chat_with_retry(client, model, messages)

    try:
        return parse_grading_response(raw, criteria)
    except LLMParseError:
        logger.warning(
            "LLM grading parse failed on first attempt; retrying with corrective prompt",
        )
        retry_messages: list[dict[str, str]] = module.build_retry_messages(
            rubric_json, strictness, essay_text
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


# ---------------------------------------------------------------------------
# Type alias exported for consumers
# ---------------------------------------------------------------------------

__all__ = [
    "call_grading",
    "call_feedback",
    "call_instruction",
    "CriterionInfo",
    "ParsedGradingResponse",
    "ParsedFeedbackResponse",
    "ParsedInstructionResponse",
]
