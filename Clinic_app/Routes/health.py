from fastapi import APIRouter
from datetime import datetime, timezone
from sqlalchemy import text
from Clinic_app.common.database import AsyncSessionLocal

health_router = APIRouter()


@health_router.get("/health")
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    # Test database connection
    db_status = "connected"
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"disconnected: {str(e)}"
    
    # Determine overall status
    overall_status = "healthy" if db_status == "connected" else "unhealthy"
    
    return {
        "status": overall_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "CallCenterAI API",
        "database": db_status
    }


@health_router.get("/ping")
async def ping():
    """Simple ping endpoint - fastest response."""
    return {"pong": datetime.now(timezone.utc).isoformat()}

