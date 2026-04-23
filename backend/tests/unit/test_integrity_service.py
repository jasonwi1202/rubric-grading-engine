"""Unit tests for app/services/integrity.py (M4.5).

Coverage:
- Provider selection via ``get_provider()`` based on ``settings.integrity_provider``
- Fallback to ``InternalProvider`` when third-party provider raises
  ``IntegrityProviderUnavailableError``
- ``OriginalityAiProvider.check`` — happy path (mocked HTTP)
- ``OriginalityAiProvider.check`` — network error raises
  ``IntegrityProviderUnavailableError``
- ``InternalProvider.check`` — delegates to embedding service functions
- ``run_integrity_check`` — fallback on network error
- ``run_integrity_check`` — no fallback when InternalProvider is already active

No real HTTP calls, no real database calls, no real OpenAI calls.
No student PII in any fixture.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.integrity_report import IntegrityReport
from app.services.integrity import (
    IntegrityProviderUnavailableError,
    IntegrityResult,
    InternalProvider,
    OriginalityAiProvider,
    get_provider,
    run_integrity_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_db() -> AsyncMock:
    """Minimal async DB session mock (tenant check passes, no existing report)."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    # First call: tenant-scoped ownership check → passes (returns a UUID).
    ownership_result = MagicMock()
    ownership_result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    # Second call: idempotency check → no existing report (returns None).
    idempotency_result = MagicMock()
    idempotency_result.scalar_one_or_none = MagicMock(return_value=None)
    # Third call: atomic pg_insert returning → row was inserted (returns a UUID).
    insert_result = MagicMock()
    insert_result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
    db.execute = AsyncMock(side_effect=[ownership_result, idempotency_result, insert_result])
    return db


def _make_db_tenant_miss(*, exists: bool) -> AsyncMock:
    """DB mock where the tenant-scoped ownership query returns no row.

    Args:
        exists: When True the essay version exists but belongs to a different
            teacher (triggers ForbiddenError).  When False the essay version
            does not exist at all (triggers NotFoundError).
    """
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    # First execute call = tenant-scoped ownership check → no row.
    ownership_result = MagicMock()
    ownership_result.scalar_one_or_none = MagicMock(return_value=None)

    # Second execute call = bare existence check.
    existence_result = MagicMock()
    existence_result.scalar_one_or_none = MagicMock(
        return_value=uuid.uuid4() if exists else None
    )

    db.execute = AsyncMock(side_effect=[ownership_result, existence_result])
    return db


# ---------------------------------------------------------------------------
# get_provider — provider selection
# ---------------------------------------------------------------------------


class TestGetProvider:
    def test_default_returns_internal_provider(self) -> None:
        with patch("app.services.integrity.settings") as mock_settings:
            mock_settings.integrity_provider = "internal"
            mock_settings.integrity_api_key = None
            provider = get_provider()
        assert isinstance(provider, InternalProvider)

    def test_originality_ai_returns_originality_provider(self) -> None:
        with patch("app.services.integrity.settings") as mock_settings:
            mock_settings.integrity_provider = "originality_ai"
            mock_settings.integrity_api_key = "fake-key-for-testing"
            provider = get_provider()
        assert isinstance(provider, OriginalityAiProvider)

    def test_unknown_provider_falls_back_to_internal(self) -> None:
        with patch("app.services.integrity.settings") as mock_settings:
            mock_settings.integrity_provider = "nonexistent_provider"
            mock_settings.integrity_api_key = None
            provider = get_provider()
        assert isinstance(provider, InternalProvider)

    def test_case_insensitive_provider_name(self) -> None:
        with patch("app.services.integrity.settings") as mock_settings:
            mock_settings.integrity_provider = "ORIGINALITY_AI"
            mock_settings.integrity_api_key = "test-key"
            provider = get_provider()
        assert isinstance(provider, OriginalityAiProvider)

    def test_none_provider_falls_back_to_internal(self) -> None:
        with patch("app.services.integrity.settings") as mock_settings:
            mock_settings.integrity_provider = None
            mock_settings.integrity_api_key = None
            provider = get_provider()
        assert isinstance(provider, InternalProvider)


# ---------------------------------------------------------------------------
# InternalProvider
# ---------------------------------------------------------------------------


