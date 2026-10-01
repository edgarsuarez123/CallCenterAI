"""
CallCenterAI — HEDIS Outreach Automation Platform
FastAPI application factory.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from Clinic_app.Routes.health import health_router
from Clinic_app.Routes.admin import admin_router
from Clinic_app.Routes.campaign import campaign_router
from Clinic_app.Routes.retell import retell_router
from Clinic_app.Routes.provider import provider_router
from Clinic_app.Routes.auth import auth_router
from Clinic_app.Routes.clinic import clinic_router
from Clinic_app.common.auth import verify_admin_api_key

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================================
# CORS
# ============================================================================

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
_allowed_origins: list[str] = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_is_dev = os.environ.get("APP_ENVIRONMENT", "development").lower() in ("development", "dev", "local")

if not _allowed_origins:
    # Fall back to CORS_ORIGINS env var (retell branch convention)
    _cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    _allowed_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if _is_dev:
        logger.warning(
            "ALLOWED_ORIGINS is not set — using CORS_ORIGINS fallback. "
            "Set ALLOWED_ORIGINS in production."
        )

_cors_credentials = bool(_allowed_origins) and "*" not in _allowed_origins

# ============================================================================
# LIFESPAN — startup / shutdown
# ============================================================================

_worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background workers on startup; cancel them on shutdown."""
    global _worker_task
    from Clinic_app.workers.campaign_worker import run_campaign_worker

    logger.info("Starting campaign background worker")
    _worker_task = asyncio.create_task(run_campaign_worker())

    yield  # Application runs here

    logger.info("Stopping campaign background worker")
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


# ============================================================================
# APP FACTORY
# ============================================================================

_is_production = os.environ.get("APP_ENVIRONMENT", "").lower() in ("production", "prod")

app = FastAPI(
    title="CallCenterAI — HEDIS Outreach Automation",
    description="""
## What This Does

**CallCenterAI** automates HEDIS care-gap outreach for primary care clinics.
Clinics upload a CSV of patients; the system places AI voice calls (via Retell AI),
records each patient's response, and generates an outcome report — all without
staff intervention.

## Architecture

- **Multi-tenant** — every query is scoped to `clinic_id` (row-level isolation)
- **HIPAA-compliant PHI** — patient names and phone numbers are encrypted at rest
  with AES-256-GCM; phone numbers are never logged in plaintext
- **Booking engine** (Phase 2) — inbound scheduling via Google Calendar integration
  is implemented but not activated in this release

## Authentication

Admin routes require an `X-API-Key` header. Retell webhook routes use HMAC-SHA256
signature verification.

## Demo Mode

When `RETELL_API_KEY` is not configured, the campaign worker simulates call outcomes
locally. Use `POST /admin/clinics/{clinic_id}/campaigns/{campaign_id}/process-next`
to manually step through contacts during a demo.

## Quick Start

```bash
docker compose -f docker-compose.dev.yaml up
python scripts/seed_demo.py       # load demo data
# visit http://localhost:8000/docs
```
""",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    contact={
        "name": "Edgar J. Suárez Colón",
        "url": "https://github.com/EdgarJSuarez",
    },
    openapi_tags=[
        {
            "name": "Campaigns",
            "description": (
                "Outbound HEDIS outreach campaign management. "
                "Create campaigns, upload patient CSVs, start/pause processing, view reports."
            ),
        },
        {
            "name": "Clinic Admin",
            "description": (
                "Clinic, integration, license, and provider CRUD. "
                "All routes require X-API-Key header."
            ),
        },
        {
            "name": "Retell Webhooks",
            "description": (
                "Webhook endpoints called by Retell AI during voice calls. "
                "Secured via HMAC-SHA256 signature verification."
            ),
        },
        {
            "name": "Health",
            "description": "Health check and liveness endpoints.",
        },
    ],
    lifespan=lifespan,
)

# ============================================================================
# MIDDLEWARE
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# ============================================================================
# ROUTERS
# ============================================================================

# Health — no auth
app.include_router(health_router)

# Admin routes — protected by API key
app.include_router(admin_router, dependencies=[Depends(verify_admin_api_key)])
app.include_router(campaign_router, dependencies=[Depends(verify_admin_api_key)])
app.include_router(provider_router, dependencies=[Depends(verify_admin_api_key)])

# Clinic settings — scoped JWT auth managed internally
app.include_router(clinic_router)

# Auth — Google OAuth + JWT (each endpoint manages its own auth)
app.include_router(auth_router)

# Retell webhooks — HMAC signature verified internally
app.include_router(retell_router)

# ============================================================================
# ROOT + ERROR HANDLING
# ============================================================================


@app.get("/", tags=["Health"])
def root():
    """Root endpoint — API discovery."""
    return {
        "message": "CallCenterAI API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health",
    }


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Catch-all exception handler — logs error, never leaks details in production."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    content: dict = {"error": "Internal server error"}
    if _is_dev:
        content["type"] = type(exc).__name__
        content["message"] = str(exc)
    return JSONResponse(status_code=500, content=content)


# ============================================================================
# ENTRYPOINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "Clinic_app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("APP_PORT", "8000")),
        reload=True,
        log_level="info",
    )
