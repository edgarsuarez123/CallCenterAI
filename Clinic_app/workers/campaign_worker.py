"""
Per-clinic asyncio campaign worker: outbound Retell dials with concurrency and calling hours.

One Task per clinic when any campaign is ACTIVE. Self-terminates when no ACTIVE campaigns remain.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time as dt_time, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, func

from Clinic_app.common.database import AsyncSessionLocal
from Clinic_app.common.encryption import decrypt_phi
from Clinic_app.data.enums import CampaignStatus, ContactStatus
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.clinic import Clinic
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.campaign_service import (
    count_calling_contacts,
    get_next_eligible_contact,
)
from Clinic_app.services.retell_client import RetellClientError, create_outbound_call

logger = logging.getLogger(__name__)

INTER_CALL_GAP_SECONDS = 5
NO_CONTACT_SLEEP_SECONDS = 10
AT_CAPACITY_SLEEP_SECONDS = 3
CALLING_HOURS_POLL_SECONDS = 60


def _mask_phone_e164(e164: str) -> str:
    digits = "".join(c for c in e164 if c.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else "****"
    return f"***-***-{last4}"


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    parts = hhmm.strip().split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    return h, m


def _local_now(integration: ClinicIntegration) -> datetime:
    try:
        tz = ZoneInfo(integration.timezone)
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def _is_within_calling_hours(
    integration: ClinicIntegration,
    start_str: str,
    end_str: str,
) -> bool:
    now = _local_now(integration)
    sh, sm = _parse_hhmm(start_str)
    eh, em = _parse_hhmm(end_str)
    start_t = dt_time(sh, sm)
    end_t = dt_time(eh, em)
    cur = now.time()
    if start_t <= end_t:
        return start_t <= cur <= end_t
    # Overnight window (rare)
    return cur >= start_t or cur <= end_t


async def _any_active_campaign(db, clinic_id: UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(Campaign)
        .where(
            Campaign.clinic_id == clinic_id,
            Campaign.status == CampaignStatus.ACTIVE.value,
        )
    )
    return int(result.scalar_one() or 0) > 0


async def _first_active_campaign(db, clinic_id: UUID) -> Optional[Campaign]:
    result = await db.execute(
        select(Campaign)
        .where(
            Campaign.clinic_id == clinic_id,
            Campaign.status == CampaignStatus.ACTIVE.value,
        )
        .order_by(Campaign.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class CampaignWorkerManager:
    """Singleton: one asyncio.Task per clinic_id."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def start_clinic_worker(self, clinic_id: UUID) -> None:
        async with self._lock:
            t = self._tasks.get(clinic_id)
            if t is not None and not t.done():
                return
            self._tasks[clinic_id] = asyncio.create_task(
                _clinic_worker_loop(clinic_id),
                name=f"campaign_worker:{clinic_id}",
            )

    async def stop_clinic_worker(self, clinic_id: UUID) -> None:
        async with self._lock:
            t = self._tasks.pop(clinic_id, None)
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def shutdown_all(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for t in tasks:
            if not t.done():
                t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass


campaign_worker_manager = CampaignWorkerManager()


async def resume_active_campaign_workers() -> None:
    """On app startup: restart workers for clinics with ACTIVE campaigns."""
    if AsyncSessionLocal is None:
        logger.warning("Campaign worker resume skipped: database not configured")
        return
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Campaign.clinic_id)
            .where(Campaign.status == CampaignStatus.ACTIVE.value)
            .distinct()
        )
        rows = result.all()
    for (clinic_id,) in rows:
        await campaign_worker_manager.start_clinic_worker(clinic_id)
        logger.info("Resumed campaign worker for clinic_id=%s", clinic_id)