class TestInternalProvider:
    @pytest.mark.asyncio
    async def test_delegates_to_embedding_service(self) -> None:
        """InternalProvider calls compute_and_store_embedding + flag_similar_essays."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        fake_embedding = [0.1] * 1536

        db = _make_db()
        # Simulate DB returning no existing report (no similarity found).
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result_mock)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.embedding.compute_and_store_embedding",
                new=AsyncMock(return_value=fake_embedding),
            ),
            patch(
                "app.services.embedding.flag_similar_essays",
                new=AsyncMock(return_value=0),
            ),
            patch("app.services.integrity.AsyncSessionLocal", return_value=cm),
        ):
            provider = InternalProvider()
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Sample essay content.",
            )

        assert result.provider == "internal"
        assert result.ai_likelihood is None
        assert result.similarity_score is None

    @pytest.mark.asyncio
    async def test_returns_similarity_score_when_pairs_flagged(self) -> None:
        """When flag_similar_essays returns > 0, highest similarity is queried."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        fake_embedding = [0.2] * 1536

        db = _make_db()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=0.85)
        db.execute = AsyncMock(return_value=result_mock)

        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.embedding.compute_and_store_embedding",
                new=AsyncMock(return_value=fake_embedding),
            ),
            patch(
                "app.services.embedding.flag_similar_essays",
                new=AsyncMock(return_value=1),
            ),
            patch("app.services.integrity.AsyncSessionLocal", return_value=cm),
        ):
            provider = InternalProvider()
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Sample essay content.",
            )

        assert result.similarity_score == 0.85


# ---------------------------------------------------------------------------
# OriginalityAiProvider
# ---------------------------------------------------------------------------


