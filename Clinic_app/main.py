from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse

from Clinic_app.Routes.health import health_router
from Clinic_app.Routes.admin import admin_router
from Clinic_app.Routes.retell import retell_router
from Clinic_app.Routes.provider import provider_router
from Clinic_app.Routes.auth import auth_router
from Clinic_app.Routes.clinic import clinic_router
from Clinic_app.Routes.campaigns import campaign_router
from Clinic_app.common.auth import verify_admin_api_key
from Clinic_app.common.redis import close_redis
from Clinic_app.workers.booking_reaper import scheduler, run_booking_reaper
from Clinic_app.services.playwright_ehr import playwright_ehr_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting up CallCenterAI API")

    # Start booking reaper (runs every 60 seconds)
    scheduler.add_job(run_booking_reaper, "interval", seconds=60, id="booking_reaper")
    scheduler.start()
    logger.info("Booking reaper scheduled (interval=60s)")

    try:
        await playwright_ehr_service.startup()
        logger.info("PlaywrightEHRService started")
    except Exception as e:
        logger.warning("PlaywrightEHRService startup failed — EHR tools may be unavailable: %s", e)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down CallCenterAI API")
    scheduler.shutdown(wait=False)
    try:
        await playwright_ehr_service.shutdown_all()
    except Exception as e:
        logger.warning("PlaywrightEHRService shutdown: %s", e)
    await close_redis()


# Create FastAPI app
app = FastAPI(
    title="CallCenterAI API",
    description="API for Call Center AI operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Routers ───────────────────────────────────────────────────────────────────

# Health — no auth
app.include_router(health_router)

# Admin routes — protected by API key
app.include_router(admin_router, dependencies=[Depends(verify_admin_api_key)])
app.include_router(provider_router, dependencies=[Depends(verify_admin_api_key)])

# Retell webhooks + tool endpoints — auth handled internally via HMAC signature
app.include_router(retell_router)

# Auth — Google OAuth + JWT (each endpoint manages its own auth)
app.include_router(auth_router)

# Clinic settings — scoped JWT, admin write
app.include_router(clinic_router)

# Campaigns — CSV/Excel upload, management, export
app.include_router(campaign_router)


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": "CallCenterAI API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# ── Error handler ─────────────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """General exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
