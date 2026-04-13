# Clinic_app/Routes/campaigns.py
"""
Campaign routes — CSV/Excel upload, campaign management, PHI-safe export.

POST   /campaigns/upload          — upload file, create campaign (admin only)
GET    /campaigns                 — list campaigns for clinic
GET    /campaigns/{id}            — campaign detail + progress
GET    /campaigns/{id}/contacts   — paginated contact list
POST   /campaigns/{id}/start      — start pending campaign (admin only)
POST   /campaigns/{id}/pause      — pause (admin only)
POST   /campaigns/{id}/resume     — resume (admin only)
POST   /campaigns/{id}/cancel     — cancel (admin only)
GET    /campaigns/{id}/export     — PHI-safe CSV export
"""

import csv
import io
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import get_db
from Clinic_app.common.rate_limit import auth_rate_limit, upload_rate_limit
from Clinic_app.common.encryption import decrypt_phi
from Clinic_app.common.jwt import StaffToken, require_scoped_staff
from Clinic_app.data.enums import CampaignStatus, ContactStatus
from Clinic_app.data.models.campaign_audit import CampaignAudit
from Clinic_app.services.campaign_service import (
    CampaignCreateResult,
    SkippedContact,
    cancel_campaign,
    create_campaign,
    get_campaign,
    get_campaign_contacts,
    list_campaigns,
    pause_campaign,
    resume_campaign,
    start_campaign,
)
from Clinic_app.workers.campaign_worker import campaign_worker_manager
from Clinic_app.services.auth_service import get_staff_for_clinic
from Clinic_app.services.clinic_service import get_clinic_settings
from Clinic_app.services.csv_parser import ParseError, parse_file

logger = logging.getLogger(__name__)

campaign_router = APIRouter(prefix="/campaigns", tags=["campaigns"])

# ── Constants ──────────────────────────────────────────────────────────────────

MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB
MAX_ROWS = 2000
ALLOWED_CONTENT_TYPES = {
    "text/csv",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/octet-stream",  # Some browsers send this for .xlsx
}

# ── Response schemas ───────────────────────────────────────────────────────────

class SkippedContactOut(BaseModel):
    phone_hash: str
    gap_type: str
    reason: str
    raw_row_number: int


class ParseErrorOut(BaseModel):
    row_number: int
    reason: str


class CampaignUploadResponse(BaseModel):
    campaign_id: UUID
    name: str
    measurement_year: int
    total_contacts: int
    skipped_count: int
    skipped_contacts: list[SkippedContactOut]
    parse_error_count: int
    parse_errors: list[ParseErrorOut]
    status: str


class CampaignResponse(BaseModel):
    campaign_id: UUID
    name: str
    measurement_year: int
    status: str
    total_contacts: int
    called_count: int
    booked_count: int
    failed_count: int
    calling_hours_start: str
    calling_hours_end: str
    max_attempts: int
    campaign_concurrency_limit: int
    created_at: datetime
    updated_at: datetime


class ContactResponse(BaseModel):
    contact_id: UUID
    gap_type: str
    preferred_language: str
    status: str
    attempt_count: int
    last_attempted_at: Optional[datetime]
    next_attempt_after: Optional[datetime]
    ehr_appointment_id: Optional[str]
    created_at: datetime


