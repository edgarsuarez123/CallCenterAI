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

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.encryption import encrypt_phi, hash_phi
from Clinic_app.data.enums import CampaignStatus, ContactStatus, GapType
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.clinic_service import get_clinic_settings
from Clinic_app.services.csv_parser import ParsedRow

logger = logging.getLogger(__name__)


def _allow_campaign_start_without_ehr_verification() -> bool:
    """
    Local/dev only: when ALLOW_CAMPAIGN_START_WITHOUT_EHR is truthy and
    APP_ENVIRONMENT is development, dev, or local, skip NextGen verification at start.
    Never enabled in production/staging or when APP_ENVIRONMENT is unset/unknown.
    """
    app_env = os.environ.get("APP_ENVIRONMENT", "").strip().lower()
    if app_env not in ("development", "dev", "local"):
        return False
    flag = os.environ.get("ALLOW_CAMPAIGN_START_WITHOUT_EHR", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


# Terminal statuses — contacts in these states are excluded from dedup skipping
# (a BOOKED contact should block re-upload; EXHAUSTED/DECLINED also block)
_TERMINAL_STATUSES = {
    ContactStatus.BOOKED.value,
    ContactStatus.ORDER_AGREED.value,
    ContactStatus.ORDER_DECLINED.value,
    ContactStatus.EXHAUSTED.value,
    ContactStatus.DECLINED.value,
    ContactStatus.HUMAN_REQUESTED.value,
    ContactStatus.NOT_YET_ELIGIBLE.value,
    ContactStatus.EXPIRED.value,
}

HOSPITAL_FLU_DEADLINE_DAYS = 7

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
    """HMAC-SHA256 of an E.164 phone number using PHI_HASH_KEY. Used for dedup without decryption."""
    return hash_phi(phone_e164)


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
                ContactStatus.HUMAN_REQUESTED.value: "already_declined",
            }
            reason = reason_map.get(existing.status, "already_active")
            skipped.append(SkippedContact(
                phone_hash=phone_hash,
                gap_type=gap_type_val,
                reason=reason,
                raw_row_number=row.raw_row_number,
            ))
            continue

        # Encrypt phone and optional name for dial-time metadata
        # DOB is never stored — PHI Rule #2
        phone_encrypted = encrypt_phi(row.phone_e164)
        name_enc = encrypt_phi(row.patient_name) if row.patient_name else None

        # hospital_flu contacts get priority 0 (called first); all others get 1
        is_hospital_flu = row.gap_type == GapType.HOSPITAL_FLU
        priority = 0 if is_hospital_flu else 1

        release_dt: Optional[date] = None
        if row.release_date:
            try:
                release_dt = date.fromisoformat(row.release_date)
            except ValueError:
                logger.warning(
                    f"Row {row.raw_row_number}: invalid release_date {row.release_date!r} — ignored"
                )

        contact = CampaignContact(
            id=uuid.uuid4(),
            campaign_id=campaign.id,
            clinic_id=clinic_id,
            phone_encrypted=phone_encrypted,
            phone_hash=phone_hash,
            patient_name_encrypted=name_enc,
            provider_name=row.provider_name,
            payer=row.payer,
            gap_type=gap_type_val,
            preferred_language=row.language,
            status=ContactStatus.PENDING.value,
            attempt_count=0,
            priority_order=priority,
            release_date=release_dt,
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


async def get_next_eligible_contact(
    db: AsyncSession,
    clinic_id: UUID,
) -> Optional[CampaignContact]:
    """
    Next contact to dial: PENDING, retry window open, belonging to an ACTIVE campaign.
    FIFO by contact created_at across all active campaigns for the clinic.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CampaignContact)
        .join(Campaign, CampaignContact.campaign_id == Campaign.id)
        .where(
            and_(
                CampaignContact.clinic_id == clinic_id,
                Campaign.status == CampaignStatus.ACTIVE.value,
                CampaignContact.status == ContactStatus.PENDING.value,
                or_(
                    CampaignContact.next_attempt_after.is_(None),
                    CampaignContact.next_attempt_after <= now,
                ),
            )
        )
        .order_by(CampaignContact.priority_order.asc(), CampaignContact.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def expire_overdue_hospital_flu_contacts(
    db: AsyncSession,
    clinic_id: UUID,
) -> int:
    """
    Mark PENDING hospital_flu contacts as EXPIRED when their 7-day discharge deadline
    has passed. Returns the number of contacts expired.
    """
    today = date.today()
    cutoff = today - timedelta(days=HOSPITAL_FLU_DEADLINE_DAYS)

    result = await db.execute(
        select(CampaignContact)
        .join(Campaign, CampaignContact.campaign_id == Campaign.id)
        .where(
            CampaignContact.clinic_id == clinic_id,
            Campaign.status == CampaignStatus.ACTIVE.value,
            CampaignContact.gap_type == GapType.HOSPITAL_FLU.value,
            CampaignContact.status == ContactStatus.PENDING.value,
            CampaignContact.release_date.isnot(None),
            CampaignContact.release_date <= cutoff,
        )
    )
    contacts = result.scalars().all()
    for contact in contacts:
        contact.status = ContactStatus.EXPIRED.value

    if contacts:
        await db.commit()
        logger.info(
            "Expired %d overdue hospital_flu contacts for clinic_id=%s",
            len(contacts),
            clinic_id,
        )
    return len(contacts)


def _apply_clinic_operational_defaults_to_campaign(
    campaign: Campaign,
    integration: ClinicIntegration,
) -> None:
    """
    Copy current clinic integration operational fields onto the campaign row.
    Matches create_campaign inheritance so PATCH /clinic/settings applies on
    start/resume, not only at CSV upload.
    """
    campaign.calling_hours_start = integration.calling_hours_start
    campaign.calling_hours_end = integration.calling_hours_end
    campaign.campaign_concurrency_limit = integration.campaign_concurrency_limit
    campaign.voicemail_retry_hours = integration.voicemail_retry_hours
    campaign.no_answer_retry_hours = integration.no_answer_retry_hours
    campaign.error_retry_hours = integration.error_retry_hours
    campaign.max_attempts = integration.max_attempts


async def start_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> Campaign:
    """
    PENDING or CANCELED -> ACTIVE. Restarts a previously canceled campaign without
    changing contacts or progress counters (cancel does not alter contact rows).
    Refreshes calling hours, concurrency, and retry settings from the clinic's
    current integration row so Swagger/settings changes apply at start time.
    Requires verified EHR credentials unless dev bypass is set
    (see ALLOW_CAMPAIGN_START_WITHOUT_EHR + APP_ENVIRONMENT in env.example).
    """
    campaign = await get_campaign(db, clinic_id, campaign_id)
    if campaign.status not in (
        CampaignStatus.PENDING.value,
        CampaignStatus.CANCELED.value,
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVALID_TRANSITION",
                "message": (
                    f"Campaign cannot be started from status '{campaign.status}'. "
                    "Must be pending or canceled (use resume if paused)."
                ),
            },
        )

    if not _allow_campaign_start_without_ehr_verification():
        ehr_result = await db.execute(
            select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
        )
        ehr = ehr_result.scalar_one_or_none()
        if ehr is None or ehr.connection_verified_at is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "EHR_NOT_VERIFIED",
                    "message": "NextGen EHR credentials must be configured and verified before starting a campaign.",
                },
            )
    else:
        logger.warning(
            "Campaign start without EHR verification (ALLOW_CAMPAIGN_START_WITHOUT_EHR); "
            "clinic_id=%s campaign_id=%s",
            clinic_id,
            campaign_id,
        )

    integration = await get_clinic_settings(db, clinic_id)
    _apply_clinic_operational_defaults_to_campaign(campaign, integration)

    campaign.status = CampaignStatus.ACTIVE.value
    await db.commit()
    await db.refresh(campaign)
    logger.info(f"Campaign started: id={campaign_id} clinic_id={clinic_id}")
    return campaign


async def count_calling_contacts(db: AsyncSession, clinic_id: UUID) -> int:
    """In-flight outbound calls for this clinic (status CALLING)."""
    result = await db.execute(
        select(func.count())
        .select_from(CampaignContact)
        .where(
            CampaignContact.clinic_id == clinic_id,
            CampaignContact.status == ContactStatus.CALLING.value,
        )
    )
    return int(result.scalar_one() or 0)


async def maybe_mark_campaign_completed(
    db: AsyncSession,
    clinic_id: UUID,
    campaign_id: UUID,
) -> None:
    """
    If every contact for the campaign is in a terminal state, set campaign COMPLETED.
    """
    campaign = await get_campaign(db, clinic_id, campaign_id)
    if campaign.status not in (
        CampaignStatus.ACTIVE.value,
        CampaignStatus.PAUSED.value,
    ):
        return

    result = await db.execute(
        select(CampaignContact.id).where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.clinic_id == clinic_id,
            CampaignContact.status.not_in(list(_TERMINAL_STATUSES)),
        )
    )
    if result.first() is None:
        campaign.status = CampaignStatus.COMPLETED.value
        await db.flush()
        logger.info(f"Campaign auto-completed: id={campaign_id} clinic_id={clinic_id}")


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
    Refreshes operational defaults from clinic integration (same as start_campaign).
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
    integration = await get_clinic_settings(db, clinic_id)
    _apply_clinic_operational_defaults_to_campaign(campaign, integration)
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
    Set campaign status to CANCELED. Contact rows and counters are unchanged;
    call POST /campaigns/{id}/start again to resume dialing (same as un-canceled restart).
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
