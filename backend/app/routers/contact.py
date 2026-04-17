"""Contact inquiry router.

Exposes a single public endpoint for school/district purchase inquiries
submitted from the pricing page.  No authentication is required — this is
a public-facing form endpoint.

Rate limiting (max 5 submissions per IP per hour) is enforced in the
service layer using Redis.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis import Redis

from app.db.session import AsyncSession, get_db
from app.schemas.contact import ContactInquiryRequest, ContactInquiryResponse
from app.services.contact import create_inquiry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


class _InquiryResponseEnvelope(BaseModel):
    """Standard data envelope wrapping a ContactInquiryResponse."""

    data: ContactInquiryResponse


def _get_redis() -> Redis:  # type: ignore[type-arg]
    """FastAPI dependency that returns a Redis client."""
    from app.config import settings

    return Redis.from_url(settings.redis_url, decode_responses=True)


def _get_client_ip(request: Request) -> str | None:
    """Extract the real client IP from the request.

    Checks ``X-Forwarded-For`` first (set by reverse proxies such as nginx or
    Railway's edge), falling back to the direct connection address.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # The header may contain a comma-separated list; the first entry is the
        # original client IP.
        return forwarded_for.split(",")[0].strip()
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
    redis_client: Redis = Depends(_get_redis),  # type: ignore[type-arg]
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

        send_inquiry_notification.delay(
            inquiry_id=str(inquiry.id),
            name=inquiry.name,
            school_name=inquiry.school_name,
            email=inquiry.email,
            district=inquiry.district,
            estimated_teachers=inquiry.estimated_teachers,
            message=inquiry.message,
        )
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
