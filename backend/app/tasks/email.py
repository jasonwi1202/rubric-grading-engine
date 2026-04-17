"""Email notification Celery tasks.

Tasks in this module send notification emails for internal operational
purposes (e.g. new school inquiry alerts).  They do not send email to
students or process student data.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(  # type: ignore[untyped-decorator]
    name="tasks.email.send_inquiry_notification",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def send_inquiry_notification(
    self: object,
    inquiry_id: str,
    name: str,
    school_name: str,
    email: str,
    district: str | None,
    estimated_teachers: int | None,
    message: str | None,
) -> None:
    """Send an internal notification email when a new contact inquiry arrives.

    The email is sent to ``settings.contact_email``.  If that setting is not
    configured, the task exits early (no-op) — this allows the feature to
    operate without an SMTP server during development.

    Args:
        inquiry_id: UUID of the persisted ContactInquiry record.
        name: Submitter's name.
        school_name: School or district name from the form.
        email: Submitter's email address.
        district: Optional district name.
        estimated_teachers: Optional teacher count.
        message: Optional free-text message.
    """
    from app.config import settings  # imported here to avoid circular import at module load

    recipient = settings.contact_email
    if not recipient:
        logger.info(
            "CONTACT_EMAIL not configured — skipping inquiry notification email",
            extra={"inquiry_id": inquiry_id},
        )
        return

    body_lines = [
        f"New school/district inquiry received (ID: {inquiry_id})",
        "",
        f"Name:               {name}",
        f"Email:              {email}",
        f"School:             {school_name}",
        f"District:           {district or '—'}",
        f"Estimated teachers: {estimated_teachers or '—'}",
        "",
        "Message:",
        message or "(none)",
    ]

    msg = EmailMessage()
    msg["Subject"] = f"New inquiry from {school_name}"
    msg["From"] = recipient
    msg["To"] = recipient
    msg.set_content("\n".join(body_lines))

    try:
        with smtplib.SMTP("localhost") as smtp:
            smtp.send_message(msg)
        logger.info(
            "Inquiry notification email sent",
            extra={"inquiry_id": inquiry_id, "recipient": recipient},
        )
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "Failed to send inquiry notification email — will retry",
            extra={"inquiry_id": inquiry_id, "error": str(exc)},
        )
        raise self.retry(exc=exc) from exc  # type: ignore[attr-defined]
