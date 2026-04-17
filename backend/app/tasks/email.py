"""Email notification Celery tasks.

Tasks in this module send notification emails for internal operational
purposes (e.g. new school inquiry alerts, DPA request alerts, email
verification).  They do not send email to students or process student data.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import smtplib
import uuid
from datetime import UTC, date, datetime, timedelta
from email.message import EmailMessage
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.tasks.celery_app import celery

if TYPE_CHECKING:
    from app.models.contact import ContactInquiry
    from app.models.dpa_request import DpaRequest
    from app.models.user import User

logger = logging.getLogger(__name__)


async def _load_inquiry(inquiry_id: str) -> ContactInquiry | None:
    """Load a ContactInquiry record from the database by ID.

    Returns the ORM instance, or ``None`` if not found.  Imported lazily
    inside the task to avoid circular imports at module load time.
    """
    from app.models.contact import ContactInquiry as _ContactInquiry  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(_ContactInquiry).where(_ContactInquiry.id == uuid.UUID(inquiry_id))
        )
        return result.scalar_one_or_none()


async def _load_dpa_request(dpa_request_id: str) -> DpaRequest | None:
    """Load a DpaRequest record from the database by ID."""
    from app.models.dpa_request import DpaRequest as _DpaRequest  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(_DpaRequest).where(_DpaRequest.id == uuid.UUID(dpa_request_id))
        )
        return result.scalar_one_or_none()


async def _load_user(user_id: str) -> User | None:
    """Load a User record from the database by ID."""
    from app.models.user import User as _User  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(_User).where(_User.id == uuid.UUID(user_id)))
        return result.scalar_one_or_none()


def _generate_unsubscribe_token(user_id: str, email_type: str, secret: str) -> str:
    """Generate an HMAC-SHA256 unsubscribe token scoped to user and email type.

    The token is deterministic for a given (user_id, email_type, secret) triple
    so the same link is always re-generatable for verification.

    Args:
        user_id: UUID string of the teacher.
        email_type: A short descriptor of the email category (e.g. ``"trial_warning"``).
        secret: HMAC signing secret from settings.

    Returns:
        Hex-encoded SHA-256 digest (64 characters).
    """
    msg = f"{user_id}:{email_type}"
    return hmac.new(
        key=secret.encode(),
        msg=msg.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _build_unsubscribe_url(user_id: str, email_type: str, frontend_url: str, secret: str) -> str:
    """Return the full unsubscribe URL with an HMAC-signed token."""
    token = _generate_unsubscribe_token(user_id, email_type, secret)
    base = frontend_url.rstrip("/")
    return f"{base}/unsubscribe?user_id={user_id}&type={email_type}&token={token}"


def _send_smtp_message(msg: EmailMessage) -> None:
    """Deliver an EmailMessage via the configured SMTP server.

    Supports optional SMTP authentication when ``settings.smtp_user`` and
    ``settings.smtp_password`` are both set.
    """
    from app.config import settings  # noqa: PLC0415

    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
    ) as smtp:
        if settings.smtp_user and settings.smtp_password:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def _write_email_audit_log(user_id: str, email_type: str) -> None:
    """Insert an ``email_sent`` audit log entry for the given user and email type.

    Args:
        user_id: UUID string of the teacher.
        email_type: Short descriptor used in the ``after_value`` metadata.
    """
    from app.models.audit_log import AuditLog  # noqa: PLC0415

    entry = AuditLog(
        teacher_id=uuid.UUID(user_id),
        entity_type="user",
        entity_id=uuid.UUID(user_id),
        action="email_sent",
        after_value={"email_type": email_type},
    )
    async with AsyncSessionLocal() as db:
        db.add(entry)
        await db.commit()


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_inquiry_notification",
    bind=True,
    max_retries=3,
)
def send_inquiry_notification(self: object, inquiry_id: str) -> None:
    """Send an internal notification email when a new contact inquiry arrives.

    Loads the persisted ``ContactInquiry`` record by ``inquiry_id`` so that
    retries always work from the canonical source of truth rather than a
    potentially stale serialised payload.

    The email is sent to ``settings.contact_email``.  If that setting is not
    configured, the task exits early (no-op) — this allows the feature to
    operate without an SMTP server during development.

    Args:
        inquiry_id: UUID of the persisted ContactInquiry record.
    """
    from app.config import settings  # imported here to avoid circular import at module load

    recipient = settings.contact_email
    if not recipient:
        logger.info(
            "CONTACT_EMAIL not configured — skipping inquiry notification email",
            extra={"inquiry_id": inquiry_id},
        )
        return

    inquiry = asyncio.run(_load_inquiry(inquiry_id))
    if inquiry is None:
        logger.warning(
            "Inquiry record not found — skipping notification email",
            extra={"inquiry_id": inquiry_id},
        )
        return

    body_lines = [
        f"New school/district inquiry received (ID: {inquiry_id})",
        "",
        f"Name:               {inquiry.name}",
        f"Email:              {inquiry.email}",
        f"School:             {inquiry.school_name}",
        f"District:           {inquiry.district or '—'}",
        f"Estimated teachers: {inquiry.estimated_teachers or '—'}",
        "",
        "Message:",
        inquiry.message or "(none)",
    ]

    msg = EmailMessage()
    msg["Subject"] = f"New inquiry from {inquiry.school_name}"
    msg["From"] = recipient
    msg["To"] = recipient
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info(
            "Inquiry notification email sent",
            extra={"inquiry_id": inquiry_id, "recipient": recipient},
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send inquiry notification email — will retry",
            extra={"inquiry_id": inquiry_id, "error_type": type(exc).__name__},
        )
        # Exponential backoff: 60s, 120s, 240s for retries 0, 1, 2.
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_dpa_request_notification",
    bind=True,
    max_retries=3,
)
def send_dpa_request_notification(self: object, dpa_request_id: str) -> None:
    """Send an internal notification email when a new DPA request arrives.

    Loads the persisted ``DpaRequest`` record by ``dpa_request_id`` so that
    retries always work from the canonical source of truth.

    The email is sent to ``settings.contact_email``.  If that setting is not
    configured, the task exits early (no-op).

    Args:
        dpa_request_id: UUID of the persisted DpaRequest record.
    """
    from app.config import settings  # imported here to avoid circular import at module load

    recipient = settings.contact_email
    if not recipient:
        logger.info(
            "CONTACT_EMAIL not configured — skipping DPA request notification email",
            extra={"dpa_request_id": dpa_request_id},
        )
        return

    dpa_req = asyncio.run(_load_dpa_request(dpa_request_id))
    if dpa_req is None:
        logger.warning(
            "DPA request record not found — skipping notification email",
            extra={"dpa_request_id": dpa_request_id},
        )
        return

    body_lines = [
        f"New DPA request received (ID: {dpa_request_id})",
        "",
        f"Name:     {dpa_req.name}",
        f"Email:    {dpa_req.email}",
        f"School:   {dpa_req.school_name}",
        f"District: {dpa_req.district or '—'}",
        "",
        "Message:",
        dpa_req.message or "(none)",
    ]

    msg = EmailMessage()
    msg["Subject"] = f"New DPA request from {dpa_req.school_name}"
    msg["From"] = recipient
    msg["To"] = recipient
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info(
            "DPA request notification email sent",
            extra={"dpa_request_id": dpa_request_id, "recipient": recipient},
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send DPA request notification email — will retry",
            extra={"dpa_request_id": dpa_request_id, "error_type": type(exc).__name__},
        )
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_verification_email",
    bind=True,
    max_retries=3,
)
def send_verification_email(self: object, user_id: str, raw_token: str) -> None:
    """Send an email-verification link to a newly registered teacher.

    The verification URL is built from ``settings.frontend_url`` so the link
    takes the teacher to the frontend's ``/verify?token=<raw_token>`` page
    which then calls the backend verify endpoint.

    Args:
        user_id: UUID of the User record (used to load the recipient email).
        raw_token: The un-HMAC'd token to embed in the verification URL.
    """
    from app.config import settings  # imported here to avoid circular import at module load

    db_user = asyncio.run(_load_user(user_id))
    if db_user is None:
        logger.warning(
            "User record not found — skipping verification email",
            extra={"user_id": user_id},
        )
        return

    sender = settings.verification_email_from or settings.contact_email
    if not sender:
        logger.info(
            "Neither VERIFICATION_EMAIL_FROM nor CONTACT_EMAIL configured — "
            "skipping verification email",
            extra={"user_id": user_id},
        )
        return

    verify_url = f"{settings.frontend_url.rstrip('/')}/verify?token={raw_token}"

    body_lines = [
        f"Hi {db_user.first_name},",
        "",
        "Thanks for signing up for the Rubric Grading Engine.",
        "Please verify your email address by clicking the link below:",
        "",
        verify_url,
        "",
        "This link expires in 24 hours and can only be used once.",
        "",
        "If you did not create this account, you can safely ignore this email.",
    ]

    msg = EmailMessage()
    msg["Subject"] = "Verify your Rubric Grading Engine account"
    msg["From"] = sender
    msg["To"] = db_user.email
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info(
            "Verification email sent",
            extra={"user_id": user_id},
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send verification email — will retry",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Trial lifecycle email tasks
# ---------------------------------------------------------------------------


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_welcome_email",
    bind=True,
    max_retries=3,
)
def send_welcome_email(self: object, user_id: str) -> None:
    """Send a welcome email to a newly verified teacher.

    Triggered after email verification.  Contains a "Get Started" link to
    the onboarding wizard.  This is a transactional email; no unsubscribe
    link is required.

    No student PII is included in the email subject, body, or log lines.

    Args:
        user_id: UUID of the User record.
    """
    from app.config import settings  # noqa: PLC0415

    db_user = asyncio.run(_load_user(user_id))
    if db_user is None:
        logger.warning(
            "User record not found — skipping welcome email",
            extra={"user_id": user_id},
        )
        return

    sender = settings.verification_email_from or settings.contact_email
    if not sender:
        logger.info(
            "No sender configured — skipping welcome email",
            extra={"user_id": user_id},
        )
        return

    get_started_url = f"{settings.frontend_url.rstrip('/')}/onboarding"

    body_lines = [
        f"Hi {db_user.first_name},",
        "",
        "Welcome to the Rubric Grading Engine — your account is now active.",
        "",
        "Get started by setting up your first class and rubric:",
        "",
        get_started_url,
        "",
        "Your free trial gives you full access for 30 days.",
        "If you have any questions, just reply to this email.",
    ]

    msg = EmailMessage()
    msg["Subject"] = "Welcome to the Rubric Grading Engine"
    msg["From"] = sender
    msg["To"] = db_user.email
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info("Welcome email sent", extra={"user_id": user_id})
        asyncio.run(_write_email_audit_log(user_id, "welcome"))
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send welcome email — will retry",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_trial_expiry_warning",
    bind=True,
    max_retries=3,
)
def send_trial_expiry_warning(self: object, user_id: str, days_remaining: int) -> None:
    """Send a trial expiry warning email to a teacher.

    Called at 7 days and 1 day remaining.  Contains an upgrade CTA and an
    HMAC-signed unsubscribe link (non-transactional).

    No student PII is included in the email subject, body, or log lines.

    Args:
        user_id: UUID of the User record.
        days_remaining: Number of days left in the trial (7 or 1).
    """
    from app.config import settings  # noqa: PLC0415

    db_user = asyncio.run(_load_user(user_id))
    if db_user is None:
        logger.warning(
            "User record not found — skipping trial expiry warning",
            extra={"user_id": user_id},
        )
        return

    sender = settings.verification_email_from or settings.contact_email
    if not sender:
        logger.info(
            "No sender configured — skipping trial expiry warning",
            extra={"user_id": user_id},
        )
        return

    upgrade_url = f"{settings.frontend_url.rstrip('/')}/pricing"
    unsubscribe_url = _build_unsubscribe_url(
        user_id, "trial_warning", settings.frontend_url, settings.unsubscribe_hmac_secret
    )

    day_label = f"{days_remaining} day{'s' if days_remaining != 1 else ''}"
    body_lines = [
        f"Hi {db_user.first_name},",
        "",
        f"Your Rubric Grading Engine trial ends in {day_label}.",
        "",
        "Upgrade now to keep grading without interruption:",
        "",
        upgrade_url,
        "",
        "Your data is safe — nothing is deleted when your trial ends.",
        "",
        "—",
        f"To stop receiving these reminders: {unsubscribe_url}",
    ]

    msg = EmailMessage()
    msg["Subject"] = f"Your trial ends in {day_label} — upgrade to continue grading"
    msg["From"] = sender
    msg["To"] = db_user.email
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info(
            "Trial expiry warning sent",
            extra={"user_id": user_id, "days_remaining": days_remaining},
        )
        asyncio.run(_write_email_audit_log(user_id, "trial_warning"))
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send trial expiry warning — will retry",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_trial_expired",
    bind=True,
    max_retries=3,
)
def send_trial_expired(self: object, user_id: str) -> None:
    """Send a trial-expired notification to a teacher.

    Called on day 0.  Contains an upgrade CTA and an HMAC-signed
    unsubscribe link (non-transactional).

    No student PII is included in the email subject, body, or log lines.

    Args:
        user_id: UUID of the User record.
    """
    from app.config import settings  # noqa: PLC0415

    db_user = asyncio.run(_load_user(user_id))
    if db_user is None:
        logger.warning(
            "User record not found — skipping trial expired email",
            extra={"user_id": user_id},
        )
        return

    sender = settings.verification_email_from or settings.contact_email
    if not sender:
        logger.info(
            "No sender configured — skipping trial expired email",
            extra={"user_id": user_id},
        )
        return

    upgrade_url = f"{settings.frontend_url.rstrip('/')}/pricing"
    unsubscribe_url = _build_unsubscribe_url(
        user_id, "trial_expired", settings.frontend_url, settings.unsubscribe_hmac_secret
    )

    body_lines = [
        f"Hi {db_user.first_name},",
        "",
        "Your Rubric Grading Engine trial has ended.",
        "",
        "Your existing grades and data are preserved.  Upgrade now to resume grading:",
        "",
        upgrade_url,
        "",
        "—",
        f"To stop receiving these emails: {unsubscribe_url}",
    ]

    msg = EmailMessage()
    msg["Subject"] = "Your Rubric Grading Engine trial has ended — upgrade to continue"
    msg["From"] = sender
    msg["To"] = db_user.email
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content("\n".join(body_lines))

    try:
        _send_smtp_message(msg)
        logger.info("Trial expired email sent", extra={"user_id": user_id})
        asyncio.run(_write_email_audit_log(user_id, "trial_expired"))
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send trial expired email — will retry",
            extra={"user_id": user_id, "error_type": type(exc).__name__},
        )
        countdown = 60 * (2**self.request.retries)  # type: ignore[attr-defined]
        raise self.retry(exc=exc, countdown=countdown) from exc  # type: ignore[attr-defined]


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.scan_trial_expirations",
)
def scan_trial_expirations() -> None:
    """Daily Celery Beat task: scan for expiring trials and enqueue warning emails.

    For each ``days`` value in ``[7, 1, 0]``:
    - 7 or 1: enqueues ``send_trial_expiry_warning`` for teachers whose trial
      ends exactly that many calendar days from today (UTC).
    - 0: enqueues ``send_trial_expired`` for teachers whose trial ended
      at or before the current UTC moment (i.e. the trial has actually expired).

    Only teachers with verified email addresses are included.  This task is
    **not idempotent** — running it more than once on the same UTC day enqueues
    duplicate emails, so the Celery Beat schedule must not fire more than once
    per UTC day.

    No student PII is read or logged.
    """
    asyncio.run(_do_scan_trial_expirations())


async def _do_scan_trial_expirations() -> None:
    """Async implementation of the trial expiration scan."""
    from app.models.user import User  # noqa: PLC0415

    now = datetime.now(UTC)
    today: date = now.date()

    for days in (7, 1, 0):
        target_date = today + timedelta(days=days)
        window_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        window_end = window_start + timedelta(days=1)

        # For day 0 (expired), only select users whose trial has already ended
        # at the current moment to avoid sending "expired" emails before expiry.
        extra_conditions = [User.trial_ends_at <= now] if days == 0 else []

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User.id).where(
                    User.trial_ends_at >= window_start,
                    User.trial_ends_at < window_end,
                    User.email_verified.is_(True),
                    *extra_conditions,
                )
            )
            user_ids = [str(row[0]) for row in result.all()]

        for uid in user_ids:
            if days == 0:
                send_trial_expired.delay(user_id=uid)
                logger.info(
                    "Enqueued trial_expired task",
                    extra={"user_id": uid},
                )
            else:
                send_trial_expiry_warning.delay(user_id=uid, days_remaining=days)
                logger.info(
                    "Enqueued trial_expiry_warning task",
                    extra={"user_id": uid, "days_remaining": days},
                )
