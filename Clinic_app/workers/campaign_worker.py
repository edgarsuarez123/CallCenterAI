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
from datetime import datetime, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.common.database import AsyncSessionLocal
from Clinic_app.data.enums import CampaignStatus
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.services.campaign import simulate_next_call, get_next_pending_contact

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30
MAX_CONCURRENT_CALLS_PER_CLINIC = 3  # default; overridden by clinic license in production


async def _get_active_campaigns(db: AsyncSession) -> list[Campaign]:
    """Fetch all campaigns in QUEUED or RUNNING status."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.status.in_([CampaignStatus.QUEUED, CampaignStatus.RUNNING])
        )
    )
    return list(result.scalars().all())


async def _process_campaign(db: AsyncSession, campaign: Campaign) -> None:
    """
    Process a single campaign: pick next pending contact and simulate/trigger a call.
    Marks campaign as RUNNING on first call, COMPLETED when all contacts are done.
    """
    if campaign.status == CampaignStatus.QUEUED:
        campaign.status = CampaignStatus.RUNNING
        campaign.updated_at = datetime.now(timezone.utc)
        await db.flush()

    # Check if there are any pending contacts
    contact = await get_next_pending_contact(db, campaign.id, campaign.clinic_id)
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
        result = await simulate_next_call(db, campaign.id, campaign.clinic_id)
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
