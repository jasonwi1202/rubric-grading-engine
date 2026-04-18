"""DPA request service.

Handles storing inbound Data Processing Agreement (DPA) requests submitted
from /legal/dpa.  Rate-limiting (max 3 submissions per IP per hour) is
enforced using Redis counters.

No student PII is collected, processed, or stored by this service.
"""

from __future__ import annotations

import logging

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import RateLimitError
from app.models.dpa_request import DpaRequest
from app.schemas.dpa import DpaRequestCreate

logger = logging.getLogger(__name__)

# Rate-limit constants — stricter than the contact inquiry endpoint because
# DPA requests are expected to be rare (one per district, not per teacher).
_RATE_LIMIT_MAX = 3
_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour


def _rate_limit_key(ip: str) -> str:
    """Return the Redis key used to track DPA submission counts for an IP."""
    return f"contact:dpa_request:ratelimit:{ip}"


async def _check_rate_limit(redis_client: Redis, ip: str) -> None:  # type: ignore[type-arg]
    """Raise RateLimitError if the IP has exceeded the rate limit.

    Uses a simple Redis counter with a 1-hour TTL.
    """
    key = _rate_limit_key(ip)
    current: int = await redis_client.incr(key)
    if current == 1:
        await redis_client.expire(key, _RATE_LIMIT_WINDOW_SECONDS)
    if current > _RATE_LIMIT_MAX:
        raise RateLimitError(
            "Too many DPA request submissions from this IP. Please try again later.",
        )


async def create_dpa_request(
    db: AsyncSession,
    redis_client: Redis,  # type: ignore[type-arg]
    payload: DpaRequestCreate,
    submitter_ip: str | None,
) -> DpaRequest:
    """Persist a new DPA request and enforce rate limiting.

    Args:
        db: Async database session.
        redis_client: Redis client used for rate-limit tracking.
        payload: Validated DPA request data.
        submitter_ip: IP address of the submitter (may be None in tests).

    Returns:
        The newly created ``DpaRequest`` ORM instance.

    Raises:
        RateLimitError: If the submitter IP has exceeded the rate limit.
    """
    if submitter_ip:
        await _check_rate_limit(redis_client, submitter_ip)

    dpa_request = DpaRequest(
        name=payload.name,
        email=payload.email,
        school_name=payload.school_name,
        district=payload.district,
        message=payload.message,
        submitter_ip=submitter_ip,
    )
    db.add(dpa_request)
    await db.commit()
    await db.refresh(dpa_request)

    logger.info(
        "DPA request created",
        extra={"dpa_request_id": str(dpa_request.id)},
    )
    return dpa_request
