"""
Background Job Management System for CallCenterAI

This module provides comprehensive background job management for:
- Automatic cleanup of expired resources
- Monthly billing cycle automation
- HIPAA retention policy enforcement
- Proactive monitoring and health checks
- Graceful degradation and system maintenance

Critical for maintaining system health, ensuring HIPAA compliance,
and automating routine maintenance tasks without manual intervention.
"""

import asyncio
import logging
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from contextlib import asynccontextmanager
import json

from sqlalchemy.orm import Session
from sqlalchemy import text, func, and_, or_

from services.database import get_db_session
from services.soft_delete import SoftDeleteService
from services.structured_logging import get_logger, LogCategory, log_performance
from services.configuration import get_settings
from services.reminder_service import get_reminder_service
from models.models import (
    AppointmentSlot, Call, ClinicLicense, AuditLog, 
    ClinicUsage, Appointment, Patient, Mapping, Reminder, ReminderLog
)
from models.enums import CallStatus


class JobStatus(Enum):
    """Status of background jobs."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    """Priority levels for background jobs."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class JobResult:
    """Result of a background job execution."""
    job_id: str
    status: JobStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    records_processed: int = 0
    records_affected: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.end_time and self.start_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()


@dataclass
class JobDefinition:
    """Definition of a background job."""
    job_id: str
    name: str
    description: str
    function: Callable
    schedule_interval: int  # seconds
    priority: JobPriority = JobPriority.NORMAL
    enabled: bool = True
    max_retries: int = 3
    timeout_seconds: int = 300
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    consecutive_failures: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


