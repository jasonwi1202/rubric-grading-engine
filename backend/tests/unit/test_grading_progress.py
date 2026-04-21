"""Unit tests for app/services/grading_progress.py.

All Redis operations are mocked — no real Redis instance required.
No student PII in any fixture.

Coverage:
- grading_progress_key: key format
- initialize_progress: pipeline calls and mapping construction
- mark_essay_grading: sets status field
- mark_essay_complete: idempotent Lua-based counter increment
- mark_essay_failed: idempotent Lua-based counter increment
- reset_essay_for_retry: Lua-based conditional decrement (no-op unless failed)
- get_progress: parses hash data, returns BatchProgress or None
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.grading_progress import (
    get_progress,
    grading_progress_key,
    initialize_progress,
    mark_essay_complete,
    mark_essay_failed,
    mark_essay_grading,
    reset_essay_for_retry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline_redis_mock(pipeline_results: list[object] | None = None) -> MagicMock:
    """Return a mock Redis client with a mock pipeline (for initialize_progress / mark_grading)."""
    redis = MagicMock()
    pipe = AsyncMock()
    pipe.hset = MagicMock()
    pipe.delete = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.hmget = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=pipeline_results or [])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


def _make_eval_redis_mock(eval_result: list[object] | None = None) -> MagicMock:
    """Return a mock Redis client with a mock eval (for Lua-based functions)."""
    redis = MagicMock()
    redis.eval = AsyncMock(return_value=eval_result or [None, None, None])
    return redis


# ---------------------------------------------------------------------------
# Tests — grading_progress_key
# ---------------------------------------------------------------------------


class TestGradingProgressKey:
    def test_key_format(self) -> None:
        aid = uuid.uuid4()
        assert grading_progress_key(aid) == f"grading_progress:{aid}"

    def test_key_is_deterministic(self) -> None:
        aid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert grading_progress_key(aid) == "grading_progress:12345678-1234-5678-1234-567812345678"


# ---------------------------------------------------------------------------
# Tests — initialize_progress
# ---------------------------------------------------------------------------


class TestInitializeProgress:
    @pytest.mark.asyncio
    async def test_sets_total_and_per_essay_fields(self) -> None:
        """initialize_progress builds a mapping with total, complete, failed, and per-essay fields."""
        redis = _make_pipeline_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        student_name = "Test Student"

        await initialize_progress(redis, assignment_id, [(essay_id, student_name)])

        # Inspect the hset call mapping
        hset_call = pipe.hset.call_args
        mapping = hset_call.kwargs["mapping"]

        assert mapping["total"] == "1"
        assert mapping["complete"] == "0"
        assert mapping["failed"] == "0"
        assert mapping[f"s:{essay_id}"] == "queued"
        assert mapping[f"n:{essay_id}"] == student_name
        assert mapping[f"e:{essay_id}"] == ""

    @pytest.mark.asyncio
    async def test_null_student_name_stored_as_empty_string(self) -> None:
        redis = _make_pipeline_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await initialize_progress(redis, assignment_id, [(essay_id, None)])

        mapping = pipe.hset.call_args.kwargs["mapping"]
        assert mapping[f"n:{essay_id}"] == ""

    @pytest.mark.asyncio
    async def test_deletes_previous_key_first(self) -> None:
        """initialize_progress deletes the previous key before writing the new hash."""
        redis = _make_pipeline_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()

        await initialize_progress(redis, assignment_id, [])

        pipe.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_ttl(self) -> None:
        redis = _make_pipeline_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()

        with patch("app.services.grading_progress.settings") as mock_settings:
            mock_settings.redis_grading_ttl_seconds = 3600
            await initialize_progress(redis, assignment_id, [])

        pipe.expire.assert_called_once_with(grading_progress_key(assignment_id), 3600)


# ---------------------------------------------------------------------------
# Tests — mark_essay_grading
# ---------------------------------------------------------------------------


class TestMarkEssayGrading:
    @pytest.mark.asyncio
    async def test_sets_status_to_grading(self) -> None:
        redis = _make_pipeline_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await mark_essay_grading(redis, assignment_id, essay_id)

        pipe.hset.assert_called_once_with(
            grading_progress_key(assignment_id), f"s:{essay_id}", "grading"
        )


# ---------------------------------------------------------------------------
# Tests — mark_essay_complete
# ---------------------------------------------------------------------------


class TestMarkEssayComplete:
    @pytest.mark.asyncio
    async def test_returns_updated_counters(self) -> None:
        """mark_essay_complete returns a dict with the updated counter values."""
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["5", "3", "1"])

        counters = await mark_essay_complete(redis, assignment_id, essay_id)

        assert counters == {"total": 5, "complete": 3, "failed": 1}

    @pytest.mark.asyncio
    async def test_calls_eval_with_correct_key(self) -> None:
        """mark_essay_complete invokes redis.eval with the correct hash key."""
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["1", "1", "0"])

        await mark_essay_complete(redis, assignment_id, essay_id)

        redis.eval.assert_called_once()
        call_args = redis.eval.call_args
        # Second positional arg (after script) is numkeys; third is the key
        assert call_args.args[2] == grading_progress_key(assignment_id)
        assert call_args.args[3] == f"s:{essay_id}"

    @pytest.mark.asyncio
    async def test_returns_zeros_on_expired_key(self) -> None:
        """When Redis key is gone (None values), counters are all 0."""
        redis = _make_eval_redis_mock(eval_result=[None, None, None])

        counters = await mark_essay_complete(redis, uuid.uuid4(), uuid.uuid4())

        assert counters == {"total": 0, "complete": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_idempotent_no_double_increment(self) -> None:
        """Calling mark_essay_complete twice uses Lua script that prevents double-counting.

        We verify the Lua script is invoked (not a raw HINCRBY pipeline), so the
        idempotency guard in the script is the defence against double-counting.
        """
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["1", "1", "0"])

        await mark_essay_complete(redis, assignment_id, essay_id)
        await mark_essay_complete(redis, assignment_id, essay_id)

        # Both calls go through redis.eval (which includes the idempotency guard)
        assert redis.eval.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_zeros_when_hash_expired_before_write(self) -> None:
        """Lua guard: when the hash is missing (total == nil), script returns
        all nils and the function safely returns all-zero counters."""
        redis = _make_eval_redis_mock(eval_result=[None, None, None])

        counters = await mark_essay_complete(redis, uuid.uuid4(), uuid.uuid4())

        assert counters == {"total": 0, "complete": 0, "failed": 0}


# ---------------------------------------------------------------------------
# Tests — mark_essay_failed
# ---------------------------------------------------------------------------


class TestMarkEssayFailed:
    @pytest.mark.asyncio
    async def test_returns_updated_counters(self) -> None:
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["5", "3", "2"])

        counters = await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")

        assert counters == {"total": 5, "complete": 3, "failed": 2}

    @pytest.mark.asyncio
    async def test_passes_error_code_to_eval(self) -> None:
        """mark_essay_failed passes the error code as an ARGV to the Lua script."""
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["1", "0", "1"])

        await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")

        redis.eval.assert_called_once()
        call_args = redis.eval.call_args
        # ARGV[3] (index 5 in positional args: script, numkeys, key, ARGV1, ARGV2, ARGV3, ARGV4)
        assert "LLM_UNAVAILABLE" in call_args.args

    @pytest.mark.asyncio
    async def test_idempotent_no_double_increment(self) -> None:
        """Calling mark_essay_failed twice uses Lua script that prevents double-counting."""
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        redis = _make_eval_redis_mock(eval_result=["1", "0", "1"])

        await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")
        await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")

        assert redis.eval.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_zeros_when_hash_expired_before_write(self) -> None:
        """Lua guard: when the hash is missing (total == nil), script returns
        all nils and the function safely returns all-zero counters."""
        redis = _make_eval_redis_mock(eval_result=[None, None, None])

        counters = await mark_essay_failed(redis, uuid.uuid4(), uuid.uuid4(), "LLM_UNAVAILABLE")

        assert counters == {"total": 0, "complete": 0, "failed": 0}


# ---------------------------------------------------------------------------
# Tests — reset_essay_for_retry
# ---------------------------------------------------------------------------


class TestResetEssayForRetry:
    @pytest.mark.asyncio
    async def test_calls_eval_for_conditional_decrement(self) -> None:
        """reset_essay_for_retry uses redis.eval for the guarded decrement."""
        redis = _make_eval_redis_mock(eval_result=[1])
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await reset_essay_for_retry(redis, assignment_id, essay_id)

        redis.eval.assert_called_once()
        call_args = redis.eval.call_args
        assert call_args.args[2] == grading_progress_key(assignment_id)
        assert call_args.args[3] == f"s:{essay_id}"
        assert call_args.args[4] == f"e:{essay_id}"

    @pytest.mark.asyncio
    async def test_no_op_on_missing_key_does_not_raise(self) -> None:
        """reset_essay_for_retry is a no-op when the key is missing (eval returns 1)."""
        redis = _make_eval_redis_mock(eval_result=[1])
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        # Should not raise even if Redis key is absent
        await reset_essay_for_retry(redis, assignment_id, essay_id)


# ---------------------------------------------------------------------------
# Tests — get_progress
# ---------------------------------------------------------------------------


class TestGetProgress:
    @pytest.mark.asyncio
    async def test_returns_none_when_key_not_found(self) -> None:
        """get_progress returns None when the Redis hash is empty (key missing)."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(return_value={})

        result = await get_progress(redis, uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_parses_progress_hash(self) -> None:
        essay_id = uuid.uuid4()
        redis = MagicMock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "5",
                "complete": "3",
                "failed": "1",
                f"s:{essay_id}": "complete",
                f"n:{essay_id}": "Test Student",
                f"e:{essay_id}": "",
            }
        )

        result = await get_progress(redis, uuid.uuid4())

        assert result is not None
        assert result.total == 5
        assert result.complete == 3
        assert result.failed == 1
        assert len(result.essays) == 1
        ep = result.essays[0]
        assert ep.essay_id == essay_id
        assert ep.status == "complete"
        assert ep.student_name == "Test Student"
        assert ep.error is None  # Empty string → None

    @pytest.mark.asyncio
    async def test_failed_essay_has_error_code(self) -> None:
        essay_id = uuid.uuid4()
        redis = MagicMock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "2",
                "complete": "1",
                "failed": "1",
                f"s:{essay_id}": "failed",
                f"n:{essay_id}": "",
                f"e:{essay_id}": "LLM_UNAVAILABLE",
            }
        )

        result = await get_progress(redis, uuid.uuid4())

        assert result is not None
        ep = result.essays[0]
        assert ep.status == "failed"
        assert ep.error == "LLM_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_unassigned_essay_student_name_is_none(self) -> None:
        essay_id = uuid.uuid4()
        redis = MagicMock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "1",
                "complete": "0",
                "failed": "0",
                f"s:{essay_id}": "queued",
                f"n:{essay_id}": "",
                f"e:{essay_id}": "",
            }
        )

        result = await get_progress(redis, uuid.uuid4())

        assert result is not None
        assert result.essays[0].student_name is None

    @pytest.mark.asyncio
    async def test_ignores_non_essay_fields(self) -> None:
        """Fields that are not ``s:`` prefixed are not included in the essays list."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "0",
                "complete": "0",
                "failed": "0",
            }
        )

        result = await get_progress(redis, uuid.uuid4())

        assert result is not None
        assert result.essays == []

    @pytest.mark.asyncio
    async def test_skips_invalid_uuid_essay_fields(self) -> None:
        """Malformed UUIDs in essay fields are silently skipped."""
        redis = MagicMock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "0",
                "complete": "0",
                "failed": "0",
                "s:not-a-uuid": "queued",
            }
        )

        result = await get_progress(redis, uuid.uuid4())

        assert result is not None
        assert result.essays == []
