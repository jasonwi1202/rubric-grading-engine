"""Application configuration.

All settings are loaded from environment variables (or a .env file) via
``pydantic-settings``.  Import the singleton ``settings`` object wherever
configuration values are needed::

    from app.config import settings

    db_url = settings.database_url

Never read ``os.environ`` directly in application code.
"""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # -------------------------------------------------------------------------
    # Redis
    # -------------------------------------------------------------------------
    redis_url: str
    redis_grading_ttl_seconds: int = 3600

    # -------------------------------------------------------------------------
    # Celery
    # -------------------------------------------------------------------------
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_worker_concurrency: int = 4
    celery_result_expires_seconds: int = 3600
    grading_task_soft_time_limit: int = 120
    grading_task_hard_time_limit: int = 180

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # -------------------------------------------------------------------------
    # Email verification
    # -------------------------------------------------------------------------
    # Secret used to HMAC-sign verification tokens.  Must be at least 32 chars.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    email_verification_hmac_secret: str
    # TTL in seconds for verification tokens stored in Redis (default: 24 h).
    verification_token_ttl_seconds: int = 86400
    # Base URL of the frontend — used to build verification links in emails.
    frontend_url: str = "http://localhost:3000"
    # "From" address for verification emails.  Optional — if not set the task
    # will use the same address as contact_email, or skip sending if both are
    # absent.
    verification_email_from: str | None = None

    # -------------------------------------------------------------------------
    # LLM / OpenAI
    # -------------------------------------------------------------------------
    openai_api_key: str
    openai_grading_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    llm_request_timeout_seconds: int = 60
    llm_max_retries: int = 3
    grading_prompt_version: str = "v1"

    # -------------------------------------------------------------------------
    # File Storage (S3 / MinIO)
    # -------------------------------------------------------------------------
    s3_bucket_name: str
    s3_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_endpoint_url: str | None = None
    s3_presigned_url_expire_seconds: int = 3600

    # -------------------------------------------------------------------------
    # Integrity Checking
    # -------------------------------------------------------------------------
    integrity_provider: str = "internal"
    integrity_api_key: str | None = None
    integrity_similarity_threshold: float = 0.25
    integrity_ai_likelihood_threshold: float = 0.7

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str
    max_essay_file_size_mb: int = 10
    max_batch_size: int = 100
    # Email address that receives school/district inquiry notifications.
    # Optional — if not set, the notification email task is skipped.
    contact_email: str | None = None
    # SMTP server used for sending notification emails.
    smtp_host: str = "localhost"
    smtp_port: int = 25
    # Timeout in seconds for SMTP connections; prevents hung Celery workers.
    smtp_timeout: int = 10

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------

    @field_validator("jwt_secret_key")
    @classmethod
    def jwt_secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("email_verification_hmac_secret")
    @classmethod
    def email_verification_hmac_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("EMAIL_VERIFICATION_HMAC_SECRET must be at least 32 characters")
        return v

    @field_validator("environment")
    @classmethod
    def environment_allowed_values(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {sorted(allowed)}")
        return v

    @model_validator(mode="after")
    def celery_defaults_from_redis(self) -> "Settings":
        """Default Celery broker/backend to REDIS_URL when not explicitly set."""
        if not self.celery_broker_url:
            self.celery_broker_url = self.redis_url
        if not self.celery_result_backend:
            self.celery_result_backend = self.redis_url
        return self

    @model_validator(mode="after")
    def integrity_api_key_required(self) -> "Settings":
        """Require INTEGRITY_API_KEY when provider is not 'internal'."""
        if self.integrity_provider != "internal" and not self.integrity_api_key:
            raise ValueError(
                "INTEGRITY_API_KEY is required when INTEGRITY_PROVIDER is not 'internal'"
            )
        return self

    # -------------------------------------------------------------------------
    # Derived helpers
    # -------------------------------------------------------------------------

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS_ORIGINS as a parsed list of stripped origin strings."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings populates fields from env vars, not constructor args
