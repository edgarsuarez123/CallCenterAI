"""
Campaign service — business logic for outbound HEDIS outreach campaigns.

Handles:
- Campaign lifecycle (create, start, pause, complete)
- CSV contact upload with PHI encryption and phone dedup
- Outcome recording from Retell webhooks
- Report generation with PHI decryption for display
- Demo-mode call simulation (used when RETELL_API_KEY is not configured)
"""

import csv
import hashlib
import io
import logging
import random
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

import re

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.encryption import encrypt_phi, decrypt_phi
from Clinic_app.data.enums import CampaignStatus, ContactOutcome
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact

logger = logging.getLogger(__name__)

# ============================================================================
# HELPERS
# ============================================================================

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_DIGITS_RE = re.compile(r"\D")


def _normalize_phone(phone: str) -> Optional[str]:
    """
    Normalize a US phone number to E.164 format.

    Strips formatting and prepends +1 for 10-digit US numbers.
    Returns the normalized string or None if invalid.
    """
    if not phone:
        return None
    stripped = _DIGITS_RE.sub("", phone)
    # Already E.164 (starts with +)
    candidate = phone.strip()
    if candidate.startswith("+"):
        candidate = "+" + _DIGITS_RE.sub("", candidate[1:])
        if _E164_RE.match(candidate):
            return candidate
        return None
    # 10-digit US number → +1XXXXXXXXXX
    if len(stripped) == 10:
        candidate = f"+1{stripped}"
        if _E164_RE.match(candidate):
            return candidate
    # 11-digit starting with 1 → +1XXXXXXXXXX
    if len(stripped) == 11 and stripped.startswith("1"):
        candidate = f"+{stripped}"
        if _E164_RE.match(candidate):
            return candidate
    return None


def _hash_phone(normalized_phone: str) -> str:
    """SHA-256 hash of normalized E.164 phone for dedup without decryption."""
    return hashlib.sha256(normalized_phone.encode("utf-8")).hexdigest()


def _mask_phone(normalized_phone: str) -> str:
    """Return last 4 digits only for display: ***-***-1234."""
    return f"***-***-{normalized_phone[-4:]}" if len(normalized_phone) >= 4 else "***-***-****"


# ============================================================================
# CAMPAIGN CRUD
# ============================================================================


async def create_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    name: str,
    reason: str,
) -> Campaign:
    """Create a new draft campaign."""
    campaign = Campaign(
        clinic_id=clinic_id,
        name=name,
        reason=reason,
        status=CampaignStatus.DRAFT,
        total_contacts=0,
        completed_contacts=0,
    )
    db.add(campaign)
    await db.flush()
    await db.refresh(campaign)
    logger.info(f"Created campaign {campaign.id} for clinic {clinic_id}")
    return campaign


