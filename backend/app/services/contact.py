"""Contact inquiry service.

Handles storing inbound school/district purchase inquiries.  Rate-limiting
(max 5 submissions per IP per hour) is enforced here using Redis counters
so that the router stays thin and the logic is unit-testable.

No student PII is collected, processed, or stored by this service.
"""

import logging

from redis import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import RateLimitError
from app.models.contact import ContactInquiry
from app.schemas.contact import ContactInquiryRequest

logger = logging.getLogger(__name__)

# Rate-limit constants
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour


def _rate_limit_key(ip: str) -> str:
    """Return the Redis key used to track submission counts for an IP."""
    return f"contact:inquiry:ratelimit:{ip}"


def _check_rate_limit(redis_client: Redis, ip: str) -> None:  # type: ignore[type-arg]
    """Raise ValidationError if the IP has exceeded the rate limit.

    Uses a simple Redis counter with a 1-hour TTL.  The counter is
    incremented atomically and the TTL is set only on first creation so
    that the window resets naturally after one hour.
    """
    key = _rate_limit_key(ip)
    current: int = redis_client.incr(key)
    if current == 1:
        # First submission within this window — set the expiry.
        redis_client.expire(key, _RATE_LIMIT_WINDOW_SECONDS)
    if current > _RATE_LIMIT_MAX:
        raise RateLimitError(
            "Too many inquiry submissions from this IP. Please try again later.",
        )


async def create_inquiry(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    payload: ContactInquiryRequest,
    submitter_ip: str | None,
) -> ContactInquiry:
    """Persist a new contact inquiry and enforce rate limiting.

    Args:
        db: Async database session.
        redis_client: Redis client used for rate-limit tracking.
        payload: Validated inquiry request data.
        submitter_ip: IP address of the submitter (may be None in tests).

    Returns:
        The newly created ``ContactInquiry`` ORM instance.

    Raises:
        ValidationError: If the submitter IP has exceeded the rate limit.
    """
    if submitter_ip:
        _check_rate_limit(redis_client, submitter_ip)

    inquiry = ContactInquiry(
        name=payload.name,
        email=payload.email,
        school_name=payload.school_name,
        district=payload.district,
        estimated_teachers=payload.estimated_teachers,
        message=payload.message,
        submitter_ip=submitter_ip,
    )
    db.add(inquiry)
    await db.commit()
    await db.refresh(inquiry)

    logger.info(
        "Contact inquiry created",
        extra={"inquiry_id": str(inquiry.id)},
    )
    return inquiry
