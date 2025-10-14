"""
Background Job Management API Endpoints

Provides REST API for monitoring and managing background jobs:
- Job status and health monitoring
- Manual job execution
- Job enable/disable controls
- System health metrics
- Job execution history
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from services.database import get_db
from services.background_jobs import get_background_job_manager, BackgroundJobManager
from services.structured_logging import get_logger, LogCategory
from sqlalchemy.orm import Session


router = APIRouter(prefix="/background-jobs", tags=["Background Jobs"])
logger = get_logger("background_jobs_api")


class JobStatusResponse(BaseModel):
    """Response model for job status."""
    job_id: str
    name: str
    description: str
    enabled: bool
    priority: int
    schedule_interval: int
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    consecutive_failures: int
    max_retries: int
    recent_results: List[Dict[str, Any]] = Field(default_factory=list)


class JobExecutionResult(BaseModel):
    """Response model for job execution result."""
    job_id: str
    status: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    records_processed: int
    records_affected: int
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SystemHealthResponse(BaseModel):
    """Response model for system health."""
    health_score: float
    total_jobs: int
    enabled_jobs: int
    failed_jobs: int
    disabled_jobs: int
    total_executed: int
    total_failed: int
    success_rate: float


class JobControlRequest(BaseModel):
    """Request model for job control operations."""
    enabled: Optional[bool] = None
    priority: Optional[int] = None


@router.get("/", response_model=Dict[str, JobStatusResponse])
def get_all_jobs_status():
    """Get status of all background jobs."""
    try:
        manager = get_background_job_manager()
        jobs_status = manager.get_all_jobs_status()
        
        logger.info(
            "Retrieved all jobs status",
            LogCategory.API,
            extra_data={'total_jobs': len(jobs_status)}
        )
        
        return jobs_status
        
    except Exception as e:
        logger.error(
            "Failed to get jobs status",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get jobs status: {str(e)}"
        )


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str):
    """Get status of a specific background job."""
    try:
        manager = get_background_job_manager()
        job_status = manager.get_job_status(job_id)
        
        if not job_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        logger.info(
            f"Retrieved job status: {job_id}",
            LogCategory.API,
            extra_data={'job_id': job_id}
        )
        
        return job_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get job status: {job_id}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job status: {str(e)}"
        )


@router.get("/{job_id}/history", response_model=List[JobExecutionResult])
def get_job_execution_history(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0)
):
    """Get execution history for a specific job."""
    try:
        manager = get_background_job_manager()
        
        if job_id not in manager.jobs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        results = manager.job_results.get(job_id, [])
        
        # Apply pagination
        paginated_results = results[offset:offset + limit]
        
        # Convert to response format
        history = []
        for result in paginated_results:
            history.append(JobExecutionResult(
                job_id=result.job_id,
                status=result.status.value,
                start_time=result.start_time.isoformat(),
                end_time=result.end_time.isoformat() if result.end_time else None,
                duration_seconds=result.duration_seconds,
                records_processed=result.records_processed,
                records_affected=result.records_affected,
                error_message=result.error_message,
                metadata=result.metadata
            ))
        
        logger.info(
            f"Retrieved job execution history: {job_id}",
            LogCategory.API,
            extra_data={
                'job_id': job_id,
                'limit': limit,
                'offset': offset,
                'total_results': len(results),
                'returned_results': len(history)
            }
        )
        
        return history
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get job execution history: {job_id}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get job execution history: {str(e)}"
        )


@router.post("/{job_id}/run", response_model=Dict[str, str])
def run_job_now(job_id: str):
    """Run a background job immediately (outside of schedule)."""
    try:
        manager = get_background_job_manager()
        
        if job_id not in manager.jobs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        job = manager.jobs[job_id]
        if not job.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Job is disabled: {job_id}"
            )
        
        success = manager.run_job_now(job_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start job: {job_id}"
            )
        
        logger.info(
            f"Manually triggered job: {job_id}",
            LogCategory.API,
            extra_data={'job_id': job_id}
        )
        
        return {
            "message": f"Job {job_id} has been triggered",
            "job_id": job_id,
            "status": "triggered"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to run job: {job_id}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run job: {str(e)}"
        )


@router.put("/{job_id}/enable", response_model=Dict[str, str])
def enable_job(job_id: str):
    """Enable a background job."""
    try:
        manager = get_background_job_manager()
        
        success = manager.enable_job(job_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        logger.info(
            f"Enabled job: {job_id}",
            LogCategory.API,
            extra_data={'job_id': job_id}
        )
        
        return {
            "message": f"Job {job_id} has been enabled",
            "job_id": job_id,
            "status": "enabled"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to enable job: {job_id}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable job: {str(e)}"
        )


@router.put("/{job_id}/disable", response_model=Dict[str, str])
def disable_job(job_id: str):
    """Disable a background job."""
    try:
        manager = get_background_job_manager()
        
        success = manager.disable_job(job_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job not found: {job_id}"
            )
        
        logger.info(
            f"Disabled job: {job_id}",
            LogCategory.API,
            extra_data={'job_id': job_id}
        )
        
        return {
            "message": f"Job {job_id} has been disabled",
            "job_id": job_id,
            "status": "disabled"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to disable job: {job_id}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable job: {str(e)}"
        )


@router.get("/health/system", response_model=SystemHealthResponse)
def get_system_health():
    """Get overall system health based on background job status."""
    try:
        manager = get_background_job_manager()
        health = manager.get_system_health()
        
        logger.info(
            "Retrieved system health",
            LogCategory.API,
            extra_data=health
        )
        
        return SystemHealthResponse(**health)
        
    except Exception as e:
        logger.error(
            "Failed to get system health",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get system health: {str(e)}"
        )


@router.get("/health/detailed", response_model=Dict[str, Any])
def get_detailed_health():
    """Get detailed health information including individual job status."""
    try:
        manager = get_background_job_manager()
        
        # Get system health
        system_health = manager.get_system_health()
        
        # Get all job statuses
        jobs_status = manager.get_all_jobs_status()
        
        # Calculate health metrics
        total_jobs = len(jobs_status)
        enabled_jobs = len([j for j in jobs_status.values() if j['enabled']])
        failed_jobs = len([j for j in jobs_status.values() if j['consecutive_failures'] > 0])
        
        # Get recent failures
        recent_failures = []
        for job_id, job_status in jobs_status.items():
            if job_status['consecutive_failures'] > 0:
                recent_failures.append({
                    'job_id': job_id,
                    'name': job_status['name'],
                    'consecutive_failures': job_status['consecutive_failures'],
                    'max_retries': job_status['max_retries']
                })
        
        detailed_health = {
            'system_health': system_health,
            'job_summary': {
                'total_jobs': total_jobs,
                'enabled_jobs': enabled_jobs,
                'failed_jobs': failed_jobs,
                'disabled_jobs': total_jobs - enabled_jobs
            },
            'recent_failures': recent_failures,
            'jobs_status': jobs_status,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(
            "Retrieved detailed system health",
            LogCategory.API,
            extra_data={
                'total_jobs': total_jobs,
                'failed_jobs': failed_jobs,
                'health_score': system_health['health_score']
            }
        )
        
        return detailed_health
        
    except Exception as e:
        logger.error(
            "Failed to get detailed health",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get detailed health: {str(e)}"
        )


@router.get("/stats/performance", response_model=Dict[str, Any])
def get_performance_stats():
    """Get performance statistics for background jobs."""
    try:
        manager = get_background_job_manager()
        
        # Calculate performance metrics
        total_executed = manager.total_jobs_executed
        total_failed = manager.total_jobs_failed
        total_attempts = total_executed + total_failed
        
        success_rate = (total_executed / total_attempts * 100) if total_attempts > 0 else 100
        
        # Get job-specific performance
        job_performance = {}
        for job_id, results in manager.job_results.items():
            if not results:
                continue
            
            recent_results = results[-10:]  # Last 10 executions
            successful = len([r for r in recent_results if r.status.value == "completed"])
            failed = len([r for r in recent_results if r.status.value == "failed"])
            
            avg_duration = 0
            if recent_results:
                durations = [r.duration_seconds for r in recent_results if r.duration_seconds]
                avg_duration = sum(durations) / len(durations) if durations else 0
            
            job_performance[job_id] = {
                'recent_executions': len(recent_results),
                'successful': successful,
                'failed': failed,
                'success_rate': (successful / len(recent_results) * 100) if recent_results else 100,
                'average_duration_seconds': avg_duration
            }
        
        performance_stats = {
            'overall': {
                'total_executed': total_executed,
                'total_failed': total_failed,
                'total_attempts': total_attempts,
                'success_rate': success_rate,
                'average_execution_time': manager.average_execution_time
            },
            'job_performance': job_performance,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        logger.info(
            "Retrieved performance statistics",
            LogCategory.API,
            extra_data={
                'total_attempts': total_attempts,
                'success_rate': success_rate
            }
        )
        
        return performance_stats
        
    except Exception as e:
        logger.error(
            "Failed to get performance stats",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get performance stats: {str(e)}"
        )


@router.post("/start", response_model=Dict[str, str])
def start_background_jobs():
    """Start the background job manager."""
    try:
        manager = get_background_job_manager()
        
        if manager.running:
            return {
                "message": "Background job manager is already running",
                "status": "already_running"
            }
        
        manager.start()
        
        logger.info(
            "Started background job manager",
            LogCategory.API
        )
        
        return {
            "message": "Background job manager started successfully",
            "status": "started"
        }
        
    except Exception as e:
        logger.error(
            "Failed to start background job manager",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start background job manager: {str(e)}"
        )


@router.post("/stop", response_model=Dict[str, str])
def stop_background_jobs():
    """Stop the background job manager."""
    try:
        manager = get_background_job_manager()
        
        if not manager.running:
            return {
                "message": "Background job manager is not running",
                "status": "not_running"
            }
        
        manager.stop()
        
        logger.info(
            "Stopped background job manager",
            LogCategory.API
        )
        
        return {
            "message": "Background job manager stopped successfully",
            "status": "stopped"
        }
        
    except Exception as e:
        logger.error(
            "Failed to stop background job manager",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop background job manager: {str(e)}"
        )
