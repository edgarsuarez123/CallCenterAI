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
from Clinic_app.common.auth import verify_admin_api_key

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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
    docs_url="/docs",
    redoc_url="/redoc",
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
                "Secured via HMAC-SHA256 signature verification. "
                "Phase 2 booking tool endpoints are included for completeness."
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

cors_origins_raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
cors_origins = [o.strip() for o in cors_origins_raw.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# ROUTERS
# ============================================================================

app.include_router(health_router)

# Admin routes — API key required
app.include_router(
    admin_router,
    dependencies=[Depends(verify_admin_api_key)],
)
app.include_router(
    campaign_router,
    dependencies=[Depends(verify_admin_api_key)],
)

# Retell routes — signature-verified internally
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
    """Catch-all exception handler — logs error, returns 500."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )


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
