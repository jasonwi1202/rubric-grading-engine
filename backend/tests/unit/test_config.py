"""Unit tests for app.config.Settings.

These tests cover all validators and derived helpers on the Settings class.
No database, network, or file I/O is performed — all settings are constructed
directly from keyword arguments, which pydantic-settings supports for testing.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE: dict[str, str] = {
    "database_url": "postgresql+asyncpg://user:pass@localhost:5432/testdb",
    "redis_url": "redis://localhost:6379/0",
    "jwt_secret_key": "a" * 32,
    "openai_api_key": "dummy_openai_api_key",
    "s3_bucket_name": "test-bucket",
    "s3_region": "us-east-1",
    "aws_access_key_id": "dummy_aws_access_key_id",
    "aws_secret_access_key": "dummy_aws_secret_access_key",
    "cors_origins": "http://localhost:3000",
}


def _make(**overrides: object) -> Settings:
    """Build a Settings instance from _BASE, applying keyword overrides.

    Passes _env_file=None so that the local .env file does not interfere with
    tests that assert on defaults or required-field validation.
    """
    return Settings(_env_file=None, **{**_BASE, **overrides})  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Required field validation
# ---------------------------------------------------------------------------


class TestRequiredFields:
    def test_missing_database_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        kwargs = {k: v for k, v in _BASE.items() if k != "database_url"}
        with pytest.raises(ValidationError, match="database_url"):
            Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]

    def test_missing_redis_url_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        kwargs = {k: v for k, v in _BASE.items() if k != "redis_url"}
        with pytest.raises(ValidationError, match="redis_url"):
            Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]

    def test_missing_jwt_secret_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        kwargs = {k: v for k, v in _BASE.items() if k != "jwt_secret_key"}
        with pytest.raises(ValidationError, match="jwt_secret_key"):
            Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]

    def test_missing_cors_origins_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        kwargs = {k: v for k, v in _BASE.items() if k != "cors_origins"}
        with pytest.raises(ValidationError, match="cors_origins"):
            Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# JWT secret key validator
# ---------------------------------------------------------------------------


class TestJwtSecretKeyValidator:
    def test_accepts_32_char_key(self) -> None:
        s = _make(jwt_secret_key="x" * 32)
        assert len(s.jwt_secret_key) == 32

    def test_accepts_key_longer_than_32_chars(self) -> None:
        s = _make(jwt_secret_key="x" * 64)
        assert len(s.jwt_secret_key) == 64

    def test_rejects_key_shorter_than_32_chars(self) -> None:
        with pytest.raises(ValidationError, match="JWT_SECRET_KEY must be at least 32"):
            _make(jwt_secret_key="short")

    def test_rejects_31_char_key(self) -> None:
        with pytest.raises(ValidationError):
            _make(jwt_secret_key="a" * 31)


# ---------------------------------------------------------------------------
# Environment validator
# ---------------------------------------------------------------------------


class TestEnvironmentValidator:
    @pytest.mark.parametrize("env", ["development", "staging", "production"])
    def test_accepts_valid_environment(self, env: str) -> None:
        overrides: dict[str, object] = {"environment": env}
        if env in {"staging", "production"}:
            overrides.update(
                {
                    "trust_proxy_headers": True,
                    "frontend_url": "https://app.example.com",
                }
            )
        s = _make(**overrides)
        assert s.environment == env

    def test_rejects_invalid_environment(self) -> None:
        with pytest.raises(ValidationError, match="ENVIRONMENT must be one of"):
            _make(environment="local")


# ---------------------------------------------------------------------------
# Celery defaults
# ---------------------------------------------------------------------------


class TestCeleryDefaults:
    def test_celery_broker_defaults_to_redis_url(self) -> None:
        s = _make()
        assert s.celery_broker_url == _BASE["redis_url"]

    def test_celery_result_backend_defaults_to_redis_url(self) -> None:
        s = _make()
        assert s.celery_result_backend == _BASE["redis_url"]

    def test_explicit_celery_broker_not_overridden(self) -> None:
        custom = "redis://broker:6379/1"
        s = _make(celery_broker_url=custom)
        assert s.celery_broker_url == custom

    def test_explicit_celery_result_backend_not_overridden(self) -> None:
        custom = "redis://backend:6379/2"
        s = _make(celery_result_backend=custom)
        assert s.celery_result_backend == custom


# ---------------------------------------------------------------------------
# Integrity API key validator
# ---------------------------------------------------------------------------


class TestIntegrityApiKeyValidator:
    def test_internal_provider_no_key_ok(self) -> None:
        s = _make(integrity_provider="internal", integrity_api_key=None)
        assert s.integrity_provider == "internal"

    def test_third_party_provider_without_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="INTEGRITY_API_KEY is required"):
            _make(integrity_provider="originality_ai", integrity_api_key=None)

    def test_third_party_provider_with_key_ok(self) -> None:
        s = _make(integrity_provider="originality_ai", integrity_api_key="api-key-123")
        assert s.integrity_api_key == "api-key-123"

    def test_unknown_provider_no_key_ok(self) -> None:
        """Unknown provider values fall back to InternalProvider — no API key required."""
        s = _make(integrity_provider="typo_provider", integrity_api_key=None)
        assert s.integrity_provider == "typo_provider"


# ---------------------------------------------------------------------------
# cors_origins_list helper
# ---------------------------------------------------------------------------


class TestCorsOriginsList:
    def test_single_origin(self) -> None:
        s = _make(cors_origins="http://localhost:3000")
        assert s.cors_origins_list == ["http://localhost:3000"]

    def test_multiple_origins(self) -> None:
        s = _make(cors_origins="http://localhost:3000,https://app.example.com")
        assert s.cors_origins_list == [
            "http://localhost:3000",
            "https://app.example.com",
        ]

    def test_strips_whitespace(self) -> None:
        s = _make(cors_origins="http://localhost:3000 , https://app.example.com ")
        assert s.cors_origins_list == [
            "http://localhost:3000",
            "https://app.example.com",
        ]

    def test_ignores_empty_segments(self) -> None:
        s = _make(cors_origins="http://localhost:3000,,https://app.example.com")
        assert s.cors_origins_list == [
            "http://localhost:3000",
            "https://app.example.com",
        ]


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_database_pool_size_default(self) -> None:
        assert _make().database_pool_size == 10

    def test_database_max_overflow_default(self) -> None:
        assert _make().database_max_overflow == 20

    def test_access_token_expire_minutes_default(self) -> None:
        assert _make().access_token_expire_minutes == 15

    def test_refresh_token_expire_days_default(self) -> None:
        assert _make().refresh_token_expire_days == 7

    def test_environment_default(self) -> None:
        assert _make().environment == "development"

    def test_s3_endpoint_url_default_is_none(self) -> None:
        assert _make().s3_endpoint_url is None


# ---------------------------------------------------------------------------
# Production/staging security guardrails
# ---------------------------------------------------------------------------


class TestProductionSecurityGuardrails:
    def test_staging_requires_trusted_proxy_headers(self) -> None:
        with pytest.raises(ValidationError, match="TRUST_PROXY_HEADERS must be true"):
            _make(
                environment="staging",
                trust_proxy_headers=False,
                frontend_url="https://app.example.com",
            )

    def test_production_rejects_unverified_login_bypass(self) -> None:
        with pytest.raises(
            ValidationError,
            match="ALLOW_UNVERIFIED_LOGIN_IN_TEST must be false",
        ):
            _make(
                environment="production",
                trust_proxy_headers=True,
                allow_unverified_login_in_test=True,
                frontend_url="https://app.example.com",
            )

    def test_production_requires_https_frontend_url(self) -> None:
        with pytest.raises(ValidationError, match="FRONTEND_URL must use https://"):
            _make(
                environment="production",
                trust_proxy_headers=True,
                frontend_url="http://app.example.com",
            )

    def test_staging_accepts_secure_configuration(self) -> None:
        s = _make(
            environment="staging",
            trust_proxy_headers=True,
            frontend_url="https://staging.example.com",
        )
        assert s.environment == "staging"

    def test_production_rejects_llm_fake_mode(self) -> None:
        with pytest.raises(
            ValidationError,
            match="LLM_FAKE_MODE must be false",
        ):
            _make(
                environment="production",
                trust_proxy_headers=True,
                llm_fake_mode=True,
                frontend_url="https://app.example.com",
            )

    def test_staging_rejects_llm_fake_mode(self) -> None:
        with pytest.raises(
            ValidationError,
            match="LLM_FAKE_MODE must be false",
        ):
            _make(
                environment="staging",
                trust_proxy_headers=True,
                llm_fake_mode=True,
                frontend_url="https://staging.example.com",
            )

    def test_production_rejects_export_task_force_fail(self) -> None:
        with pytest.raises(
            ValidationError,
            match="EXPORT_TASK_FORCE_FAIL must be false",
        ):
            _make(
                environment="production",
                trust_proxy_headers=True,
                export_task_force_fail=True,
                frontend_url="https://app.example.com",
            )

    def test_staging_rejects_export_task_force_fail(self) -> None:
        with pytest.raises(
            ValidationError,
            match="EXPORT_TASK_FORCE_FAIL must be false",
        ):
            _make(
                environment="staging",
                trust_proxy_headers=True,
                export_task_force_fail=True,
                frontend_url="https://staging.example.com",
            )

    def test_development_allows_llm_fake_mode(self) -> None:
        s = _make(llm_fake_mode=True)
        assert s.llm_fake_mode is True

    def test_development_allows_export_task_force_fail(self) -> None:
        s = _make(export_task_force_fail=True)
        assert s.export_task_force_fail is True

    def test_production_rejects_short_lived_token_ttl_seconds(self) -> None:
        with pytest.raises(
            ValidationError,
            match="SHORT_LIVED_TOKEN_TTL_SECONDS must not be set",
        ):
            _make(
                environment="production",
                trust_proxy_headers=True,
                frontend_url="https://app.example.com",
                short_lived_token_ttl_seconds=3,
            )

    def test_staging_rejects_short_lived_token_ttl_seconds(self) -> None:
        with pytest.raises(
            ValidationError,
            match="SHORT_LIVED_TOKEN_TTL_SECONDS must not be set",
        ):
            _make(
                environment="staging",
                trust_proxy_headers=True,
                frontend_url="https://staging.example.com",
                short_lived_token_ttl_seconds=3,
            )

    def test_development_allows_short_lived_token_ttl_seconds(self) -> None:
        s = _make(short_lived_token_ttl_seconds=3)
        assert s.short_lived_token_ttl_seconds == 3


# ---------------------------------------------------------------------------
# short_lived_token_ttl_seconds validator
# ---------------------------------------------------------------------------


class TestShortLivedTokenTtlSeconds:
    def test_default_is_none(self) -> None:
        s = _make()
        assert s.short_lived_token_ttl_seconds is None

    def test_accepts_positive_integer(self) -> None:
        s = _make(short_lived_token_ttl_seconds=5)
        assert s.short_lived_token_ttl_seconds == 5

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError, match="must be at least 1"):
            _make(short_lived_token_ttl_seconds=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValidationError, match="must be at least 1"):
            _make(short_lived_token_ttl_seconds=-1)
