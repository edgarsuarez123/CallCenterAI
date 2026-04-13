# Clinic_app/Routes/clinic.py
"""
Clinic settings API.
Allows clinic staff to read and update their clinic's operational defaults
(calling hours, max attempts, retry hours, timezone).

GET  /clinic/settings  — any scoped staff
PATCH /clinic/settings — admin role only
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import get_db
from Clinic_app.common.jwt import StaffToken, require_scoped_staff
from Clinic_app.common.rate_limit import auth_rate_limit
from Clinic_app.services.clinic_service import get_clinic_settings, update_clinic_settings

logger = logging.getLogger(__name__)

clinic_router = APIRouter(prefix="/clinic", tags=["clinic"])


# ── Response schema ────────────────────────────────────────────────────────────

class ClinicSettingsResponse(BaseModel):
    timezone: str
    calling_hours_start: str
    calling_hours_end: str
    campaign_concurrency_limit: int
    max_attempts: int
    voicemail_retry_hours: int
    no_answer_retry_hours: int
    error_retry_hours: int


# ── PATCH request body ─────────────────────────────────────────────────────────

class ClinicSettingsPatch(BaseModel):
    calling_hours_start: Optional[str] = None
    calling_hours_end: Optional[str] = None
    campaign_concurrency_limit: Optional[int] = None
    max_attempts: Optional[int] = None
    voicemail_retry_hours: Optional[int] = None
    no_answer_retry_hours: Optional[int] = None
    error_retry_hours: Optional[int] = None
    timezone: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@clinic_router.get("/settings", response_model=ClinicSettingsResponse)
async def get_settings(
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> ClinicSettingsResponse:
    """Return current operational settings for the staff member's clinic."""
    integration = await get_clinic_settings(db, staff.clinic_id)
    return ClinicSettingsResponse(
        timezone=integration.timezone,
        calling_hours_start=integration.calling_hours_start,
        calling_hours_end=integration.calling_hours_end,
        campaign_concurrency_limit=integration.campaign_concurrency_limit,
        max_attempts=integration.max_attempts,
        voicemail_retry_hours=integration.voicemail_retry_hours,
        no_answer_retry_hours=integration.no_answer_retry_hours,
        error_retry_hours=integration.error_retry_hours,
    )


@clinic_router.patch("/settings", response_model=ClinicSettingsResponse)
async def patch_settings(
    body: ClinicSettingsPatch,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> ClinicSettingsResponse:
    """Update operational settings for the clinic. Requires admin role."""
    if staff.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "Only clinic admins can update settings."},
        )

    integration = await update_clinic_settings(
        db,
        staff.clinic_id,
        calling_hours_start=body.calling_hours_start,
        calling_hours_end=body.calling_hours_end,
        campaign_concurrency_limit=body.campaign_concurrency_limit,
        max_attempts=body.max_attempts,
        voicemail_retry_hours=body.voicemail_retry_hours,
        no_answer_retry_hours=body.no_answer_retry_hours,
        error_retry_hours=body.error_retry_hours,
        timezone=body.timezone,
    )
    return ClinicSettingsResponse(
        timezone=integration.timezone,
        calling_hours_start=integration.calling_hours_start,
        calling_hours_end=integration.calling_hours_end,
        campaign_concurrency_limit=integration.campaign_concurrency_limit,
        max_attempts=integration.max_attempts,
        voicemail_retry_hours=integration.voicemail_retry_hours,
        no_answer_retry_hours=integration.no_answer_retry_hours,
        error_retry_hours=integration.error_retry_hours,
    )