class AuditResponse(BaseModel):
    audit_id: UUID
    contact_id: UUID
    retell_call_id: str
    outcome: str
    attempt_number: int
    called_at: datetime
    call_summary: Optional[str] = None
    patient_name: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _campaign_to_response(c) -> CampaignResponse:
    return CampaignResponse(
        campaign_id=c.id,
        name=c.name,
        measurement_year=c.measurement_year,
        status=c.status,
        total_contacts=c.total_contacts,
        called_count=c.called_count,
        booked_count=c.booked_count,
        failed_count=c.failed_count,
        calling_hours_start=c.calling_hours_start,
        calling_hours_end=c.calling_hours_end,
        max_attempts=c.max_attempts,
        campaign_concurrency_limit=c.campaign_concurrency_limit,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _require_admin(staff: StaffToken) -> None:
    if staff.role != "admin":
        raise HTTPException(
            status_code=403,
            detail={"code": "FORBIDDEN", "message": "Admin role required."},
        )


# ── Upload endpoint ────────────────────────────────────────────────────────────

@campaign_router.post("/upload", response_model=CampaignUploadResponse, status_code=201)
async def upload_campaign(
    file: UploadFile = File(...),
    name: str = Form(...),
    measurement_year: int = Form(default=datetime.utcnow().year),
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(upload_rate_limit()),
) -> CampaignUploadResponse:
    """
    Upload a CSV or Excel patient list to create a HEDIS outreach campaign.
    Requires admin role. File must be ≤10MB and ≤2000 data rows.
    """
    _require_admin(staff)

    # Content type check (lenient — also accept octet-stream for Excel)
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_FILE_TYPE",
                "message": f"Unsupported file type '{file.content_type}'. Upload a CSV or Excel file.",
            },
        )

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=422,
            detail={"code": "FILE_TOO_LARGE", "message": "File exceeds the 10MB limit."},
        )

    filename = file.filename or ""

    # Parse file (CSV or Excel)
    try:
        parsed_rows, parse_errors = parse_file(file_bytes, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "PARSE_ERROR", "message": str(exc)})

    if len(parsed_rows) > MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOO_MANY_ROWS",
                "message": f"File contains {len(parsed_rows)} valid rows — maximum is {MAX_ROWS}.",
            },
        )

    if not parsed_rows:
        raise HTTPException(
            status_code=422,
            detail={"code": "NO_VALID_ROWS", "message": "No valid patient rows found in file."},
        )

    # Load clinic integration defaults
    clinic_integration = await get_clinic_settings(db, staff.clinic_id)

    # Resolve clinic_staff.id from google_sub (JWT carries sub, not DB UUID)
    staff_record = await get_staff_for_clinic(db, staff.google_sub, staff.clinic_id)
    staff_db_id = staff_record.id if staff_record else None

    # Create campaign
    result: CampaignCreateResult = await create_campaign(
        db=db,
        clinic_id=staff.clinic_id,
        staff_id=staff_db_id,
        name=name,
        measurement_year=measurement_year,
        parsed_rows=parsed_rows,
        clinic_integration=clinic_integration,
    )

    return CampaignUploadResponse(
        campaign_id=result.campaign_id,
        name=result.name,
        measurement_year=result.measurement_year,
        total_contacts=result.total_contacts,
        skipped_count=len(result.skipped_contacts),
        skipped_contacts=[
            SkippedContactOut(**{
                "phone_hash": s.phone_hash,
                "gap_type": s.gap_type,
                "reason": s.reason,
                "raw_row_number": s.raw_row_number,
            })
            for s in result.skipped_contacts
        ],
        parse_error_count=len(parse_errors),
        parse_errors=[ParseErrorOut(row_number=e.row_number, reason=e.reason) for e in parse_errors],
        status=result.status,
    )


# ── List campaigns ─────────────────────────────────────────────────────────────

@campaign_router.get("", response_model=list[CampaignResponse])
async def list_campaigns_route(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> list[CampaignResponse]:
    """List all campaigns for the current clinic, newest first."""
    status_enum: Optional[CampaignStatus] = None
    if status:
        try:
            status_enum = CampaignStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATUS", "message": f"Unknown campaign status: {status!r}"},
            )
    campaigns = await list_campaigns(db, staff.clinic_id, status=status_enum)
    return [_campaign_to_response(c) for c in campaigns]


# ── Campaign detail ────────────────────────────────────────────────────────────

@campaign_router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> CampaignResponse:
    """Get campaign details including progress counters."""
    campaign = await get_campaign(db, staff.clinic_id, campaign_id)
    return _campaign_to_response(campaign)


# ── Contact list ───────────────────────────────────────────────────────────────

@campaign_router.get("/{campaign_id}/contacts", response_model=list[ContactResponse])
async def get_contacts_route(
    campaign_id: UUID,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> list[ContactResponse]:
    """
    Paginated list of contacts for a campaign.
    Phone numbers are NOT returned (PHI). Only status, gap_type, attempt info.
    """
    status_enum: Optional[ContactStatus] = None
    if status:
        try:
            status_enum = ContactStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_STATUS", "message": f"Unknown contact status: {status!r}"},
            )

    contacts = await get_campaign_contacts(
        db, staff.clinic_id, campaign_id,
        status=status_enum, limit=limit, offset=offset,
    )
    return [
        ContactResponse(
            contact_id=c.id,
            gap_type=c.gap_type,
            preferred_language=c.preferred_language,
            status=c.status,
            attempt_count=c.attempt_count,
            last_attempted_at=c.last_attempted_at,
            next_attempt_after=c.next_attempt_after,
            ehr_appointment_id=c.ehr_appointment_id,
            created_at=c.created_at,
        )
        for c in contacts
    ]


# ── Audit records (call summaries) ─────────────────────────────────────────────

