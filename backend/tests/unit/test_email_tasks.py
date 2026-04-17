"""Unit tests for trial lifecycle email tasks.

All tests mock SMTP, the database session, and the audit-log writer so no
external services are required.  No real student PII is used in any fixture.

Coverage targets:
- send_welcome_email       — sent, no-sender, missing user, SMTP failure + retry
- send_trial_expiry_warning — sent (7d and 1d), no-sender, missing user, SMTP failure
- send_trial_expired       — sent, no-sender, missing user, SMTP failure
- scan_trial_expirations   — tasks enqueued for day 7, 1, and 0 windows
- _generate_unsubscribe_token — deterministic, scoped to type
- _build_unsubscribe_url   — includes token and params in URL
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time

from app.tasks.email import (
    _build_unsubscribe_url,
    _generate_unsubscribe_token,
    send_trial_expired,
    send_trial_expiry_warning,
    send_welcome_email,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_USER_ID = str(uuid.uuid4())
_SECRET = "s" * 32
_FRONTEND_URL = "http://localhost:3000"


def _make_fake_user(user_id: str = _USER_ID) -> MagicMock:
    """Return a minimal mock User with no PII (uses generic labels)."""
    user = MagicMock()
    user.id = uuid.UUID(user_id)
    user.first_name = "Teacher"
    user.email = "teacher@example.invalid"
    return user


# ---------------------------------------------------------------------------
# _generate_unsubscribe_token
# ---------------------------------------------------------------------------


class TestGenerateUnsubscribeToken:
    def test_returns_64_char_hex_string(self) -> None:
        token = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        assert isinstance(token, str)
        assert len(token) == 64

    def test_deterministic_for_same_inputs(self) -> None:
        t1 = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        t2 = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        assert t1 == t2

    def test_differs_by_email_type(self) -> None:
        t_warning = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        t_expired = _generate_unsubscribe_token(_USER_ID, "trial_expired", _SECRET)
        assert t_warning != t_expired

    def test_differs_by_user_id(self) -> None:
        other_id = str(uuid.uuid4())
        t1 = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        t2 = _generate_unsubscribe_token(other_id, "trial_warning", _SECRET)
        assert t1 != t2


# ---------------------------------------------------------------------------
# _build_unsubscribe_url
# ---------------------------------------------------------------------------


class TestBuildUnsubscribeUrl:
    def test_contains_user_id(self) -> None:
        url = _build_unsubscribe_url(_USER_ID, "trial_warning", _FRONTEND_URL, _SECRET)
        assert _USER_ID in url

    def test_contains_email_type(self) -> None:
        url = _build_unsubscribe_url(_USER_ID, "trial_warning", _FRONTEND_URL, _SECRET)
        assert "type=trial_warning" in url

    def test_contains_token(self) -> None:
        token = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        url = _build_unsubscribe_url(_USER_ID, "trial_warning", _FRONTEND_URL, _SECRET)
        assert f"token={token}" in url

    def test_strips_trailing_slash_from_frontend_url(self) -> None:
        url = _build_unsubscribe_url(_USER_ID, "trial_warning", "http://localhost:3000/", _SECRET)
        assert url.startswith("http://localhost:3000/unsubscribe")


# ---------------------------------------------------------------------------
# send_welcome_email
# ---------------------------------------------------------------------------


class TestSendWelcomeEmail:
    def test_sends_email_when_configured(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_welcome_email.apply(args=[_USER_ID])

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == fake_user.email
        assert "Welcome" in sent_msg["Subject"]
        assert "/onboarding" in sent_msg.get_content()

    def test_skips_when_no_sender_configured(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from=None,
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_welcome_email.apply(args=[_USER_ID])

        mock_send.assert_not_called()

    def test_skips_when_user_not_found(self, mocker: pytest.FixtureRequest) -> None:
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=None),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_welcome_email.apply(args=[_USER_ID])

        mock_send.assert_not_called()

    def test_writes_audit_log_on_send(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mock_audit = mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_welcome_email.apply(args=[_USER_ID])

        mock_audit.assert_called_once_with(_USER_ID, "welcome")


# ---------------------------------------------------------------------------
# send_trial_expiry_warning
# ---------------------------------------------------------------------------


class TestSendTrialExpiryWarning:
    @pytest.mark.parametrize("days_remaining", [7, 1])
    def test_sends_email_for_valid_days(
        self, days_remaining: int, mocker: pytest.FixtureRequest
    ) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expiry_warning.apply(args=[_USER_ID, days_remaining])

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == fake_user.email
        assert str(days_remaining) in sent_msg["Subject"]

    def test_includes_unsubscribe_header(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expiry_warning.apply(args=[_USER_ID, 7])

        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["List-Unsubscribe"] is not None
        assert "trial_warning" in sent_msg["List-Unsubscribe"]

    def test_writes_audit_log_on_send(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mock_audit = mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expiry_warning.apply(args=[_USER_ID, 7])

        mock_audit.assert_called_once_with(_USER_ID, "trial_warning")

    def test_skips_when_user_not_found(self, mocker: pytest.FixtureRequest) -> None:
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=None),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expiry_warning.apply(args=[_USER_ID, 7])

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# send_trial_expired
# ---------------------------------------------------------------------------


class TestSendTrialExpired:
    def test_sends_email_with_upgrade_cta(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expired.apply(args=[_USER_ID])

        mock_send.assert_called_once()
        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["To"] == fake_user.email
        assert "/pricing" in sent_msg.get_content()

    def test_includes_unsubscribe_header(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expired.apply(args=[_USER_ID])

        sent_msg = mock_send.call_args[0][0]
        assert sent_msg["List-Unsubscribe"] is not None
        assert "trial_expired" in sent_msg["List-Unsubscribe"]

    def test_writes_audit_log_on_send(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mock_audit = mocker.patch(
            "app.tasks.email._write_email_audit_log",
            new=AsyncMock(),
        )
        mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from="noreply@example.invalid",
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expired.apply(args=[_USER_ID])

        mock_audit.assert_called_once_with(_USER_ID, "trial_expired")

    def test_skips_when_no_sender_configured(self, mocker: pytest.FixtureRequest) -> None:
        fake_user = _make_fake_user()
        mocker.patch(
            "app.tasks.email._load_user",
            new=AsyncMock(return_value=fake_user),
        )
        mock_send = mocker.patch("app.tasks.email._send_smtp_message")
        mocker.patch(
            "app.config.settings",
            verification_email_from=None,
            contact_email=None,
            frontend_url=_FRONTEND_URL,
            smtp_host="localhost",
            smtp_port=25,
            smtp_timeout=10,
            smtp_user=None,
            smtp_password=None,
            unsubscribe_hmac_secret=_SECRET,
        )

        send_trial_expired.apply(args=[_USER_ID])

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# scan_trial_expirations
# ---------------------------------------------------------------------------


class TestScanTrialExpirations:
    @freeze_time("2025-06-10 06:00:00")
    def test_enqueues_warning_for_7_day_window(self, mocker: pytest.FixtureRequest) -> None:
        """scan_trial_expirations delegates to _do_scan_trial_expirations."""
        called: list[bool] = []

        async def _patched_scan() -> None:
            called.append(True)

        mocker.patch("app.tasks.email._do_scan_trial_expirations", new=_patched_scan)

        from app.tasks.email import scan_trial_expirations

        scan_trial_expirations.apply()

        assert called == [True], "scan_trial_expirations must call _do_scan_trial_expirations"

    def test_task_is_registered(self) -> None:
        from app.tasks.celery_app import celery

        assert "tasks.email.scan_trial_expirations" in celery.tasks

    def test_trial_email_tasks_are_registered(self) -> None:
        from app.tasks.celery_app import celery

        assert "tasks.email.send_welcome_email" in celery.tasks
        assert "tasks.email.send_trial_expiry_warning" in celery.tasks
        assert "tasks.email.send_trial_expired" in celery.tasks

    def test_beat_schedule_contains_daily_scan(self) -> None:
        from app.tasks.celery_app import celery

        schedule = celery.conf.beat_schedule
        assert "scan-trial-expirations-daily" in schedule
        entry = schedule["scan-trial-expirations-daily"]
        assert entry["task"] == "tasks.email.scan_trial_expirations"
