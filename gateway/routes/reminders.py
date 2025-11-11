"""
Reminder Management API Routes

Provides endpoints for managing appointment reminders, including:
- Scheduling reminders for appointments
- Viewing reminder status and history
- Cancelling reminders
- Manual reminder execution
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from services.database import get_async_db
from services.reminder_service import get_reminder_service
from services.structured_logging import get_logger, LogCategory
from services.exceptions import ValidationError
from models.models import Reminder, ReminderLog

router = APIRouter(prefix="/reminders", tags=["Reminders"])
logger = get_logger("reminder_routes")


# Pydantic models for request/response
class ReminderScheduleRequest(BaseModel):
    """Request model for scheduling a reminder."""
    appointment_id: str = Field(..., description="ID of the appointment to remind about")
    reminder_type: str = Field(default="appointment_reminder", description="Type of reminder")
    custom_scheduled_time: Optional[datetime] = Field(None, description="Custom scheduled time (optional)")


class ReminderResponse(BaseModel):
    """Response model for reminder information."""
    reminder_id: str
    appointment_id: str
    scheduled_time: datetime
    reminder_type: str
    status: str
    retry_count: int
    max_retries: int
    next_retry_time: Optional[datetime]
    call_duration_seconds: Optional[int]
    call_outcome: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]


class ReminderLogResponse(BaseModel):
    """Response model for reminder log information."""
    log_id: str
    reminder_id: str
    attempt_number: int
    call_started_at: datetime
    call_ended_at: Optional[datetime]
    call_status: str
    call_duration_seconds: Optional[int]
    call_outcome: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    caller_id: Optional[str]
    created_at: datetime


class ReminderExecutionResponse(BaseModel):
    """Response model for reminder execution results."""
    reminder_id: str
    status: str
    outcome: Optional[str]
    duration_seconds: Optional[int]
    retry_count: int
    next_retry_time: Optional[datetime]


@router.post("/schedule", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def schedule_reminder(
    request: ReminderScheduleRequest,
    db: AsyncSession = Depends(get_async_db)
):
    """
    Schedule a reminder call for an appointment.
    
    This endpoint creates a new reminder that will be executed at the scheduled time.
    The reminder time is calculated based on clinic settings unless a custom time is provided.
    """
    reminder_service = get_reminder_service()
    
    reminder = await reminder_service.schedule_reminder(
        db=db,
        appointment_id=request.appointment_id,
        reminder_type=request.reminder_type,
        custom_scheduled_time=request.custom_scheduled_time
    )
    
    logger.info(f"Reminder scheduled successfully", LogCategory.REMINDER,
               extra_data={
                   'reminder_id': reminder.reminder_id,
                   'appointment_id': request.appointment_id,
                   'scheduled_time': reminder.scheduled_time.isoformat()
               })
    
    return ReminderResponse(
        reminder_id=reminder.reminder_id,
        appointment_id=reminder.appointment_id,
        scheduled_time=reminder.scheduled_time,
        reminder_type=reminder.reminder_type,
        status=reminder.status,
        retry_count=reminder.retry_count,
        max_retries=reminder.max_retries,
        next_retry_time=reminder.next_retry_time,
        call_duration_seconds=reminder.call_duration_seconds,
        call_outcome=reminder.call_outcome,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
        completed_at=reminder.completed_at
    )


@router.get("/{reminder_id}", response_model=ReminderResponse)
async def get_reminder(
    reminder_id: str = Path(..., min_length=3, max_length=64, description="Reminder ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get details of a specific reminder.
    """
    result = await db.execute(
        select(Reminder).where(
            Reminder.reminder_id == reminder_id,
            Reminder.is_deleted == 'no'
        )
    )
    reminder = result.scalar_one_or_none()
    
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder {reminder_id} not found"
        )
    
    return ReminderResponse(
        reminder_id=reminder.reminder_id,
        appointment_id=reminder.appointment_id,
        scheduled_time=reminder.scheduled_time,
        reminder_type=reminder.reminder_type,
        status=reminder.status,
        retry_count=reminder.retry_count,
        max_retries=reminder.max_retries,
        next_retry_time=reminder.next_retry_time,
        call_duration_seconds=reminder.call_duration_seconds,
        call_outcome=reminder.call_outcome,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
        completed_at=reminder.completed_at
    )


