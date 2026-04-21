"""Unit tests for app/llm/client.py.

Tests verify:
    - _load_prompt_module: happy path and missing-module error.
    - _chat_with_retry: success, timeout retry, API error retry,
      exhausted retries.
    - call_grading: happy path, parse-error retry, parse-error exhausted.
    - call_feedback: happy path, parse-error retry.
    - call_instruction: happy path, parse-error retry.

No real OpenAI calls are made — all OpenAI interactions are mocked.
No student PII in fixtures.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import LLMError, LLMParseError
from app.llm.client import (
    _chat_with_retry,
    _load_prompt_module,
    call_feedback,
    call_grading,
    call_instruction,
)
from app.llm.parsers import (
    CriterionInfo,
    ParsedFeedbackResponse,
    ParsedGradingResponse,
    ParsedInstructionResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_openai_response(content: str) -> MagicMock:
    """Build a minimal mock that looks like an OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def _grading_json(criterion_id: str = "c1", score: int = 3) -> str:
    return json.dumps(
        {
            "criterion_scores": [
                {
                    "criterion_id": criterion_id,
                    "score": score,
                    "justification": "A sufficiently long justification string for test.",
                    "confidence": "high",
                }
            ],
            "summary_feedback": "Well structured essay with clear thesis.",
        }
    )


def _feedback_json() -> str:
    return json.dumps(
        {
            "summary": "Good overall.",
            "criterion_feedback": [{"criterion_id": "c1", "feedback": "Clear thesis."}],
            "next_steps": ["Vary sentence length."],
        }
    )