async def _clinic_worker_loop(clinic_id: UUID) -> None:
    logger.info("Campaign worker started clinic_id=%s", clinic_id)
    try:
        while True:
            if AsyncSessionLocal is None:
                logger.error("Campaign worker exiting: DB unavailable clinic_id=%s", clinic_id)
                break

            try:
                async with AsyncSessionLocal() as db:
                    if not await _any_active_campaign(db, clinic_id):
                        logger.info(
                            "Campaign worker stopping: no active campaigns clinic_id=%s",
                            clinic_id,
                        )
                        break

                    integ_result = await db.execute(
                        select(ClinicIntegration).where(
                            ClinicIntegration.clinic_id == clinic_id
                        )
                    )
                    integration = integ_result.scalar_one_or_none()
                    if integration is None:
                        logger.error(
                            "Campaign worker: missing clinic_integration clinic_id=%s",
                            clinic_id,
                        )
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    camp = await _first_active_campaign(db, clinic_id)
                    if camp is None:
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    if not _is_within_calling_hours(
                        integration,
                        camp.calling_hours_start,
                        camp.calling_hours_end,
                    ):
                        await asyncio.sleep(CALLING_HOURS_POLL_SECONDS)
                        continue

                    limit = integration.campaign_concurrency_limit
                    active_calls = await count_calling_contacts(db, clinic_id)
                    if active_calls >= limit:
                        await asyncio.sleep(AT_CAPACITY_SLEEP_SECONDS)
                        continue

                    contact = await get_next_eligible_contact(db, clinic_id)
                    if contact is None:
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    clinic_result = await db.execute(
                        select(Clinic).where(Clinic.id == clinic_id)
                    )
                    clinic = clinic_result.scalar_one_or_none()
                    if clinic is None:
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    phone = decrypt_phi(contact.phone_encrypted)
                    patient_name = (
                        decrypt_phi(contact.patient_name_encrypted)
                        if contact.patient_name_encrypted
                        else ""
                    )
                    patient_dob = (
                        decrypt_phi(contact.patient_dob_encrypted)
                        if contact.patient_dob_encrypted
                        else ""
                    )

                    from_number = (
                        integration.retell_outbound_number
                        or os.environ.get("RETELL_FROM_NUMBER", "").strip()
                    )
                    if not from_number:
                        logger.error(
                            "Campaign worker: no outbound from_number "
                            "(set retell_outbound_number or RETELL_FROM_NUMBER) clinic_id=%s",
                            clinic_id,
                        )
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    callback_phone = integration.retell_did or from_number

                    metadata = {
                        "call_type": "hedis_campaign",
                        "campaign_contact_id": str(contact.id),
                        "gap_type": contact.gap_type,
                        "clinic_name": clinic.name,
                        "clinic_phone": callback_phone,
                        "patient_name": patient_name or "Patient",
                        "provider_name": contact.provider_name or "",
                        "payer": contact.payer or "",
                    }
                    if patient_dob:
                        metadata["patient_dob"] = patient_dob

                    try:
                        call_id = await create_outbound_call(
                            agent_id=integration.retell_agent_id,
                            from_number=from_number,
                            to_number=phone,
                            metadata=metadata,
                        )
                    except RetellClientError as exc:
                        logger.error(
                            "Retell outbound failed clinic_id=%s contact=%s err=%s",
                            clinic_id,
                            contact.id,
                            exc,
                        )
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue
                    except Exception as exc:
                        logger.error(
                            "Retell outbound unexpected error clinic_id=%s contact=%s",
                            clinic_id,
                            contact.id,
                            exc_info=True,
                        )
                        await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
                        continue

                    contact.status = ContactStatus.CALLING.value
                    contact.attempt_count = (contact.attempt_count or 0) + 1
                    contact.last_attempted_at = datetime.now(timezone.utc)

                    c_row = await db.get(Campaign, contact.campaign_id)
                    if c_row:
                        c_row.called_count = (c_row.called_count or 0) + 1

                    await db.commit()
                    logger.info(
                        "Outbound call placed retell_call_id=%s clinic_id=%s to=%s",
                        call_id,
                        clinic_id,
                        _mask_phone_e164(phone),
                    )

                await asyncio.sleep(INTER_CALL_GAP_SECONDS)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Campaign worker iteration error clinic_id=%s: %s",
                    clinic_id,
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(NO_CONTACT_SLEEP_SECONDS)
    except asyncio.CancelledError:
        logger.info("Campaign worker cancelled clinic_id=%s", clinic_id)
    finally:
        async with campaign_worker_manager._lock:
            campaign_worker_manager._tasks.pop(clinic_id, None)