@router.get("/{reminder_id}/logs", response_model=List[ReminderLogResponse])
async def get_reminder_logs(
    reminder_id: str = Path(..., min_length=3, max_length=64, description="Reminder ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get the call logs for a specific reminder.
    """
    # Verify reminder exists
    reminder_result = await db.execute(
        select(Reminder).where(
            Reminder.reminder_id == reminder_id,
            Reminder.is_deleted == 'no'
        )
    )
    reminder = reminder_result.scalar_one_or_none()
    
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reminder {reminder_id} not found"
        )
    
    # Get reminder logs
    logs_result = await db.execute(
        select(ReminderLog).where(
            ReminderLog.reminder_id == reminder_id,
            ReminderLog.is_deleted == 'no'
        ).order_by(ReminderLog.attempt_number.asc())
    )
    logs = logs_result.scalars().all()
    
    return [
        ReminderLogResponse(
            log_id=log.log_id,
            reminder_id=log.reminder_id,
            attempt_number=log.attempt_number,
            call_started_at=log.call_started_at,
            call_ended_at=log.call_ended_at,
            call_status=log.call_status,
            call_duration_seconds=log.call_duration_seconds,
            call_outcome=log.call_outcome,
            error_code=log.error_code,
            error_message=log.error_message,
            caller_id=log.caller_id,
            created_at=log.created_at
        )
        for log in logs
    ]


@router.post("/{reminder_id}/execute", response_model=ReminderExecutionResponse)
async def execute_reminder(
    reminder_id: str = Path(..., min_length=3, max_length=64, description="Reminder ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Manually execute a reminder call.
    
    This endpoint allows manual execution of a reminder, bypassing the scheduled time.
    Useful for testing or urgent reminder needs.
    """
    reminder_service = get_reminder_service()
    
    result = await reminder_service.execute_reminder(db, reminder_id)
    
    logger.info(f"Reminder executed manually", LogCategory.REMINDER,
               extra_data={
                   'reminder_id': reminder_id,
                   'status': result['status'],
                   'outcome': result.get('outcome')
               })
    
    # Handle next_retry_time - service returns ISO string, convert to datetime if needed
    next_retry_time = result.get('next_retry_time')
    if next_retry_time and isinstance(next_retry_time, str):
        try:
            next_retry_time = datetime.fromisoformat(next_retry_time.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            # If parsing fails, set to None
            next_retry_time = None
    
    return ReminderExecutionResponse(
        reminder_id=result['reminder_id'],
        status=result['status'],
        outcome=result.get('outcome'),
        duration_seconds=result.get('duration_seconds'),
        retry_count=result['retry_count'],
        next_retry_time=next_retry_time
    )


@router.delete("/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_reminder(
    reminder_id: str = Path(..., min_length=3, max_length=64, description="Reminder ID"),
    reason: str = Query("cancelled_by_user", description="Reason for cancellation"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Cancel a scheduled reminder.
    
    This endpoint cancels a reminder that hasn't been completed yet.
    """
    reminder_service = get_reminder_service()
    
    success = await reminder_service.cancel_reminder(db, reminder_id, reason)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Reminder {reminder_id} could not be cancelled"
        )
    
    logger.info(f"Reminder cancelled successfully", LogCategory.REMINDER,
               extra_data={
                   'reminder_id': reminder_id,
                   'reason': reason
               })


@router.get("/appointment/{appointment_id}", response_model=List[ReminderResponse])
async def get_appointment_reminders(
    appointment_id: str = Path(..., min_length=3, max_length=64, description="Appointment ID"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Get all reminders for a specific appointment.
    """
    result = await db.execute(
        select(Reminder).where(
            Reminder.appointment_id == appointment_id,
            Reminder.is_deleted == 'no'
        ).order_by(Reminder.created_at.desc())
    )
    reminders = result.scalars().all()
    
    return [
        ReminderResponse(
            reminder_id=reminder.reminder_id,
            appointment_id=reminder.appointment_id,
            scheduled_time=reminder.scheduled_time,
            reminder_type=reminder.reminder_type,
            status=reminder.status,
            retry_count=reminder.retry_count,
            max_retries=reminder.max_retries,
            next_retry_time=reminder.next_retry_time,
            call_duration_seconds=reminder.call_duration_seconds,
            call_outcome=reminder.call_outcome,
            created_at=reminder.created_at,
            updated_at=reminder.updated_at,
            completed_at=reminder.completed_at
        )
        for reminder in reminders
    ]


@router.get("/due/process", response_model=Dict[str, Any])
async def process_due_reminders(
    limit: int = Query(50, ge=1, le=500, description="Maximum number of reminders to process"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    Manually trigger processing of due reminders.
    
    This endpoint allows manual execution of the reminder processing job.
    Useful for testing or urgent reminder processing needs.
    
    Args:
        limit: Maximum number of reminders to process (1-500)
    """
    reminder_service = get_reminder_service()
    
    # Get due reminders
    due_reminders = await reminder_service.get_due_reminders(db, limit=limit)
    
    processed_count = 0
    success_count = 0
    failed_count = 0
    
    for reminder in due_reminders:
        try:
            processed_count += 1
            result = await reminder_service.execute_reminder(db, reminder.reminder_id)
            
            if result['status'] == 'completed':
                success_count += 1
            else:
                failed_count += 1
                
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to process reminder {reminder.reminder_id}: {e}", LogCategory.REMINDER, exception=e)
    
    logger.info(f"Manually processed {processed_count} due reminders", LogCategory.REMINDER,
               extra_data={
                   'processed_count': processed_count,
                   'success_count': success_count,
                   'failed_count': failed_count
               })
    
    return {
        'processed_count': processed_count,
        'success_count': success_count,
        'failed_count': failed_count,
        'message': f"Processed {processed_count} reminders: {success_count} successful, {failed_count} failed"
    }
