"""Unit tests for app/services/grading_progress.py.

All Redis operations are mocked — no real Redis instance required.
No student PII in any fixture.

Coverage:
- grading_progress_key: key format
- initialize_progress: pipeline calls and mapping construction
- mark_essay_grading: sets status field
- mark_essay_complete: increments complete counter, returns counters
- mark_essay_failed: increments failed counter, stores error code
- reset_essay_for_retry: decrements failed counter, clears error
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


def _make_redis_mock(pipeline_results: list[object] | None = None) -> MagicMock:
    """Return a mock Redis client with a mock pipeline."""
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
        redis = _make_redis_mock()
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
        redis = _make_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await initialize_progress(redis, assignment_id, [(essay_id, None)])

        mapping = pipe.hset.call_args.kwargs["mapping"]
        assert mapping[f"n:{essay_id}"] == ""

    @pytest.mark.asyncio
    async def test_deletes_previous_key_first(self) -> None:
        """initialize_progress deletes the previous key before writing the new hash."""
        redis = _make_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()

        await initialize_progress(redis, assignment_id, [])

        pipe.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_ttl(self) -> None:
        redis = _make_redis_mock()
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
        redis = _make_redis_mock()
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
        # Pipeline results: [hset_result, hincrby_result, hmget_result, expire_result]
        redis = _make_redis_mock(pipeline_results=[None, 1, ["5", "3", "1"], None])

        counters = await mark_essay_complete(redis, assignment_id, essay_id)

        assert counters == {"total": 5, "complete": 3, "failed": 1}

    @pytest.mark.asyncio
    async def test_sets_essay_status_to_complete(self) -> None:
        redis = _make_redis_mock(pipeline_results=[None, 1, ["1", "1", "0"], None])
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await mark_essay_complete(redis, assignment_id, essay_id)

        # First hset call should set the essay status to complete
        hset_calls = [str(c) for c in pipe.hset.call_args_list]
        assert any(f"s:{essay_id}" in c and "complete" in c for c in hset_calls)

    @pytest.mark.asyncio
    async def test_returns_zeros_on_expired_key(self) -> None:
        """When Redis key is gone (None values), counters are all 0."""
        redis = _make_redis_mock(pipeline_results=[None, 0, [None, None, None], None])

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
        # Pipeline results: [hset_status, hset_error, hincrby, hmget, expire]
        redis = _make_redis_mock(pipeline_results=[None, None, 1, ["5", "3", "2"], None])

        counters = await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")

        assert counters == {"total": 5, "complete": 3, "failed": 2}

    @pytest.mark.asyncio
    async def test_stores_error_code(self) -> None:
        redis = _make_redis_mock(pipeline_results=[None, None, 1, ["1", "0", "1"], None])
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await mark_essay_failed(redis, assignment_id, essay_id, "LLM_UNAVAILABLE")

        hset_calls = [str(c) for c in pipe.hset.call_args_list]
        assert any(f"e:{essay_id}" in c and "LLM_UNAVAILABLE" in c for c in hset_calls)


# ---------------------------------------------------------------------------
# Tests — reset_essay_for_retry
# ---------------------------------------------------------------------------


class TestResetEssayForRetry:
    @pytest.mark.asyncio
    async def test_resets_status_and_decrements_failed(self) -> None:
        redis = _make_redis_mock()
        pipe = redis.pipeline()
        assignment_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        await reset_essay_for_retry(redis, assignment_id, essay_id)

        hset_calls = [str(c) for c in pipe.hset.call_args_list]
        # Status field should be reset to "queued"
        assert any(f"s:{essay_id}" in c and "queued" in c for c in hset_calls)
        # Error field should be cleared
        assert any(f"e:{essay_id}" in c for c in hset_calls)
        # Failed counter decremented
        pipe.hincrby.assert_called_once_with(grading_progress_key(assignment_id), "failed", -1)


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
