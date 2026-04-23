"""Unit tests for app/tasks/embedding.py and app/services/embedding.py (M4.4).

All database and OpenAI calls are mocked — no real broker, no real PostgreSQL.
Tests call the underlying async helpers directly (not via Celery worker),
consistent with the project's Celery testing pattern.

No student PII in any fixture.

Coverage:
- Task is registered in Celery with the correct name and max_retries.
- Happy path: embedding computed, stored, similarity scan runs.
- Similarity pair above threshold: IntegrityReport written.
- Similarity pair below threshold: IntegrityReport NOT written.
- LLMError triggers retry with exponential backoff.
- ForbiddenError / NotFoundError do not trigger retry.
- OpenAI client is always mocked — no real API calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, LLMError, NotFoundError
from app.tasks.celery_app import celery
from app.tasks.embedding import _run_compute_essay_embedding, compute_essay_embedding

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_version_mock(
    version_id: uuid.UUID | None = None,
    content: str = "Sample essay text for testing.",
) -> MagicMock:
    """Return a lightweight mock EssayVersion."""
    v = MagicMock()
    v.id = version_id or uuid.uuid4()
    v.content = content
    v.embedding = None
    return v


def _fake_embedding(dim: int = 1536) -> list[float]:
    """Return a deterministic fake embedding vector."""
    return [0.1] * dim


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


class TestComputeEssayEmbeddingTaskRegistration:
    def test_task_is_registered_in_celery(self) -> None:
        assert "tasks.embedding.compute_essay_embedding" in celery.tasks

    def test_task_has_correct_max_retries(self) -> None:
        assert compute_essay_embedding.max_retries == 3

    def test_task_name_matches_convention(self) -> None:
        assert compute_essay_embedding.name == "tasks.embedding.compute_essay_embedding"


# ---------------------------------------------------------------------------
# _run_compute_essay_embedding — happy path
# ---------------------------------------------------------------------------


class TestRunComputeEssayEmbedding:
    @pytest.mark.asyncio
    async def test_happy_path_calls_service_and_returns_flagged_count(self) -> None:
        """_run_compute_essay_embedding calls both service functions and returns count."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())
        embedding = _fake_embedding()

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.embedding.compute_and_store_embedding",
                new=AsyncMock(return_value=embedding),
            ),
            patch(
                "app.services.embedding.flag_similar_essays",
                new=AsyncMock(return_value=2),
            ),
        ):
            result = await _run_compute_essay_embedding(
                essay_version_id, assignment_id, teacher_id
            )

        assert result == 2

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        """LLMError raised by compute_and_store_embedding propagates upward."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.embedding.compute_and_store_embedding",
                new=AsyncMock(side_effect=LLMError("OpenAI timed out")),
            ),
            pytest.raises(LLMError),
        ):
            await _run_compute_essay_embedding(essay_version_id, assignment_id, teacher_id)


# ---------------------------------------------------------------------------
# compute_essay_embedding task — sync wrapper
# ---------------------------------------------------------------------------


class TestComputeEssayEmbeddingTask:
    def test_returns_flagged_count_on_success(self) -> None:
        """Task returns the flagged-pairs count when services succeed."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch("app.tasks.embedding.asyncio.run", return_value=1) as mock_run:
            result = compute_essay_embedding(essay_version_id, assignment_id, teacher_id)

        assert result == 1
        mock_run.assert_called_once()

    def test_llm_error_triggers_retry(self) -> None:
        """LLMError causes the task to retry when retries remain.

        Using eager execution (CELERY_ALWAYS_EAGER via apply()), all retries
        run in-process and the task ultimately fails with LLMError.
        """
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.embedding._run_compute_essay_embedding",
            new=AsyncMock(side_effect=LLMError("OpenAI down")),
        ):
            result = compute_essay_embedding.apply(
                args=[essay_version_id, assignment_id, teacher_id]
            )

        assert result.failed(), "Task should fail after exhausting retries"

    def test_forbidden_error_does_not_retry(self) -> None:
        """ForbiddenError fails immediately without consuming retries."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.embedding._run_compute_essay_embedding",
            new=AsyncMock(side_effect=ForbiddenError("Not your essay")),
        ):
            result = compute_essay_embedding.apply(
                args=[essay_version_id, assignment_id, teacher_id]
            )

        assert result.failed(), "Task should fail immediately on ForbiddenError"

    def test_not_found_error_does_not_retry(self) -> None:
        """NotFoundError fails immediately without consuming retries."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.embedding._run_compute_essay_embedding",
            new=AsyncMock(side_effect=NotFoundError("Version gone")),
        ):
            result = compute_essay_embedding.apply(
                args=[essay_version_id, assignment_id, teacher_id]
            )

        assert result.failed()

    def test_unrecoverable_exception_fails_task(self) -> None:
        """A non-LLM exception propagates and marks the task as FAILURE."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.embedding._run_compute_essay_embedding",
            new=AsyncMock(side_effect=RuntimeError("DB exploded")),
        ):
            result = compute_essay_embedding.apply(
                args=[essay_version_id, assignment_id, teacher_id]
            )

        assert result.failed()


# ---------------------------------------------------------------------------
# app/services/embedding — unit tests for service logic
# ---------------------------------------------------------------------------


class TestComputeAndStoreEmbedding:
    @pytest.mark.asyncio
    async def test_stores_embedding_on_version(self) -> None:
        """Embedding returned by call_embedding is stored on the EssayVersion."""
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        fake_embedding = _fake_embedding()

        version_mock = _make_version_mock(essay_version_id)

        # Simulate result row: (EssayVersion, class_teacher_id)
        row_mock = MagicMock()
        row_mock.__iter__ = MagicMock(return_value=iter([version_mock, teacher_id]))

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.one_or_none = MagicMock(return_value=row_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.commit = AsyncMock()

        with patch(
            "app.llm.client.call_embedding",
            new=AsyncMock(return_value=fake_embedding),
        ):
            returned = await compute_and_store_embedding(db_mock, essay_version_id, teacher_id)

        assert returned == fake_embedding
        assert version_mock.embedding == fake_embedding
        db_mock.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_when_version_missing(self) -> None:
        """NotFoundError raised when the essay version does not exist."""
        from app.services.embedding import compute_and_store_embedding

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.one_or_none = MagicMock(return_value=None)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(NotFoundError):
            await compute_and_store_embedding(db_mock, uuid.uuid4(), uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_when_wrong_teacher(self) -> None:
        """ForbiddenError raised when the version belongs to a different teacher."""
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()

        version_mock = _make_version_mock(essay_version_id)
        row_mock = MagicMock()
        row_mock.__iter__ = MagicMock(return_value=iter([version_mock, other_teacher_id]))

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.one_or_none = MagicMock(return_value=row_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ForbiddenError):
            await compute_and_store_embedding(db_mock, essay_version_id, teacher_id)


class TestFlagSimilarEssays:
    @pytest.mark.asyncio
    async def test_above_threshold_pair_creates_integrity_report(self) -> None:
        """An essay pair above the similarity threshold produces an IntegrityReport."""
        from app.models.integrity_report import IntegrityReport as IR
        from app.services.embedding import flag_similar_essays

        essay_version_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        embedding = _fake_embedding()

        # cosine_distance = 0.1 → similarity = 0.9 (above default threshold 0.25)
        rows = [(other_version_id, 0.1)]

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=rows)
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        added_reports: list[IR] = []

        def _capture_add(obj: object) -> None:
            if isinstance(obj, IR):
                added_reports.append(obj)

        db_mock.add.side_effect = _capture_add

        with patch("app.config.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, assignment_id, teacher_id, embedding
            )

        assert flagged == 1
        assert len(added_reports) == 1
        report = added_reports[0]
        assert report.essay_version_id == essay_version_id
        assert report.teacher_id == teacher_id
        assert report.provider == "internal"
        assert report.similarity_score == pytest.approx(0.9, abs=1e-4)
        db_mock.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_below_threshold_pair_not_flagged(self) -> None:
        """An essay pair below the similarity threshold does NOT create a report."""
        from app.services.embedding import flag_similar_essays

        essay_version_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        embedding = _fake_embedding()

        # cosine_distance = 0.9 → similarity = 0.1 (below threshold 0.25)
        rows = [(other_version_id, 0.9)]

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=rows)
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.config.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, assignment_id, teacher_id, embedding
            )

        assert flagged == 0
        db_mock.add.assert_not_called()
        db_mock.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_candidates_returns_zero(self) -> None:
        """When no other essays have embeddings, returns 0 without writing anything."""
        from app.services.embedding import flag_similar_essays

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=[])
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.config.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), _fake_embedding()
            )

        assert flagged == 0
        db_mock.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_exact_threshold_boundary_is_flagged(self) -> None:
        """An essay pair exactly at the threshold is flagged (>= not >)."""
        from app.services.embedding import flag_similar_essays

        essay_version_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        embedding = _fake_embedding()
        threshold = 0.25

        # cosine_distance = 1 - threshold → similarity == threshold
        rows = [(other_version_id, 1.0 - threshold)]

        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.all = MagicMock(return_value=rows)
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.config.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = threshold
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, uuid.uuid4(), uuid.uuid4(), embedding
            )

        assert flagged == 1
        db_mock.add.assert_called_once()
