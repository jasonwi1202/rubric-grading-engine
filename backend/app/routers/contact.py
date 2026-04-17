"""Contact inquiry router.

Exposes a single public endpoint for school/district purchase inquiries
submitted from the pricing page.  No authentication is required — this is
a public-facing form endpoint.

Rate limiting (max 5 submissions per IP per hour) is enforced in the
service layer using Redis.
"""

import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.schemas.contact import ContactInquiryRequest, ContactInquiryResponse
from app.services.contact import create_inquiry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


class _InquiryResponseEnvelope(BaseModel):
    """Standard data envelope wrapping a ContactInquiryResponse."""

    data: ContactInquiryResponse


async def _get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency that yields an async Redis client and closes it on teardown."""
    from app.config import settings

    client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


def _get_client_ip(request: Request) -> str | None:
    """Extract the client IP address from the direct request connection.

    This public unauthenticated endpoint does not trust ``X-Forwarded-For``
    headers — a caller can spoof them to bypass per-IP rate limiting.  Use
    the direct socket address instead.
    """
    if request.client:
        return request.client.host
    return None


@router.post(
    "/inquiry",
    status_code=201,
    response_model=_InquiryResponseEnvelope,
    summary="Submit a school or district purchase inquiry",
)
async def submit_inquiry(
    request: Request,
    payload: ContactInquiryRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),
) -> JSONResponse:
    """Store an inbound school/district inquiry and enqueue a notification email.

    - Input is validated by the ``ContactInquiryRequest`` Pydantic model.
    - Rate-limited to 5 requests per IP per hour (raises 429 on excess).
    - No student PII is collected or stored.
    - On success, enqueues a Celery task to send a notification email to
      ``settings.contact_email``.
    """
    client_ip = _get_client_ip(request)
    inquiry = await create_inquiry(db, redis_client, payload, client_ip)

    # Enqueue notification email asynchronously.  This is fire-and-forget:
    # a failure to send the email does not affect the HTTP response.
    try:
        from app.tasks.email import send_inquiry_notification

        send_inquiry_notification.delay(inquiry_id=str(inquiry.id))
    except Exception:
        logger.exception(
            "Failed to enqueue inquiry notification task",
            extra={"inquiry_id": str(inquiry.id)},
        )

    response_data = ContactInquiryResponse.model_validate(inquiry)
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )
