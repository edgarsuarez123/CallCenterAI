from fastapi import APIRouter
from datetime import datetime, timezone

health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "CallCenterAI API"
    }


@health_router.get("/ping")
async def ping():
    """Simple ping endpoint - fastest response."""
    return {"pong": datetime.now(timezone.utc).isoformat()}

