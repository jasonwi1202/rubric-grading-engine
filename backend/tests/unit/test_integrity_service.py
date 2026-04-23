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

from app.services.integrity import (
    InternalProvider,
    IntegrityProviderUnavailableError,
    IntegrityResult,
    OriginalityAiProvider,
    get_provider,
    run_integrity_check,
)
from app.models.integrity_report import IntegrityReport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _make_db() -> AsyncMock:
    """Minimal async DB session mock."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
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
            mock_settings.integrity_api_key = "test-originality-api-key"
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
            mock_settings.integrity_api_key = "test-originality-api-key"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="test-originality-api-key")
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
            provider = OriginalityAiProvider(api_key="test-originality-api-key")
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
            provider = OriginalityAiProvider(api_key="test-originality-api-key")
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
        """OriginalityAiProvider writes an IntegrityReport record and commits."""
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
            mock_settings.integrity_api_key = "test-originality-api-key"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="test-originality-api-key")
            await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Essay text here.",
            )

        # Verify an IntegrityReport was added and db.commit was called.
        db.add.assert_called_once()
        added_report = db.add.call_args[0][0]
        assert isinstance(added_report, IntegrityReport)
        assert added_report.provider == "originality_ai"
        assert added_report.essay_version_id == essay_version_id
        assert added_report.teacher_id == teacher_id
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
            mock_settings.integrity_api_key = "test-originality-api-key"
            mock_settings.integrity_ai_likelihood_threshold = 0.7

            provider = OriginalityAiProvider(api_key="test-originality-api-key")
            result = await provider.check(
                db=db,
                essay_version_id=essay_version_id,
                assignment_id=assignment_id,
                teacher_id=teacher_id,
                essay_text="Some text.",
            )

        assert result.ai_likelihood == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# run_integrity_check — fallback behaviour
# ---------------------------------------------------------------------------


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
        ):
            with pytest.raises(IntegrityProviderUnavailableError):
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
