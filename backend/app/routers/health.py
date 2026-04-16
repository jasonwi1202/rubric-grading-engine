"""Health check router."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return service health status."""
    return JSONResponse(content={"status": "ok"})
