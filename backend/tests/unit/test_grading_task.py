"""Unit tests for app/tasks/grading.py.

All database and LLM calls are mocked — no real broker, no real PostgreSQL.
Tests call the underlying async helpers and service directly (not via Celery
worker), consistent with the project's Celery testing pattern.

No student PII in any fixture.

Coverage:
- _run_grade_essay: happy path, LLMError propagation.
- grade_essay task: registered in celery, happy path eager execution.
- LLM retry logic: LLMError triggers retry with exponential backoff.
- Exhausted retries: essay status reverted to queued.
- Unrecoverable exception: essay reverted and exception re-raised.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ConflictError, ForbiddenError, LLMError
from app.tasks.celery_app import celery
from app.tasks.grading import _revert_essay_to_queued, _run_grade_essay, grade_essay

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grade_mock(grade_id: uuid.UUID | None = None) -> MagicMock:
    grade = MagicMock()
    grade.id = grade_id or uuid.uuid4()
    return grade


# ---------------------------------------------------------------------------
# Tests — task registration
# ---------------------------------------------------------------------------


class TestGradeEssayTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.grading.grade_essay" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert grade_essay.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert grade_essay.name == "tasks.grading.grade_essay"


# ---------------------------------------------------------------------------
# Tests — _run_grade_essay async helper
# ---------------------------------------------------------------------------


class TestRunGradeEssay:
    @pytest.mark.asyncio
    async def test_calls_grade_essay_service_and_returns_grade_id(self) -> None:
        """_run_grade_essay calls the grading service and returns a grade ID string."""
        grade_id = uuid.uuid4()
        grade_mock = _make_grade_mock(grade_id)

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.grading.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.grading.grade_essay",
                new=AsyncMock(return_value=grade_mock),
            ) as mock_svc,
        ):
            result = await _run_grade_essay(str(uuid.uuid4()), str(uuid.uuid4()), "balanced")

        assert result == str(grade_id)
        mock_svc.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_error_propagates_from_service(self) -> None:
        """LLMError raised by the grading service propagates from _run_grade_essay."""
        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.grading.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.grading.grade_essay",
                new=AsyncMock(side_effect=LLMError("LLM timed out")),
            ),
            pytest.raises(LLMError),
        ):
            await _run_grade_essay(str(uuid.uuid4()), str(uuid.uuid4()), "balanced")

    @pytest.mark.asyncio
    async def test_marks_essay_grading_before_db_work_when_assignment_id_provided(self) -> None:
        """When assignment_id is set, _mark_essay_grading_in_redis is called before grading."""
        grade_id = uuid.uuid4()
        grade_mock = _make_grade_mock(grade_id)
        essay_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        mark_grading_called: list[tuple[str, str]] = []

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        async def _fake_mark_grading(eid: str, aid: str) -> None:
            mark_grading_called.append((eid, aid))

        with (
            patch("app.tasks.grading.AsyncSessionLocal", return_value=cm),
            patch("app.services.grading.grade_essay", new=AsyncMock(return_value=grade_mock)),
            patch("app.tasks.grading._mark_essay_grading_in_redis", side_effect=_fake_mark_grading),
            patch("app.tasks.grading._update_redis_on_success", new=AsyncMock()),
        ):
            await _run_grade_essay(essay_id, teacher_id, "balanced", assignment_id)

        assert len(mark_grading_called) == 1
        assert mark_grading_called[0] == (essay_id, assignment_id)

    @pytest.mark.asyncio
    async def test_redis_grading_mark_failure_does_not_abort_grading(self) -> None:
        """A Redis failure when marking as grading is non-fatal; grading continues."""
        grade_id = uuid.uuid4()
        grade_mock = _make_grade_mock(grade_id)
        essay_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.grading.AsyncSessionLocal", return_value=cm),
            patch("app.services.grading.grade_essay", new=AsyncMock(return_value=grade_mock)),
            patch(
                "app.tasks.grading._mark_essay_grading_in_redis",
                side_effect=ConnectionError("Redis down"),
            ),
            patch("app.tasks.grading._update_redis_on_success", new=AsyncMock()),
        ):
            # Should NOT raise despite Redis failure
            result = await _run_grade_essay(essay_id, teacher_id, "balanced", assignment_id)

        assert result == str(grade_id)

    @pytest.mark.asyncio
    async def test_redis_success_update_failure_does_not_fail_graded_essay(self) -> None:
        """A Redis failure on success update is non-fatal; the grade is already written."""
        grade_id = uuid.uuid4()
        grade_mock = _make_grade_mock(grade_id)
        essay_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = AsyncMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.grading.AsyncSessionLocal", return_value=cm),
            patch("app.services.grading.grade_essay", new=AsyncMock(return_value=grade_mock)),
            patch("app.tasks.grading._mark_essay_grading_in_redis", new=AsyncMock()),
            patch(
                "app.tasks.grading._update_redis_on_success",
                side_effect=ConnectionError("Redis down"),
            ),
        ):
            # Should NOT raise — grade was already committed to DB
            result = await _run_grade_essay(essay_id, teacher_id, "balanced", assignment_id)

        assert result == str(grade_id)


# ---------------------------------------------------------------------------
# Tests — _revert_essay_to_queued async helper
# ---------------------------------------------------------------------------


class TestRevertEssayToQueued:
    @pytest.mark.asyncio
    async def test_sets_essay_status_to_queued(self) -> None:
        """_revert_essay_to_queued sets essay.status = queued and commits."""
        from app.models.essay import EssayStatus

        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        essay_mock = MagicMock()
        essay_mock.status = EssayStatus.grading

        db_mock = AsyncMock()
        db_mock.add = MagicMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=essay_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tasks.grading.AsyncSessionLocal", return_value=cm):
            await _revert_essay_to_queued(essay_id, teacher_id)

        assert essay_mock.status == EssayStatus.queued
        db_mock.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_error_when_essay_not_found(self) -> None:
        """_revert_essay_to_queued is a no-op when the essay doesn't exist."""
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        db_mock.execute = AsyncMock(return_value=result_mock)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tasks.grading.AsyncSessionLocal", return_value=cm):
            # Should not raise
            await _revert_essay_to_queued(essay_id, teacher_id)

        db_mock.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op_when_essay_not_in_grading_status(self) -> None:
        """_revert_essay_to_queued is a no-op when essay.status is not grading."""
        from app.models.essay import EssayStatus

        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        essay_mock = MagicMock()
        essay_mock.status = EssayStatus.graded  # Already graded — must not be downgraded

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=essay_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch("app.tasks.grading.AsyncSessionLocal", return_value=cm):
            await _revert_essay_to_queued(essay_id, teacher_id)

        # Status must remain graded and no commit should be issued.
        assert essay_mock.status == EssayStatus.graded
        db_mock.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — grade_essay task (eager execution via mock)
