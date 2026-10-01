import logging
from fastapi import APIRouter, Response
from datetime import datetime, timezone
from sqlalchemy import text
from Clinic_app.common.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

health_router = APIRouter()


@health_router.get("/health")
async def health_check(response: Response):
    """Health check endpoint for load balancers and monitoring.

    Returns 200 when healthy, 503 when the database is unreachable.
    """
    # Test database connection
    db_status = "connected"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.error(f"Health check database error: {e}", exc_info=True)
        db_status = "disconnected"

    # Determine overall status
    overall_status = "healthy" if db_status == "connected" else "unhealthy"

    if overall_status != "healthy":
        response.status_code = 503

    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "CallCenterAI API",
        "database": db_status,
    }


@health_router.get("/ping")
async def ping():
    """Simple ping endpoint - fastest response."""
    return {"pong": datetime.now(timezone.utc).isoformat()}
