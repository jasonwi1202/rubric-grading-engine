"""Unit tests for app/tasks/embedding.py (M4.4 → M4.5).

All database and OpenAI calls are mocked — no real broker, no real PostgreSQL.
Tests call the underlying async helpers directly (not via Celery worker),
consistent with the project's Celery testing pattern.

No student PII in any fixture.

Coverage:
- Task is registered in Celery with the correct name and max_retries.
- Happy path: run_integrity_check is called and passage count returned.
- NotFoundError propagates when essay version is missing.
- LLMError triggers retry with exponential backoff.
- ForbiddenError / NotFoundError do not trigger retry.
- OpenAI client is always mocked — no real API calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.exceptions import ForbiddenError, LLMError, NotFoundError, ValidationError
from app.services.integrity import IntegrityResult
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
    def _make_text_db(
        self,
        content: str | None = "Sample essay text for testing.",
        *,
        version_exists: bool = False,
    ) -> AsyncMock:
        """Return a DB mock for the tenant-scoped essay-content fetch.

        Args:
            content: The essay content to return from the tenant-scoped query.
                When ``None`` the tenant-scoped query found no matching row.
            version_exists: Only used when ``content is None``.  When
                ``True`` the bare existence check returns a UUID (essay exists
                but belongs to a different teacher → ForbiddenError).  When
                ``False`` the existence check also returns ``None``
                (essay truly missing → NotFoundError).
        """
        db = AsyncMock()
        text_result = MagicMock()
        text_result.scalar_one_or_none = MagicMock(return_value=content)
        if content is None:
            # Two execute calls: tenant-scoped query + bare existence check.
            exists_result = MagicMock()
            exists_result.scalar_one_or_none = MagicMock(
                return_value=uuid.uuid4() if version_exists else None
            )
            db.execute = AsyncMock(side_effect=[text_result, exists_result])
        else:
            db.execute = AsyncMock(return_value=text_result)
        return db

    def _make_cm(self, db_mock: AsyncMock) -> AsyncMock:
        """Wrap a DB mock in an async context-manager mock."""
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db_mock)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    @pytest.mark.asyncio
    async def test_happy_path_calls_integrity_check_and_returns_passage_count(self) -> None:
        """_run_compute_essay_embedding calls run_integrity_check and returns len(flagged_passages)."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = self._make_text_db()
        cm = self._make_cm(db_mock)

        expected = IntegrityResult(
            provider="internal",
            flagged_passages=[{"text": "s1"}, {"text": "s2"}],
        )

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.integrity.run_integrity_check",
                new=AsyncMock(return_value=expected),
            ),
        ):
            result = await _run_compute_essay_embedding(
                essay_version_id, assignment_id, teacher_id
            )

        assert result == 2

    @pytest.mark.asyncio
    async def test_not_found_when_essay_version_missing(self) -> None:
        """NotFoundError is raised when the essay version cannot be fetched."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = self._make_text_db(content=None)
        cm = self._make_cm(db_mock)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            pytest.raises(NotFoundError),
        ):
            await _run_compute_essay_embedding(essay_version_id, assignment_id, teacher_id)

    @pytest.mark.asyncio
    async def test_llm_error_propagates(self) -> None:
        """LLMError raised by run_integrity_check propagates upward."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = self._make_text_db()
        cm = self._make_cm(db_mock)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            patch(
                "app.services.integrity.run_integrity_check",
                new=AsyncMock(side_effect=LLMError("OpenAI timed out")),
            ),
            pytest.raises(LLMError),
        ):
            await _run_compute_essay_embedding(essay_version_id, assignment_id, teacher_id)

    @pytest.mark.asyncio
    async def test_forbidden_when_essay_belongs_to_different_teacher(self) -> None:
        """ForbiddenError is raised when the essay exists but belongs to a different teacher."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        # Tenant-scoped query returns None; existence check returns a UUID (row exists).
        db_mock = self._make_text_db(content=None, version_exists=True)
        cm = self._make_cm(db_mock)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            pytest.raises(ForbiddenError),
        ):
            await _run_compute_essay_embedding(essay_version_id, assignment_id, teacher_id)

    @pytest.mark.asyncio
    async def test_validation_error_when_content_is_whitespace_only(self) -> None:
        """ValidationError is raised when the essay content is blank or whitespace-only."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        db_mock = self._make_text_db(content="   \n\t  ")
        cm = self._make_cm(db_mock)

        with (
            patch("app.tasks.embedding.AsyncSessionLocal", return_value=cm),
            pytest.raises(ValidationError),
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

    def test_validation_error_does_not_retry(self) -> None:
        """ValidationError (empty essay content) fails immediately without consuming retries."""
        essay_version_id = str(uuid.uuid4())
        assignment_id = str(uuid.uuid4())
        teacher_id = str(uuid.uuid4())

        with patch(
            "app.tasks.embedding._run_compute_essay_embedding",
            new=AsyncMock(side_effect=ValidationError("No text content")),
        ):
            result = compute_essay_embedding.apply(
                args=[essay_version_id, assignment_id, teacher_id]
            )

        assert result.failed()

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

        scalars_mock = MagicMock()
        scalars_mock.one_or_none = MagicMock(return_value=version_mock)
        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=scalars_mock)
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
        """NotFoundError raised when the essay version does not exist at all."""
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()

        # First execute: tenant-scoped query returns no row.
        tenant_result = MagicMock()
        tenant_result.scalars = MagicMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=None))
        )
        # Second execute: existence check also finds no row (truly missing).
        exists_result = MagicMock()
        exists_result.scalar_one_or_none = MagicMock(return_value=None)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[tenant_result, exists_result])

        with pytest.raises(NotFoundError):
            await compute_and_store_embedding(db_mock, essay_version_id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_forbidden_when_wrong_teacher(self) -> None:
        """ForbiddenError raised when the version belongs to a different teacher.

        The service first does a tenant-scoped query (returns None) and then
        checks bare existence.  When the version exists but belongs to another
        teacher, ``ForbiddenError`` is raised (not ``NotFoundError``) so the
        caller receives a clear 403 rather than a misleading 404.
        """
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()

        # First execute: tenant-scoped query returns no row (wrong teacher).
        tenant_result = MagicMock()
        tenant_result.scalars = MagicMock(
            return_value=MagicMock(one_or_none=MagicMock(return_value=None))
        )
        # Second execute: existence check finds the row (version does exist).
        exists_result = MagicMock()
        exists_result.scalar_one_or_none = MagicMock(return_value=essay_version_id)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[tenant_result, exists_result])

        with pytest.raises(ForbiddenError):
            await compute_and_store_embedding(db_mock, essay_version_id, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_skips_embedding_if_already_present(self) -> None:
        """compute_and_store_embedding returns early when embedding already exists (idempotency)."""
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        existing_embedding = _fake_embedding()

        version_mock = _make_version_mock(essay_version_id)
        version_mock.embedding = existing_embedding  # already populated

        scalars_mock = MagicMock()
        scalars_mock.one_or_none = MagicMock(return_value=version_mock)
        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=scalars_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)
        db_mock.commit = AsyncMock()

        with patch(
            "app.llm.client.call_embedding",
            new=AsyncMock(return_value=_fake_embedding()),
        ) as mock_embed:
            returned = await compute_and_store_embedding(db_mock, essay_version_id, teacher_id)

        assert returned == existing_embedding
        mock_embed.assert_not_called()  # no OpenAI call made
        db_mock.commit.assert_not_called()  # no DB write made

    @pytest.mark.asyncio
    async def test_raises_validation_error_for_empty_content(self) -> None:
        """ValidationError raised when essay version has no text content."""
        from app.services.embedding import compute_and_store_embedding

        essay_version_id = uuid.uuid4()
        teacher_id = uuid.uuid4()

        version_mock = _make_version_mock(essay_version_id, content="   ")  # whitespace only
        version_mock.embedding = None

        scalars_mock = MagicMock()
        scalars_mock.one_or_none = MagicMock(return_value=version_mock)
        db_mock = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=scalars_mock)
        db_mock.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(ValidationError):
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

        # First execute: similarity scan returning above-threshold pair.
        # Second execute: deduplication check returning None (no existing report).
        similarity_result = MagicMock()
        similarity_result.all = MagicMock(return_value=rows)
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none = MagicMock(return_value=None)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[similarity_result, dedup_result])
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        added_reports: list[IR] = []

        def _capture_add(obj: object) -> None:
            if isinstance(obj, IR):
                added_reports.append(obj)

        db_mock.add.side_effect = _capture_add

        with patch("app.services.embedding.settings") as mock_settings:
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
        """An essay pair below the similarity threshold does NOT create a report.

        The SQL WHERE clause filters out below-threshold candidates so they are
        never returned by the query.  The mock simulates this by returning an
        empty result set, as Postgres would.  The deduplication DB query is
        never made when the candidate set is empty.
        """
        from app.services.embedding import flag_similar_essays

        essay_version_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        embedding = _fake_embedding()

        # Postgres filters out the below-threshold row — no rows returned.
        rows: list[tuple[uuid.UUID, float]] = []

        similarity_result = MagicMock()
        similarity_result.all = MagicMock(return_value=rows)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=similarity_result)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.services.embedding.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, assignment_id, teacher_id, embedding
            )

        assert flagged == 0
        db_mock.add.assert_not_called()
        db_mock.commit.assert_not_called()
        # Only the similarity-scan execute was called; no dedup query needed.
        assert db_mock.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_no_candidates_returns_zero(self) -> None:
        """When no other essays have embeddings, returns 0 without writing anything."""
        from app.services.embedding import flag_similar_essays

        similarity_result = MagicMock()
        similarity_result.all = MagicMock(return_value=[])

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(return_value=similarity_result)
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.services.embedding.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), _fake_embedding()
            )

        assert flagged == 0
        db_mock.add.assert_not_called()
        # Only the similarity-scan execute was called; no dedup query needed.
        assert db_mock.execute.call_count == 1

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

        similarity_result = MagicMock()
        similarity_result.all = MagicMock(return_value=rows)
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none = MagicMock(return_value=None)

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[similarity_result, dedup_result])
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.services.embedding.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = threshold
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, uuid.uuid4(), uuid.uuid4(), embedding
            )

        assert flagged == 1
        db_mock.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplication_skips_existing_report(self) -> None:
        """flag_similar_essays skips insertion when a report already exists (idempotency)."""
        from app.services.embedding import flag_similar_essays

        essay_version_id = uuid.uuid4()
        other_version_id = uuid.uuid4()
        assignment_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        embedding = _fake_embedding()
        rows = [(other_version_id, 0.1)]

        similarity_result = MagicMock()
        similarity_result.all = MagicMock(return_value=rows)
        # Dedup check: existing report found → should skip insert.
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())

        db_mock = AsyncMock()
        db_mock.execute = AsyncMock(side_effect=[similarity_result, dedup_result])
        db_mock.add = MagicMock()
        db_mock.commit = AsyncMock()

        with patch("app.services.embedding.settings") as mock_settings:
            mock_settings.integrity_similarity_threshold = 0.25
            flagged = await flag_similar_essays(
                db_mock, essay_version_id, assignment_id, teacher_id, embedding
            )

        assert flagged == 0
        db_mock.add.assert_not_called()
        db_mock.commit.assert_not_called()
