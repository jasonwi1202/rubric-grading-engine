"""Unit tests for app/services/batch_grading.py.

All database and Redis calls are mocked — no real broker, no real PostgreSQL,
no real Redis.  No student PII in any fixture.

Coverage:
- trigger_batch_grading: happy path, not-gradeable state, no queued essays,
  already-grading state accepted, enqueues correct task args
- get_grading_status: reads from Redis, returns idle when key absent
- retry_essay_grading: queued essay enqueued, grading rejects, completed rejects,
  cross-teacher returns 403, missing essay returns 404
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import (
    AssignmentNotGradeableError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.assignment import AssignmentStatus
from app.models.essay import EssayStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assignment(
    assignment_id: uuid.UUID | None = None,
    status: AssignmentStatus = AssignmentStatus.open,
) -> MagicMock:
    a = MagicMock()
    a.id = assignment_id or uuid.uuid4()
    a.status = status
    a.created_at = datetime.now(UTC)
    return a


def _make_essay(
    essay_id: uuid.UUID | None = None,
    assignment_id: uuid.UUID | None = None,
    status: EssayStatus = EssayStatus.queued,
) -> MagicMock:
    e = MagicMock()
    e.id = essay_id or uuid.uuid4()
    e.assignment_id = assignment_id or uuid.uuid4()
    e.status = status
    return e


def _make_redis_mock() -> MagicMock:
    """Return a minimal async Redis mock for service calls."""
    redis = MagicMock()
    redis.pipeline = MagicMock()
    pipe = AsyncMock()
    pipe.delete = MagicMock()
    pipe.hset = MagicMock()
    pipe.expire = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    redis.pipeline.return_value = pipe
    redis.hgetall = AsyncMock(return_value={})
    return redis


def _make_db_mock() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Tests — trigger_batch_grading
# ---------------------------------------------------------------------------


class TestTriggerBatchGrading:
    @pytest.mark.asyncio
    async def test_enqueues_tasks_for_queued_essays(self) -> None:
        """trigger_batch_grading enqueues one task per queued essay."""
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        assignment = _make_assignment(assignment_id=assignment_id, status=AssignmentStatus.open)
        essay1 = _make_essay(assignment_id=assignment_id)
        essay2 = _make_essay(assignment_id=assignment_id)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[(essay1, "Student A"), (essay2, None)])
        db.execute = AsyncMock(return_value=result_mock)

        enqueue_calls: list[tuple[str, str, str, str]] = []

        def fake_delay(essay_id: str, tid: str, strictness: str, aid: str) -> None:
            enqueue_calls.append((essay_id, tid, strictness, aid))

        mock_task = MagicMock()
        mock_task.delay = fake_delay

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(return_value=assignment),
            ),
            patch("app.services.batch_grading.initialize_progress", new=AsyncMock()),
            patch("app.tasks.grading.grade_essay", mock_task),
        ):
            from app.services.batch_grading import trigger_batch_grading

            count = await trigger_batch_grading(
                db=db,
                redis=redis,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                strictness="balanced",
            )

        assert count == 2
        assert len(enqueue_calls) == 2
        for _essay_id_str, tid_str, strictness, aid_str in enqueue_calls:
            assert tid_str == str(teacher_id)
            assert strictness == "balanced"
            assert aid_str == str(assignment_id)

    @pytest.mark.asyncio
    async def test_transitions_open_assignment_to_grading(self) -> None:
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        assignment = _make_assignment(assignment_id=assignment_id, status=AssignmentStatus.open)
        essay = _make_essay(assignment_id=assignment_id)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[(essay, None)])
        db.execute = AsyncMock(return_value=result_mock)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(return_value=assignment),
            ),
            patch("app.services.batch_grading.initialize_progress", new=AsyncMock()),
            patch("app.tasks.grading.grade_essay", mock_task),
        ):
            from app.services.batch_grading import trigger_batch_grading

            await trigger_batch_grading(
                db=db, redis=redis, assignment_id=assignment_id, teacher_id=teacher_id
            )

        # Assignment status should have been mutated to grading before commit
        assert assignment.status == AssignmentStatus.grading
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_already_grading_state_accepted(self) -> None:
        """An assignment already in grading state is accepted: no DB commit, but tasks enqueued."""
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        assignment = _make_assignment(assignment_id=assignment_id, status=AssignmentStatus.grading)
        essay = _make_essay(assignment_id=assignment_id)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[(essay, None)])
        db.execute = AsyncMock(return_value=result_mock)

        enqueue_calls: list[str] = []

        mock_task = MagicMock()
        mock_task.delay = MagicMock(side_effect=lambda eid, *a: enqueue_calls.append(eid))

        init_progress = AsyncMock()

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(return_value=assignment),
            ),
            patch("app.services.batch_grading.initialize_progress", init_progress),
            patch("app.tasks.grading.grade_essay", mock_task),
        ):
            from app.services.batch_grading import trigger_batch_grading

            count = await trigger_batch_grading(
                db=db, redis=redis, assignment_id=assignment_id, teacher_id=teacher_id
            )

        assert count == 1
        # No status transition should happen (already grading)
        db.commit.assert_not_called()
        # Redis progress IS re-initialized (overwrites previous state for re-trigger)
        init_progress.assert_called_once()
        # The essay task IS enqueued
        assert len(enqueue_calls) == 1
        assert enqueue_calls[0] == str(essay.id)

    @pytest.mark.asyncio
    async def test_raises_when_assignment_not_gradeable(self) -> None:
        """Non-gradeable state raises AssignmentNotGradeableError."""
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        assignment = _make_assignment(assignment_id=assignment_id, status=AssignmentStatus.review)

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(return_value=assignment),
            ),
            pytest.raises(AssignmentNotGradeableError),
        ):
            from app.services.batch_grading import trigger_batch_grading

            await trigger_batch_grading(
                db=db, redis=redis, assignment_id=assignment_id, teacher_id=teacher_id
            )

    @pytest.mark.asyncio
    async def test_raises_when_no_queued_essays(self) -> None:
        """AssignmentNotGradeableError when there are no queued essays."""
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        assignment = _make_assignment(assignment_id=assignment_id, status=AssignmentStatus.open)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[])
        db.execute = AsyncMock(return_value=result_mock)

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(return_value=assignment),
            ),
            pytest.raises(AssignmentNotGradeableError),
        ):
            from app.services.batch_grading import trigger_batch_grading

            await trigger_batch_grading(
                db=db, redis=redis, assignment_id=assignment_id, teacher_id=teacher_id
            )

    @pytest.mark.asyncio
    async def test_cross_teacher_access_returns_forbidden(self) -> None:
        """ForbiddenError from get_assignment propagates (cross-teacher)."""
        teacher_id = uuid.uuid4()
        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(side_effect=ForbiddenError("Not your assignment.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            from app.services.batch_grading import trigger_batch_grading

            await trigger_batch_grading(
                db=db,
                redis=redis,
                assignment_id=uuid.uuid4(),
                teacher_id=teacher_id,
            )


# ---------------------------------------------------------------------------
# Tests — get_grading_status
# ---------------------------------------------------------------------------


class TestGetGradingStatus:
    @pytest.mark.asyncio
    async def test_returns_idle_when_no_redis_key(self) -> None:
        """get_grading_status returns idle status when Redis key is missing."""
        assignment = _make_assignment()
        db = _make_db_mock()
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(return_value={})

        with patch(
            "app.services.batch_grading.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            from app.services.batch_grading import get_grading_status

            result = await get_grading_status(
                db=db, redis=redis, assignment_id=assignment.id, teacher_id=uuid.uuid4()
            )

        assert result["status"] == "idle"
        assert result["total"] == 0
        assert result["complete"] == 0
        assert result["failed"] == 0
        assert result["essays"] == []

    @pytest.mark.asyncio
    async def test_returns_processing_status(self) -> None:
        """get_grading_status returns processing when some essays are still in flight."""
        essay_id = uuid.uuid4()
        assignment = _make_assignment()
        db = _make_db_mock()
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "3",
                "complete": "1",
                "failed": "0",
                f"s:{essay_id}": "grading",
                f"n:{essay_id}": "",
                f"e:{essay_id}": "",
            }
        )

        with patch(
            "app.services.batch_grading.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            from app.services.batch_grading import get_grading_status

            result = await get_grading_status(
                db=db, redis=redis, assignment_id=assignment.id, teacher_id=uuid.uuid4()
            )

        assert result["status"] == "processing"
        assert result["total"] == 3
        assert result["complete"] == 1

    @pytest.mark.asyncio
    async def test_returns_complete_status(self) -> None:
        essay_id = uuid.uuid4()
        assignment = _make_assignment()
        db = _make_db_mock()
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "2",
                "complete": "2",
                "failed": "0",
                f"s:{essay_id}": "complete",
                f"n:{essay_id}": "Student A",
                f"e:{essay_id}": "",
            }
        )

        with patch(
            "app.services.batch_grading.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            from app.services.batch_grading import get_grading_status

            result = await get_grading_status(
                db=db, redis=redis, assignment_id=assignment.id, teacher_id=uuid.uuid4()
            )

        assert result["status"] == "complete"

    @pytest.mark.asyncio
    async def test_returns_failed_status_when_all_failed(self) -> None:
        essay_id = uuid.uuid4()
        assignment = _make_assignment()
        db = _make_db_mock()
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "1",
                "complete": "0",
                "failed": "1",
                f"s:{essay_id}": "failed",
                f"n:{essay_id}": "",
                f"e:{essay_id}": "LLM_UNAVAILABLE",
            }
        )

        with patch(
            "app.services.batch_grading.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            from app.services.batch_grading import get_grading_status

            result = await get_grading_status(
                db=db, redis=redis, assignment_id=assignment.id, teacher_id=uuid.uuid4()
            )

        assert result["status"] == "failed"
        assert result["essays"][0]["error"] == "LLM_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_returns_partial_status_when_mixed(self) -> None:
        essay1_id = uuid.uuid4()
        essay2_id = uuid.uuid4()
        assignment = _make_assignment()
        db = _make_db_mock()
        redis = _make_redis_mock()
        redis.hgetall = AsyncMock(
            return_value={
                "total": "2",
                "complete": "1",
                "failed": "1",
                f"s:{essay1_id}": "complete",
                f"n:{essay1_id}": "",
                f"e:{essay1_id}": "",
                f"s:{essay2_id}": "failed",
                f"n:{essay2_id}": "",
                f"e:{essay2_id}": "LLM_UNAVAILABLE",
            }
        )

        with patch(
            "app.services.batch_grading.get_assignment",
            new=AsyncMock(return_value=assignment),
        ):
            from app.services.batch_grading import get_grading_status

            result = await get_grading_status(
                db=db, redis=redis, assignment_id=assignment.id, teacher_id=uuid.uuid4()
            )

        assert result["status"] == "partial"

    @pytest.mark.asyncio
    async def test_cross_teacher_raises_forbidden(self) -> None:
        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.batch_grading.get_assignment",
                new=AsyncMock(side_effect=ForbiddenError("Not yours.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            from app.services.batch_grading import get_grading_status

            await get_grading_status(
                db=db, redis=redis, assignment_id=uuid.uuid4(), teacher_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# Tests — retry_essay_grading
# ---------------------------------------------------------------------------


class TestRetryEssayGrading:
    @pytest.mark.asyncio
    async def test_enqueues_task_for_queued_essay(self) -> None:
        teacher_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        essay = _make_essay(assignment_id=assignment_id, status=EssayStatus.queued)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=essay)
        db.execute = AsyncMock(return_value=result_mock)

        enqueue_calls: list[tuple[str, str, str, str]] = []

        def fake_delay(eid: str, tid: str, strictness: str, aid: str) -> None:
            enqueue_calls.append((eid, tid, strictness, aid))

        mock_task = MagicMock()
        mock_task.delay = fake_delay

        with (
            patch("app.services.batch_grading.reset_essay_for_retry", new=AsyncMock()),
            patch("app.tasks.grading.grade_essay", mock_task),
        ):
            from app.services.batch_grading import retry_essay_grading

            await retry_essay_grading(
                db=db,
                redis=redis,
                essay_id=essay.id,
                teacher_id=teacher_id,
                strictness="strict",
            )

        assert len(enqueue_calls) == 1
        eid, tid, strictness, aid = enqueue_calls[0]
        assert eid == str(essay.id)
        assert tid == str(teacher_id)
        assert strictness == "strict"
        assert aid == str(assignment_id)

    @pytest.mark.asyncio
    async def test_raises_conflict_when_grading(self) -> None:
        teacher_id = uuid.uuid4()
        essay = _make_essay(status=EssayStatus.grading)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=essay)
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ConflictError):
            from app.services.batch_grading import retry_essay_grading

            await retry_essay_grading(db=db, redis=redis, essay_id=essay.id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_conflict_when_already_graded(self) -> None:
        """Completed essays (graded status) cannot be retried."""
        teacher_id = uuid.uuid4()
        essay = _make_essay(status=EssayStatus.graded)

        db = _make_db_mock()
        redis = _make_redis_mock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=essay)
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ConflictError):
            from app.services.batch_grading import retry_essay_grading

            await retry_essay_grading(db=db, redis=redis, essay_id=essay.id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_essay_missing(self) -> None:
        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        # Both queries return None — essay truly does not exist.
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(NotFoundError):
            from app.services.batch_grading import retry_essay_grading

            await retry_essay_grading(db=db, redis=redis, essay_id=essay_id, teacher_id=teacher_id)

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_other_teachers_essay(self) -> None:
        """Essay that belongs to another teacher returns ForbiddenError."""
        teacher_id = uuid.uuid4()
        essay_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        # First query (tenant-scoped) returns None; second (bare exists check) returns a row.
        exists_result = MagicMock()
        exists_result.scalar_one_or_none = MagicMock(return_value=essay_id)

        no_result = MagicMock()
        no_result.scalar_one_or_none = MagicMock(return_value=None)

        db.execute = AsyncMock(side_effect=[no_result, exists_result])

        with pytest.raises(ForbiddenError):
            from app.services.batch_grading import retry_essay_grading

            await retry_essay_grading(db=db, redis=redis, essay_id=essay_id, teacher_id=teacher_id)
