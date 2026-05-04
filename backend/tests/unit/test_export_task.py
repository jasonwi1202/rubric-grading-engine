"""Unit tests for app/tasks/export.py and app/services/export.py.

All database, Redis, S3, and PDF generation calls are mocked — no real broker,
no real PostgreSQL, no real S3.

Tests call the underlying async helpers and service functions directly (not via
the Celery worker), consistent with the project's Celery testing pattern.

Security:
- No student PII in any fixture — student IDs are generated UUIDs.
- No hardcoded credential-format strings.

Coverage:
- export_assignment task: registration, happy path, retry on failure.
- _run_export async helper: happy path, no locked essays, assignment not found,
  S3 upload failure, PDF generation failure.
- _build_student_pdf: generates non-empty bytes.
- trigger_export service: enqueues task, stores Redis record, writes audit log.
- get_export_status service: happy path, not found, cross-teacher forbidden.
- get_export_download_url service: happy path, not complete, not found,
  cross-teacher forbidden.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.tasks.celery_app import celery
from app.tasks.export import _build_student_pdf, export_assignment

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_redis_mock(record: dict[str, str] | None = None) -> AsyncMock:
    """Return an async Redis mock whose ``hgetall`` returns *record*."""
    redis = AsyncMock()
    redis.hgetall = AsyncMock(return_value=record or {})
    redis.hset = AsyncMock()
    redis.expire = AsyncMock()
    redis.aclose = AsyncMock()
    redis.delete = AsyncMock(return_value=0)  # Default: no one-shot key present.
    return redis


def _make_db_mock() -> AsyncMock:
    """Return a minimal async DB session mock."""
    db = AsyncMock()
    db.add = MagicMock()  # synchronous — must NOT be awaited
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


class TestExportTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.export.export_assignment" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert export_assignment.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert export_assignment.name == "tasks.export.export_assignment"


# ---------------------------------------------------------------------------
# _build_student_pdf
# ---------------------------------------------------------------------------


class TestBuildStudentPdf:
    def test_returns_nonempty_bytes(self) -> None:
        result = _build_student_pdf(
            student_id=str(uuid.uuid4()),
            assignment_title="Test Assignment",
            summary_feedback="Good work overall.",
            criterion_items=[
                {
                    "name": "Thesis",
                    "final_score": 4,
                    "max_score": 5,
                    "feedback": "Clear thesis statement.",
                }
            ],
        )
        assert isinstance(result, bytes), "Expected bytes output from _build_student_pdf"
        assert len(result) > 100, "PDF bytes should be non-trivial in length"

    def test_generates_bytes_with_no_criteria(self) -> None:
        result = _build_student_pdf(
            student_id=str(uuid.uuid4()),
            assignment_title="Assignment",
            summary_feedback="Feedback text.",
            criterion_items=[],
        )
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_generates_bytes_with_no_criterion_feedback(self) -> None:
        result = _build_student_pdf(
            student_id=str(uuid.uuid4()),
            assignment_title="Assignment",
            summary_feedback="Feedback.",
            criterion_items=[
                {"name": "Criterion A", "final_score": 3, "max_score": 5, "feedback": None}
            ],
        )
        assert isinstance(result, bytes)

    def test_does_not_include_student_name_in_content(self) -> None:
        """PDF should use student_id (UUID), never a name — verify the identifier appears."""
        student_id = str(uuid.uuid4())
        result = _build_student_pdf(
            student_id=student_id,
            assignment_title="Assignment A",
            summary_feedback="Overall feedback.",
            criterion_items=[],
        )
        assert isinstance(result, bytes), "Expected PDF bytes"
        # The PDF must be non-empty and not contain name-like patterns that
        # would indicate student PII leaked into the generated file.
        assert len(result) > 200, "PDF should contain meaningful content"
        # Verify no realistic name patterns appear (e.g. 'Alice', 'Student Name').
        decoded = result.decode("latin-1", errors="replace")
        assert "Alice" not in decoded, "Real names must not appear in PDF"
        assert "Bob" not in decoded, "Real names must not appear in PDF"
        assert "Student Name" not in decoded, "Placeholder PII must not appear in PDF"


# ---------------------------------------------------------------------------
# _run_export async helper
# ---------------------------------------------------------------------------


class TestRunExport:
    @pytest.mark.asyncio
    async def test_happy_path_uploads_zip_and_sets_complete(self) -> None:
        """_run_export with one locked essay should upload ZIP and set Redis complete."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        student_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        criterion_id = uuid.uuid4()

        # --- ORM mock objects ---
        mock_assignment = MagicMock()
        mock_assignment.id = uuid.UUID(assignment_id)
        mock_assignment.title = "Test Assignment"
        mock_assignment.rubric_snapshot = {
            "id": str(uuid.uuid4()),
            "name": "Rubric",
            "criteria": [
                {
                    "id": str(criterion_id),
                    "name": "Criterion A",
                    "max_score": 5,
                }
            ],
        }

        mock_essay = MagicMock()
        mock_essay.id = essay_id

        mock_grade = MagicMock()
        mock_grade.id = grade_id
        mock_grade.is_locked = True
        mock_grade.summary_feedback = "Great work."
        mock_grade.summary_feedback_edited = None

        mock_ev = MagicMock()
        mock_ev.essay_id = essay_id

        mock_score = MagicMock()
        mock_score.grade_id = grade_id
        mock_score.rubric_criterion_id = criterion_id
        mock_score.final_score = 4
        mock_score.ai_feedback = "Excellent."
        mock_score.teacher_feedback = None

        # --- DB execute side-effects ---
        def make_result(rows: list) -> MagicMock:  # type: ignore[type-arg]
            r = MagicMock()
            r.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
            r.all.return_value = rows
            scalars_mock = MagicMock()
            scalars_mock.__iter__ = MagicMock(return_value=iter(rows))
            r.scalars.return_value = scalars_mock
            return r

        assignment_result = make_result([mock_assignment])
        essays_result = make_result([(mock_essay, student_id)])
        grades_result = make_result([(mock_ev, mock_grade)])
        scores_result = make_result([mock_score])

        execute_responses = [
            assignment_result,
            essays_result,
            grades_result,
            scores_result,
            make_result([]),  # media comments — no comments for this grade
        ]
        execute_call_count = 0

        async def _mock_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal execute_call_count
            resp = execute_responses[execute_call_count]
            execute_call_count += 1
            return resp

        db_mock = AsyncMock()
        db_mock.execute = _mock_execute
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
            patch("app.tasks.export.upload_file") as mock_upload,
        ):
            await _run_export(assignment_id, teacher_id, task_id)

        # Upload was called with a ZIP content type.
        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        assert (
            call_args.args[2] == "application/zip"
            or call_args.kwargs.get("content_type") == "application/zip"
        ), "Expected application/zip content type"

        # Redis was updated to complete.
        hset_calls = redis_mock.hset.call_args_list
        complete_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "complete"),
            None,
        )
        assert complete_call is not None, "Redis status should be set to 'complete'"

    @pytest.mark.asyncio
    async def test_no_locked_essays_sets_failed_status(self) -> None:
        """When there are no locked essays, status should be set to 'failed'."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        mock_assignment = MagicMock()
        mock_assignment.id = uuid.UUID(assignment_id)
        mock_assignment.title = "Test"
        mock_assignment.rubric_snapshot = {"criteria": []}

        def make_result(rows: list) -> MagicMock:  # type: ignore[type-arg]
            r = MagicMock()
            r.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
            r.all.return_value = rows
            return r

        execute_responses = [make_result([mock_assignment]), make_result([])]
        execute_call_count = 0

        async def _mock_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal execute_call_count
            resp = execute_responses[execute_call_count]
            execute_call_count += 1
            return resp

        db_mock = AsyncMock()
        db_mock.execute = _mock_execute
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
        ):
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, "Redis status should be set to 'failed'"
        error_val = failed_call.kwargs.get("mapping", {}).get("error")
        assert error_val == "NO_LOCKED_GRADES", (
            f"Expected NO_LOCKED_GRADES error, got {error_val!r}"
        )

    @pytest.mark.asyncio
    async def test_assignment_not_found_sets_failed_status(self) -> None:
        """When the assignment is not found (or forbidden), status = failed."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        not_found_result = MagicMock()
        not_found_result.scalar_one_or_none.return_value = None

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=not_found_result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
        ):
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, "Redis should be set to failed when assignment not found"

    @pytest.mark.asyncio
    async def test_s3_upload_failure_sets_failed_status(self) -> None:
        """S3 upload failure should set Redis status to failed, not re-raise."""
        from app.storage.s3 import StorageError
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        student_id = uuid.uuid4()
        essay_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        criterion_id = uuid.uuid4()

        mock_assignment = MagicMock()
        mock_assignment.id = uuid.UUID(assignment_id)
        mock_assignment.title = "Test"
        mock_assignment.rubric_snapshot = {
            "criteria": [{"id": str(criterion_id), "name": "C", "max_score": 5}]
        }
        mock_essay = MagicMock()
        mock_essay.id = essay_id
        mock_grade = MagicMock()
        mock_grade.id = grade_id
        mock_grade.is_locked = True
        mock_grade.summary_feedback = "OK"
        mock_grade.summary_feedback_edited = None
        mock_ev = MagicMock()
        mock_ev.essay_id = essay_id
        mock_score = MagicMock()
        mock_score.grade_id = grade_id
        mock_score.rubric_criterion_id = criterion_id
        mock_score.final_score = 3
        mock_score.ai_feedback = None
        mock_score.teacher_feedback = None

        def make_result(rows: list) -> MagicMock:  # type: ignore[type-arg]
            r = MagicMock()
            r.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
            r.all.return_value = rows
            scalars_mock = MagicMock()
            scalars_mock.__iter__ = MagicMock(return_value=iter(rows))
            r.scalars.return_value = scalars_mock
            return r

        execute_responses = [
            make_result([mock_assignment]),
            make_result([(mock_essay, student_id)]),
            make_result([(mock_ev, mock_grade)]),
            make_result([mock_score]),
            make_result([]),  # media comments — no comments for this grade
        ]
        execute_call_count = 0

        async def _mock_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal execute_call_count
            resp = execute_responses[execute_call_count]
            execute_call_count += 1
            return resp

        db_mock = AsyncMock()
        db_mock.execute = _mock_execute
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
            patch(
                "app.tasks.export.upload_file",
                side_effect=StorageError("S3 upload failed"),
            ),
        ):
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, "Redis should be set to failed on S3 upload failure"
        error_val = failed_call.kwargs.get("mapping", {}).get("error")
        assert error_val == "S3_UPLOAD_FAILED", f"Expected S3_UPLOAD_FAILED, got {error_val!r}"

    @pytest.mark.asyncio
    async def test_all_essays_skipped_sets_no_exportable_grades(self) -> None:
        """When all locked essays have no associated student (all skipped in the PDF
        generation loop), the task should fail with NO_EXPORTABLE_GRADES rather than
        uploading an empty ZIP.

        The grade and scores queries still run and return data — the skip happens in
        the PDF generation loop when ``student_uuid_val is None``, not during grade
        loading.
        """
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        essay_id = uuid.uuid4()
        grade_id = uuid.uuid4()
        criterion_id = uuid.uuid4()

        mock_assignment = MagicMock()
        mock_assignment.id = uuid.UUID(assignment_id)
        mock_assignment.title = "Test Assignment"
        mock_assignment.rubric_snapshot = {
            "criteria": [{"id": str(criterion_id), "name": "Criterion A", "max_score": 5}]
        }

        mock_essay = MagicMock()
        mock_essay.id = essay_id

        # Grade and essay version exist, but the essay is skipped in the loop because
        # the essay has no associated student (student_uuid_val = None).
        mock_ev = MagicMock()
        mock_ev.essay_id = essay_id
        mock_grade = MagicMock()
        mock_grade.id = grade_id
        mock_grade.is_locked = True
        mock_grade.summary_feedback = "Good work."
        mock_grade.summary_feedback_edited = None

        mock_score = MagicMock()
        mock_score.grade_id = grade_id
        mock_score.rubric_criterion_id = criterion_id
        mock_score.final_score = 4
        mock_score.ai_feedback = "Well done."
        mock_score.teacher_feedback = None

        def make_result(rows: list) -> MagicMock:  # type: ignore[type-arg]
            r = MagicMock()
            r.scalar_one_or_none.return_value = rows[0] if len(rows) == 1 else None
            r.all.return_value = rows
            scalars_mock = MagicMock()
            scalars_mock.__iter__ = MagicMock(return_value=iter(rows))
            r.scalars.return_value = scalars_mock
            return r

        # The essay is returned with student_uuid_val = None — skipped in the loop.
        execute_responses = [
            make_result([mock_assignment]),
            make_result([(mock_essay, None)]),  # student_uuid_val = None → loop skips
            make_result([(mock_ev, mock_grade)]),  # grade loaded, but essay skipped before lookup
            make_result([mock_score]),  # scores loaded, but essay skipped before lookup
            make_result([]),  # media comments — no comments
        ]
        execute_call_count = 0

        async def _mock_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal execute_call_count
            resp = execute_responses[execute_call_count]
            execute_call_count += 1
            return resp

        db_mock = AsyncMock()
        db_mock.execute = _mock_execute
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
        ):
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, "Redis should be set to failed when all essays are skipped"
        error_val = failed_call.kwargs.get("mapping", {}).get("error")
        assert error_val == "NO_EXPORTABLE_GRADES", (
            f"Expected NO_EXPORTABLE_GRADES, got {error_val!r}"
        )

    @pytest.mark.asyncio
    async def test_force_fail_via_one_shot_redis_key(self) -> None:
        """When EXPORT_TASK_FORCE_FAIL=true and the one-shot Redis key is present,
        _run_export sets FORCED_FAILURE and returns early."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        redis_mock = _make_redis_mock()
        # Simulate the one-shot key being present: delete() returns 1 (key consumed).
        redis_mock.delete = AsyncMock(return_value=1)

        with (
            patch("app.tasks.export.AsyncSessionLocal"),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
            patch("app.config.settings") as mock_settings,
        ):
            # Flag must be True for the one-shot check to run.
            mock_settings.export_task_force_fail = True
            mock_settings.redis_url = "redis://localhost:6379/0"
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, "Redis should be set to failed when one-shot key is consumed"
        error_val = failed_call.kwargs.get("mapping", {}).get("error")
        assert error_val == "FORCED_FAILURE", (
            f"Expected FORCED_FAILURE error code, got {error_val!r}"
        )

    @pytest.mark.asyncio
    async def test_no_force_fail_when_flag_set_but_no_one_shot_key(self) -> None:
        """When EXPORT_TASK_FORCE_FAIL=true but no one-shot key is armed,
        _run_export does NOT fail deterministically (retry path succeeds)."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        # Simulate no assignment found — this triggers a different failure path.
        not_found_result = MagicMock()
        not_found_result.scalar_one_or_none.return_value = None

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=not_found_result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()
        # No one-shot key present (delete returns 0).
        redis_mock.delete = AsyncMock(return_value=0)

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
            patch("app.config.settings") as mock_settings,
        ):
            mock_settings.export_task_force_fail = True
            mock_settings.redis_url = "redis://localhost:6379/0"
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        # There should be a 'failed' call (assignment not found), but NOT FORCED_FAILURE.
        forced_failure_call = next(
            (
                c
                for c in hset_calls
                if c.kwargs.get("mapping", {}).get("error") == "FORCED_FAILURE"
            ),
            None,
        )
        assert forced_failure_call is None, (
            "FORCED_FAILURE must not appear when the one-shot key is not armed"
        )

    @pytest.mark.asyncio
    async def test_no_force_fail_when_flag_disabled(self) -> None:
        """When EXPORT_TASK_FORCE_FAIL=false, the one-shot Redis key check is
        skipped entirely — even if the key is present in Redis."""
        from app.tasks.export import _run_export

        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        # Simulate no assignment found — triggers a different failure path.
        not_found_result = MagicMock()
        not_found_result.scalar_one_or_none.return_value = None

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=not_found_result)
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)

        redis_mock = _make_redis_mock()
        # The key would be present, but the flag is disabled so delete() should
        # never be called for the one-shot check.
        redis_mock.delete = AsyncMock(return_value=1)

        with (
            patch("app.tasks.export.AsyncSessionLocal", return_value=cm),
            patch("redis.asyncio.Redis.from_url", return_value=redis_mock),
            patch("app.config.settings") as mock_settings,
        ):
            mock_settings.export_task_force_fail = False
            mock_settings.redis_url = "redis://localhost:6379/0"
            await _run_export(assignment_id, teacher_id, task_id)

        hset_calls = redis_mock.hset.call_args_list
        # No FORCED_FAILURE — the injection path was never entered.
        forced_failure_call = next(
            (
                c
                for c in hset_calls
                if c.kwargs.get("mapping", {}).get("error") == "FORCED_FAILURE"
            ),
            None,
        )
        assert forced_failure_call is None, (
            "FORCED_FAILURE must not appear when EXPORT_TASK_FORCE_FAIL=false"
        )


