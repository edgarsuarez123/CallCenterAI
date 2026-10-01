#!/usr/bin/env python3
"""
Demo data seeder for CallCenterAI.

Creates a realistic demo dataset for recruiter demos and development testing.
Idempotent: checks for existing data before creating.

Usage:
    # With docker-compose running:
    docker exec -it callcenterai-app-1 python scripts/seed_demo.py

    # Or directly with DB env vars set:
    python scripts/seed_demo.py
"""

import asyncio
import hashlib
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import AsyncSessionLocal
from Clinic_app.common.encryption import encrypt_phi
from Clinic_app.data.enums import CampaignStatus, ContactOutcome
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.data.models.license import License
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact

# ============================================================================
# DEMO DATA
# ============================================================================

DEMO_CLINIC_NAME = "Sunshine Family Practice"

# Realistic patient dataset (names/phones are fictional)
DEMO_PATIENTS = [
    # Completed campaign patients (varied outcomes)
    {
        "name": "Maria Garcia",
        "phone": "+17875550101",
        "outcome": "accepted",
        "notes": "Patient acknowledged annual visit is overdue and agreed to schedule.",
    },
    {
        "name": "James Wilson",
        "phone": "+17875550102",
        "outcome": "voicemail",
        "notes": "Voicemail reached; message left with clinic callback number.",
    },
    {
        "name": "Angela Torres",
        "phone": "+17875550103",
        "outcome": "accepted",
        "notes": "Patient expressed intent to call clinic and schedule within the week.",
    },
    {
        "name": "Robert Kim",
        "phone": "+17875550104",
        "outcome": "declined",
        "notes": "Patient stated they recently had a visit at another location.",
    },
    {
        "name": "Linda Morales",
        "phone": "+17875550105",
        "outcome": "no_answer",
        "notes": "No answer after four rings; no voicemail detected.",
    },
    {
        "name": "David Chen",
        "phone": "+17875550106",
        "outcome": "accepted",
        "notes": "Patient was receptive; confirmed intent to schedule A1C follow-up.",
    },
    {
        "name": "Patricia Johnson",
        "phone": "+17875550107",
        "outcome": "voicemail",
        "notes": "Voicemail reached; message left.",
    },
    {
        "name": "Carlos Rivera",
        "phone": "+17875550108",
        "outcome": "accepted",
        "notes": "Patient agreed; requested morning appointment preference noted.",
    },
    {
        "name": "Susan Lee",
        "phone": "+17875550109",
        "outcome": "declined",
        "notes": "Patient declined; stated they are no longer a patient at this clinic.",
    },
    {
        "name": "Michael Patel",
        "phone": "+17875550110",
        "outcome": "no_answer",
        "notes": "No answer; attempt count recorded.",
    },
    # Draft campaign patients (pending)
    {"name": "Jennifer Adams", "phone": "+17875550201", "outcome": "pending", "notes": None},
    {"name": "Thomas Martinez", "phone": "+17875550202", "outcome": "pending", "notes": None},
    {"name": "Dorothy Hernandez", "phone": "+17875550203", "outcome": "pending", "notes": None},
    {"name": "Richard Lopez", "phone": "+17875550204", "outcome": "pending", "notes": None},
    {"name": "Margaret Brown", "phone": "+17875550205", "outcome": "pending", "notes": None},
]

COMPLETED_PATIENTS = [p for p in DEMO_PATIENTS if p["outcome"] != "pending"]
PENDING_PATIENTS = [p for p in DEMO_PATIENTS if p["outcome"] == "pending"]


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()


def _random_call_date(days_ago_max: int = 14) -> datetime:
    import random

    delta = timedelta(days=random.randint(0, days_ago_max), hours=random.randint(9, 17))
    return datetime.now(timezone.utc) - delta


def _random_duration(outcome: str) -> int | None:
    import random

    if outcome in ("accepted", "declined"):
        return random.randint(45, 180)
    elif outcome == "voicemail":
        return random.randint(15, 30)
    elif outcome == "no_answer":
        return random.randint(8, 20)
    return None