def _instruction_json() -> str:
    return json.dumps(
        {
            "recommendations": [
                {
                    "skill_dimension": "thesis",
                    "title": "Thesis Workshop",
                    "description": "Write five thesis statements.",
                    "estimated_minutes": 20,
                    "strategy_type": "guided_practice",
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# _load_prompt_module
# ---------------------------------------------------------------------------


class TestLoadPromptModule:
    def test_loads_grading_v1(self) -> None:
        module = _load_prompt_module("grading", "v1")
        assert hasattr(module, "build_messages")
        assert hasattr(module, "build_retry_messages")

    def test_loads_feedback_v1(self) -> None:
        module = _load_prompt_module("feedback", "v1")
        assert hasattr(module, "build_messages")

    def test_loads_instruction_v1(self) -> None:
        module = _load_prompt_module("instruction", "v1")
        assert hasattr(module, "build_messages")

    def test_unknown_version_raises_llm_error(self) -> None:
        with pytest.raises(LLMError, match="Prompt module not found"):
            _load_prompt_module("grading", "v999")

    def test_unknown_type_raises_llm_error(self) -> None:
        with pytest.raises(LLMError, match="Prompt module not found"):
            _load_prompt_module("unknown_type", "v1")


# ---------------------------------------------------------------------------
# _chat_with_retry
# ---------------------------------------------------------------------------


class TestChatWithRetry:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self) -> None:
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_make_openai_response('{"ok": true}')
        )
        with patch("app.llm.client.settings") as mock_settings:
            mock_settings.llm_max_retries = 3
            result = await _chat_with_retry(client, "gpt-4o", [])
        assert result == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self) -> None:
        import openai

        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                openai.APITimeoutError(request=MagicMock()),
                _make_openai_response('{"ok": true}'),
            ]
        )
        with (
            patch("app.llm.client.settings") as mock_settings,
            patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.llm_max_retries = 3
            result = await _chat_with_retry(client, "gpt-4o", [])
        assert result == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_retries_on_api_error(self) -> None:
        import openai

        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                openai.APIError("bad", request=MagicMock(), body=None),
                _make_openai_response('{"ok": true}'),
            ]
        )
        with (
            patch("app.llm.client.settings") as mock_settings,
            patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.llm_max_retries = 3
            result = await _chat_with_retry(client, "gpt-4o", [])
        assert result == '{"ok": true}'

    @pytest.mark.asyncio
    async def test_raises_llm_error_when_retries_exhausted(self) -> None:
        import openai

        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=openai.APITimeoutError(request=MagicMock())
        )
        with (
            patch("app.llm.client.settings") as mock_settings,
            patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            mock_settings.llm_max_retries = 1  # 1 retry → 2 total attempts
            with pytest.raises(LLMError):
                await _chat_with_retry(client, "gpt-4o", [])


# ---------------------------------------------------------------------------
# call_grading
# ---------------------------------------------------------------------------


class TestCallGrading:
    _criteria = [CriterionInfo(criterion_id="c1", min_score=1, max_score=5)]

    @pytest.mark.asyncio
    async def test_happy_path_returns_parsed_response(self) -> None:
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v1"
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_grading_json("c1"))
            )
            mock_client_factory.return_value = mock_client

            result = await call_grading(
                rubric_json='{"criteria": []}',
                strictness="balanced",
                essay_text="The essay content goes here.",
                criteria=self._criteria,
            )

        assert isinstance(result, ParsedGradingResponse)
        assert len(result.criterion_scores) == 1

    @pytest.mark.asyncio
    async def test_parse_error_triggers_corrective_retry(self) -> None:
        """On first parse failure, call_grading retries with corrective messages."""
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v1"
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            # First call returns bad JSON; second returns valid JSON.
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[
                    _make_openai_response("not json at all"),
                    _make_openai_response(_grading_json("c1")),
                ]
            )
            mock_client_factory.return_value = mock_client

            result = await call_grading(
                rubric_json='{"criteria": []}',
                strictness="balanced",
                essay_text="The essay content goes here.",
                criteria=self._criteria,
            )

        assert isinstance(result, ParsedGradingResponse)
        assert mock_client.chat.completions.create.call_count == 2

    @pytest.mark.asyncio
    async def test_parse_error_propagates_after_retry_also_fails(self) -> None:
        """If both attempts produce bad JSON, LLMParseError propagates."""
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v1"
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response("still not json")
            )
            mock_client_factory.return_value = mock_client

            with pytest.raises(LLMParseError):
                await call_grading(
                    rubric_json='{"criteria": []}',
                    strictness="balanced",
                    essay_text="The essay content goes here.",
                    criteria=self._criteria,
                )

    @pytest.mark.asyncio
    async def test_prompt_version_override(self) -> None:
        """Explicit prompt_version overrides settings.grading_prompt_version."""
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v1"
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_grading_json("c1"))
            )
            mock_client_factory.return_value = mock_client

            # Should work fine when specifying v1 explicitly.
            result = await call_grading(
                rubric_json='{"criteria": []}',
                strictness="balanced",
                essay_text="The essay content goes here.",
                criteria=self._criteria,
                prompt_version="v1",
            )
        assert isinstance(result, ParsedGradingResponse)

    @pytest.mark.asyncio
    async def test_unknown_prompt_version_raises_llm_error(self) -> None:
        with (
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.grading_prompt_version = "v999"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60

            with pytest.raises(LLMError, match="Prompt module not found"):
                await call_grading(
                    rubric_json="{}",
                    strictness="balanced",
                    essay_text="Essay text here.",
                    criteria=self._criteria,
                )


# ---------------------------------------------------------------------------
# call_feedback
# ---------------------------------------------------------------------------


class TestCallFeedback:
    @pytest.mark.asyncio
    async def test_happy_path_returns_parsed_response(self) -> None:
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_feedback_json())
            )
            mock_client_factory.return_value = mock_client

            result = await call_feedback(
                approved_scores_json='{"scores": []}',
                tone="encouraging",
                essay_text="The essay content goes here.",
            )

        assert isinstance(result, ParsedFeedbackResponse)
        assert result.summary == "Good overall."

    @pytest.mark.asyncio
    async def test_parse_error_triggers_corrective_retry(self) -> None:
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[
                    _make_openai_response("bad json"),
                    _make_openai_response(_feedback_json()),
                ]
            )
            mock_client_factory.return_value = mock_client

            result = await call_feedback(
                approved_scores_json='{"scores": []}',
                tone="neutral",
                essay_text="The essay content goes here.",
            )

        assert isinstance(result, ParsedFeedbackResponse)
        assert mock_client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# call_instruction
# ---------------------------------------------------------------------------


class TestCallInstruction:
    @pytest.mark.asyncio
    async def test_happy_path_returns_parsed_response(self) -> None:
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=_make_openai_response(_instruction_json())
            )
            mock_client_factory.return_value = mock_client

            result = await call_instruction(
                skill_profile_json='{"dimensions": []}',
                grade_level="Grade 8",
                duration_minutes=20,
            )

        assert isinstance(result, ParsedInstructionResponse)
        assert len(result.recommendations) == 1

    @pytest.mark.asyncio
    async def test_parse_error_triggers_corrective_retry(self) -> None:
        with (
            patch("app.llm.client._get_openai_client") as mock_client_factory,
            patch("app.llm.client.settings") as mock_settings,
        ):
            mock_settings.openai_grading_model = "gpt-4o"
            mock_settings.openai_api_key = "test-openai-key"
            mock_settings.llm_request_timeout_seconds = 60
            mock_settings.llm_max_retries = 3

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[
                    _make_openai_response("not json"),
                    _make_openai_response(_instruction_json()),
                ]
            )
            mock_client_factory.return_value = mock_client

            result = await call_instruction(
                skill_profile_json='{"dimensions": []}',
                grade_level="Grade 6",
                duration_minutes=15,
            )

        assert isinstance(result, ParsedInstructionResponse)
        assert mock_client.chat.completions.create.call_count == 2
