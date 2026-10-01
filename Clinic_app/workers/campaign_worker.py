"""
Background campaign worker — processes outbound HEDIS outreach calls.

Polls every 30 seconds for campaigns in QUEUED or RUNNING status.
In demo mode (RETELL_API_KEY not set): uses simulate_next_call() to
generate realistic outcomes without real API calls.
In production mode (RETELL_API_KEY set): would trigger real Retell
outbound calls (implementation stub included).

Started as an asyncio task via the FastAPI lifespan event in main.py.
"""

import asyncio
import logging
import os
import uuid as _uuid_mod
from datetime import datetime, time, timezone
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import AsyncSessionLocal
from Clinic_app.data.enums import CampaignStatus
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.clinic_integration import ClinicIntegration
from Clinic_app.services.campaign import simulate_next_call, get_next_pending_contact

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30
MAX_CONCURRENT_CALLS_PER_CLINIC = 3  # default; overridden by clinic license in production


# ── Time helpers ──────────────────────────────────────────────────────────────


def _local_now(integ) -> datetime:
    """Return the current datetime in the clinic's local timezone."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(integ.timezone or "UTC")
    except Exception:
        tz = timezone.utc
    return datetime.now(tz)


def _is_within_calling_hours(integ, start_str: str, end_str: str) -> bool:
    """Return True if the current local time is within [start_str, end_str] (HH:MM)."""
    now = _local_now(integ)
    try:
        start = time.fromisoformat(start_str)
        end = time.fromisoformat(end_str)
    except ValueError:
        return False
    return start <= now.time() <= end


# ── Per-clinic worker loop (stub — global loop handles all clinics) ───────────


async def _clinic_worker_loop(clinic_id: _uuid_mod.UUID) -> None:
    """Per-clinic worker loop placeholder. Global run_campaign_worker handles all clinics."""
    pass


# ── Campaign worker manager ───────────────────────────────────────────────────


class CampaignWorkerManager:
    """
    Manages per-clinic asyncio worker tasks.

    In the current implementation the global poll loop (run_campaign_worker)
    handles all clinics, so per-clinic tasks are lightweight stubs. The class
    exists so route code can call start_clinic_worker() without knowing about
    the global loop, and for unit-testability.
    """

    def __init__(self) -> None:
        self._tasks: Dict[_uuid_mod.UUID, asyncio.Task] = {}

    async def start_clinic_worker(self, clinic_id: _uuid_mod.UUID) -> None:
        """Start a per-clinic worker task if one is not already running."""
        existing = self._tasks.get(clinic_id)
        if existing is not None and not existing.done():
            return  # already running — idempotent
        self._tasks[clinic_id] = asyncio.create_task(_clinic_worker_loop(clinic_id))

    async def shutdown_all(self) -> None:
        """Cancel all running per-clinic tasks."""
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()


campaign_worker_manager = CampaignWorkerManager()


async def _get_active_campaigns(db: AsyncSession) -> list[Campaign]:
    """Fetch all campaigns in QUEUED or RUNNING status."""
    result = await db.execute(
        select(Campaign).where(Campaign.status.in_([CampaignStatus.QUEUED, CampaignStatus.RUNNING]))
    )
    return list(result.scalars().all())


async def _process_campaign(db: AsyncSession, campaign: Campaign) -> None:
    """
    Process a single campaign: pick next pending contact and simulate/trigger a call.
    Marks campaign as RUNNING on first call, COMPLETED when all contacts are done.
    Skips processing outside configured calling hours (9am-6pm clinic timezone by default).
    """
    # ── Calling hours enforcement ──────────────────────────────────────────────
    integ_result = await db.execute(
        select(ClinicIntegration).where(ClinicIntegration.clinic_id == campaign.clinic_id)
    )
    integ = integ_result.scalar_one_or_none()

    if integ is not None:
        start_str = campaign.calling_hours_start or integ.calling_hours_start or "09:00"
        end_str = campaign.calling_hours_end or integ.calling_hours_end or "18:00"
        if not _is_within_calling_hours(integ, start_str, end_str):
            logger.info(
                "[worker] Campaign %s: outside calling hours (%s-%s %s), skipping",
                campaign.id,
                start_str,
                end_str,
                integ.timezone or "UTC",
            )
            return
    # No integration row → demo mode; skip hours enforcement

    if campaign.status == CampaignStatus.QUEUED:
        campaign.status = CampaignStatus.RUNNING
        campaign.updated_at = datetime.now(timezone.utc)
        await db.flush()

    max_attempts = campaign.max_attempts or 3

    # Check if there are any pending contacts
    contact = await get_next_pending_contact(db, campaign.id, campaign.clinic_id, max_attempts)
    if not contact:
        # All contacts processed — mark complete if not already
        if campaign.status != CampaignStatus.COMPLETED:
            campaign.status = CampaignStatus.COMPLETED
            campaign.updated_at = datetime.now(timezone.utc)
            await db.flush()
            logger.info(f"[worker] Campaign {campaign.id} marked COMPLETED (no pending contacts)")
        return

    demo_mode = not os.getenv("RETELL_API_KEY")

    if demo_mode:
        result = await simulate_next_call(db, campaign.id, campaign.clinic_id, max_attempts)
        logger.info(
            f"[worker][DEMO] Campaign {campaign.id}: "
            f"contact {result.get('contact_id')} -> {result.get('outcome')}"
        )
    else:
        # Production: trigger real Retell outbound call
        # This would import and call retell_outbound.trigger_outbound_call()
        # Stubbed here — implement when RETELL_API_KEY is available
        logger.info(
            f"[worker] Campaign {campaign.id}: production call trigger not yet implemented; "
            "set RETELL_API_KEY and implement retell_outbound service"
        )


async def run_campaign_worker() -> None:
    """
    Main worker loop. Runs indefinitely, polling for active campaigns.
    Designed to be started as an asyncio background task.
    """
    logger.info("[worker] Campaign worker starting (poll interval: %ds)", POLL_INTERVAL_SECONDS)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                campaigns = await _get_active_campaigns(db)
                if campaigns:
                    logger.info(f"[worker] Found {len(campaigns)} active campaign(s)")
                    for campaign in campaigns:
                        try:
                            await _process_campaign(db, campaign)
                        except Exception as e:
                            logger.error(
                                f"[worker] Error processing campaign {campaign.id}: {e}",
                                exc_info=True,
                            )
                    await db.commit()
        except asyncio.CancelledError:
            logger.info("[worker] Campaign worker shutting down")
            break
        except Exception as e:
            logger.error(f"[worker] Unexpected error in worker loop: {e}", exc_info=True)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
