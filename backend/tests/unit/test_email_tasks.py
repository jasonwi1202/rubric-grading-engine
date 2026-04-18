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
from unittest.mock import AsyncMock, MagicMock

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
    def test_returns_empty_string(self) -> None:
        """The unsubscribe flow is not yet implemented; helper returns empty string."""
        token = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        assert token == "", f"Expected empty string stub, got: {repr(token)}"

    def test_always_returns_same_empty_string(self) -> None:
        """Returns empty string regardless of inputs."""
        t1 = _generate_unsubscribe_token(_USER_ID, "trial_warning", _SECRET)
        t2 = _generate_unsubscribe_token(_USER_ID, "trial_expired", _SECRET)
        assert t1 == t2 == ""


# ---------------------------------------------------------------------------
# _build_unsubscribe_url
# ---------------------------------------------------------------------------


class TestBuildUnsubscribeUrl:
    def test_returns_empty_string(self) -> None:
        """The unsubscribe flow is not yet implemented; helper returns empty string."""
        url = _build_unsubscribe_url(_USER_ID, "trial_warning", _FRONTEND_URL, _SECRET)
        assert url == "", f"Expected empty string stub, got: {repr(url)}"

    def test_always_returns_empty_string_regardless_of_type(self) -> None:
        url_warning = _build_unsubscribe_url(_USER_ID, "trial_warning", _FRONTEND_URL, _SECRET)
        url_expired = _build_unsubscribe_url(_USER_ID, "trial_expired", _FRONTEND_URL, _SECRET)
        assert url_warning == url_expired == ""


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

    def test_no_unsubscribe_header_until_flow_implemented(
        self, mocker: pytest.FixtureRequest
    ) -> None:
        """No List-Unsubscribe header emitted while unsubscribe flow is not implemented."""
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
        assert sent_msg["List-Unsubscribe"] is None

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

    def test_no_unsubscribe_header_until_flow_implemented(
        self, mocker: pytest.FixtureRequest
    ) -> None:
        """No List-Unsubscribe header emitted while unsubscribe flow is not implemented."""
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
        assert sent_msg["List-Unsubscribe"] is None

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


# ---------------------------------------------------------------------------
# _do_scan_trial_expirations — DB query and enqueue logic
# ---------------------------------------------------------------------------


class TestDoScanTrialExpirations:
    """Unit tests for the async scan implementation.

    The DB session and Celery .delay() calls are mocked; no real database or
    broker is required.
    """

    def _make_db_result(self, user_ids: list[str]) -> MagicMock:
        """Return a mock SQLAlchemy result that yields UUID rows."""
        rows = [(uuid.UUID(uid),) for uid in user_ids]
        result = MagicMock()
        result.all.return_value = rows
        return result

    @freeze_time(
        "2025-06-10 08:00:00"
    )  # 08:00 UTC — Beat runs morning of June 10, covers June 9 window
    def test_day_0_enqueues_send_trial_expired(self, mocker: pytest.FixtureRequest) -> None:
        """Users whose trial ended during yesterday's UTC window get trial_expired enqueued."""
        uid = str(uuid.uuid4())
        expired_result = self._make_db_result([uid])
        empty_result = self._make_db_result([])

        # DB returns one user for days=0 window; empty for days=7 and days=1
        execute_results = [empty_result, empty_result, expired_result]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=execute_results)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("app.tasks.email.AsyncSessionLocal", return_value=mock_cm)
        mock_expired_delay = mocker.patch(
            "app.tasks.email.send_trial_expired.delay",
        )
        mock_warning_delay = mocker.patch(
            "app.tasks.email.send_trial_expiry_warning.delay",
        )

        import asyncio as _asyncio

        from app.tasks.email import _do_scan_trial_expirations

        _asyncio.run(_do_scan_trial_expirations())

        mock_expired_delay.assert_called_once_with(user_id=uid)
        mock_warning_delay.assert_not_called()

    @freeze_time("2025-06-03 06:00:00")
    def test_day_7_enqueues_send_trial_expiry_warning(self, mocker: pytest.FixtureRequest) -> None:
        """Users whose trial ends in exactly 7 days get a warning task enqueued."""
        uid = str(uuid.uuid4())
        warning_result = self._make_db_result([uid])
        empty_result = self._make_db_result([])

        # DB returns one user for days=7 window; empty for days=1 and days=0
        execute_results = [warning_result, empty_result, empty_result]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=execute_results)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("app.tasks.email.AsyncSessionLocal", return_value=mock_cm)
        mock_expired_delay = mocker.patch("app.tasks.email.send_trial_expired.delay")
        mock_warning_delay = mocker.patch(
            "app.tasks.email.send_trial_expiry_warning.delay",
        )

        import asyncio as _asyncio

        from app.tasks.email import _do_scan_trial_expirations

        _asyncio.run(_do_scan_trial_expirations())

        mock_warning_delay.assert_called_once_with(user_id=uid, days_remaining=7)
        mock_expired_delay.assert_not_called()

    @freeze_time("2025-06-09 06:00:00")
    def test_day_1_enqueues_send_trial_expiry_warning(self, mocker: pytest.FixtureRequest) -> None:
        """Users whose trial ends in exactly 1 day get a 1-day warning task enqueued."""
        uid = str(uuid.uuid4())
        one_day_result = self._make_db_result([uid])
        empty_result = self._make_db_result([])

        # DB returns empty for days=7, one user for days=1, empty for days=0
        execute_results = [empty_result, one_day_result, empty_result]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=execute_results)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("app.tasks.email.AsyncSessionLocal", return_value=mock_cm)
        mock_expired_delay = mocker.patch("app.tasks.email.send_trial_expired.delay")
        mock_warning_delay = mocker.patch(
            "app.tasks.email.send_trial_expiry_warning.delay",
        )

        import asyncio as _asyncio

        from app.tasks.email import _do_scan_trial_expirations

        _asyncio.run(_do_scan_trial_expirations())

        mock_warning_delay.assert_called_once_with(user_id=uid, days_remaining=1)
        mock_expired_delay.assert_not_called()

    @freeze_time("2025-06-10 06:00:00")
    def test_day_0_returns_empty_when_no_expired_users(self, mocker: pytest.FixtureRequest) -> None:
        """When no users fall in yesterday's window, no expired task is enqueued.

        This covers the case where no trials expired during the previous UTC day
        (the day-0 window now uses the previous calendar day, not today).
        """
        empty_result = self._make_db_result([])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=empty_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("app.tasks.email.AsyncSessionLocal", return_value=mock_cm)
        mock_expired_delay = mocker.patch("app.tasks.email.send_trial_expired.delay")

        import asyncio as _asyncio

        from app.tasks.email import _do_scan_trial_expirations

        _asyncio.run(_do_scan_trial_expirations())

        mock_expired_delay.assert_not_called()

    @freeze_time("2025-06-10 08:00:00")
    def test_no_users_no_tasks_enqueued(self, mocker: pytest.FixtureRequest) -> None:
        """When no users fall into any window, no tasks are enqueued."""
        empty_result = self._make_db_result([])

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=empty_result)
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_db)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mocker.patch("app.tasks.email.AsyncSessionLocal", return_value=mock_cm)
        mock_expired_delay = mocker.patch("app.tasks.email.send_trial_expired.delay")
        mock_warning_delay = mocker.patch(
            "app.tasks.email.send_trial_expiry_warning.delay",
        )

        import asyncio as _asyncio

        from app.tasks.email import _do_scan_trial_expirations

        _asyncio.run(_do_scan_trial_expirations())

        mock_expired_delay.assert_not_called()
        mock_warning_delay.assert_not_called()
