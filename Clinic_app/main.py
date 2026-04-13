import os
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
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
from Clinic_app.common.rate_limit import admin_rate_limit
from Clinic_app.workers.booking_reaper import scheduler, run_booking_reaper
from Clinic_app.workers.campaign_worker import (
    campaign_worker_manager,
    resume_active_campaign_workers,
)
from Clinic_app.services.playwright_ehr import playwright_ehr_service
from Clinic_app.workers.slot_prefetch_worker import slot_prefetch_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
_allowed_origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_is_dev = os.environ.get("APP_ENVIRONMENT", "").lower() in ("development", "dev", "local")

if not _allowed_origins and _is_dev:
    _cors_origins: list[str] = ["*"]
    logger.warning(
        "ALLOWED_ORIGINS is not set — allowing all origins. "
        "Set ALLOWED_ORIGINS in production."
    )
else:
    _cors_origins = _allowed_origins  # empty list → no cross-origin allowed in prod

# allow_credentials=True requires explicit origins (not "*").
_cors_credentials = bool(_cors_origins) and "*" not in _cors_origins


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

    try:
        await resume_active_campaign_workers()
    except Exception as e:
        logger.warning("Campaign worker resume failed: %s", e)

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down CallCenterAI API")
    try:
        await campaign_worker_manager.shutdown_all()
    except Exception as e:
        logger.warning("Campaign worker shutdown: %s", e)
    try:
        await slot_prefetch_manager.stop_all()
    except Exception as e:
        logger.warning("SlotPrefetchWorker shutdown: %s", e)
    scheduler.shutdown(wait=False)
    try:
        await playwright_ehr_service.shutdown_all()
    except Exception as e:
        logger.warning("PlaywrightEHRService shutdown: %s", e)
    await close_redis()


# Create FastAPI app
_is_production = os.environ.get("APP_ENVIRONMENT", "").lower() in ("production", "prod")
app = FastAPI(
    title="CallCenterAI API",
    description="API for Call Center AI operations",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    lifespan=lifespan,
)

# Register CORS middleware — must be added before routers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
)


# ── Routers ───────────────────────────────────────────────────────────────────

# Health — no auth
app.include_router(health_router)

# Admin routes — protected by API key + rate limited
app.include_router(admin_router, dependencies=[
    Depends(verify_admin_api_key),
    Depends(admin_rate_limit()),
])
app.include_router(provider_router, dependencies=[
    Depends(verify_admin_api_key),
    Depends(admin_rate_limit()),
])

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
    """General exception handler. Never leaks exception details in production."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    content: dict = {"error": "Internal server error"}
    if _is_dev:
        # Include traceback details locally so Edgar can debug without grepping logs.
        content["type"] = type(exc).__name__
        content["message"] = str(exc)
    return JSONResponse(status_code=500, content=content)


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
