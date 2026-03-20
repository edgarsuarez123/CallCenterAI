# Clinic_app/services/campaign_service.py
"""
Campaign service — create and manage HEDIS outreach campaigns.

Core responsibilities:
  - Create Campaign + CampaignContact rows from parsed CSV data
  - Cross-campaign dedup: phone_hash + gap_type + measurement_year per clinic
  - Phone AES-256-GCM encryption + SHA-256 hash (dual-column pattern)
  - Campaign lifecycle: pause, resume, cancel
  - Tenant-isolated queries (clinic_id filter on every query)
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.encryption import encrypt_phi
from Clinic_app.data.enums import CampaignStatus, ContactStatus
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.csv_parser import ParsedRow

logger = logging.getLogger(__name__)

# Terminal statuses — contacts in these states are excluded from dedup skipping
# (a BOOKED contact should block re-upload; EXHAUSTED/DECLINED also block)
_TERMINAL_STATUSES = {
    ContactStatus.BOOKED.value,
    ContactStatus.EXHAUSTED.value,
    ContactStatus.DECLINED.value,
}

# Non-terminal statuses that DO block re-upload (still active)
_ACTIVE_STATUSES = {
    ContactStatus.PENDING.value,
    ContactStatus.CALLING.value,
    ContactStatus.VOICEMAIL.value,
    ContactStatus.NO_ANSWER.value,
    ContactStatus.ERROR.value,
}

# All statuses that should prevent a re-upload duplicate
_DEDUP_BLOCK_STATUSES = _TERMINAL_STATUSES | _ACTIVE_STATUSES


# ── Result types ───────────────────────────────────────────────────────────────

@dataclass
class SkippedContact:
    """A row that was skipped during ingestion due to dedup."""
    phone_hash: str
    gap_type: str
    reason: str   # "already_active" | "already_booked" | "already_exhausted"
    raw_row_number: int


@dataclass
class CampaignCreateResult:
    campaign_id: UUID
    name: str
    measurement_year: int
    total_contacts: int
    skipped_contacts: list[SkippedContact] = field(default_factory=list)
    status: str = CampaignStatus.PENDING.value


# ── Phone hashing ──────────────────────────────────────────────────────────────

def hash_phone(phone_e164: str) -> str:
    """SHA-256 hash of an E.164 phone number. Used for dedup without decryption."""
    return hashlib.sha256(phone_e164.encode("utf-8")).hexdigest()


# ── Dedup query ────────────────────────────────────────────────────────────────

async def _find_duplicate_contact(
    db: AsyncSession,
    clinic_id: UUID,
    phone_hash: str,
    gap_type: str,
    measurement_year: int,
) -> Optional[CampaignContact]:
    """
    Check for an existing CampaignContact that matches the dedup key:
      clinic_id + phone_hash + gap_type + measurement_year

    Returns the existing contact if a blocking duplicate exists, else None.
    Joins campaign_contact → campaign to get measurement_year.
    """
    result = await db.execute(
        select(CampaignContact)
        .join(Campaign, CampaignContact.campaign_id == Campaign.id)
        .where(
            and_(
                CampaignContact.clinic_id == clinic_id,
                CampaignContact.phone_hash == phone_hash,
                CampaignContact.gap_type == gap_type,
                Campaign.measurement_year == measurement_year,
                CampaignContact.status.in_(list(_DEDUP_BLOCK_STATUSES)),
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Campaign creation ──────────────────────────────────────────────────────────

async def create_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    staff_id: Optional[UUID],
    name: str,
    measurement_year: int,
    parsed_rows: list[ParsedRow],
    clinic_integration: ClinicIntegration,
) -> CampaignCreateResult:
    """
    Create one Campaign row and N CampaignContact rows from parsed CSV data.

    For each row:
      1. Compute SHA-256 hash of E.164 phone
      2. Check dedup: existing active/terminal contact for same clinic+phone+gap+year → skip
      3. Encrypt phone with AES-256-GCM
      4. Insert CampaignContact

    Campaign defaults inherit from clinic_integration at creation time.
    Returns CampaignCreateResult with counts and any skipped rows.
    """
    campaign = Campaign(
        id=uuid.uuid4(),
        clinic_id=clinic_id,
        name=name,
        status=CampaignStatus.PENDING.value,
        measurement_year=measurement_year,
        # Inherit operational defaults from clinic settings
        calling_hours_start=clinic_integration.calling_hours_start,
        calling_hours_end=clinic_integration.calling_hours_end,
        campaign_concurrency_limit=clinic_integration.campaign_concurrency_limit,
        voicemail_retry_hours=clinic_integration.voicemail_retry_hours,
        no_answer_retry_hours=clinic_integration.no_answer_retry_hours,
        error_retry_hours=clinic_integration.error_retry_hours,
        max_attempts=clinic_integration.max_attempts,
        created_by=staff_id,
        total_contacts=0,
    )
    db.add(campaign)
    await db.flush()  # Get campaign.id without committing

    inserted: list[CampaignContact] = []
    skipped: list[SkippedContact] = []

    for row in parsed_rows:
        phone_hash = hash_phone(row.phone_e164)
        gap_type_val = row.gap_type.value

        # Dedup check
        existing = await _find_duplicate_contact(
            db, clinic_id, phone_hash, gap_type_val, measurement_year
        )
        if existing:
            reason_map = {
                ContactStatus.BOOKED.value: "already_booked",
                ContactStatus.EXHAUSTED.value: "already_exhausted",
                ContactStatus.DECLINED.value: "already_declined",
            }
            reason = reason_map.get(existing.status, "already_active")
            skipped.append(SkippedContact(
                phone_hash=phone_hash,
                gap_type=gap_type_val,
                reason=reason,
                raw_row_number=row.raw_row_number,
            ))
            continue

        # Encrypt phone
        phone_encrypted = encrypt_phi(row.phone_e164)

        contact = CampaignContact(
            id=uuid.uuid4(),
            campaign_id=campaign.id,
            clinic_id=clinic_id,
            phone_encrypted=phone_encrypted,
            phone_hash=phone_hash,
            gap_type=gap_type_val,
            preferred_language=row.language,
            status=ContactStatus.PENDING.value,
            attempt_count=0,
        )
        db.add(contact)
        inserted.append(contact)

    # Update campaign total after dedup
    campaign.total_contacts = len(inserted)
    await db.commit()

    logger.info(
        f"Campaign created: id={campaign.id} clinic_id={clinic_id} "
        f"name={name!r} year={measurement_year} "
        f"inserted={len(inserted)} skipped={len(skipped)}"
    )

    return CampaignCreateResult(
        campaign_id=campaign.id,
        name=name,
        measurement_year=measurement_year,
        total_contacts=len(inserted),
        skipped_contacts=skipped,
    )


# ── Campaign reads ─────────────────────────────────────────────────────────────

async def get_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    """
    Fetch a Campaign by ID, enforcing clinic_id tenant filter.
    Raises HTTP 404 if not found or belongs to a different clinic.
    """
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.clinic_id == clinic_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "CAMPAIGN_NOT_FOUND", "message": "Campaign not found."},
        )
    return campaign


async def list_campaigns(
    db: AsyncSession,
    clinic_id: UUID,
    status: Optional[CampaignStatus] = None,
) -> list[Campaign]:
    """
    List campaigns for a clinic. Optionally filter by status.
    Always ordered by created_at DESC (newest first).
    """
    q = select(Campaign).where(Campaign.clinic_id == clinic_id)
    if status is not None:
        q = q.where(Campaign.status == status.value)
    q = q.order_by(Campaign.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_campaign_contacts(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
    status: Optional[ContactStatus] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[CampaignContact]:
    """
    Paginated list of contacts for a campaign.
    Tenant-isolated: requires both campaign_id and clinic_id match.
    """
    # Verify the campaign belongs to the clinic first
    await get_campaign(db, clinic_id, campaign_id)

    q = select(CampaignContact).where(
        CampaignContact.campaign_id == campaign_id,
        CampaignContact.clinic_id == clinic_id,
    )
    if status is not None:
        q = q.where(CampaignContact.status == status.value)
    q = q.order_by(CampaignContact.created_at.asc()).limit(limit).offset(offset)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Campaign lifecycle ─────────────────────────────────────────────────────────

async def pause_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    """
    Set campaign status to PAUSED. Raises 409 if not currently ACTIVE.
    """
    campaign = await get_campaign(db, clinic_id, campaign_id)
    if campaign.status != CampaignStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSITION",
                "message": f"Campaign cannot be paused from status '{campaign.status}'. Must be active.",
            },
        )
    campaign.status = CampaignStatus.PAUSED.value
    await db.commit()
    await db.refresh(campaign)
    logger.info(f"Campaign paused: id={campaign_id} clinic_id={clinic_id}")
    return campaign


async def resume_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    """
    Set campaign status to ACTIVE. Raises 409 if not currently PAUSED.
    """
    campaign = await get_campaign(db, clinic_id, campaign_id)
    if campaign.status != CampaignStatus.PAUSED.value:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSITION",
                "message": f"Campaign cannot be resumed from status '{campaign.status}'. Must be paused.",
            },
        )
    campaign.status = CampaignStatus.ACTIVE.value
    await db.commit()
    await db.refresh(campaign)
    logger.info(f"Campaign resumed: id={campaign_id} clinic_id={clinic_id}")
    return campaign


async def cancel_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    """
    Set campaign status to CANCELED. Terminal — cannot be reversed.
    Raises 409 if already completed or canceled.
    """
    campaign = await get_campaign(db, clinic_id, campaign_id)
    if campaign.status in (CampaignStatus.COMPLETED.value, CampaignStatus.CANCELED.value):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSITION",
                "message": f"Campaign is already in terminal status '{campaign.status}'.",
            },
        )
    campaign.status = CampaignStatus.CANCELED.value
    await db.commit()
    await db.refresh(campaign)
    logger.info(f"Campaign canceled: id={campaign_id} clinic_id={clinic_id}")
    return campaign
