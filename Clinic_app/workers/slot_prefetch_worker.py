"""
Slot pre-fetch worker — keeps Redis slot cache warm for active HEDIS campaigns.

Runs one asyncio.Task per clinic with active campaigns. Every 60 seconds it uses
Browser-Use to navigate the EHR and find the next available appointment slots for
each active provider, then caches results in Redis (90s TTL).

This pre-fetch ensures GET /tools/get_available_slots can respond within Retell's
3-second deadline by reading from cache rather than launching a browser.

Integration:
  CampaignWorkerManager.start_clinic_worker  → slot_prefetch_manager.start(clinic_id)
  CampaignWorkerManager.stop_clinic_worker   → slot_prefetch_manager.stop(clinic_id)
  main.py lifespan shutdown                  → slot_prefetch_manager.stop_all()
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from Clinic_app.common.database import AsyncSessionLocal
from Clinic_app.data.enums import CampaignStatus, APPOINTMENT_BASED_GAP_TYPES
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
from Clinic_app.services.playbook_cache import set_cached_slots

logger = logging.getLogger(__name__)

PREFETCH_INTERVAL_SECONDS = 60
MAX_PROVIDERS_PER_CYCLE = 5


class SlotPrefetchManager:
    """Manages one pre-fetch asyncio.Task per clinic_id."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start(self, clinic_id: UUID) -> None:
        """Start pre-fetch loop for a clinic if not already running."""
        async with self._lock:
            t = self._tasks.get(clinic_id)
            if t is not None and not t.done():
                return
            self._tasks[clinic_id] = asyncio.create_task(
                _prefetch_loop(clinic_id),
                name=f"slot_prefetch:{clinic_id}",
            )
            logger.info("SlotPrefetchWorker started for clinic_id=%s", clinic_id)

    async def stop(self, clinic_id: UUID) -> None:
        """Cancel the pre-fetch loop for a clinic."""
        async with self._lock:
            t = self._tasks.pop(clinic_id, None)
        if t is not None and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        logger.info("SlotPrefetchWorker stopped for clinic_id=%s", clinic_id)

    async def stop_all(self) -> None:
        """Cancel all pre-fetch loops (called on app shutdown)."""
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
        logger.info("SlotPrefetchWorker: all tasks stopped")


slot_prefetch_manager = SlotPrefetchManager()


async def _prefetch_loop(clinic_id: UUID) -> None:
    """
    Background loop: every 60s, find active providers for this clinic and
    use Browser-Use to discover next available slots, caching results in Redis.
    Exits when no active appointment-based campaigns remain.
    """
    logger.info("slot_prefetch_loop starting for clinic_id=%s", clinic_id)
    try:
        while True:
            if AsyncSessionLocal is None:
                logger.error("SlotPrefetchWorker: DB unavailable, stopping clinic_id=%s", clinic_id)
                break

            try:
                async with AsyncSessionLocal() as db:
                    # Check if there are active appointment-based campaigns
                    providers = await _get_active_providers(db, clinic_id)

                if not providers:
                    logger.info(
                        "SlotPrefetchWorker: no active appointment-based providers, "
                        "stopping for clinic_id=%s",
                        clinic_id,
                    )
                    break

                # Import here to avoid circular imports at module load
                from Clinic_app.services.playwright_ehr import playwright_ehr_service

                for provider_name in providers[:MAX_PROVIDERS_PER_CYCLE]:
                    try:
                        async with AsyncSessionLocal() as db:
                            slots = await playwright_ehr_service.fetch_slots_live(
                                db, clinic_id, provider_name
                            )
                        if slots:
                            await set_cached_slots(clinic_id, provider_name, slots)
                            logger.info(
                                "Pre-fetched %d slots for clinic %s provider '%s'",
                                len(slots),
                                clinic_id,
                                provider_name,
                            )
                        else:
                            logger.warning(
                                "No slots returned for clinic %s provider '%s' — "
                                "EHR may be fully booked or navigation failed",
                                clinic_id,
                                provider_name,
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.error(
                            "slot_prefetch_loop error for clinic %s provider '%s': %s",
                            clinic_id,
                            provider_name,
                            e,
                        )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("slot_prefetch_loop outer error clinic_id=%s: %s", clinic_id, e)

            await asyncio.sleep(PREFETCH_INTERVAL_SECONDS)

    except asyncio.CancelledError:
        logger.info("slot_prefetch_loop cancelled for clinic_id=%s", clinic_id)


async def _get_active_providers(db, clinic_id: UUID) -> list[str]:
    """
    Return distinct provider names from PENDING appointment-based contacts
    for active campaigns belonging to this clinic. Capped at MAX_PROVIDERS_PER_CYCLE.
    """
    # First check if EHR config exists — no point pre-fetching without it
    ehr_result = await db.execute(
        select(ClinicEHRConfig).where(ClinicEHRConfig.clinic_id == clinic_id)
    )
    if ehr_result.scalar_one_or_none() is None:
        return []

    # Find active campaigns for this clinic that have appointment-based gap types
    campaigns_result = await db.execute(
        select(Campaign.id).where(
            Campaign.clinic_id == clinic_id,
            Campaign.status == CampaignStatus.ACTIVE.value,
        )
    )
    campaign_ids = [row[0] for row in campaigns_result.all()]
    if not campaign_ids:
        return []

    # Get distinct providers from PENDING contacts with appointment-based gap types
    appointment_gap_values = [g.value for g in APPOINTMENT_BASED_GAP_TYPES]
    contacts_result = await db.execute(
        select(CampaignContact.provider_name)
        .where(
            CampaignContact.campaign_id.in_(campaign_ids),
            CampaignContact.status == "pending",
            CampaignContact.gap_type.in_(appointment_gap_values),
            CampaignContact.provider_name.isnot(None),
        )
        .distinct()
        .limit(MAX_PROVIDERS_PER_CYCLE)
    )
    providers = [row[0] for row in contacts_result.all() if row[0]]
    return providers
