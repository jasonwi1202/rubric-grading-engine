"""Unit tests for app.storage.s3.

All boto3 calls are intercepted with ``pytest-mock`` — no real S3 or MinIO
connection is made.  The tests verify that:

* ``upload_file`` calls ``put_object`` with the correct arguments.
* ``generate_presigned_url`` calls ``generate_presigned_url`` on the boto3
  client with the correct arguments.
* Both functions raise :class:`~app.storage.s3.StorageError` when boto3
  raises a :class:`botocore.exceptions.ClientError`.
* All configuration (bucket name, endpoint URL, region, credentials) comes
  from ``settings.*`` — none is hard-coded.
"""

from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from pytest_mock import MockerFixture

from app.config import settings
from app.storage.s3 import StorageError, generate_presigned_url, upload_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client_error() -> ClientError:
    """Return a minimal ClientError suitable for use in tests."""
    return ClientError(
        error_response={"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
        operation_name="PutObject",
    )


def _patch_make_client(mocker: MockerFixture) -> MagicMock:
    """Patch ``_make_client`` so it returns a MagicMock boto3 client."""
    mock_client = MagicMock()
    mocker.patch("app.storage.s3._make_client", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------


class TestUploadFile:
    def test_calls_put_object_with_correct_arguments(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)

        upload_file("essays/test.pdf", b"hello", "application/pdf")

        mock_client.put_object.assert_called_once_with(
            Bucket=settings.s3_bucket_name,
            Key="essays/test.pdf",
            Body=b"hello",
            ContentType="application/pdf",
        )

    def test_uses_bucket_name_from_settings(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)

        upload_file("docs/file.txt", b"data", "text/plain")

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == settings.s3_bucket_name, (
            f"Expected bucket {settings.s3_bucket_name!r}, got {call_kwargs['Bucket']!r}"
        )

    def test_forwards_content_type(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)

        upload_file(
            "key", b"x", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["ContentType"] == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_returns_none_on_success(self, mocker: MockerFixture) -> None:
        _patch_make_client(mocker)
        result = upload_file("key", b"data", "text/plain")
        assert result is None

    def test_raises_storage_error_on_client_error(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.put_object.side_effect = _make_client_error()

        with pytest.raises(StorageError, match="upload"):
            upload_file("bad/key", b"data", "text/plain")

    def test_storage_error_chains_original_exception(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        original = _make_client_error()
        mock_client.put_object.side_effect = original

        with pytest.raises(StorageError) as exc_info:
            upload_file("key", b"data", "text/plain")

        assert exc_info.value.__cause__ is original, (
            "StorageError should chain the original ClientError as __cause__"
        )

    def test_passes_data_bytes_unchanged(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        payload = b"\x00\x01\x02binary\xff"

        upload_file("bin/file", payload, "application/octet-stream")

        call_kwargs = mock_client.put_object.call_args.kwargs
        assert call_kwargs["Body"] == payload

    def test_raises_storage_error_on_botocore_error(self, mocker: MockerFixture) -> None:
        """Non-ClientError BotoCoreError subclasses (e.g. NoCredentialsError) are also wrapped."""
        mock_client = _patch_make_client(mocker)
        mock_client.put_object.side_effect = NoCredentialsError()

        with pytest.raises(StorageError, match="upload"):
            upload_file("key", b"data", "text/plain")

    def test_botocore_error_chains_original_exception(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        original = NoCredentialsError()
        mock_client.put_object.side_effect = original

        with pytest.raises(StorageError) as exc_info:
            upload_file("key", b"data", "text/plain")

        assert exc_info.value.__cause__ is original, (
            "StorageError should chain the original BotoCoreError as __cause__"
        )


# ---------------------------------------------------------------------------
# generate_presigned_url
# ---------------------------------------------------------------------------


class TestGeneratePresignedUrl:
    def test_returns_url_string(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.return_value = "https://example.com/signed"

        url = generate_presigned_url("essays/test.pdf")

        assert url == "https://example.com/signed", f"Got {url!r}"

    def test_calls_generate_presigned_url_with_correct_params(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.return_value = "https://example.com/signed"

        generate_presigned_url("essays/abc.pdf")

        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": settings.s3_bucket_name, "Key": "essays/abc.pdf"},
            ExpiresIn=settings.s3_presigned_url_expire_seconds,
        )

    def test_uses_default_expiry_from_settings(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.return_value = "https://example.com/s"

        generate_presigned_url("key")

        call_kwargs = mock_client.generate_presigned_url.call_args.kwargs
        assert call_kwargs["ExpiresIn"] == settings.s3_presigned_url_expire_seconds, (
            f"Expected {settings.s3_presigned_url_expire_seconds}, got {call_kwargs['ExpiresIn']}"
        )

    def test_custom_expires_in_overrides_default(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.return_value = "https://example.com/s"

        generate_presigned_url("key", expires_in=60)

        call_kwargs = mock_client.generate_presigned_url.call_args.kwargs
        assert call_kwargs["ExpiresIn"] == 60, f"Expected 60, got {call_kwargs['ExpiresIn']}"

    def test_uses_bucket_name_from_settings(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.return_value = "https://example.com/s"

        generate_presigned_url("key")

        call_kwargs = mock_client.generate_presigned_url.call_args.kwargs
        assert call_kwargs["Params"]["Bucket"] == settings.s3_bucket_name

    def test_raises_storage_error_on_client_error(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.side_effect = _make_client_error()

        with pytest.raises(StorageError, match="presigned"):
            generate_presigned_url("bad/key")

    def test_storage_error_chains_original_exception(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        original = _make_client_error()
        mock_client.generate_presigned_url.side_effect = original

        with pytest.raises(StorageError) as exc_info:
            generate_presigned_url("key")

        assert exc_info.value.__cause__ is original

    def test_raises_storage_error_on_botocore_error(self, mocker: MockerFixture) -> None:
        """Non-ClientError BotoCoreError subclasses (e.g. NoCredentialsError) are also wrapped."""
        mock_client = _patch_make_client(mocker)
        mock_client.generate_presigned_url.side_effect = NoCredentialsError()

        with pytest.raises(StorageError, match="presigned"):
            generate_presigned_url("bad/key")

    def test_botocore_error_chains_original_exception(self, mocker: MockerFixture) -> None:
        mock_client = _patch_make_client(mocker)
        original = NoCredentialsError()
        mock_client.generate_presigned_url.side_effect = original

        with pytest.raises(StorageError) as exc_info:
            generate_presigned_url("key")

        assert exc_info.value.__cause__ is original, (
            "StorageError should chain the original BotoCoreError as __cause__"
        )


# ---------------------------------------------------------------------------
# _make_client — configuration forwarded to boto3
# ---------------------------------------------------------------------------


class TestMakeClient:
    """Verify that _make_client passes the correct kwargs to boto3.client."""

    def test_endpoint_url_passed_when_set(self, mocker: MockerFixture) -> None:
        mock_boto3_client = mocker.patch("app.storage.s3.boto3.client")
        mocker.patch.object(settings, "s3_endpoint_url", "http://localhost:9000")

        from app.storage.s3 import _make_client

        _make_client()

        call_kwargs = mock_boto3_client.call_args.kwargs
        assert call_kwargs.get("endpoint_url") == "http://localhost:9000", (
            f"endpoint_url not forwarded: {call_kwargs}"
        )

    def test_path_style_addressing_set_when_endpoint_url_present(
        self, mocker: MockerFixture
    ) -> None:
        """Path-style addressing must be configured when a custom endpoint is used."""
        mock_boto3_client = mocker.patch("app.storage.s3.boto3.client")
        mocker.patch.object(settings, "s3_endpoint_url", "http://localhost:9000")

        from app.storage.s3 import _make_client

        _make_client()

        call_kwargs = mock_boto3_client.call_args.kwargs
        cfg = call_kwargs.get("config")
        assert cfg is not None, "config should be set when endpoint_url is present"
        assert cfg.s3 == {"addressing_style": "path"}, (
            f"Expected path-style addressing, got: {cfg.s3}"
        )

    def test_no_config_override_when_endpoint_url_is_none(
        self, mocker: MockerFixture
    ) -> None:
        """No addressing_style config override when using AWS S3 (no custom endpoint)."""
        mock_boto3_client = mocker.patch("app.storage.s3.boto3.client")
        mocker.patch.object(settings, "s3_endpoint_url", None)

        from app.storage.s3 import _make_client

        _make_client()

        call_kwargs = mock_boto3_client.call_args.kwargs
        assert "config" not in call_kwargs, (
            "config should not be set when using AWS S3 (no endpoint_url)"
        )

    def test_endpoint_url_omitted_when_none(self, mocker: MockerFixture) -> None:
        mock_boto3_client = mocker.patch("app.storage.s3.boto3.client")
        mocker.patch.object(settings, "s3_endpoint_url", None)

        from app.storage.s3 import _make_client

        _make_client()

        call_kwargs = mock_boto3_client.call_args.kwargs
        assert "endpoint_url" not in call_kwargs, (
            "endpoint_url should be omitted when S3_ENDPOINT_URL is not set"
        )

    def test_credentials_come_from_settings(self, mocker: MockerFixture) -> None:
        mock_boto3_client = mocker.patch("app.storage.s3.boto3.client")

        from app.storage.s3 import _make_client

        _make_client()

        call_kwargs = mock_boto3_client.call_args.kwargs
        assert call_kwargs["aws_access_key_id"] == settings.aws_access_key_id
        assert call_kwargs["aws_secret_access_key"] == settings.aws_secret_access_key
        assert call_kwargs["region_name"] == settings.s3_region
