# Clinic_app/services/clinic_service.py
"""
Clinic settings service — read and update ClinicIntegration operational defaults.
These defaults (calling hours, max attempts, retry hours) are configurable by
clinic admins from the dashboard without needing a superadmin API key.
"""

import logging
from zoneinfo import available_timezones
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from Clinic_app.data.models.clinic_integration import ClinicIntegration

logger = logging.getLogger(__name__)


async def get_clinic_settings(db: AsyncSession, clinic_id: UUID) -> ClinicIntegration:
    """
    Return the ClinicIntegration row for the given clinic.
    Raises 404 if no integration record exists yet.
    """
    result = await db.execute(
        select(ClinicIntegration).where(ClinicIntegration.clinic_id == clinic_id)
    )
    integration = result.scalar_one_or_none()
    if integration is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SETTINGS_NOT_FOUND",
                "message": "Clinic integration settings not configured yet.",
            },
        )
    return integration


def validate_hhmm(value: str, field_name: str) -> None:
    """Validate a string is a valid HH:MM time value."""
    try:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError()
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TIME",
                "message": f"{field_name} must be HH:MM format (00:00–23:59).",
            },
        )


async def update_clinic_settings(
    db: AsyncSession,
    clinic_id: UUID,
    *,
    calling_hours_start: str | None = None,
    calling_hours_end: str | None = None,
    campaign_concurrency_limit: int | None = None,
    max_attempts: int | None = None,
    voicemail_retry_hours: int | None = None,
    no_answer_retry_hours: int | None = None,
    error_retry_hours: int | None = None,
    timezone: str | None = None,
) -> ClinicIntegration:
    """
    Partially update ClinicIntegration settings. Only provided fields are changed.
    Validates field values before applying. Raises 422 on invalid input.
    """
    integration = await get_clinic_settings(db, clinic_id)

    # Collect final values (merge incoming with current) for cross-field validation
    new_start = calling_hours_start or integration.calling_hours_start
    new_end = calling_hours_end or integration.calling_hours_end

    if calling_hours_start is not None:
        validate_hhmm(calling_hours_start, "calling_hours_start")
    if calling_hours_end is not None:
        validate_hhmm(calling_hours_end, "calling_hours_end")

    # Validate start < end after normalizing both
    if new_start >= new_end:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_HOURS",
                "message": "calling_hours_start must be before calling_hours_end.",
            },
        )

    if campaign_concurrency_limit is not None and not (1 <= campaign_concurrency_limit <= 10):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_CONCURRENCY",
                "message": "campaign_concurrency_limit must be between 1 and 10.",
            },
        )

    if max_attempts is not None and not (1 <= max_attempts <= 5):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_ATTEMPTS", "message": "max_attempts must be between 1 and 5."},
        )

    for field_val, field_name in [
        (voicemail_retry_hours, "voicemail_retry_hours"),
        (no_answer_retry_hours, "no_answer_retry_hours"),
        (error_retry_hours, "error_retry_hours"),
    ]:
        if field_val is not None and not (1 <= field_val <= 72):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_RETRY_HOURS",
                    "message": f"{field_name} must be between 1 and 72.",
                },
            )

    if timezone is not None and timezone not in available_timezones():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_TIMEZONE",
                "message": f"'{timezone}' is not a valid IANA timezone.",
            },
        )

    # Apply changes
    if calling_hours_start is not None:
        integration.calling_hours_start = calling_hours_start
    if calling_hours_end is not None:
        integration.calling_hours_end = calling_hours_end
    if campaign_concurrency_limit is not None:
        integration.campaign_concurrency_limit = campaign_concurrency_limit
    if max_attempts is not None:
        integration.max_attempts = max_attempts
    if voicemail_retry_hours is not None:
        integration.voicemail_retry_hours = voicemail_retry_hours
    if no_answer_retry_hours is not None:
        integration.no_answer_retry_hours = no_answer_retry_hours
    if error_retry_hours is not None:
        integration.error_retry_hours = error_retry_hours
    if timezone is not None:
        integration.timezone = timezone

    await db.commit()
    await db.refresh(integration)
    logger.info(f"clinic_id={clinic_id} settings updated")
    return integration
