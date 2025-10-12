"""
API Routes Package
Comprehensive REST API endpoints for the CallCenterAI system.
"""

from fastapi import APIRouter
from .clinics import router as clinics_router
from .providers import router as providers_router
from .appointments import router as appointments_router
from .google_calendar import router as google_calendar_router
from .call_simulator import router as call_simulator_router

# Create main API router
api_router = APIRouter(prefix="/api")

# Include all route modules
api_router.include_router(clinics_router)
api_router.include_router(providers_router)
api_router.include_router(appointments_router)
api_router.include_router(google_calendar_router)
api_router.include_router(call_simulator_router)

# Export the main router
__all__ = ["api_router"]
