"""Contact inquiry router.

Exposes public endpoints for school/district purchase inquiries and DPA
requests.  No authentication is required — these are public-facing form
endpoints.

Rate limiting is enforced in the service layer using Redis.
"""

import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from app.db.session import AsyncSession, get_db
from app.schemas.contact import ContactInquiryRequest, ContactInquiryResponse
from app.schemas.dpa import DpaRequestCreate, DpaRequestResponse
from app.services.contact import create_inquiry
from app.services.dpa import create_dpa_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])


class _InquiryResponseEnvelope(BaseModel):
    """Standard data envelope wrapping a ContactInquiryResponse."""

    data: ContactInquiryResponse


class _DpaResponseEnvelope(BaseModel):
    """Standard data envelope wrapping a DpaRequestResponse."""

    data: DpaRequestResponse


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


@router.post(
    "/dpa-request",
    status_code=201,
    response_model=_DpaResponseEnvelope,
    summary="Submit a Data Processing Agreement request",
)
async def submit_dpa_request(
    request: Request,
    payload: DpaRequestCreate,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(_get_redis),
) -> JSONResponse:
    """Store an inbound DPA request and enqueue a notification email.

    - Input is validated by the ``DpaRequestCreate`` Pydantic model.
    - Rate-limited to 3 requests per IP per hour (raises 429 on excess).
    - No student PII is collected or stored.
    - On success, enqueues a Celery task to send a notification email to
      ``settings.contact_email``.
    """
    client_ip = _get_client_ip(request)
    dpa_req = await create_dpa_request(db, redis_client, payload, client_ip)

    # Enqueue notification email asynchronously.  Fire-and-forget.
    try:
        from app.tasks.email import send_dpa_request_notification

        send_dpa_request_notification.delay(dpa_request_id=str(dpa_req.id))
    except Exception:
        logger.exception(
            "Failed to enqueue DPA request notification task",
            extra={"dpa_request_id": str(dpa_req.id)},
        )

    response_data = DpaRequestResponse.model_validate(dpa_req)
    return JSONResponse(
        status_code=201,
        content={"data": response_data.model_dump(mode="json")},
    )
