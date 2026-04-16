"""Integration tests for app.storage.s3.

These tests spin up a real MinIO container (via testcontainers), upload a
file using :func:`~app.storage.s3.upload_file`, generate a pre-signed URL
with :func:`~app.storage.s3.generate_presigned_url`, and verify that the
URL is actually accessible via an HTTP GET request.

Requirements:
* Docker must be available in the test environment.
* The tests are marked ``integration`` and are skipped when Docker is not
  reachable (the container will fail to start and the fixture raises a skip).

The MinIO container is started once per test *session* (session-scoped
fixture) so that multiple test functions share the same container, keeping
CI times low.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_container_is_ready

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MINIO_IMAGE = "minio/minio:RELEASE.2024-01-16T16-07-38Z"
_MINIO_PORT = 9000
_ACCESS_KEY = "minioadmin"
_SECRET_KEY = "minioadmin"
_BUCKET = "test-integration-bucket"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def minio_endpoint() -> Generator[str, None, None]:
    """Start a MinIO container and yield its ``http://host:port`` endpoint.

    The container is stopped automatically when the test session ends.
    If Docker is not available, the test session is skipped with a clear
    message rather than failing with an obscure Docker error.
    """
    try:
        container = (
            DockerContainer(_MINIO_IMAGE)
            .with_exposed_ports(_MINIO_PORT)
            .with_env("MINIO_ROOT_USER", _ACCESS_KEY)
            .with_env("MINIO_ROOT_PASSWORD", _SECRET_KEY)
            .with_command(f"server /data --address :{_MINIO_PORT}")
        )
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker not available — skipping MinIO integration tests: {exc}")

    host = container.get_container_host_ip()
    port = container.get_exposed_port(_MINIO_PORT)
    endpoint = f"http://{host}:{port}"

    # Wait until MinIO is ready and yield; always stop the container on exit.
    try:
        _wait_for_minio(endpoint)
        yield endpoint
    finally:
        container.stop()


def _wait_for_minio(endpoint: str) -> None:
    """Wait until MinIO's health endpoint returns 200.

    Uses testcontainers' built-in ``wait_container_is_ready`` retry mechanism
    so there is no manual sleep loop.
    """
    health_url = f"{endpoint}/minio/health/live"

    @wait_container_is_ready(httpx.RequestError, httpx.HTTPStatusError)
    def _probe() -> None:
        resp = httpx.get(health_url, timeout=2.0)
        resp.raise_for_status()

    _probe()


@pytest.fixture(scope="session")
def s3_client(minio_endpoint: str) -> Any:
    """Return a boto3 S3 client configured to talk to the MinIO container.

    The return type is ``Any`` because boto3 clients are typed via ``boto3-stubs``
    optional extras and the exact ``S3Client`` type is not guaranteed at runtime.
    """
    client = boto3.client(
        "s3",
        endpoint_url=minio_endpoint,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="us-east-1",
    )
    # Create the test bucket once for the whole session.
    client.create_bucket(Bucket=_BUCKET)
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_settings(minio_endpoint: str) -> MagicMock:
    """Build a MagicMock that mimics the subset of *settings* used by app.storage.s3."""
    mock = MagicMock()
    mock.s3_bucket_name = _BUCKET
    mock.s3_endpoint_url = minio_endpoint
    mock.s3_presigned_url_expire_seconds = 3600
    mock.aws_access_key_id = _ACCESS_KEY
    mock.aws_secret_access_key = _SECRET_KEY
    mock.s3_region = "us-east-1"
    return mock


def _boto3_client_for(minio_endpoint: str) -> Any:
    """Return a boto3 S3 client pointed at the test MinIO container."""
    return boto3.client(
        "s3",
        endpoint_url=minio_endpoint,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="us-east-1",
    )


def _upload(minio_endpoint: str, key: str, data: bytes, content_type: str) -> None:
    """Call :func:`app.storage.s3.upload_file` wired to the test MinIO container."""
    from app.storage.s3 import upload_file

    with (
        patch("app.storage.s3.settings", _make_mock_settings(minio_endpoint)),
        patch("app.storage.s3._make_client", return_value=_boto3_client_for(minio_endpoint)),
    ):
        upload_file(key, data, content_type)


def _presign(minio_endpoint: str, key: str, expires_in: int = 3600) -> str:
    """Call :func:`app.storage.s3.generate_presigned_url` wired to the test MinIO container."""
    from app.storage.s3 import generate_presigned_url

    with (
        patch("app.storage.s3.settings", _make_mock_settings(minio_endpoint)),
        patch("app.storage.s3._make_client", return_value=_boto3_client_for(minio_endpoint)),
    ):
        return generate_presigned_url(key, expires_in=expires_in)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestS3IntegrationUpload:
    """Upload a file and verify it was stored in MinIO."""

    def test_upload_plain_text(self, minio_endpoint: str, s3_client: Any) -> None:
        key = f"integration/{uuid.uuid4()}.txt"
        content = b"Hello from the integration test!"

        _upload(minio_endpoint, key, content, "text/plain")

        # Verify the object was stored by reading it back directly.
        response = s3_client.get_object(Bucket=_BUCKET, Key=key)
        stored = response["Body"].read()
        assert stored == content, f"Stored content mismatch: expected {content!r}, got {stored!r}"

    def test_upload_binary_content(self, minio_endpoint: str, s3_client: Any) -> None:
        key = f"integration/{uuid.uuid4()}.bin"
        content = bytes(range(256))

        _upload(minio_endpoint, key, content, "application/octet-stream")

        response = s3_client.get_object(Bucket=_BUCKET, Key=key)
        stored = response["Body"].read()
        assert stored == content, "Binary payload round-trip failed"

    def test_upload_stores_content_type(self, minio_endpoint: str, s3_client: Any) -> None:
        key = f"integration/{uuid.uuid4()}.pdf"
        content = b"%PDF-1.4 fake pdf"

        _upload(minio_endpoint, key, content, "application/pdf")

        head = s3_client.head_object(Bucket=_BUCKET, Key=key)
        assert head["ContentType"] == "application/pdf", (
            f"ContentType mismatch: {head['ContentType']!r}"
        )


@pytest.mark.integration
class TestS3IntegrationPresignedUrl:
    """Generate a pre-signed URL and verify the object is accessible via HTTP GET."""

    def test_presigned_url_returns_correct_content(
        self, minio_endpoint: str, s3_client: Any
    ) -> None:
        key = f"integration/{uuid.uuid4()}.txt"
        content = b"Presigned URL integration test content."

        # First upload the file directly via boto3.
        s3_client.put_object(Bucket=_BUCKET, Key=key, Body=content, ContentType="text/plain")

        # Generate a pre-signed URL via the module under test.
        url = _presign(minio_endpoint, key, expires_in=300)

        assert url, "Expected a non-empty URL"
        assert key in url or _BUCKET in url, (
            f"Expected URL to reference the key or bucket, got: {url}"
        )

        # Verify the URL is accessible and returns the correct content.
        response = httpx.get(url, timeout=30.0)
        assert response.status_code == 200, f"Presigned URL returned HTTP {response.status_code}"
        assert response.content == content, (
            f"Content mismatch: expected {content!r}, got {response.content!r}"
        )

    def test_presigned_url_for_uploaded_object(self, minio_endpoint: str) -> None:
        """Upload via the module function, then verify via presigned URL."""
        key = f"integration/{uuid.uuid4()}.txt"
        content = b"Uploaded then accessed via presigned URL."

        _upload(minio_endpoint, key, content, "text/plain")

        url = _presign(minio_endpoint, key, expires_in=60)

        response = httpx.get(url, timeout=30.0)
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code} for presigned URL"
        )
        assert response.content == content, "Round-trip content mismatch via presigned URL"

    def test_presigned_url_is_string(self, minio_endpoint: str, s3_client: Any) -> None:
        key = f"integration/{uuid.uuid4()}.txt"
        s3_client.put_object(Bucket=_BUCKET, Key=key, Body=b"data", ContentType="text/plain")

        url = _presign(minio_endpoint, key)

        assert isinstance(url, str), f"Expected str, got {type(url)}"
        assert url.startswith("http"), f"Expected URL to start with 'http', got {url!r}"
