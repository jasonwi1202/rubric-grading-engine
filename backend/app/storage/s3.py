"""S3/MinIO client wrapper.

Provides :func:`upload_file` and :func:`generate_presigned_url` backed by
boto3.  All configuration (endpoint URL, credentials, bucket name, presigned
URL TTL) comes from :mod:`app.config` — no hardcoded values here.

Usage::

    from app.storage.s3 import upload_file, generate_presigned_url

    upload_file("essays/abc123.pdf", pdf_bytes, "application/pdf")
    url = generate_presigned_url("essays/abc123.pdf")

Both functions raise :class:`StorageError` on failure.  The original
:class:`botocore.exceptions.BotoCoreError` (which includes
:class:`~botocore.exceptions.ClientError`,
:class:`~botocore.exceptions.EndpointConnectionError`, and
:class:`~botocore.exceptions.NoCredentialsError`) is chained as the
``__cause__``.
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when an S3 / object-storage operation fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_client() -> Any:  # boto3 client is not easily typed without mypy extras
    """Create a fresh boto3 S3 client using application settings.

    Supports both AWS S3 (no endpoint override) and S3-compatible endpoints
    such as MinIO (``S3_ENDPOINT_URL`` set in environment).
    """
    kwargs: dict[str, Any] = {
        "service_name": "s3",
        "region_name": settings.s3_region,
        "aws_access_key_id": settings.aws_access_key_id,
        "aws_secret_access_key": settings.aws_secret_access_key,
    }
    if settings.s3_endpoint_url:
        # Force path-style addressing for S3-compatible endpoints (e.g. MinIO).
        # AWS S3 uses virtual-host style (bucket.s3.amazonaws.com) by default,
        # but MinIO and other self-hosted stores require path style
        # (host/bucket/key) to resolve correctly on the local network.
        # This config block is intentionally absent when s3_endpoint_url is
        # not set so that AWS S3 retains its default addressing behaviour.
        kwargs["endpoint_url"] = settings.s3_endpoint_url
        kwargs["config"] = Config(s3={"addressing_style": "path"})
    return boto3.client(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def upload_file(key: str, data: bytes, content_type: str) -> None:
    """Upload *data* to the configured S3 bucket under *key*.

    Args:
        key: Object key (path) within the bucket, e.g. ``"essays/abc123.pdf"``.
        data: Raw bytes to upload.
        content_type: MIME type of the content, e.g. ``"application/pdf"``.

    Raises:
        StorageError: If the upload fails for any reason (HTTP error, connection
            failure, missing credentials, etc.).
    """
    client = _make_client()
    try:
        client.put_object(
            Bucket=settings.s3_bucket_name,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "S3 upload failed",
            extra={"error_type": type(exc).__name__},
        )
        raise StorageError("S3 upload failed") from exc


def copy_file(source_key: str, dest_key: str) -> None:
    """Copy the object at *source_key* to *dest_key* within the same bucket.

    Args:
        source_key: Source object key within the bucket.
        dest_key: Destination object key within the bucket.

    Raises:
        StorageError: If the copy fails for any reason.
    """
    client = _make_client()
    try:
        client.copy_object(
            Bucket=settings.s3_bucket_name,
            CopySource={"Bucket": settings.s3_bucket_name, "Key": source_key},
            Key=dest_key,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "S3 copy failed",
            extra={"error_type": type(exc).__name__},
        )
        raise StorageError("S3 copy failed") from exc


def delete_file(key: str) -> None:
    """Delete the object at *key* from the configured S3 bucket.

    Args:
        key: Object key (path) within the bucket, e.g. ``"essays/abc123.pdf"``.

    Raises:
        StorageError: If the deletion fails for any reason.
    """
    client = _make_client()
    try:
        client.delete_object(Bucket=settings.s3_bucket_name, Key=key)
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "S3 delete failed",
            extra={"error_type": type(exc).__name__},
        )
        raise StorageError("S3 delete failed") from exc


def generate_presigned_url(key: str, expires_in: int | None = None) -> str:
    """Return a pre-signed GET URL for the object at *key*.

    Args:
        key: Object key within the bucket.
        expires_in: URL lifetime in seconds.  Defaults to
            ``settings.s3_presigned_url_expire_seconds``.

    Returns:
        A pre-signed URL string valid for *expires_in* seconds.

    Raises:
        StorageError: If URL generation fails (HTTP error, connection failure,
            missing credentials, etc.).
    """
    if expires_in is None:
        expires_in = settings.s3_presigned_url_expire_seconds
    client = _make_client()
    try:
        url: str = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except (BotoCoreError, ClientError) as exc:
        logger.error(
            "S3 presigned URL generation failed",
            extra={"error_type": type(exc).__name__},
        )
        raise StorageError("S3 presigned URL generation failed") from exc