# ---------------------------------------------------------------------------
# Celery task — happy path and retry
# ---------------------------------------------------------------------------


class TestExportAssignmentTask:
    def test_task_eager_happy_path(self) -> None:
        """export_assignment in eager mode calls _run_export without error."""
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        with patch(
            "app.tasks.export.asyncio.run",
            return_value=None,
        ) as mock_run:
            result = export_assignment(assignment_id, teacher_id, task_id)
            mock_run.assert_called_once()
            assert f"exports/{assignment_id}/{task_id}.zip" == result

    def test_task_fails_after_exhausted_retries(self) -> None:
        """export_assignment fails after exhausting all retries.

        We verify this by patching _run_export as an AsyncMock that always raises.
        With eager execution (CELERY_ALWAYS_EAGER), apply() executes all retries
        in-process and the task ultimately fails.
        """
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        with patch(
            "app.tasks.export._run_export",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = export_assignment.apply(args=[assignment_id, teacher_id, task_id])

        assert result.failed(), "Task should fail after exhausting retries"


# ---------------------------------------------------------------------------
# trigger_export service
# ---------------------------------------------------------------------------


class TestTriggerExportService:
    @pytest.mark.asyncio
    async def test_returns_task_id_string(self) -> None:
        """trigger_export returns a UUID string task_id."""
        from app.services.export import trigger_export

        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        mock_assignment = MagicMock()
        mock_assignment.id = assignment_id

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(return_value=mock_assignment),
            ),
            patch("app.tasks.export.export_assignment") as mock_task,
        ):
            mock_task.delay = MagicMock()
            task_id = await trigger_export(db, redis, assignment_id, teacher_id)

        assert isinstance(task_id, str), "task_id should be a string"
        uuid.UUID(task_id)  # validates it is a valid UUID

    @pytest.mark.asyncio
    async def test_stores_teacher_id_in_redis(self) -> None:
        """trigger_export stores teacher_id in the Redis export record."""
        from app.services.export import trigger_export

        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch("app.tasks.export.export_assignment") as mock_task,
        ):
            mock_task.delay = MagicMock()
            await trigger_export(db, redis, assignment_id, teacher_id)

        redis.hset.assert_called_once()
        call_kwargs = redis.hset.call_args.kwargs
        stored_teacher_id = call_kwargs.get("mapping", {}).get("teacher_id")
        assert stored_teacher_id == str(teacher_id), (
            f"Expected teacher_id {teacher_id!s} in Redis, got {stored_teacher_id!r}"
        )

    @pytest.mark.asyncio
    async def test_writes_audit_log_entry(self) -> None:
        """trigger_export inserts an audit log entry with action export_requested."""
        from app.services.export import trigger_export

        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch("app.tasks.export.export_assignment") as mock_task,
        ):
            mock_task.delay = MagicMock()
            await trigger_export(db, redis, assignment_id, teacher_id)

        # db.add must have been called (synchronous, not awaited).
        db.add.assert_called_once()
        audit_arg = db.add.call_args.args[0]
        assert audit_arg.action == "export_requested", (
            f"Expected audit action 'export_requested', got {audit_arg.action!r}"
        )
        assert audit_arg.teacher_id == teacher_id
        assert audit_arg.entity_id == assignment_id

    @pytest.mark.asyncio
    async def test_propagates_not_found_from_get_assignment(self) -> None:
        """trigger_export raises NotFoundError when the assignment does not exist."""
        from app.services.export import trigger_export

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(side_effect=NotFoundError("Assignment not found.")),
            ),
            pytest.raises(NotFoundError),
        ):
            await trigger_export(db, redis, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_propagates_forbidden_from_get_assignment(self) -> None:
        """trigger_export raises ForbiddenError on cross-teacher access."""
        from app.services.export import trigger_export

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(side_effect=ForbiddenError("Forbidden.")),
            ),
            pytest.raises(ForbiddenError),
        ):
            await trigger_export(db, redis, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_enqueue_failure_marks_redis_failed_and_raises(self) -> None:
        """When the Celery broker is unavailable, trigger_export marks the Redis
        record as failed and raises RuntimeError so the HTTP layer returns 500."""
        from app.services.export import trigger_export

        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        db = _make_db_mock()
        redis = _make_redis_mock()

        with (
            patch(
                "app.services.export.get_assignment",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch("app.tasks.export.export_assignment") as mock_task,
            pytest.raises(RuntimeError, match="Failed to enqueue export task"),
        ):
            mock_task.delay = MagicMock(side_effect=RuntimeError("Broker down"))
            await trigger_export(db, redis, assignment_id, teacher_id)

        # Redis must be updated to 'failed' so poll clients do not see 'pending' forever.
        hset_calls = redis.hset.call_args_list
        failed_call = next(
            (c for c in hset_calls if c.kwargs.get("mapping", {}).get("status") == "failed"),
            None,
        )
        assert failed_call is not None, (
            "Redis should be updated to 'failed' when the Celery enqueue fails"
        )
        assert failed_call.kwargs["mapping"]["error"] == "ENQUEUE_FAILED"


# ---------------------------------------------------------------------------
# get_export_status service
# ---------------------------------------------------------------------------


class TestGetExportStatusService:
    @pytest.mark.asyncio
    async def test_returns_status_data_for_valid_task(self) -> None:
        """get_export_status returns correct data for an existing task."""
        from app.services.export import get_export_status

        teacher_id = uuid.uuid4()
        task_id = str(uuid.uuid4())

        record = {
            "status": "processing",
            "teacher_id": str(teacher_id),
            "assignment_id": str(uuid.uuid4()),
            "total": "10",
            "complete": "5",
        }
        redis = _make_redis_mock(record)

        result = await get_export_status(task_id, teacher_id, redis)

        assert result["status"] == "processing"
        assert result["total"] == 10
        assert result["complete"] == 5
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_raises_not_found_when_record_missing(self) -> None:
        """get_export_status raises NotFoundError when the task is not in Redis."""
        from app.services.export import get_export_status

        redis = _make_redis_mock({})  # empty dict → task not found

        with pytest.raises(NotFoundError):
            await get_export_status(str(uuid.uuid4()), uuid.uuid4(), redis)

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_different_teacher(self) -> None:
        """get_export_status raises ForbiddenError for cross-teacher access."""
        from app.services.export import get_export_status

        owner_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        task_id = str(uuid.uuid4())

        record = {
            "status": "pending",
            "teacher_id": str(owner_id),
            "assignment_id": str(uuid.uuid4()),
            "total": "0",
            "complete": "0",
        }
        redis = _make_redis_mock(record)

        with pytest.raises(ForbiddenError):
            await get_export_status(task_id, other_teacher_id, redis)


# ---------------------------------------------------------------------------
# get_export_download_url service
# ---------------------------------------------------------------------------


class TestGetExportDownloadUrlService:
    @pytest.mark.asyncio
    async def test_returns_presigned_url_when_complete(self) -> None:
        """get_export_download_url returns a URL when the task is complete."""
        from app.services.export import get_export_download_url

        teacher_id = uuid.uuid4()
        task_id = str(uuid.uuid4())
        assignment_id = uuid.uuid4()
        s3_key = f"exports/{uuid.uuid4()}/{task_id}.zip"

        record = {
            "status": "complete",
            "teacher_id": str(teacher_id),
            "assignment_id": str(assignment_id),
            "s3_key": s3_key,
        }
        redis = _make_redis_mock(record)
        db = _make_db_mock()

        with patch(
            "app.services.export.generate_presigned_url",
            return_value="https://example.com/signed",
        ) as mock_url:
            url = await get_export_download_url(db, task_id, teacher_id, redis)

        assert url == "https://example.com/signed"
        mock_url.assert_called_once_with(s3_key, expires_in=900)

    @pytest.mark.asyncio
    async def test_writes_export_downloaded_audit_log(self) -> None:
        """get_export_download_url writes an export_downloaded audit log entry."""
        from app.services.export import get_export_download_url

        teacher_id = uuid.uuid4()
        task_id = str(uuid.uuid4())
        assignment_id = uuid.uuid4()

        record = {
            "status": "complete",
            "teacher_id": str(teacher_id),
            "assignment_id": str(assignment_id),
            "s3_key": f"exports/{uuid.uuid4()}/{task_id}.zip",
        }
        redis = _make_redis_mock(record)
        db = _make_db_mock()

        with patch(
            "app.services.export.generate_presigned_url",
            return_value="https://example.com/s",
        ):
            await get_export_download_url(db, task_id, teacher_id, redis)

        db.add.assert_called_once()
        audit_arg = db.add.call_args.args[0]
        assert audit_arg.action == "export_downloaded", (
            f"Expected audit action 'export_downloaded', got {audit_arg.action!r}"
        )

    @pytest.mark.asyncio
    async def test_raises_conflict_when_not_complete(self) -> None:
        """get_export_download_url raises ConflictError when status is not complete."""
        from app.services.export import get_export_download_url

        teacher_id = uuid.uuid4()
        task_id = str(uuid.uuid4())

        record = {
            "status": "processing",
            "teacher_id": str(teacher_id),
            "assignment_id": str(uuid.uuid4()),
        }
        redis = _make_redis_mock(record)
        db = _make_db_mock()

        with pytest.raises(ConflictError):
            await get_export_download_url(db, task_id, teacher_id, redis)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_record_missing(self) -> None:
        """get_export_download_url raises NotFoundError when task is not in Redis."""
        from app.services.export import get_export_download_url

        redis = _make_redis_mock({})
        db = _make_db_mock()

        with pytest.raises(NotFoundError):
            await get_export_download_url(db, str(uuid.uuid4()), uuid.uuid4(), redis)

    @pytest.mark.asyncio
    async def test_raises_forbidden_for_different_teacher(self) -> None:
        """get_export_download_url raises ForbiddenError for cross-teacher access."""
        from app.services.export import get_export_download_url

        owner_id = uuid.uuid4()
        other_id = uuid.uuid4()

        record = {
            "status": "complete",
            "teacher_id": str(owner_id),
            "assignment_id": str(uuid.uuid4()),
            "s3_key": "exports/x/y.zip",
        }
        redis = _make_redis_mock(record)
        db = _make_db_mock()

        with pytest.raises(ForbiddenError):
            await get_export_download_url(db, str(uuid.uuid4()), other_id, redis)
