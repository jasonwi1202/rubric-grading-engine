"""Email notification Celery tasks.

Tasks in this module send notification emails for internal operational
purposes (e.g. new school inquiry alerts, DPA request alerts, email
verification).  They do not send email to students or process student data.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import uuid
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
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
        ) as smtp:
            smtp.send_message(msg)
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
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
        ) as smtp:
            smtp.send_message(msg)
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
    takes the teacher to the frontend's ``/auth/verify?token=<raw_token>`` page
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
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout
        ) as smtp:
            smtp.send_message(msg)
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
