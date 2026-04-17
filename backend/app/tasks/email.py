"""Email notification Celery tasks.

Tasks in this module send notification emails for internal operational
purposes (e.g. new school inquiry alerts).  They do not send email to
students or process student data.
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
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
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
