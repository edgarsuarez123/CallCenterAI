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
from datetime import datetime, timedelta, timezone
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
            
            # Find expired slot holds
            expired_slots = db.query(AppointmentSlot).filter(
                and_(
                    AppointmentSlot.is_booked == "held",
                    AppointmentSlot.held_until < current_time
                )
            ).all()
            
            records_affected = 0
            for slot in expired_slots:
                slot.is_booked = "no"
                slot.held_until = None
                slot.held_by_call_sid = None
                slot.booked_by_appointment_id = None
                records_affected += 1
            
            if records_affected > 0:
                db.commit()
                
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
                    Call.status == "active",
                    Call.started_at < cutoff_time
                )
            ).all()
            
            records_affected = 0
            for call in abandoned_calls:
                call.status = "abandoned"
                call.ended_at = datetime.now(timezone.utc)
                records_affected += 1
            
            if records_affected > 0:
                db.commit()
                
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
                db.commit()
                
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
        
        # Only run on the 1st of the month
        if current_date.day != 1:
            return {
                'records_processed': 0,
                'records_affected': 0,
                'metadata': {'skipped': 'not_first_of_month'}
            }
        
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
                db.commit()
                
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
            # Update current concurrent calls for all licenses
            licenses = db.query(ClinicLicense).all()
            
            records_affected = 0
            for license in licenses:
                # Count active calls for this clinic
                active_calls = db.query(Call).filter(
                    and_(
                        Call.status == "active",
                        Call.patient_id.in_(
                            db.query(Patient.patient_id).filter(
                                Patient.clinic_id == license.clinic_id
                            )
                        )
                    )
                ).count()
                
                license.current_concurrent_calls = active_calls
                records_affected += 1
            
            if records_affected > 0:
                db.commit()
            
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
            
            # Enforce retention policy for all models
            result = soft_delete_service.enforce_retention_policy(dry_run=False)
            
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
                db.commit()
            
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
            db = get_db_session()
            
            # Get due reminders
            due_reminders = asyncio.run(reminder_service.get_due_reminders(db, limit=50))
            
            processed_count = 0
            success_count = 0
            failed_count = 0
            
            for reminder in due_reminders:
                try:
                    processed_count += 1
                    
                    # Execute the reminder
                    result = asyncio.run(reminder_service.execute_reminder(db, reminder.reminder_id))
                    
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
            
            self.logger.info(
                f"Processed {processed_count} due reminders: {success_count} successful, {failed_count} failed",
                LogCategory.REMINDER,
                extra_data={
                    'processed_count': processed_count,
                    'success_count': success_count,
                    'failed_count': failed_count
                }
            )
            
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
            db = get_db_session()
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
                    
                    deleted_count += 1
                    
                except Exception as e:
                    self.logger.error(
                        f"Failed to cleanup reminder {reminder.reminder_id}",
                        LogCategory.REMINDER,
                        exception=e
                    )
            
            db.commit()
            
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
            db.rollback()
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
