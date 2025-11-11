"""
Admission Control Service
Enforces concurrent call limits per clinic using semaphores with queuing.

This service prevents system overload by:
1. Using asyncio.Semaphore per clinic to enforce hard limits
2. Queuing calls when capacity is exceeded
3. Processing queued calls when capacity becomes available
"""

import asyncio
import time
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass
from collections import defaultdict

from services.structured_logging import get_logger, LogCategory
from services.database import get_async_db_session
from sqlalchemy import select
from models.models import ClinicLicense, Clinic


@dataclass
class AdmissionResult:
    """Result of admission control check."""
    admitted: bool
    reason: str
    current_calls: int
    max_calls: int
    queue_position: Optional[int] = None
    wait_time_seconds: Optional[float] = None


@dataclass
class QueuedCall:
    """Represents a call waiting in the queue."""
    call_id: str
    clinic_id: str
    future: asyncio.Future
    queued_at: float
    timeout_seconds: float


class AdmissionController:
    """
    Admission controller with semaphore-based capacity management and queuing.
    
    Uses asyncio.Semaphore to enforce hard concurrent call limits and queues
    calls when capacity is exceeded. Processes queued calls when capacity becomes available.
    """
    
    def __init__(self):
        self.logger = get_logger("admission_controller")
        # Semaphore per clinic: clinic_id -> asyncio.Semaphore
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        # Lock for semaphore creation/updates
        self._semaphore_lock = asyncio.Lock()
        # Queue per clinic: clinic_id -> list of QueuedCall
        self._queues: Dict[str, list[QueuedCall]] = defaultdict(list)
        # Lock for queue operations
        self._queue_lock = asyncio.Lock()
        # Track call_id -> QueuedCall for removal
        self._queued_calls: Dict[str, QueuedCall] = {}
    
    async def check_admission(
        self, 
        call_id: str,
        clinic_id: str, 
        timeout_seconds: Optional[float] = None
    ) -> AdmissionResult:
        """
        Check if a call can be admitted for a clinic.
        If capacity is full, the call is queued and waits for capacity.
        
        Args:
            call_id: ID of the call requesting admission
            clinic_id: Clinic ID requesting admission
            timeout_seconds: Maximum time to wait in queue (None = use clinic's queue_timeout_seconds)
            
        Returns:
            AdmissionResult with admission status and details
        """
        try:
            # Get or create semaphore for clinic
            semaphore = await self._get_semaphore(clinic_id)
            
            if semaphore is None:
                return AdmissionResult(
                    admitted=False,
                    reason="clinic_not_found",
                    current_calls=0,
                    max_calls=0
                )
            
            # Get queue timeout from clinic config if not provided
            if timeout_seconds is None:
                timeout_seconds = await self._get_queue_timeout(clinic_id)
            
            # Try to acquire semaphore immediately
            try:
                # Try to acquire with very short timeout to check availability
                acquired = await asyncio.wait_for(
                    semaphore.acquire(),
                    timeout=0.001  # 1ms timeout
                )
                
                # Admission granted immediately
                current_calls = await self._get_current_calls(clinic_id)
                max_calls = await self._get_max_calls(clinic_id)
                
                # Update active calls metric
                try:
                    from services.metrics import get_metrics_service
                    metrics_service = get_metrics_service()
                    metrics_service.set_active_calls(clinic_id, current_calls + 1)
                except Exception as metrics_error:
                    self.logger.warning(f"Failed to update active calls metric: {metrics_error}")
                
                self.logger.info(
                    f"Call {call_id} admitted immediately for clinic {clinic_id}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={
                        'call_id': call_id,
                        'clinic_id': clinic_id,
                        'current_calls': current_calls + 1,
                        'max_calls': max_calls
                    }
                )
                
                return AdmissionResult(
                    admitted=True,
                    reason="admitted",
                    current_calls=current_calls + 1,
                    max_calls=max_calls
                )
                
            except asyncio.TimeoutError:
                # Capacity is full - add to queue
                return await self._queue_call(call_id, clinic_id, semaphore, timeout_seconds)
                
        except Exception as e:
            self.logger.error(
                f"Error checking admission for call {call_id}, clinic {clinic_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
            return AdmissionResult(
                admitted=False,
                reason="error",
                current_calls=0,
                max_calls=0
            )
    
    async def _queue_call(
        self,
        call_id: str,
        clinic_id: str,
        semaphore: asyncio.Semaphore,
        timeout_seconds: float
    ) -> AdmissionResult:
        """Add call to queue and wait for capacity."""
        
        # Create future for this queued call
        future = asyncio.Future()
        queued_call = QueuedCall(
            call_id=call_id,
            clinic_id=clinic_id,
            future=future,
            queued_at=time.time(),
            timeout_seconds=timeout_seconds
        )
        
        # Add to queue
        async with self._queue_lock:
            self._queues[clinic_id].append(queued_call)
            self._queued_calls[call_id] = queued_call
            queue_position = len(self._queues[clinic_id])
        
        current_calls = await self._get_current_calls(clinic_id)
        max_calls = await self._get_max_calls(clinic_id)
        
        self.logger.info(
            f"Call {call_id} queued for clinic {clinic_id} (position {queue_position})",
            LogCategory.CALL_ORCHESTRATION,
            extra_data={
                'call_id': call_id,
                'clinic_id': clinic_id,
                'queue_position': queue_position,
                'current_calls': current_calls,
                'max_calls': max_calls,
                'timeout_seconds': timeout_seconds
            }
        )
        
        # Wait for admission or timeout
        try:
            # Wait for future to be set (when capacity becomes available) or timeout
            await asyncio.wait_for(future, timeout=timeout_seconds)
            
            # Check if admission was granted
            if future.result():
                # Admission granted from queue
                current_calls = await self._get_current_calls(clinic_id)
                max_calls = await self._get_max_calls(clinic_id)
                
                # Update active calls metric
                try:
                    from services.metrics import get_metrics_service
                    metrics_service = get_metrics_service()
                    metrics_service.set_active_calls(clinic_id, current_calls)
                except Exception as metrics_error:
                    self.logger.warning(f"Failed to update active calls metric: {metrics_error}")
                
                self.logger.info(
                    f"Call {call_id} admitted from queue for clinic {clinic_id}",
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={
                        'call_id': call_id,
                        'clinic_id': clinic_id,
                        'current_calls': current_calls,
                        'max_calls': max_calls
                    }
                )
                
                return AdmissionResult(
                    admitted=True,
                    reason="admitted_from_queue",
                    current_calls=current_calls,
                    max_calls=max_calls,
                    queue_position=queue_position
                )
            else:
                # Admission was cancelled (caller hung up)
                return AdmissionResult(
                    admitted=False,
                    reason="cancelled",
                    current_calls=current_calls,
                    max_calls=max_calls,
                    queue_position=queue_position
                )
                
        except asyncio.TimeoutError:
            # Queue timeout - remove from queue
            await self.remove_from_queue(call_id)
            
            self.logger.warning(
                f"Call {call_id} timed out in queue for clinic {clinic_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    'call_id': call_id,
                    'clinic_id': clinic_id,
                    'timeout_seconds': timeout_seconds
                }
            )
            
            # Record admission reject metric
            try:
                from services.metrics import get_metrics_service
                metrics_service = get_metrics_service()
                metrics_service.increment_admission_rejects(clinic_id)
            except Exception as metrics_error:
                self.logger.warning(f"Failed to record admission reject metric: {metrics_error}")
            
            return AdmissionResult(
                admitted=False,
                reason="queue_timeout",
                current_calls=current_calls,
                max_calls=max_calls,
                queue_position=queue_position,
                wait_time_seconds=timeout_seconds
            )
    
    async def release_admission(self, clinic_id: str, call_id: Optional[str] = None):
        """
        Release admission for a call (decrement semaphore) and process next queued call.
        
        Args:
            clinic_id: Clinic ID releasing admission
            call_id: Optional call ID (for logging)
        """
        try:
            semaphore = self._semaphores.get(clinic_id)
            if semaphore:
                semaphore.release()
                
                # Update active calls metric
                current_calls = await self._get_current_calls(clinic_id)
                try:
                    from services.metrics import get_metrics_service
                    metrics_service = get_metrics_service()
                    metrics_service.set_active_calls(clinic_id, current_calls - 1)
                except Exception as metrics_error:
                    self.logger.warning(f"Failed to update active calls metric: {metrics_error}")
                
                self.logger.debug(
                    f"Admission released for clinic {clinic_id}" + (f" (call {call_id})" if call_id else ""),
                    LogCategory.CALL_ORCHESTRATION,
                    extra_data={
                        'clinic_id': clinic_id,
                        'call_id': call_id,
                        'current_calls': current_calls - 1
                    }
                )
                
                # Process next queued call
                await self._process_queue(clinic_id, semaphore)
                
        except Exception as e:
            self.logger.error(
                f"Error releasing admission for clinic {clinic_id}: {e}",
                LogCategory.CALL_ORCHESTRATION,
                exception=e
            )
    
    async def _process_queue(self, clinic_id: str, semaphore: asyncio.Semaphore):
        """Process the next call in the queue for a clinic."""
        async with self._queue_lock:
            queue = self._queues.get(clinic_id, [])
            if not queue:
                return
            
            # Get next queued call
            queued_call = queue.pop(0)
            
            # Remove from queued_calls dict
            if queued_call.call_id in self._queued_calls:
                del self._queued_calls[queued_call.call_id]
        
        # Try to acquire semaphore for queued call
        try:
            # Try to acquire with very short timeout
            acquired = await asyncio.wait_for(
                semaphore.acquire(),
                timeout=0.001  # 1ms timeout
            )
            
            # Grant admission to queued call
            queued_call.future.set_result(True)
            
            self.logger.info(
                f"Queued call {queued_call.call_id} granted admission for clinic {clinic_id}",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    'call_id': queued_call.call_id,
                    'clinic_id': clinic_id,
                    'wait_time': time.time() - queued_call.queued_at
                }
            )
            
        except asyncio.TimeoutError:
            # Capacity was taken by another call - put back at front of queue
            async with self._queue_lock:
                self._queues[clinic_id].insert(0, queued_call)
                self._queued_calls[queued_call.call_id] = queued_call
            
            self.logger.warning(
                f"Failed to grant admission to queued call {queued_call.call_id} - capacity taken",
                LogCategory.CALL_ORCHESTRATION,
                extra_data={
                    'call_id': queued_call.call_id,
                    'clinic_id': clinic_id
                }
            )
    
    async def remove_from_queue(self, call_id: str) -> bool:
        """
        Remove a call from the queue (e.g., when caller hangs up).
        
        Args:
            call_id: ID of the call to remove from queue
            
        Returns:
            True if call was removed from queue, False if not found
        """
        async with self._queue_lock:
            queued_call = self._queued_calls.get(call_id)
            if not queued_call:
                return False
            
            # Remove from queue
            clinic_id = queued_call.clinic_id
            queue = self._queues.get(clinic_id, [])
            if queued_call in queue:
                queue.remove(queued_call)
            
            # Remove from queued_calls dict
            del self._queued_calls[call_id]
            
            # Cancel the future
            if not queued_call.future.done():
                queued_call.future.set_result(False)  # Signal cancellation
        
        self.logger.info(
            f"Call {call_id} removed from queue for clinic {clinic_id}",
            LogCategory.CALL_ORCHESTRATION,
            extra_data={
                'call_id': call_id,
                'clinic_id': clinic_id
            }
        )
        
        return True
    
    async def _get_semaphore(self, clinic_id: str) -> Optional[asyncio.Semaphore]:
        """
        Get or create semaphore for a clinic.
        
        Args:
            clinic_id: Clinic ID
            
        Returns:
            Semaphore for the clinic, or None if clinic not found
        """
        # Check if semaphore already exists
        if clinic_id in self._semaphores:
            return self._semaphores[clinic_id]
        
        # Create semaphore with lock to prevent race conditions
        async with self._semaphore_lock:
            # Double-check after acquiring lock
            if clinic_id in self._semaphores:
                return self._semaphores[clinic_id]
            
            # Get max concurrent calls from database
            try:
                async with get_async_db_session() as db:
                    license_result = await db.execute(
                        select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id)
                    )
                    license = license_result.scalar_one_or_none()
                    
                    if not license:
                        self.logger.warning(f"Clinic {clinic_id} not found in database")
                        return None
                    
                    max_calls = license.max_concurrent_calls or 10  # Default to 10 if not set
                    
                    # Create semaphore with max_calls as the limit
                    semaphore = asyncio.Semaphore(max_calls)
                    self._semaphores[clinic_id] = semaphore
                    
                    self.logger.info(
                        f"Created semaphore for clinic {clinic_id} with max_calls={max_calls}",
                        LogCategory.CALL_ORCHESTRATION
                    )
                    
                    return semaphore
                    
            except Exception as e:
                self.logger.error(
                    f"Error creating semaphore for clinic {clinic_id}: {e}",
                    LogCategory.CALL_ORCHESTRATION,
                    exception=e
                )
                return None
    
    async def _get_queue_timeout(self, clinic_id: str) -> float:
        """Get queue timeout for a clinic from database."""
        try:
            async with get_async_db_session() as db:
                clinic_result = await db.execute(
                    select(Clinic).where(Clinic.clinic_id == clinic_id)
                )
                clinic = clinic_result.scalar_one_or_none()
                
                if clinic and clinic.queue_timeout_seconds:
                    return float(clinic.queue_timeout_seconds)
                
                return 45.0  # Default timeout
        except Exception as e:
            self.logger.warning(
                f"Failed to get queue timeout for clinic {clinic_id}: {e}",
                LogCategory.CALL_ORCHESTRATION
            )
            return 45.0  # Default timeout
    
    async def _get_current_calls(self, clinic_id: str) -> int:
        """Get current number of active calls for a clinic."""
        semaphore = self._semaphores.get(clinic_id)
        if semaphore:
            # Semaphore value represents available capacity
            max_calls = await self._get_max_calls(clinic_id)
            available = semaphore._value if hasattr(semaphore, '_value') else 0
            return max(0, max_calls - available)
        return 0
    
    async def _get_max_calls(self, clinic_id: str) -> int:
        """Get maximum concurrent calls for a clinic."""
        try:
            async with get_async_db_session() as db:
                license_result = await db.execute(
                    select(ClinicLicense).where(ClinicLicense.clinic_id == clinic_id)
                )
                license = license_result.scalar_one_or_none()
                
                if license and license.max_concurrent_calls:
                    return license.max_concurrent_calls
                
                return 10  # Default
        except Exception as e:
            self.logger.warning(
                f"Failed to get max calls for clinic {clinic_id}: {e}",
                LogCategory.CALL_ORCHESTRATION
            )
            return 10  # Default


# Global instance
_admission_controller: Optional[AdmissionController] = None


def get_admission_controller() -> AdmissionController:
    """Get the global AdmissionController instance."""
    global _admission_controller
    if _admission_controller is None:
        _admission_controller = AdmissionController()
    return _admission_controller
