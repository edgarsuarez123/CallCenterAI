"""
Campaign management routes for outbound HEDIS outreach.

All routes are protected by admin API key auth (applied in main.py).
All routes enforce clinic_id tenant isolation.

Flow:
  1. POST /campaigns          — create campaign (name + reason)
  2. POST /campaigns/{id}/upload   — upload patient CSV
  3. POST /campaigns/{id}/start    — queue campaign for processing
  4. POST /campaigns/{id}/process-next  — (demo) manually process one contact
  5. GET  /campaigns/{id}/report   — view decrypted outcomes report
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import get_db
from Clinic_app.common.schemas import APIResponse
from Clinic_app.services.campaign import (
    create_campaign,
    get_campaign,
    list_campaigns,
    start_campaign,
    pause_campaign,
    upload_contacts,
    get_campaign_report,
    simulate_next_call,
)

logger = logging.getLogger(__name__)

campaign_router = APIRouter(
    prefix="/admin/clinics/{clinic_id}/campaigns",
    tags=["Campaigns"],
)


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class CampaignCreateRequest(BaseModel):
    """Request body for creating a new outreach campaign."""
    name: str
    reason: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Q3 HEDIS Wellness Outreach",
                "reason": "Annual wellness visit is overdue. Your care team recommends scheduling a visit this month.",
            }
        }
    }


class CampaignResponse(BaseModel):
    """Campaign summary returned by list and detail endpoints."""
    id: str
    clinic_id: str
    name: str
    reason: str
    status: str
    total_contacts: int
    completed_contacts: int
    progress_pct: float
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


def _campaign_to_dict(c) -> dict:
    progress = (c.completed_contacts / c.total_contacts * 100) if c.total_contacts > 0 else 0.0
    return {
        "id": str(c.id),
        "clinic_id": str(c.clinic_id),
        "name": c.name,
        "reason": c.reason,
        "status": c.status,
        "total_contacts": c.total_contacts,
        "completed_contacts": c.completed_contacts,
        "progress_pct": round(progress, 1),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


# ============================================================================
# ENDPOINTS
# ============================================================================

@campaign_router.post(
    "",
    response_model=APIResponse,
    summary="Create outreach campaign",
    description=(
        "Create a new outbound outreach campaign for a clinic. "
        "The campaign starts in **DRAFT** status. "
        "Upload a patient CSV next, then call /start to begin processing."
    ),
)
async def create_campaign_endpoint(
    clinic_id: UUID,
    body: CampaignCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        campaign = await create_campaign(
            db=db,
            clinic_id=clinic_id,
            name=body.name,
            reason=body.reason,
        )
        await db.commit()
        return APIResponse(success=True, data=_campaign_to_dict(campaign))
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create campaign: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@campaign_router.get(
    "",
    response_model=APIResponse,
    summary="List campaigns for a clinic",
    description="Returns all campaigns for the clinic, optionally filtered by status.",
)
async def list_campaigns_endpoint(
    clinic_id: UUID,
    status: Optional[str] = Query(None, description="Filter by status: draft|queued|running|paused|completed"),
    db: AsyncSession = Depends(get_db),
):
    campaigns = await list_campaigns(db, clinic_id, status_filter=status)
    return APIResponse(
        success=True,
        data=[_campaign_to_dict(c) for c in campaigns],
    )


@campaign_router.get(
    "/{campaign_id}",
    response_model=APIResponse,
    summary="Get campaign details",
)
async def get_campaign_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return APIResponse(success=True, data=_campaign_to_dict(campaign))


@campaign_router.post(
    "/{campaign_id}/upload",
    response_model=APIResponse,
    summary="Upload patient CSV",
    description=(
        "Upload a CSV of patients to call. Required columns: **patient_name**, **phone**. "
        "Optional column: **reason** (overrides campaign default per patient). "
        "Phone numbers are normalized to E.164. "
        "Duplicate phone numbers within the same clinic are skipped. "
        "All PHI is encrypted at rest with AES-256-GCM before storage."
    ),
)
async def upload_contacts_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    file: UploadFile = File(..., description="CSV file with patient_name and phone columns"),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=413, detail="CSV file exceeds 10MB limit")

    result = await upload_contacts(
        db=db,
        campaign_id=campaign_id,
        clinic_id=clinic_id,
        csv_content=content,
        default_reason=campaign.reason,
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    await db.commit()
    return APIResponse(
        success=True,
        data=result,
        message=f"Imported {result['imported']} contacts",
    )


@campaign_router.post(
    "/{campaign_id}/start",
    response_model=APIResponse,
    summary="Start campaign",
    description=(
        "Transition a campaign from DRAFT or PAUSED to **QUEUED**. "
        "The background campaign worker will pick it up and begin placing calls. "
        "In demo mode (no RETELL_API_KEY configured), use /process-next to simulate calls manually."
    ),
)
async def start_campaign_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign, error = await start_campaign(db, campaign_id, clinic_id)
    if error:
        raise HTTPException(status_code=400, detail=error)
    await db.commit()
    return APIResponse(success=True, data=_campaign_to_dict(campaign))


@campaign_router.post(
    "/{campaign_id}/pause",
    response_model=APIResponse,
    summary="Pause campaign",
    description="Pause a RUNNING or QUEUED campaign. Can be resumed by calling /start again.",
)
async def pause_campaign_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign, error = await pause_campaign(db, campaign_id, clinic_id)
    if error:
        raise HTTPException(status_code=400, detail=error)
    await db.commit()
    return APIResponse(success=True, data=_campaign_to_dict(campaign))


@campaign_router.post(
    "/{campaign_id}/process-next",
    response_model=APIResponse,
    summary="[Demo] Process next contact",
    description=(
        "**Demo mode endpoint.** Picks the next PENDING contact in the campaign and "
        "simulates a call outcome (ACCEPTED / DECLINED / VOICEMAIL / NO_ANSWER / FAILED) "
        "with realistic probability weights. "
        "Does not make real API calls. "
        "Call this repeatedly to walk through contacts one at a time during a demo. "
        "In production, the background worker handles this automatically."
    ),
)
async def process_next_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.status not in ("queued", "running", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Campaign must be in queued/running/paused status to process. Current: {campaign.status}",
        )

    result = await simulate_next_call(db, campaign_id, clinic_id)
    await db.commit()
    return APIResponse(success=True, data=result)


@campaign_router.get(
    "/{campaign_id}/report",
    response_model=APIResponse,
    summary="Get campaign outcome report",
    description=(
        "Returns a decrypted report of all contacts and their call outcomes. "
        "Patient names are decrypted from AES-256-GCM storage for display. "
        "Phone numbers are shown as last 4 digits only (***-***-XXXX). "
        "This is the clinic-facing view: patient name | reason | outcome | call date."
    ),
)
async def get_report_endpoint(
    clinic_id: UUID,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    campaign, rows = await get_campaign_report(db, campaign_id, clinic_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    return APIResponse(
        success=True,
        data={
            "campaign": _campaign_to_dict(campaign),
            "contacts": rows,
            "summary": {
                "total": len(rows),
                "accepted": sum(1 for r in rows if r["outcome"] == "accepted"),
                "declined": sum(1 for r in rows if r["outcome"] == "declined"),
                "voicemail": sum(1 for r in rows if r["outcome"] == "voicemail"),
                "no_answer": sum(1 for r in rows if r["outcome"] == "no_answer"),
                "failed": sum(1 for r in rows if r["outcome"] == "failed"),
                "pending": sum(1 for r in rows if r["outcome"] == "pending"),
            },
        },
    )
