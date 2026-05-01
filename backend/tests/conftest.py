"""Root pytest configuration.

Sets minimum required environment variables before any application module is
imported.  This ensures module-level singletons (settings, engine) are
initialised with valid values in all unit tests, without needing a real
database or Redis instance.

Tests that need to vary these values should use ``monkeypatch.setenv`` /
``monkeypatch.delenv`` within the test.
"""

import os

# Set defaults only — do not overwrite values already provided by the caller
# (e.g. CI may inject real credentials for integration tests).
_DEFAULTS: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://test-db-user:test-db-password@localhost:5432/testdb",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET_KEY": "a" * 32,
    "EMAIL_VERIFICATION_HMAC_SECRET": "b" * 32,
    "UNSUBSCRIBE_HMAC_SECRET": "c" * 32,
    "OPENAI_API_KEY": "test_openai_api_key",
    "S3_BUCKET_NAME": "test-bucket",
    "S3_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test_aws_access_key_id",
    "AWS_SECRET_ACCESS_KEY": "test_aws_secret_access_key",
    "CORS_ORIGINS": "http://localhost:3000",
}

for _key, _value in _DEFAULTS.items():
    os.environ.setdefault(_key, _value)
