"""
Booking reaper — expires tentative booking holds that have passed their hold_expires_at.

Runs every 60 seconds via APScheduler (wired in main.py lifespan).
Prevents stale TENTATIVE holds from blocking appointment slots indefinitely
when a call drops or the patient hangs up before confirming.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_booking_reaper() -> None:
    """
    Find and expire all TENTATIVE bookings whose hold_expires_at has passed.
    Each expired booking is committed individually so a single failure
    does not roll back the entire batch.
    """
    from Clinic_app.common.database import AsyncSessionLocal
    from Clinic_app.services.booking import get_expired_tentative_bookings, expire_booking

    try:
        async with AsyncSessionLocal() as db:
            expired = await get_expired_tentative_bookings(db)
            if not expired:
                return

            logger.info(f"Booking reaper: found {len(expired)} expired hold(s)")
            for booking in expired:
                try:
                    await expire_booking(db, booking.id)
                    await db.commit()
                    logger.info(f"Booking reaper: expired booking {booking.id}")
                except Exception as exc:
                    await db.rollback()
                    logger.error(
                        f"Booking reaper: failed to expire booking {booking.id}: {exc}",
                        exc_info=True,
                    )
    except Exception as exc:
        logger.error(f"Booking reaper: unexpected error: {exc}", exc_info=True)