async def seed(db: AsyncSession) -> None:
    print("=" * 60)
    print("CallCenterAI Demo Seeder")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Clinic
    # ------------------------------------------------------------------
    existing = await db.execute(select(Clinic).where(Clinic.name == DEMO_CLINIC_NAME))
    clinic = existing.scalar_one_or_none()

    if clinic:
        print(f"[SKIP] Clinic already exists: {clinic.id}")
    else:
        clinic = Clinic(
            id=uuid.uuid4(),
            name=DEMO_CLINIC_NAME,
            tier="pro",
            status="active",
            license_token=f"demo-{uuid.uuid4().hex[:12]}",
            business_hours_start="09:00",
            business_hours_end="17:00",
        )
        db.add(clinic)
        await db.flush()
        print(f"[OK]   Created clinic: {clinic.id}  ({clinic.name})")

    clinic_id = clinic.id

    # ------------------------------------------------------------------
    # License
    # ------------------------------------------------------------------
    existing_lic = await db.get(License, clinic_id)
    if existing_lic:
        print(f"[SKIP] License already exists for clinic {clinic_id}")
    else:
        license_ = License(
            clinic_id=clinic_id,
            token=clinic.license_token,
            tier="pro",
            status="active",
            max_concurrency=3,
            features={"hedis_outreach": True, "gcal_integration": False},
        )
        db.add(license_)
        await db.flush()
        print(f"[OK]   Created license (tier=pro, max_concurrency=3)")

    # ------------------------------------------------------------------
    # ClinicIntegration
    # ------------------------------------------------------------------
    existing_int = await db.execute(
        select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
    )
    integration = existing_int.scalar_one_or_none()
    if integration:
        print(f"[SKIP] Integration already exists for clinic {clinic_id}")
    else:
        integration = ClinicIntegration(
            clinic_id=clinic_id,
            retell_agent_id="demo_agent_abc123",
            retell_did="+17875559000",
        )
        db.add(integration)
        await db.flush()
        print(f"[OK]   Created clinic integration (retell_agent_id=demo_agent_abc123)")

    # ------------------------------------------------------------------
    # Campaign 1 — Completed (wellness outreach)
    # ------------------------------------------------------------------
    existing_camp = await db.execute(
        select(Campaign).where(
            Campaign.clinic_id == clinic_id,
            Campaign.name == "Q3 Wellness Visit Outreach",
        )
    )
    campaign1 = existing_camp.scalar_one_or_none()

    if campaign1:
        print(f"[SKIP] Campaign 1 already exists: {campaign1.id}")
    else:
        campaign1 = Campaign(
            clinic_id=clinic_id,
            name="Q3 Wellness Visit Outreach",
            reason="Your annual wellness visit is overdue. Preventive care helps us catch issues early.",
            status=CampaignStatus.COMPLETED,
            total_contacts=len(COMPLETED_PATIENTS),
            completed_contacts=len(COMPLETED_PATIENTS),
        )
        db.add(campaign1)
        await db.flush()
        print(f"[OK]   Created campaign 1 (COMPLETED): {campaign1.id}")

        for p in COMPLETED_PATIENTS:
            enc_name = encrypt_phi(p["name"])
            enc_phone = encrypt_phi(p["phone"])
            ph_hash = _hash_phone(p["phone"])
            call_date = _random_call_date() if p["outcome"] != "pending" else None
            duration = _random_duration(p["outcome"])

            contact = CampaignContact(
                campaign_id=campaign1.id,
                clinic_id=clinic_id,
                patient_name_encrypted=enc_name,
                phone_encrypted=enc_phone,
                phone_hash=ph_hash,
                reason="Annual wellness visit is overdue.",
                outcome=p["outcome"],
                notes=p["notes"],
                call_date=call_date,
                call_duration_seconds=duration,
                attempt_count=1,
                retell_call_id=f"demo_{ph_hash[:8]}",
            )
            db.add(contact)
        await db.flush()
        print(f"[OK]   Seeded {len(COMPLETED_PATIENTS)} contacts with outcomes")

    # ------------------------------------------------------------------
    # Campaign 2 — Draft (A1C outreach, pending contacts)
    # ------------------------------------------------------------------
    existing_camp2 = await db.execute(
        select(Campaign).where(
            Campaign.clinic_id == clinic_id,
            Campaign.name == "Q4 A1C Follow-Up",
        )
    )
    campaign2 = existing_camp2.scalar_one_or_none()

    if campaign2:
        print(f"[SKIP] Campaign 2 already exists: {campaign2.id}")
    else:
        campaign2 = Campaign(
            clinic_id=clinic_id,
            name="Q4 A1C Follow-Up",
            reason="Your A1C test results are due for follow-up. Please schedule a visit with your care team.",
            status=CampaignStatus.DRAFT,
            total_contacts=len(PENDING_PATIENTS),
            completed_contacts=0,
        )
        db.add(campaign2)
        await db.flush()
        print(f"[OK]   Created campaign 2 (DRAFT): {campaign2.id}")

        for p in PENDING_PATIENTS:
            enc_name = encrypt_phi(p["name"])
            enc_phone = encrypt_phi(p["phone"])
            ph_hash = _hash_phone(p["phone"])
            contact = CampaignContact(
                campaign_id=campaign2.id,
                clinic_id=clinic_id,
                patient_name_encrypted=enc_name,
                phone_encrypted=enc_phone,
                phone_hash=ph_hash,
                reason="A1C follow-up appointment is recommended.",
                outcome=ContactOutcome.PENDING,
                attempt_count=0,
            )
            db.add(contact)
        await db.flush()
        print(f"[OK]   Seeded {len(PENDING_PATIENTS)} pending contacts")

    await db.commit()

    print()
    print("=" * 60)
    print("SEED COMPLETE — copy these IDs for your Swagger demo:")
    print(f"  clinic_id:    {clinic_id}")
    print(f"  campaign1_id: {campaign1.id}  (COMPLETED — view report)")
    print(f"  campaign2_id: {campaign2.id}  (DRAFT — upload CSV, start, process)")
    print()
    print("Demo flow:")
    print("  1. GET  /admin/clinics/{clinic_id}/campaigns")
    print("  2. GET  /admin/clinics/{clinic_id}/campaigns/{campaign1_id}/report")
    print("  3. POST /admin/clinics/{clinic_id}/campaigns/{campaign2_id}/start")
    print("  4. POST /admin/clinics/{clinic_id}/campaigns/{campaign2_id}/process-next  (x5)")
    print("  5. GET  /admin/clinics/{clinic_id}/campaigns/{campaign2_id}/report")
    print("=" * 60)


async def main():
    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