# ---------------------------------------------------------------------------


class TestGradeEssayTask:
    def test_returns_grade_id_on_success(self) -> None:
        """task returns the grade ID string when the service succeeds."""
        grade_id = str(uuid.uuid4())
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch("app.tasks.grading.asyncio.run", return_value=grade_id) as mock_run:
            result = grade_essay(essay_id, teacher_id, "balanced")
            assert result == grade_id
            mock_run.assert_called_once()

    def test_llm_error_triggers_retry(self) -> None:
        """LLMError causes the task to be retried when retries remain.

        We verify this by patching _run_grade_essay as an AsyncMock that raises
        LLMError.  With eager execution (CELERY_ALWAYS_EAGER), apply() executes
        all retries in-process and the task ultimately fails with LLMError after
        exhausting max_retries.  Separately verify that _revert_essay_to_queued
        is called on exhaustion.
        """
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        revert_called: list[str] = []

        # Patch the async helper so asyncio.run(_run_grade_essay(...)) raises LLMError
        # Patch _revert_essay_to_queued to succeed and record the call
        with (
            patch(
                "app.tasks.grading._run_grade_essay",
                new=AsyncMock(side_effect=LLMError("LLM timed out")),
            ),
            patch(
                "app.tasks.grading._revert_essay_to_queued",
                new=AsyncMock(side_effect=lambda eid, tid: revert_called.append(eid)),
            ),
        ):
            result = grade_essay.apply(args=[essay_id, teacher_id, "balanced"])

        assert result.failed(), "Task should fail after exhausting retries"
        assert len(revert_called) == 1, "Essay should be reverted to queued once"
        assert revert_called[0] == essay_id

    def test_exhausted_retries_reverts_essay_and_reraises(self) -> None:
        """On max retries, essay is reverted to queued and the exception propagates."""
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        revert_called: list[str] = []

        with (
            patch(
                "app.tasks.grading._run_grade_essay",
                new=AsyncMock(side_effect=LLMError("LLM timed out")),
            ),
            patch(
                "app.tasks.grading._revert_essay_to_queued",
                new=AsyncMock(side_effect=lambda eid, tid: revert_called.append(eid)),
            ),
        ):
            result = grade_essay.apply(args=[essay_id, teacher_id, "balanced"])

        assert result.failed(), "Task should be in FAILURE state"
        assert revert_called, "Essay should be reverted after exhausted retries"

    def test_non_llm_exception_reverts_essay_and_reraises(self) -> None:
        """Non-LLM exceptions also revert the essay and re-raise."""
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        revert_called: list[str] = []

        with (
            patch(
                "app.tasks.grading._run_grade_essay",
                new=AsyncMock(side_effect=RuntimeError("Unexpected DB failure")),
            ),
            patch(
                "app.tasks.grading._revert_essay_to_queued",
                new=AsyncMock(side_effect=lambda eid, tid: revert_called.append(eid)),
            ),
        ):
            result = grade_essay.apply(args=[essay_id, teacher_id, "balanced"])

        assert result.failed(), "Task should be in FAILURE state for non-LLM exceptions"
        assert revert_called, "Essay should be reverted on unrecoverable errors"

    def test_forbidden_error_does_not_revert_essay(self) -> None:
        """ForbiddenError does not trigger _revert_essay_to_queued (nothing to revert)."""
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        revert_called: list[str] = []

        with (
            patch(
                "app.tasks.grading._run_grade_essay",
                new=AsyncMock(side_effect=ForbiddenError("Not your essay")),
            ),
            patch(
                "app.tasks.grading._revert_essay_to_queued",
                new=AsyncMock(side_effect=lambda eid, tid: revert_called.append(eid)),
            ),
        ):
            result = grade_essay.apply(args=[essay_id, teacher_id, "balanced"])

        assert result.failed(), "Task should fail with ForbiddenError"
        assert len(revert_called) == 0, "Revert must not be called for ForbiddenError"

    def test_conflict_error_does_not_revert_essay(self) -> None:
        """ConflictError (e.g., duplicate grade) does not trigger _revert_essay_to_queued."""
        essay_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        revert_called: list[str] = []

        with (
            patch(
                "app.tasks.grading._run_grade_essay",
                new=AsyncMock(side_effect=ConflictError("already graded")),
            ),
            patch(
                "app.tasks.grading._revert_essay_to_queued",
                new=AsyncMock(side_effect=lambda eid, tid: revert_called.append(eid)),
            ),
        ):
            result = grade_essay.apply(args=[essay_id, teacher_id, "balanced"])

        assert result.failed(), "Task should fail with ConflictError"
        assert len(revert_called) == 0, "Revert must not be called for ConflictError"