async def get_campaign(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> Optional[Campaign]:
    """Get a campaign by ID, enforcing clinic_id tenant isolation."""
    result = await db.execute(
        select(Campaign).where(
            and_(
                Campaign.id == campaign_id,
                Campaign.clinic_id == clinic_id,
            )
        )
    )
    return result.scalar_one_or_none()


async def list_campaigns(
    db: AsyncSession,
    clinic_id: UUID,
    status_filter: Optional[str] = None,
) -> List[Campaign]:
    """List campaigns for a clinic, optionally filtered by status."""
    query = select(Campaign).where(Campaign.clinic_id == clinic_id)
    if status_filter:
        query = query.where(Campaign.status == status_filter)
    query = query.order_by(Campaign.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def start_campaign(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> Tuple[Optional[Campaign], Optional[str]]:
    """
    Transition a campaign from DRAFT/PAUSED to QUEUED.

    Returns (campaign, None) on success or (None, error_message) on failure.
    """
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return None, "Campaign not found"
    if campaign.total_contacts == 0:
        return None, "Cannot start a campaign with no contacts. Upload a CSV first."
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        return None, f"Campaign is {campaign.status}, cannot start"

    campaign.status = CampaignStatus.QUEUED
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(campaign)
    logger.info(f"Campaign {campaign_id} queued for processing")
    return campaign, None


async def pause_campaign(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> Tuple[Optional[Campaign], Optional[str]]:
    """Pause a RUNNING or QUEUED campaign."""
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return None, "Campaign not found"
    if campaign.status not in (CampaignStatus.RUNNING, CampaignStatus.QUEUED):
        return None, f"Campaign is {campaign.status}, cannot pause"

    campaign.status = CampaignStatus.PAUSED
    campaign.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(campaign)
    logger.info(f"Campaign {campaign_id} paused")
    return campaign, None


# ============================================================================
# CSV UPLOAD
# ============================================================================


async def upload_contacts(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
    csv_content: bytes,
    default_reason: str,
) -> dict:
    """
    Parse a CSV file and create CampaignContact rows with encrypted PHI.

    Expected CSV columns (case-insensitive):
      - patient_name (required)
      - phone (required) — any US format, normalized to E.164
      - reason (optional) — overrides campaign default reason per patient

    Returns:
      {
        "imported": N,
        "duplicates_skipped": N,
        "invalid_rows": N,
        "errors": ["row 3: invalid phone number", ...]
      }
    """
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return {"error": "Campaign not found"}
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        return {"error": f"Cannot upload to a campaign in status '{campaign.status}'"}

    # Pre-load existing phone hashes for this clinic to detect duplicates
    existing_hashes_result = await db.execute(
        select(CampaignContact.phone_hash).where(CampaignContact.clinic_id == clinic_id)
    )
    existing_hashes = set(existing_hashes_result.scalars().all())

    text = csv_content.decode("utf-8-sig")  # handle BOM from Excel exports
    reader = csv.DictReader(io.StringIO(text))

    # Normalize header names
    if reader.fieldnames is None:
        return {"error": "CSV file appears to be empty"}

    headers = {h.strip().lower(): h for h in reader.fieldnames}

    if "patient_name" not in headers and "name" not in headers:
        return {"error": "CSV must have a 'patient_name' or 'name' column"}
    if "phone" not in headers:
        return {"error": "CSV must have a 'phone' column"}

    name_col = headers.get("patient_name") or headers.get("name")
    phone_col = headers["phone"]
    reason_col = headers.get("reason")

    imported = 0
    duplicates_skipped = 0
    invalid_rows = 0
    errors = []
    new_contacts = []

    for row_num, row in enumerate(reader, start=2):  # row 1 is header
        name = row.get(name_col, "").strip()
        phone_raw = row.get(phone_col, "").strip()
        reason = row.get(reason_col, "").strip() if reason_col else ""
        if not reason:
            reason = default_reason

        if not name:
            errors.append(f"Row {row_num}: patient_name is empty, skipping")
            invalid_rows += 1
            continue

        normalized_phone = _normalize_phone(phone_raw)
        if not normalized_phone:
            errors.append(f"Row {row_num}: invalid phone '{phone_raw}', skipping")
            invalid_rows += 1
            continue

        phone_hash = _hash_phone(normalized_phone)

        # Dedup: skip if this phone already exists for this clinic
        if phone_hash in existing_hashes:
            duplicates_skipped += 1
            continue

        try:
            name_enc = encrypt_phi(name)
            phone_enc = encrypt_phi(normalized_phone)
        except Exception as e:
            errors.append(f"Row {row_num}: encryption failed — {e}")
            invalid_rows += 1
            continue

        contact = CampaignContact(
            campaign_id=campaign_id,
            clinic_id=clinic_id,
            patient_name_encrypted=name_enc,
            phone_encrypted=phone_enc,
            phone_hash=phone_hash,
            reason=reason,
            outcome=ContactOutcome.PENDING,
            attempt_count=0,
        )
        new_contacts.append(contact)
        existing_hashes.add(phone_hash)  # prevent intra-batch duplicates
        imported += 1

    # Bulk insert
    if new_contacts:
        db.add_all(new_contacts)
        await db.flush()
        campaign.total_contacts += imported
        campaign.updated_at = datetime.now(timezone.utc)
        await db.flush()

    logger.info(
        f"Campaign {campaign_id} upload: {imported} imported, "
        f"{duplicates_skipped} duplicates, {invalid_rows} invalid"
    )
    return {
        "imported": imported,
        "duplicates_skipped": duplicates_skipped,
        "invalid_rows": invalid_rows,
        "errors": errors,
    }


# ============================================================================
# OUTCOME RECORDING
# ============================================================================


async def record_outcome(
    db: AsyncSession,
    contact_id: UUID,
    clinic_id: UUID,
    outcome: str,
    retell_call_id: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    notes: Optional[str] = None,
) -> Optional[CampaignContact]:
    """
    Record the outcome of a call for a specific contact.

    Called by the Retell webhook handler on call_ended event.
    """
    result = await db.execute(
        select(CampaignContact).where(
            and_(
                CampaignContact.id == contact_id,
                CampaignContact.clinic_id == clinic_id,
            )
        )
    )
    contact = result.scalar_one_or_none()
    if not contact:
        logger.warning(f"record_outcome: contact {contact_id} not found for clinic {clinic_id}")
        return None

    contact.outcome = outcome
    contact.call_date = datetime.now(timezone.utc)
    if retell_call_id:
        contact.retell_call_id = retell_call_id
    if duration_seconds is not None:
        contact.call_duration_seconds = duration_seconds
    if notes:
        contact.notes = notes
    contact.updated_at = datetime.now(timezone.utc)

    await db.flush()

    # Update campaign completed_contacts counter
    terminal_outcomes = {
        ContactOutcome.ACCEPTED,
        ContactOutcome.DECLINED,
        ContactOutcome.VOICEMAIL,
        ContactOutcome.NO_ANSWER,
        ContactOutcome.FAILED,
    }
    if outcome in {o.value for o in terminal_outcomes}:
        campaign_result = await db.execute(
            select(Campaign).where(Campaign.id == contact.campaign_id)
        )
        campaign = campaign_result.scalar_one_or_none()
        if campaign:
            campaign.completed_contacts += 1
            # Auto-complete campaign if all contacts are terminal
            if campaign.completed_contacts >= campaign.total_contacts:
                campaign.status = CampaignStatus.COMPLETED
                logger.info(f"Campaign {campaign.id} auto-completed")
            campaign.updated_at = datetime.now(timezone.utc)

    return contact


# ============================================================================
# REPORT GENERATION
# ============================================================================


async def get_campaign_report(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> Tuple[Optional[Campaign], List[dict]]:
    """
    Generate a decrypted report for a campaign.

    Returns (campaign, list_of_contact_dicts).
    Contact dicts include decrypted patient_name and masked phone.
    """
    campaign = await get_campaign(db, campaign_id, clinic_id)
    if not campaign:
        return None, []

    result = await db.execute(
        select(CampaignContact)
        .where(
            and_(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.clinic_id == clinic_id,
            )
        )
        .order_by(CampaignContact.created_at.asc())
    )
    contacts = result.scalars().all()

    rows = []
    for c in contacts:
        try:
            patient_name = decrypt_phi(c.patient_name_encrypted)
            phone_normalized = decrypt_phi(c.phone_encrypted)
            phone_display = _mask_phone(phone_normalized)
        except Exception:
            patient_name = "[decryption error]"
            phone_display = "***-***-****"

        rows.append(
            {
                "id": str(c.id),
                "patient_name": patient_name,
                "phone_last4": phone_display,
                "reason": c.reason,
                "outcome": c.outcome,
                "call_date": c.call_date.isoformat() if c.call_date else None,
                "call_duration_seconds": c.call_duration_seconds,
                "attempt_count": c.attempt_count,
                "notes": c.notes,
                "retell_call_id": c.retell_call_id,
            }
        )

    return campaign, rows


# ============================================================================
# DEMO MODE — SIMULATED CALL PROCESSING
# ============================================================================

# Probability weights for realistic-looking outcomes
_OUTCOME_WEIGHTS = [
    (ContactOutcome.ACCEPTED, 0.38),
    (ContactOutcome.DECLINED, 0.15),
    (ContactOutcome.VOICEMAIL, 0.28),
    (ContactOutcome.NO_ANSWER, 0.14),
    (ContactOutcome.FAILED, 0.05),
]
_OUTCOMES = [o for o, _ in _OUTCOME_WEIGHTS]
_WEIGHTS = [w for _, w in _OUTCOME_WEIGHTS]

_DEMO_NOTES = {
    ContactOutcome.ACCEPTED: "Patient acknowledged care gap and expressed intent to schedule.",
    ContactOutcome.DECLINED: "Patient declined outreach; stated they have already addressed the concern.",
    ContactOutcome.VOICEMAIL: "Voicemail reached; message left with callback number.",
    ContactOutcome.NO_ANSWER: "No answer after four rings; no voicemail detected.",
    ContactOutcome.FAILED: "Call could not be connected; carrier error.",
}


async def get_next_pending_contact(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> Optional[CampaignContact]:
    """Get the next PENDING contact in a campaign (FIFO order)."""
    result = await db.execute(
        select(CampaignContact)
        .where(
            and_(
                CampaignContact.campaign_id == campaign_id,
                CampaignContact.clinic_id == clinic_id,
                CampaignContact.outcome == ContactOutcome.PENDING,
            )
        )
        .order_by(CampaignContact.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def simulate_next_call(
    db: AsyncSession,
    campaign_id: UUID,
    clinic_id: UUID,
) -> dict:
    """
    Demo mode: pick the next PENDING contact and simulate a call outcome.

    Simulates realistic outcome distribution without making real API calls.
    Used by the /process-next endpoint and the background campaign worker
    when RETELL_API_KEY is not configured.

    Returns a dict describing what happened.
    """
    contact = await get_next_pending_contact(db, campaign_id, clinic_id)
    if not contact:
        return {"status": "no_pending_contacts", "message": "All contacts have been processed"}

    # Simulate in-progress state
    contact.outcome = ContactOutcome.CALLING
    contact.attempt_count += 1
    contact.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # Simulate call outcome
    outcome = random.choices(_OUTCOMES, weights=_WEIGHTS, k=1)[0]
    simulated_duration = random.randint(15, 180) if outcome != ContactOutcome.FAILED else 0
    fake_call_id = f"demo_{contact.id.hex[:8]}"

    updated_contact = await record_outcome(
        db=db,
        contact_id=contact.id,
        clinic_id=clinic_id,
        outcome=outcome.value,
        retell_call_id=fake_call_id,
        duration_seconds=simulated_duration,
        notes=_DEMO_NOTES[outcome],
    )

    # Decrypt name for the response (safe — only in memory)
    try:
        patient_name = decrypt_phi(contact.patient_name_encrypted)
    except Exception:
        patient_name = "[encrypted]"

    logger.info(
        f"[DEMO] Campaign {campaign_id}: simulated call to "
        f"contact {contact.id}, outcome={outcome.value}"
    )

    return {
        "status": "processed",
        "contact_id": str(contact.id),
        "patient_name": patient_name,
        "outcome": outcome.value,
        "duration_seconds": simulated_duration,
        "notes": _DEMO_NOTES[outcome],
        "demo_mode": True,
    }
