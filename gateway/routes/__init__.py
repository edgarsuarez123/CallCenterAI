"""
API Routes Package
Comprehensive REST API endpoints for the CallCenterAI system.
"""

from fastapi import APIRouter
from services.configuration import get_settings
from .clinics import router as clinics_router
from .providers import router as providers_router
from .appointments import router as appointments_router
from .google_calendar import router as google_calendar_router
from .call_simulator import router as call_simulator_router
from .background_jobs import router as background_jobs_router
from .azure_communication import router as azure_communication_router
from .reminders import router as reminders_router
from .tokens import router as tokens_router

# Get configuration
settings = get_settings()

# Create main API router with configured prefix
api_router = APIRouter(prefix=settings.api_prefix)

# Include all route modules
api_router.include_router(clinics_router)
api_router.include_router(providers_router)
api_router.include_router(appointments_router)
api_router.include_router(google_calendar_router)
api_router.include_router(call_simulator_router)
api_router.include_router(background_jobs_router)
api_router.include_router(azure_communication_router)
api_router.include_router(reminders_router)
api_router.include_router(tokens_router)

# Export the main router
__all__ = ["api_router"]