@campaign_router.get("/{campaign_id}/audits", response_model=list[AuditResponse])
async def get_campaign_audits(
    campaign_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> list[AuditResponse]:
    """
    Return call audit records for a campaign, including decrypted call summaries
    and patient names. Useful for reviewing call outcomes and comparing summarizer
    modes. Requires scoped staff JWT. Results are ordered newest-first.
    """
    # Verify campaign belongs to this clinic
    await get_campaign(db, staff.clinic_id, campaign_id)

    stmt = (
        select(CampaignAudit)
        .where(
            CampaignAudit.clinic_id == staff.clinic_id,
            CampaignAudit.campaign_id == campaign_id,
        )
        .order_by(CampaignAudit.called_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    audits = result.scalars().all()

    out: list[AuditResponse] = []
    for a in audits:
        call_summary: Optional[str] = None
        if a.call_summary_encrypted:
            try:
                call_summary = decrypt_phi(a.call_summary_encrypted)
            except Exception:
                call_summary = "[decryption error]"

        patient_name: Optional[str] = None
        if a.patient_name_encrypted:
            try:
                patient_name = decrypt_phi(a.patient_name_encrypted)
            except Exception:
                patient_name = "[decryption error]"

        out.append(AuditResponse(
            audit_id=a.id,
            contact_id=a.campaign_contact_id,
            retell_call_id=a.retell_call_id,
            outcome=a.outcome,
            attempt_number=a.attempt_number,
            called_at=a.called_at,
            call_summary=call_summary,
            patient_name=patient_name,
        ))
    return out


# ── Start (PENDING or CANCELED -> ACTIVE) ────────────────────────────────────

@campaign_router.post("/{campaign_id}/start", response_model=CampaignResponse)
async def start_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> CampaignResponse:
    """Start a pending campaign or restart a canceled one; ensures the clinic worker runs. Admin only."""
    _require_admin(staff)
    campaign = await start_campaign(db, staff.clinic_id, campaign_id)
    await campaign_worker_manager.start_clinic_worker(staff.clinic_id)
    return _campaign_to_response(campaign)


# ── Pause ──────────────────────────────────────────────────────────────────────

@campaign_router.post("/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> CampaignResponse:
    """Pause an active campaign. Admin only."""
    _require_admin(staff)
    campaign = await pause_campaign(db, staff.clinic_id, campaign_id)
    return _campaign_to_response(campaign)


# ── Resume ─────────────────────────────────────────────────────────────────────

@campaign_router.post("/{campaign_id}/resume", response_model=CampaignResponse)
async def resume_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> CampaignResponse:
    """Resume a paused campaign. Admin only."""
    _require_admin(staff)
    campaign = await resume_campaign(db, staff.clinic_id, campaign_id)
    await campaign_worker_manager.start_clinic_worker(staff.clinic_id)
    return _campaign_to_response(campaign)


# ── Cancel ─────────────────────────────────────────────────────────────────────

@campaign_router.post("/{campaign_id}/cancel", response_model=CampaignResponse)
async def cancel_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit()),
) -> CampaignResponse:
    """Cancel a campaign. Terminal — cannot be reversed. Admin only."""
    _require_admin(staff)
    campaign = await cancel_campaign(db, staff.clinic_id, campaign_id)
    return _campaign_to_response(campaign)


# ── PHI-safe export ────────────────────────────────────────────────────────────

@campaign_router.get("/{campaign_id}/export")
async def export_campaign_route(
    campaign_id: UUID,
    staff: StaffToken = Depends(require_scoped_staff),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Export campaign contact data as CSV. PHI-safe: no patient name, no decrypted phone.
    Columns: phone_hash, gap_type, preferred_language, status, attempt_count,
             last_attempted_at, ehr_appointment_id
    """
    # Verify campaign exists and belongs to this clinic
    campaign = await get_campaign(db, staff.clinic_id, campaign_id)

    # Fetch all contacts (no pagination for export)
    contacts = await get_campaign_contacts(
        db, staff.clinic_id, campaign_id, limit=10000, offset=0
    )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "phone_hash", "gap_type", "preferred_language", "status",
        "attempt_count", "last_attempted_at", "ehr_appointment_id",
    ])
    writer.writeheader()
    for c in contacts:
        writer.writerow({
            "phone_hash": c.phone_hash,
            "gap_type": c.gap_type,
            "preferred_language": c.preferred_language,
            "status": c.status,
            "attempt_count": c.attempt_count,
            "last_attempted_at": c.last_attempted_at.isoformat() if c.last_attempted_at else "",
            "ehr_appointment_id": c.ehr_appointment_id or "",
        })

    output.seek(0)
    safe_name = "".join(c for c in campaign.name if c.isalnum() or c in " _-")[:50]
    filename = f"campaign_{safe_name}_{campaign.measurement_year}_export.csv"

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