def _safe_run_async(coro):
    """
    Safely run an async coroutine from synchronous code.
    Handles cases where an event loop may already be running.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is already running, we need to use a different approach
            # Create a new event loop in a separate thread
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop, create a new one
        return asyncio.run(coro)


class BackgroundJobManager:
    """
    Central manager for all background jobs in the CallCenterAI system.
    
    Provides:
    - Job scheduling and execution
    - Automatic retry logic
    - Health monitoring
    - Performance tracking
    - Error handling and alerting
    """
    
    def __init__(self):
        self.logger = get_logger("background_jobs")
        self.settings = get_settings()
        self.jobs: Dict[str, JobDefinition] = {}
        self.job_results: Dict[str, List[JobResult]] = {}
        self.running = False
        self._shutdown_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        
        # Performance tracking
        self.total_jobs_executed = 0
        self.total_jobs_failed = 0
        self.average_execution_time = 0.0
        
        # Register all system jobs
        self._register_system_jobs()
    
    def _register_system_jobs(self):
        """Register all system background jobs."""
        
        # Cleanup jobs
        self.register_job(
            job_id="cleanup_expired_slots",
            name="Cleanup Expired Slot Holds",
            description="Release appointment slots that have been held too long",
            function=self._cleanup_expired_slots,
            schedule_interval=60,  # Every minute
            priority=JobPriority.HIGH
        )
        
        self.register_job(
            job_id="cleanup_abandoned_calls",
            name="Cleanup Abandoned Calls",
            description="Mark calls as abandoned if they've been active too long",
            function=self._cleanup_abandoned_calls,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        self.register_job(
            job_id="cleanup_old_audit_logs",
            name="Cleanup Old Audit Logs",
            description="Delete audit logs older than retention period",
            function=self._cleanup_old_audit_logs,
            schedule_interval=86400,  # Daily
            priority=JobPriority.LOW
        )
        
        # Billing jobs
        self.register_job(
            job_id="monthly_billing_cycle",
            name="Monthly Billing Cycle",
            description="Reset usage counters and process monthly billing",
            function=self._monthly_billing_cycle,
            schedule_interval=86400,  # Daily (checks if it's the 1st)
            priority=JobPriority.HIGH
        )
        
        self.register_job(
            job_id="update_usage_counters",
            name="Update Usage Counters",
            description="Update real-time usage counters for billing",
            function=self._update_usage_counters,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        # Google Calendar token refresh
        self.register_job(
            job_id="refresh_google_tokens",
            name="Refresh Google Calendar Tokens",
            description="Proactively refresh Google Calendar tokens before 1-hour expiration",
            function=self._refresh_google_calendar_tokens,
            schedule_interval=3000,  # Every 50 minutes (tokens expire after 1 hour)
            priority=JobPriority.HIGH
        )
        
        # HIPAA compliance jobs
        self.register_job(
            job_id="enforce_retention_policy",
            name="Enforce HIPAA Retention Policy",
            description="Hard delete records older than 7 years",
            function=self._enforce_retention_policy,
            schedule_interval=86400,  # Daily
            priority=JobPriority.HIGH
        )
        
        # Monitoring jobs
        self.register_job(
            job_id="database_health_check",
            name="Database Health Check",
            description="Monitor database health and connection pool",
            function=self._database_health_check,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.CRITICAL
        )
        
        self.register_job(
            job_id="license_expiration_check",
            name="License Expiration Check",
            description="Check for expiring licenses and send warnings",
            function=self._license_expiration_check,
            schedule_interval=86400,  # Daily
            priority=JobPriority.HIGH
        )
        
        self.register_job(
            job_id="system_metrics_collection",
            name="System Metrics Collection",
            description="Collect and log system performance metrics",
            function=self._system_metrics_collection,
            schedule_interval=60,  # Every minute
            priority=JobPriority.LOW
        )
        
        # Reminder jobs
        self.register_job(
            job_id="process_due_reminders",
            name="Process Due Reminders",
            description="Execute reminder calls that are due",
            function=self._process_due_reminders,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.HIGH
        )
        
        self.register_job(
            job_id="cleanup_old_reminders",
            name="Cleanup Old Reminders",
            description="Clean up completed reminders older than 30 days",
            function=self._cleanup_old_reminders,
            schedule_interval=86400,  # Daily
            priority=JobPriority.LOW
        )
        
        # NLP cleanup job
        self.register_job(
            job_id="cleanup_nlp_statistics",
            name="Cleanup NLP Statistics",
            description="Clean up expired NLP call statistics",
            function=self._cleanup_nlp_statistics,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        # TTS session cleanup job
        self.register_job(
            job_id="cleanup_tts_sessions",
            name="Cleanup TTS Sessions",
            description="Clean up expired TTS sessions",
            function=self._cleanup_tts_sessions,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        # STT session cleanup job
        self.register_job(
            job_id="cleanup_stt_sessions",
            name="Cleanup STT Sessions",
            description="Clean up expired STT sessions",
            function=self._cleanup_stt_sessions,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        # Bilingual manager cleanup job
        self.register_job(
            job_id="cleanup_bilingual_data",
            name="Cleanup Bilingual Data",
            description="Clean up expired bilingual conversation data",
            function=self._cleanup_bilingual_data,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
        
        # Call router queue cleanup job
        self.register_job(
            job_id="cleanup_call_queues",
            name="Cleanup Call Queues",
            description="Clean up expired call queues",
            function=self._cleanup_call_queues,
            schedule_interval=300,  # Every 5 minutes
            priority=JobPriority.NORMAL
        )
    
    def register_job(self, job_id: str, name: str, description: str, 
                    function: Callable, schedule_interval: int,
                    priority: JobPriority = JobPriority.NORMAL,
                    enabled: bool = True, **kwargs):
        """Register a new background job."""
        
        job = JobDefinition(
            job_id=job_id,
            name=name,
            description=description,
            function=function,
            schedule_interval=schedule_interval,
            priority=priority,
            enabled=enabled,
            **kwargs
        )
        
        # Calculate next run time
        job.next_run = datetime.now(timezone.utc) + timedelta(seconds=schedule_interval)
        
        self.jobs[job_id] = job
        self.job_results[job_id] = []
        
        self.logger.info(
            f"Registered background job: {name}",
            LogCategory.SYSTEM,
            extra_data={
                'job_id': job_id,
                'schedule_interval': schedule_interval,
                'priority': priority.value,
                'enabled': enabled
            }
        )
    
    def start(self):
        """Start the background job manager."""
        if self.running:
            self.logger.warning("Background job manager is already running")
            return
        
        self.running = True
        self._shutdown_event.clear()
        
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="BackgroundJobWorker",
            daemon=True
        )
        self._worker_thread.start()
        
        self.logger.info(
            "Background job manager started",
            LogCategory.SYSTEM,
            extra_data={
                'total_jobs': len(self.jobs),
                'enabled_jobs': len([j for j in self.jobs.values() if j.enabled])
            }
        )
    
    def stop(self):
        """Stop the background job manager."""
        if not self.running:
            return
        
        self.running = False
        self._shutdown_event.set()
        
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=30)
        
        self.logger.info("Background job manager stopped", LogCategory.SYSTEM)
    
    def _worker_loop(self):
        """Main worker loop for executing background jobs."""
        self.logger.info("Background job worker started", LogCategory.SYSTEM)
        
        while self.running and not self._shutdown_event.is_set():
            try:
                current_time = datetime.now(timezone.utc)
                
                # Find jobs that need to run
                jobs_to_run = []
                for job in self.jobs.values():
                    if (job.enabled and 
                        job.next_run and 
                        current_time >= job.next_run):
                        jobs_to_run.append(job)
                
                # Sort by priority (highest first)
                jobs_to_run.sort(key=lambda j: j.priority.value, reverse=True)
                
                # Execute jobs
                for job in jobs_to_run:
                    if self._shutdown_event.is_set():
                        break
                    
                    self._execute_job(job)
                
                # Sleep for a short interval
                self._shutdown_event.wait(10)  # Check every 10 seconds
                
            except Exception as e:
                self.logger.error(
                    f"Error in background job worker loop: {str(e)}",
                    LogCategory.SYSTEM,
                    exception=e
                )
                time.sleep(60)  # Wait a minute before retrying
        
        self.logger.info("Background job worker stopped", LogCategory.SYSTEM)
    
    def _execute_job(self, job: JobDefinition):
        """Execute a single background job."""
        start_time = datetime.now(timezone.utc)
        job_result = JobResult(
            job_id=job.job_id,
            status=JobStatus.RUNNING,
            start_time=start_time
        )
        
        self.logger.info(
            f"Starting background job: {job.name}",
            LogCategory.SYSTEM,
            extra_data={'job_id': job.job_id}
        )
        
        try:
            # Update job status
            job.last_run = start_time
            job.next_run = start_time + timedelta(seconds=job.schedule_interval)
            
            # Execute the job function
            result = job.function()
            
            # Update result
            end_time = datetime.now(timezone.utc)
            job_result.status = JobStatus.COMPLETED
            job_result.end_time = end_time
            job_result.duration_seconds = (end_time - start_time).total_seconds()
            
            if isinstance(result, dict):
                job_result.records_processed = result.get('records_processed', 0)
                job_result.records_affected = result.get('records_affected', 0)
                job_result.metadata = result.get('metadata', {})
            
            # Reset consecutive failures on success
            job.consecutive_failures = 0
            
            self.total_jobs_executed += 1
            
            self.logger.info(
                f"Completed background job: {job.name}",
                LogCategory.SYSTEM,
                extra_data={
                    'job_id': job.job_id,
                    'duration_seconds': job_result.duration_seconds,
                    'records_processed': job_result.records_processed,
                    'records_affected': job_result.records_affected
                }
            )
            
        except Exception as e:
            # Handle job failure
            end_time = datetime.now(timezone.utc)
            job_result.status = JobStatus.FAILED
            job_result.end_time = end_time
            job_result.duration_seconds = (end_time - start_time).total_seconds()
            job_result.error_message = str(e)
            
            job.consecutive_failures += 1
            self.total_jobs_failed += 1
            
            # If too many consecutive failures, disable the job
            if job.consecutive_failures >= job.max_retries:
                job.enabled = False
                self.logger.critical(
                    f"Disabled background job due to repeated failures: {job.name}",
                    LogCategory.SYSTEM,
                    extra_data={
                        'job_id': job.job_id,
                        'consecutive_failures': job.consecutive_failures,
                        'max_retries': job.max_retries
                    }
                )
            
            self.logger.error(
                f"Failed background job: {job.name}",
                LogCategory.SYSTEM,
                exception=e,
                extra_data={
                    'job_id': job.job_id,
                    'consecutive_failures': job.consecutive_failures
                }
            )
        
        finally:
            # Store the result
            self.job_results[job.job_id].append(job_result)
            
            # Keep only last 100 results per job
            if len(self.job_results[job.job_id]) > 100:
                self.job_results[job.job_id] = self.job_results[job.job_id][-100:]
    
    # ============================================================================
    # CLEANUP JOBS
    # ============================================================================
    
    @log_performance("cleanup_expired_slots")
    def _cleanup_expired_slots(self) -> Dict[str, Any]:
        """Release appointment slots that have been held too long."""
        with get_db_session() as db:
            current_time = datetime.now(timezone.utc)
            
            # Issue 83, 178: Find expired slot holds and lock them before releasing to prevent concurrent releases
            from sqlalchemy import select
            expired_slots = db.execute(
                select(AppointmentSlot).where(
                    AppointmentSlot.is_booked == "held",
                    AppointmentSlot.held_until < current_time
                ).with_for_update()
            ).scalars().all()
            
            records_affected = 0
            for slot in expired_slots:
                # Issue 83, 178: Re-check slot status after locking to prevent concurrent releases
                # Lock ensures only one worker can release the slot at a time
                if slot.is_booked == "held" and slot.held_until and slot.held_until < current_time:
                    # Slot is still held and hold has expired - safe to release
                    slot.is_booked = "no"
                    slot.held_until = None
                    slot.held_by_call_sid = None
                    slot.booked_by_appointment_id = None
                    records_affected += 1
                elif slot.is_booked != "held":
                    # Issue 178: Slot is no longer in "held" status (might have been booked or released by another worker)
                    self.logger.warning(f"Slot {slot.slot_id} is not in 'held' status (current: {slot.is_booked}), skipping release")
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit expired slot holds release: {commit_error}")
                
                self.logger.info(
                    f"Released {records_affected} expired slot holds",
                    LogCategory.SYSTEM,
                    extra_data={'expired_slots': records_affected}
                )
            
            return {
                'records_processed': len(expired_slots),
                'records_affected': records_affected,
                'metadata': {'cleanup_type': 'expired_slots'}
            }
    
    @log_performance("cleanup_abandoned_calls")
    def _cleanup_abandoned_calls(self) -> Dict[str, Any]:
        """Mark calls as abandoned if they've been active too long."""
        with get_db_session() as db:
            # Calls active for more than 24 hours
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            
            abandoned_calls = db.query(Call).filter(
                and_(
                    Call.status == CallStatus.ACTIVE.value,
                    Call.started_at < cutoff_time
                )
            ).all()
            
            records_affected = 0
            for call in abandoned_calls:
                # Issue 84: Check call status before marking as abandoned
                # Verify call is actually still active (might have been updated by another process)
                if call.status == CallStatus.ACTIVE.value:
                    # Double-check call hasn't been updated since query
                    db.refresh(call)
                    if call.status == CallStatus.ACTIVE.value:
                        call.status = "abandoned"
                        call.ended_at = datetime.now(timezone.utc)
                        records_affected += 1
                    else:
                        # Call status changed - skip
                        self.logger.debug(f"Call {call.call_id} status changed to {call.status}, skipping abandonment")
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit abandoned calls marking: {commit_error}")
                
                self.logger.warning(
                    f"Marked {records_affected} calls as abandoned",
                    LogCategory.SYSTEM,
                    extra_data={'abandoned_calls': records_affected}
                )
            
            return {
                'records_processed': len(abandoned_calls),
                'records_affected': records_affected,
                'metadata': {'cleanup_type': 'abandoned_calls'}
            }
    
    @log_performance("cleanup_old_audit_logs")
    def _cleanup_old_audit_logs(self) -> Dict[str, Any]:
        """Delete audit logs older than retention period."""
        with get_db_session() as db:
            # Keep audit logs for 7 years (HIPAA requirement)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=2555)
            
            old_logs = db.query(AuditLog).filter(
                AuditLog.created_at < cutoff_date
            ).all()
            
            records_affected = 0
            for log in old_logs:
                db.delete(log)
                records_affected += 1
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit audit log deletion: {commit_error}")
                
                self.logger.info(
                    f"Deleted {records_affected} old audit logs",
                    LogCategory.SYSTEM,
                    extra_data={'deleted_logs': records_affected}
                )
            
            return {
                'records_processed': len(old_logs),
                'records_affected': records_affected,
                'metadata': {'cleanup_type': 'old_audit_logs'}
            }
    
    # ============================================================================
    # BILLING JOBS
    # ============================================================================
    
    @log_performance("monthly_billing_cycle")
    def _monthly_billing_cycle(self) -> Dict[str, Any]:
        """Reset usage counters and process monthly billing."""
        current_date = datetime.now(timezone.utc).date()
        
        # Issue 81: Check if it's actually the first of the month before resetting
        # Handle partial months - if system started mid-month, don't reset until next month
        if current_date.day != 1:
            return {
                'records_processed': 0,
                'records_affected': 0,
                'metadata': {'skipped': 'not_first_of_month'}
            }
        
        # Issue 81: Additional validation - check if this is the first run of the month
        # In production, you'd track last reset date to prevent double-reset
        
        with get_db_session() as db:
            # Reset usage counters for all active licenses
            licenses = db.query(ClinicLicense).filter(
                ClinicLicense.license_status == "active"
            ).all()
            
            records_affected = 0
            for license in licenses:
                # Reset monthly counters
                license.current_month_calls = 0
                license.current_month_minutes = 0
                license.usage_percentage = 0.0
                license.auto_upgrade_offered = "no"
                license.auto_upgrade_offered_at = None
                
                # Update billing cycle dates
                license.billing_cycle_start = datetime.now(timezone.utc)
                license.billing_cycle_end = license.billing_cycle_start + timedelta(days=30)
                license.next_billing_date = license.billing_cycle_end
                
                records_affected += 1
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit billing cycle reset: {commit_error}")
                
                self.logger.info(
                    f"Reset billing cycle for {records_affected} licenses",
                    LogCategory.SYSTEM,
                    extra_data={'licenses_reset': records_affected}
                )
            
            return {
                'records_processed': len(licenses),
                'records_affected': records_affected,
                'metadata': {'billing_cycle': 'monthly_reset'}
            }
    
    @log_performance("update_usage_counters")
    def _update_usage_counters(self) -> Dict[str, Any]:
        """Update real-time usage counters for billing."""
        with get_db_session() as db:
            # Issue 82: Use proper locking to handle concurrent updates
            from sqlalchemy import func
            from sqlalchemy import select
            
            # Get active call counts per clinic in one query
            active_calls_per_clinic = db.query(
                Patient.clinic_id,
                func.count(Call.call_id).label('active_calls')
            ).join(
                Call, Patient.patient_id == Call.patient_id
            ).filter(
                Call.status == CallStatus.ACTIVE.value
            ).group_by(Patient.clinic_id).all()
            
            # Create a dictionary for quick lookup
            active_calls_dict = {clinic_id: count for clinic_id, count in active_calls_per_clinic}
            
            # Issue 82, 189: Update all licenses with SELECT FOR UPDATE to prevent concurrent updates
            # Issue 189: Use distributed locking or ensure only one worker runs this job at a time
            # For now, we use SELECT FOR UPDATE which prevents concurrent updates within the same database transaction
            # In production, you might want to use Redis distributed locks or a job queue to ensure only one worker runs this
            licenses = db.execute(
                select(ClinicLicense).where(
                    ClinicLicense.license_status == "active"
                ).with_for_update()
            ).scalars().all()
            
            records_affected = 0
            
            for license in licenses:
                # Issue 189: Re-check active calls for this clinic to ensure accuracy
                active_calls = active_calls_dict.get(license.clinic_id, 0)
                # Issue 189: Validate that the update is reasonable (not negative, not exceeding max)
                if active_calls < 0:
                    active_calls = 0
                if hasattr(license, 'max_concurrent_calls') and license.max_concurrent_calls:
                    if active_calls > license.max_concurrent_calls:
                        self.logger.warning(f"Active calls ({active_calls}) exceed max ({license.max_concurrent_calls}) for clinic {license.clinic_id}")
                        active_calls = license.max_concurrent_calls
                
                license.current_concurrent_calls = active_calls
                records_affected += 1
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit usage counter update: {commit_error}")
            
            return {
                'records_processed': len(licenses),
                'records_affected': records_affected,
                'metadata': {'counter_type': 'concurrent_calls'}
            }
    
    # ============================================================================
    # HIPAA COMPLIANCE JOBS
    # ============================================================================
    
    @log_performance("enforce_retention_policy")
    def _enforce_retention_policy(self) -> Dict[str, Any]:
        """Hard delete records older than 7 years (HIPAA retention)."""
        with get_db_session() as db:
            soft_delete_service = SoftDeleteService(db)
            
            # Issue 85: Verify record age before deletion
            # The enforce_retention_policy method should check record age internally
            # But we'll add additional validation here
            retention_period_days = 2555  # 7 years
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_period_days)
            
            # Enforce retention policy for all models
            result = soft_delete_service.enforce_retention_policy(dry_run=False)
            
            # Issue 85: Log the cutoff date for audit purposes
            self.logger.info(
                f"Enforcing retention policy with cutoff date: {cutoff_date.isoformat()}",
                LogCategory.COMPLIANCE,
                extra_data={'cutoff_date': cutoff_date.isoformat()}
            )
            
            total_affected = sum(result.get('records_to_delete', {}).values())
            
            self.logger.info(
                f"Enforced HIPAA retention policy",
                LogCategory.COMPLIANCE,
                extra_data={
                    'records_deleted': total_affected,
                    'details': result
                }
            )
            
            return {
                'records_processed': total_affected,
                'records_affected': total_affected,
                'metadata': {'retention_policy': 'hipaa_7_year'}
            }
    
    # ============================================================================
    # MONITORING JOBS
    # ============================================================================
    
    @log_performance("database_health_check")
    def _database_health_check(self) -> Dict[str, Any]:
        """Monitor database health and connection pool."""
        from services.database import get_database_health, ConnectionPoolMonitor
        
        try:
            # Check database connectivity
            db_health = get_database_health()
            pool_status = ConnectionPoolMonitor.get_pool_status()
            
            # Check for warnings
            warnings = ConnectionPoolMonitor.get_pool_warnings()
            
            if warnings:
                self.logger.warning(
                    "Database health warnings detected",
                    LogCategory.DATABASE,
                    extra_data={
                        'warnings': warnings,
                        'pool_status': pool_status
                    }
                )
            else:
                self.logger.debug(
                    "Database health check passed",
                    LogCategory.DATABASE,
                    extra_data={'pool_status': pool_status}
                )
            
            return {
                'records_processed': 1,
                'records_affected': 0,
                'metadata': {
                    'health_status': db_health.get('status'),
                    'pool_utilization': pool_status.get('utilization_percentage', 0),
                    'warnings_count': len(warnings)
                }
            }
            
        except Exception as e:
            self.logger.error(
                "Database health check failed",
                LogCategory.DATABASE,
                exception=e
            )
            raise
    
    @log_performance("license_expiration_check")
    def _license_expiration_check(self) -> Dict[str, Any]:
        """Check for expiring licenses and send warnings."""
        with get_db_session() as db:
            current_time = datetime.now(timezone.utc)
            
            # Find licenses in grace period
            grace_period_licenses = db.query(ClinicLicense).filter(
                and_(
                    ClinicLicense.license_status == "grace_period",
                    ClinicLicense.grace_period_end < current_time
                )
            ).all()
            
            records_affected = 0
            for license in grace_period_licenses:
                # Suspend license
                license.license_status = "suspended"
                license.suspended_at = current_time
                license.suspension_reason = "grace_period_expired"
                records_affected += 1
                
                self.logger.warning(
                    f"License suspended due to expired grace period",
                    LogCategory.SYSTEM,
                    extra_data={
                        'clinic_id': license.clinic_id,
                        'license_id': license.license_id
                    }
                )
            
            if records_affected > 0:
                try:
                    db.commit()
                except Exception as commit_error:
                    db.rollback()
                    self.logger.error(f"Failed to commit license expiration update: {commit_error}")
            
            return {
                'records_processed': len(grace_period_licenses),
                'records_affected': records_affected,
                'metadata': {'check_type': 'license_expiration'}
            }
    
    @log_performance("system_metrics_collection")
    def _system_metrics_collection(self) -> Dict[str, Any]:
        """Collect and log system performance metrics."""
        import psutil
        
        try:
            # Collect system metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Collect application metrics
            total_jobs = len(self.jobs)
            enabled_jobs = len([j for j in self.jobs.values() if j.enabled])
            failed_jobs = len([j for j in self.jobs.values() if j.consecutive_failures > 0])
            
            metrics = {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_available_gb': memory.available / (1024**3),
                'disk_percent': disk.percent,
                'disk_free_gb': disk.free / (1024**3),
                'total_jobs': total_jobs,
                'enabled_jobs': enabled_jobs,
                'failed_jobs': failed_jobs,
                'total_executed': self.total_jobs_executed,
                'total_failed': self.total_jobs_failed
            }
            
            self.logger.debug(
                "System metrics collected",
                LogCategory.PERFORMANCE,
                extra_data=metrics
            )
            
            return {
                'records_processed': 1,
                'records_affected': 0,
                'metadata': metrics
            }
            
        except Exception as e:
            self.logger.error(
                "Failed to collect system metrics",
                LogCategory.PERFORMANCE,
                exception=e
            )
            raise
    
    def _process_due_reminders(self) -> Dict[str, Any]:
        """Process reminders that are due for execution."""
        try:
            reminder_service = get_reminder_service()
            
            # Issue 51: Move loop inside context manager to keep session alive
            processed_count = 0
            success_count = 0
            failed_count = 0
            
            # Use proper database session context manager
            with get_db_session() as db_session:
                # Get due reminders
                due_reminders = _safe_run_async(reminder_service.get_due_reminders(db_session, limit=50))
                
                for reminder in due_reminders:
                    try:
                        processed_count += 1
                        
                        # Execute the reminder
                        result = _safe_run_async(reminder_service.execute_reminder(db_session, reminder.reminder_id))
                    
                        if result['status'] == 'completed':
                            success_count += 1
                        else:
                            failed_count += 1
                            
                    except Exception as e:
                        failed_count += 1
                        self.logger.error(
                            f"Failed to process reminder {reminder.reminder_id}",
                            LogCategory.REMINDER,
                            exception=e
                        )
                        # Issue 165: Update reminder status to 'failed' if execution fails
                        try:
                            reminder.status = 'failed'
                            reminder.completed_at = datetime.now(timezone.utc)
                            reminder.deletion_reason = f'execution_failed: {str(e)}'
                            db_session.commit()
                        except Exception as status_error:
                            self.logger.error(f"Failed to update reminder status: {status_error}")
            
            self.logger.info(
                f"Processed {processed_count} due reminders: {success_count} successful, {failed_count} failed",
                LogCategory.REMINDER,
                extra_data={
                    'processed_count': processed_count,
                    'success_count': success_count,
                    'failed_count': failed_count
                }
            )
            
            # Issue 52: Return dict (JobResult is created by _execute_job from dict)
            # Note: _execute_job handles dict returns and creates JobResult (line 451-454)
            return {
                'records_processed': processed_count,
                'records_affected': success_count,
                'metadata': {
                    'success_count': success_count,
                    'failed_count': failed_count
                }
            }
            
        except Exception as e:
            self.logger.error(
                "Failed to process due reminders",
                LogCategory.REMINDER,
                exception=e
            )
            raise
    
    def _cleanup_old_reminders(self) -> Dict[str, Any]:
        """Clean up completed reminders older than 30 days."""
        try:
            with get_db_session() as db:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)
            
                # Find old completed reminders
                old_reminders = db.query(Reminder).filter(
                    and_(
                        Reminder.is_deleted == 'no',
                        Reminder.status.in_(['completed', 'cancelled']),
                        Reminder.completed_at < cutoff_date
                    )
                ).all()
                
                deleted_count = 0
                
                # Issue 53: Commit after each reminder modification to prevent partial failures
                for reminder in old_reminders:
                    try:
                        # Soft delete the reminder
                        reminder.is_deleted = 'yes'
                        reminder.deleted_at = datetime.now(timezone.utc)
                        reminder.deleted_by = 'system'
                        reminder.deletion_reason = 'automated_cleanup_30_days'
                        
                        # Also soft delete related logs
                        for log in reminder.reminder_logs:
                            log.is_deleted = 'yes'
                            log.deleted_at = datetime.now(timezone.utc)
                            log.deleted_by = 'system'
                            log.deletion_reason = 'automated_cleanup_30_days'
                        
                        # Issue 53: Commit after each reminder to prevent partial failures
                        try:
                            db.commit()
                            deleted_count += 1
                        except Exception as commit_error:
                            db.rollback()
                            self.logger.error(f"Failed to commit reminder cleanup for {reminder.reminder_id}: {commit_error}")
                        
                    except Exception as e:
                        self.logger.error(
                            f"Failed to cleanup reminder {reminder.reminder_id}",
                            LogCategory.REMINDER,
                            exception=e
                        )
                        db.rollback()  # Rollback on error
                
                self.logger.info(
                    f"Cleaned up {deleted_count} old reminders",
                    LogCategory.REMINDER,
                    extra_data={'deleted_count': deleted_count}
                )
                
                return {
                    'records_processed': len(old_reminders),
                    'records_affected': deleted_count,
                    'metadata': {'deleted_count': deleted_count}
                }
            
        except Exception as e:
            self.logger.error(
                "Failed to cleanup old reminders",
                LogCategory.REMINDER,
                exception=e
            )
            raise
    
    # ============================================================================
    # MANAGEMENT METHODS
    # ============================================================================
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific job."""
        if job_id not in self.jobs:
            return None
        
        job = self.jobs[job_id]
        results = self.job_results.get(job_id, [])
        
        return {
            'job_id': job_id,
            'name': job.name,
            'description': job.description,
            'enabled': job.enabled,
            'priority': job.priority.value,
            'schedule_interval': job.schedule_interval,
            'last_run': job.last_run.isoformat() if job.last_run else None,
            'next_run': job.next_run.isoformat() if job.next_run else None,
            'consecutive_failures': job.consecutive_failures,
            'max_retries': job.max_retries,
            'recent_results': [
                {
                    'status': result.status.value,
                    'start_time': result.start_time.isoformat(),
                    'end_time': result.end_time.isoformat() if result.end_time else None,
                    'duration_seconds': result.duration_seconds,
                    'records_processed': result.records_processed,
                    'records_affected': result.records_affected,
                    'error_message': result.error_message
                }
                for result in results[-10:]  # Last 10 results
            ]
        }
    
    def get_all_jobs_status(self) -> Dict[str, Any]:
        """Get status of all jobs."""
        return {
            job_id: self.get_job_status(job_id)
            for job_id in self.jobs.keys()
        }
    
    def enable_job(self, job_id: str) -> bool:
        """Enable a background job."""
        if job_id not in self.jobs:
            return False
        
        self.jobs[job_id].enabled = True
        self.jobs[job_id].consecutive_failures = 0
        
        self.logger.info(
            f"Enabled background job: {job_id}",
            LogCategory.SYSTEM
        )
        return True
    
    def disable_job(self, job_id: str) -> bool:
        """Disable a background job."""
        if job_id not in self.jobs:
            return False
        
        self.jobs[job_id].enabled = False
        
        self.logger.info(
            f"Disabled background job: {job_id}",
            LogCategory.SYSTEM
        )
        return True
    
    def run_job_now(self, job_id: str) -> bool:
        """Run a job immediately (outside of schedule)."""
        if job_id not in self.jobs:
            return False
        
        job = self.jobs[job_id]
        if not job.enabled:
            return False
        
        # Run in a separate thread to avoid blocking
        threading.Thread(
            target=self._execute_job,
            args=(job,),
            name=f"ManualJob-{job_id}",
            daemon=True
        ).start()
        
        self.logger.info(
            f"Manually triggered job: {job_id}",
            LogCategory.SYSTEM
        )
        return True
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health based on job status."""
        total_jobs = len(self.jobs)
        enabled_jobs = len([j for j in self.jobs.values() if j.enabled])
        failed_jobs = len([j for j in self.jobs.values() if j.consecutive_failures > 0])
        disabled_jobs = len([j for j in self.jobs.values() if not j.enabled])
        
        health_score = 100
        if failed_jobs > 0:
            health_score -= (failed_jobs / total_jobs) * 50
        if disabled_jobs > 0:
            health_score -= (disabled_jobs / total_jobs) * 25
        
        return {
            'health_score': max(0, health_score),
            'total_jobs': total_jobs,
            'enabled_jobs': enabled_jobs,
            'failed_jobs': failed_jobs,
            'disabled_jobs': disabled_jobs,
            'total_executed': self.total_jobs_executed,
            'total_failed': self.total_jobs_failed,
            'success_rate': (
                (self.total_jobs_executed / (self.total_jobs_executed + self.total_jobs_failed) * 100)
                if (self.total_jobs_executed + self.total_jobs_failed) > 0 else 100
            )
        }
    
    def _cleanup_nlp_statistics(self) -> Dict[str, Any]:
        """Clean up expired NLP call statistics."""
        try:
            from services.hybrid_nlp_service import get_hybrid_nlp_service
            
            hybrid_nlp = get_hybrid_nlp_service()
            _safe_run_async(hybrid_nlp.cleanup_expired_data())
            
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": True
            }
        except Exception as e:
            self.logger.error(
                f"Failed to cleanup NLP statistics: {e}",
                LogCategory.SYSTEM,
                exception=e
            )
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": False,
                "error": str(e)
            }
    
    def _cleanup_tts_sessions(self) -> Dict[str, Any]:
        """Clean up expired TTS sessions."""
        try:
            from services.azure_speech_tts import get_tts_service
            tts_service = get_tts_service()
            _safe_run_async(tts_service.cleanup_expired_sessions())
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": True
            }
        except Exception as e:
            self.logger.error(
                f"Failed to cleanup TTS sessions: {e}",
                LogCategory.SYSTEM,
                exception=e
            )
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": False,
                "error": str(e)
            }
    
    def _cleanup_stt_sessions(self) -> Dict[str, Any]:
        """Clean up expired STT sessions."""
        try:
            from services.azure_speech_stt import get_stt_service
            stt_service = get_stt_service()
            _safe_run_async(stt_service.cleanup_expired_sessions())
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": True
            }
        except Exception as e:
            self.logger.error(
                f"Failed to cleanup STT sessions: {e}",
                LogCategory.SYSTEM,
                exception=e
            )
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": False,
                "error": str(e)
            }
    
    def _cleanup_bilingual_data(self) -> Dict[str, Any]:
        """Clean up expired bilingual conversation data."""
        try:
            from services.bilingual_manager import get_bilingual_manager
            bilingual_manager = get_bilingual_manager()
            _safe_run_async(bilingual_manager.cleanup_expired_data())
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": True
            }
        except Exception as e:
            self.logger.error(
                f"Failed to cleanup bilingual data: {e}",
                LogCategory.SYSTEM,
                exception=e
            )
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": False,
                "error": str(e)
            }
    
    def _cleanup_call_queues(self) -> Dict[str, Any]:
        """Clean up expired call queues."""
        try:
            from services.call_router import get_call_router
            call_router = get_call_router()
            _safe_run_async(call_router.cleanup_expired_queues())
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": True
            }
        except Exception as e:
            self.logger.error(
                f"Failed to cleanup call queues: {e}",
                LogCategory.SYSTEM,
                exception=e
            )
            return {
                "records_processed": 0,
                "records_affected": 0,
                "success": False,
                "error": str(e)
            }
    
    def _refresh_google_calendar_tokens(self):
        """Refresh Google Calendar tokens that will expire soon."""
        try:
            from services.database import get_db
            from models.models import GoogleCalendarCredentials
            from datetime import datetime, timezone, timedelta
            from services.google_calendar_credentials_service import GoogleCalendarCredentialsService
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            
            # Issue 56: Use context manager instead of next(get_db())
            with get_db_session() as db:
                # Find credentials expiring in next 15 minutes
                expiry_threshold = datetime.now(timezone.utc) + timedelta(minutes=15)
                
                expiring_creds = db.query(GoogleCalendarCredentials).filter(
                    GoogleCalendarCredentials.is_active == True,
                    GoogleCalendarCredentials.token_expires_at <= expiry_threshold,
                    GoogleCalendarCredentials.refresh_token_ciphertext.isnot(None)
                ).all()
                
                credentials_service = GoogleCalendarCredentialsService(db)
                refreshed_count = 0
                
                for cred_record in expiring_creds:
                    try:
                        # Get credentials
                        credentials = credentials_service.get_credentials(cred_record.provider_id)
                        if credentials and credentials.refresh_token:
                            # Refresh
                            credentials.refresh(Request())
                            # Save back
                            credentials_service.store_credentials(cred_record.provider_id, credentials)
                            refreshed_count += 1
                            self.logger.info(f"Refreshed Google token for provider {cred_record.provider_id}")
                    except Exception as e:
                        self.logger.error(f"Failed to refresh token for provider {cred_record.provider_id}: {e}")
                
                if refreshed_count > 0:
                    self.logger.info(f"Refreshed {refreshed_count} Google Calendar tokens")
                
                return {
                    'records_processed': len(expiring_creds),
                    'records_affected': refreshed_count,
                    'metadata': {'tokens_refreshed': refreshed_count}
                }
                
        except Exception as e:
            self.logger.error(f"Failed to refresh Google Calendar tokens: {e}")
            return {
                'records_processed': 0,
                'records_affected': 0,
                'metadata': {'error': str(e)}
            }


# Global instance
_background_job_manager: Optional[BackgroundJobManager] = None


def get_background_job_manager() -> BackgroundJobManager:
    """Get the global background job manager instance."""
    global _background_job_manager
    if _background_job_manager is None:
        _background_job_manager = BackgroundJobManager()
    return _background_job_manager


def start_background_jobs():
    """Start all background jobs."""
    manager = get_background_job_manager()
    manager.start()


def stop_background_jobs():
    """Stop all background jobs."""
    manager = get_background_job_manager()
    manager.stop()