class TestOriginalityAiProvider:
    @pytest.mark.asyncio
    async def test_happy_path_returns_result(self) -> None:
        """Successful API call returns IntegrityResult with ai_likelihood."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        api_response = {
            "score": {"ai": 0.82, "human": 0.18},
            "sentences": [
                {"sentence": "This looks generated.", "generated_prob": 0.95},
                {"sentence": "This is fine.", "generated_prob": 0.1},
            ],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Sample essay text.",
            )

        assert result.provider == "originality_ai"
        assert result.ai_likelihood == pytest.approx(0.82)
        # Only the high-probability sentence should be in flagged_passages
        assert len(result.flagged_passages) == 1
        assert result.flagged_passages[0]["text"] == "This looks generated."

    @pytest.mark.asyncio
    async def test_network_error_raises_provider_unavailable(self) -> None:
        """TransportError from httpx raises IntegrityProviderUnavailableError."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.TransportError("Connection refused")
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample essay text.",
                )

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_unavailable(self) -> None:
        """TimeoutException from httpx raises IntegrityProviderUnavailableError."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample essay text.",
                )

    @pytest.mark.asyncio
    async def test_writes_integrity_report_to_db(self) -> None:
        """OriginalityAiProvider inserts an IntegrityReport via pg_insert and commits."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        api_response: dict[str, object] = {
            "score": {"ai": 0.5, "human": 0.5},
            "sentences": [],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Essay text here.",
            )

        # Verify db.execute was called for ownership, idempotency and atomic insert,
        # and that the transaction was committed.
        assert db.execute.call_count == 3
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_top_level_ai_likelihood_fallback(self) -> None:
        """If 'score.ai' is absent, top-level 'ai_likelihood' is used instead."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        # API response with no nested score dict; uses top-level ai_likelihood.
        api_response = {
            "ai_likelihood": 0.65,
            "sentences": [],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        assert result.ai_likelihood == pytest.approx(0.65)

    @pytest.mark.asyncio
    async def test_unparseable_score_ai_logs_warning(self) -> None:
        """When 'score.ai' is not parseable as float, a warning is logged and ai_likelihood stays None."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        api_response: dict[str, object] = {
            "score": {"ai": "not-a-number"},
            "sentences": [],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        assert result.ai_likelihood is None

    @pytest.mark.asyncio
    async def test_unparseable_top_level_ai_likelihood_logs_warning(self) -> None:
        """When top-level 'ai_likelihood' is not parseable, warning logged, value stays None."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        api_response: dict[str, object] = {
            "ai_likelihood": {"nested": "invalid"},
            "sentences": [],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        assert result.ai_likelihood is None

    @pytest.mark.asyncio
    async def test_non_dict_sentence_is_skipped(self) -> None:
        """Non-dict items in 'sentences' are skipped without error."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()

        api_response: dict[str, object] = {
            "score": {"ai": 0.5},
            # Mix of valid and invalid sentence types.
            "sentences": ["plain string", None, {"sentence": "Real sentence.", "generated_prob": 0.95}],
        }

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        # Only the valid dict sentence above threshold should be flagged.
        assert len(result.flagged_passages) == 1
        assert result.flagged_passages[0]["text"] == "Real sentence."

    @pytest.mark.asyncio
    async def test_raises_not_found_when_essay_version_missing(self) -> None:
        """NotFoundError is raised when the essay version does not exist."""
        from app.exceptions import NotFoundError

        db = _make_db_tenant_miss(exists=False)
        provider = OriginalityAiProvider(api_key="fake-key-for-testing")

        with pytest.raises(NotFoundError):
            await provider.check(
                db=db,
                essay_version_id=_make_uuid(),
                assignment_id=_make_uuid(),
                teacher_id=_make_uuid(),
                essay_text="Some text.",
            )

    @pytest.mark.asyncio
    async def test_raises_forbidden_when_essay_belongs_to_other_teacher(self) -> None:
        """ForbiddenError is raised when the essay exists but belongs to a different teacher."""
        from app.exceptions import ForbiddenError

        db = _make_db_tenant_miss(exists=True)
        provider = OriginalityAiProvider(api_key="fake-key-for-testing")

        with pytest.raises(ForbiddenError):
            await provider.check(
                db=db,
                essay_version_id=_make_uuid(),
                assignment_id=_make_uuid(),
                teacher_id=_make_uuid(),
                essay_text="Some text.",
            )

    @pytest.mark.asyncio
    async def test_server_error_raises_provider_unavailable(self) -> None:
        """HTTP 5xx from Originality.ai raises IntegrityProviderUnavailableError."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "Service Unavailable", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample text.",
                )

    @pytest.mark.asyncio
    async def test_rate_limit_raises_provider_unavailable(self) -> None:
        """HTTP 429 from Originality.ai raises IntegrityProviderUnavailableError."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 429
        http_error = httpx.HTTPStatusError(
            "Too Many Requests", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample text.",
                )

    @pytest.mark.asyncio
    async def test_non_retryable_4xx_propagates(self) -> None:
        """HTTP 401 from Originality.ai propagates as HTTPStatusError (not wrapped)."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError(
            "Unauthorized", request=mock_request, response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(httpx.HTTPStatusError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample text.",
                )

    @pytest.mark.asyncio
    async def test_rollback_on_commit_failure(self) -> None:
        """db.rollback() is called and ConflictError is raised on commit IntegrityError."""
        from sqlalchemy.exc import IntegrityError as SAIntegrityError

        from app.exceptions import ConflictError

        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = _make_db()
        db.commit = AsyncMock(side_effect=SAIntegrityError(None, None, Exception("unique")))

        api_response: dict[str, object] = {"score": {"ai": 0.5}, "sentences": []}

        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(ConflictError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Some text.",
                )

        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing_report_without_api_call(self) -> None:
        """When an IntegrityReport already exists, the API is not called again."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        # First call: ownership check → passes.
        ownership_result = MagicMock()
        ownership_result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())

        # Second call: idempotency check → existing report found.
        existing_report = MagicMock()
        existing_report.ai_likelihood = 0.77
        existing_report.similarity_score = None
        existing_report.flagged_passages = [{"text": "cached passage", "ai_probability": 0.9}]
        idempotency_result = MagicMock()
        idempotency_result.scalar_one_or_none = MagicMock(return_value=existing_report)

        db.execute = AsyncMock(side_effect=[ownership_result, idempotency_result])

        mock_client = AsyncMock()
        mock_client.post = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        # API must not have been called.
        mock_client.post.assert_not_called()
        # Cached values are returned.
        assert result.provider == "originality_ai"
        assert result.ai_likelihood == pytest.approx(0.77)
        assert len(result.flagged_passages) == 1
        assert result.flagged_passages[0]["text"] == "cached passage"

    @pytest.mark.asyncio
    async def test_invalid_json_response_raises_provider_unavailable(self) -> None:
        """A JSON decode error from response.json() raises IntegrityProviderUnavailableError."""
        import json as _json

        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(side_effect=_json.JSONDecodeError("No JSON content", "", 0))

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample text.",
                )

    @pytest.mark.asyncio
    async def test_non_dict_json_response_raises_provider_unavailable(self) -> None:
        """A non-dict JSON response (e.g. a list) raises IntegrityProviderUnavailableError."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        # API returns a JSON array instead of an object.
        mock_response.json = MagicMock(return_value=[{"score": 0.5}])

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            with pytest.raises(IntegrityProviderUnavailableError):
                await provider.check(
                    db=db,
                    essay_version_id=essay_version_id,
                    assignment_id=assignment_id,
                    teacher_id=teacher_id,
                    essay_text="Sample text.",
                )

    @pytest.mark.asyncio
    async def test_race_condition_concurrent_insert_returns_existing_report(self) -> None:
        """When pg_insert ON CONFLICT DO NOTHING skips the row, the existing report is returned."""
        from app.exceptions import ConflictError as _ConflictError  # noqa: F401

        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()

        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        # Call 1: ownership check → passes.
        ownership_result = MagicMock()
        ownership_result.scalar_one_or_none = MagicMock(return_value=uuid.uuid4())
        # Call 2: idempotency pre-check → no existing report (proceed to API call).
        idempotency_result = MagicMock()
        idempotency_result.scalar_one_or_none = MagicMock(return_value=None)
        # Call 3: pg_insert returning → None (ON CONFLICT DO NOTHING was triggered).
        insert_result = MagicMock()
        insert_result.scalar_one_or_none = MagicMock(return_value=None)
        # Call 4: re-select → returns the existing report from the concurrent worker.
        existing_report = MagicMock(spec=IntegrityReport)
        existing_report.ai_likelihood = 0.88
        existing_report.similarity_score = None
        existing_report.flagged_passages = [{"text": "concurrent passage", "ai_probability": 0.9}]
        re_select_result = MagicMock()
        re_select_result.scalar_one_or_none = MagicMock(return_value=existing_report)

        db.execute = AsyncMock(
            side_effect=[ownership_result, idempotency_result, insert_result, re_select_result]
        )

        api_response: dict[str, object] = {"score": {"ai": 0.5}, "sentences": []}
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value=api_response)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.integrity.settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.integrity_api_key = "fake-key-for-testing"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="fake-key-for-testing")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        # Should return the existing report from the concurrent worker.
        assert result.provider == "originality_ai"
        assert result.ai_likelihood == pytest.approx(0.88)
        assert len(result.flagged_passages) == 1
        assert result.flagged_passages[0]["text"] == "concurrent passage"


class TestRunIntegrityCheck:
    @pytest.mark.asyncio
    async def test_uses_provided_provider(self) -> None:
        """run_integrity_check delegates to the explicitly supplied provider."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        expected_result = IntegrityResult(provider="internal")
        mock_provider = AsyncMock(spec=InternalProvider)
        mock_provider.check = AsyncMock(return_value=expected_result)

        result = await run_integrity_check(
            db=db,
            essay_version_id=essay_version_id,
            assignment_id=assignment_id,
            teacher_id=teacher_id,
            essay_text="Test essay.",
            provider=mock_provider,
        )

        assert result is expected_result
        mock_provider.check.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_internal_on_provider_unavailable(self) -> None:
        """When third-party provider is unavailable, internal provider is used."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        fallback_result = IntegrityResult(provider="internal")

        third_party_provider = AsyncMock(spec=OriginalityAiProvider)
        third_party_provider.check = AsyncMock(
            side_effect=IntegrityProviderUnavailableError("Originality.ai down")
        )

        # Patch InternalProvider.check so the fallback instance returns our result.
        with patch.object(InternalProvider, "check", new=AsyncMock(return_value=fallback_result)):
            result = await run_integrity_check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Test essay.",
                provider=third_party_provider,
            )

        assert result is fallback_result

    @pytest.mark.asyncio
    async def test_no_fallback_when_internal_raises_unavailable(self) -> None:
        """IntegrityProviderUnavailableError from InternalProvider is re-raised."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        internal_provider = InternalProvider()

        with patch.object(
            internal_provider,
            "check",
            side_effect=IntegrityProviderUnavailableError("Should not happen"),
        ), pytest.raises(IntegrityProviderUnavailableError):
            await run_integrity_check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Test essay.",
                provider=internal_provider,
            )

    @pytest.mark.asyncio
    async def test_uses_get_provider_when_no_provider_arg(self) -> None:
        """When no provider argument is supplied, get_provider() is used."""
        essay_version_id = _make_uuid()
        assignment_id = _make_uuid()
        teacher_id = _make_uuid()
        db = _make_db()

        expected_result = IntegrityResult(provider="internal")
        mock_provider = AsyncMock(spec=InternalProvider)
        mock_provider.check = AsyncMock(return_value=expected_result)

        with patch("app.services.integrity.get_provider", return_value=mock_provider):
            result = await run_integrity_check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Test essay.",
            )

        assert result is expected_result
        mock_provider.check.assert_called_once()
