"""
Call routing service with capacity checking and overload policies.

This service provides:
- Intelligent call routing based on caller type
- Capacity management and load balancing
- Overload protection and queuing
- Emergency call prioritization
- Provider availability checking
- Call distribution algorithms
- Performance monitoring
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from services.call_orchestrator import get_call_orchestrator, CallOrchestrator, CallType
from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ValidationError,
    CallRoutingError,
    CapacityExceededError
)


logger = get_logger("call_router")


class CallerType(Enum):
    """Types of callers."""
    PATIENT = "patient"
    PHYSICIAN = "physician"
    PHARMACY = "pharmacy"
    INSURANCE = "insurance"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


class CallPriority(Enum):
    """Call priority levels."""
    CRITICAL = 1    # Emergency calls
    HIGH = 2        # Physician calls
    MEDIUM = 3      # Patient calls
    LOW = 4         # General inquiries


class RoutingStrategy(Enum):
    """Call routing strategies."""
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    SKILL_BASED = "skill_based"
    PRIORITY_BASED = "priority_based"
    GEOGRAPHIC = "geographic"


class OverloadPolicy(Enum):
    """Overload handling policies."""
    QUEUE = "queue"                    # Queue calls when overloaded
    REJECT = "reject"                  # Reject new calls when overloaded
    DEGRADE = "degrade"                # Degrade service quality
    ESCALATE = "escalate"              # Escalate to human agents


@dataclass
class ProviderCapacity:
    """Provider capacity information."""
    provider_id: str
    max_concurrent_calls: int
    current_calls: int
    available_capacity: int
    skills: List[str]
    languages: List[str]
    last_updated: datetime
    is_available: bool = True


@dataclass
class CallQueue:
    """Call queue for overload management."""
    queue_id: str
    caller_type: CallerType
    priority: CallPriority
    max_queue_size: int
    current_size: int
    average_wait_time: float
    calls: deque = field(default_factory=deque)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RoutingRule:
    """Routing rule configuration."""
    rule_id: str
    caller_type: CallerType
    priority: CallPriority
    target_providers: List[str]
    routing_strategy: RoutingStrategy
    overload_policy: OverloadPolicy
    max_queue_size: int
    enabled: bool = True


@dataclass
class RoutingResult:
    """Result of call routing."""
    success: bool
    provider_id: Optional[str] = None
    queue_id: Optional[str] = None
    estimated_wait_time: Optional[float] = None
    routing_strategy: Optional[RoutingStrategy] = None
    overload_policy: Optional[OverloadPolicy] = None
    error_message: Optional[str] = None
    routing_time_ms: int = 0


class CallRouter:
    """
    Intelligent call routing service.
    
    Routes calls based on caller type, provider capacity,
    and system load with overload protection.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.call_orchestrator = get_call_orchestrator()
        
        # Capacity management
        self.provider_capacities: Dict[str, ProviderCapacity] = {}
        self.total_capacity = 0
        self.current_load = 0
        
        # Call queues
        self.call_queues: Dict[str, CallQueue] = {}
        
        # Routing rules
        self.routing_rules: Dict[str, RoutingRule] = {}
        
        # Load balancing
        self.round_robin_counters: Dict[str, int] = {}
        
        # Performance tracking
        self.routing_stats: Dict[str, Any] = {
            "total_routes": 0,
            "successful_routes": 0,
            "failed_routes": 0,
            "queued_calls": 0,
            "rejected_calls": 0,
            "average_routing_time": 0.0,
            "average_wait_time": 0.0
        }
        
        # Configuration
        self.max_total_capacity = 1000
        self.overload_threshold = 0.8  # 80% capacity
        self.queue_timeout_minutes = 30
        self.routing_timeout_seconds = 5
        
        # Initialize default routing rules
        self._initialize_default_rules()
        
        self.logger.info(
            "Call router initialized",
            LogCategory.CALL_ROUTING,
            extra_data={
                "max_total_capacity": self.max_total_capacity,
                "overload_threshold": self.overload_threshold,
                "queue_timeout_minutes": self.queue_timeout_minutes
            }
        )
    
    def _initialize_default_rules(self):
        """Initialize default routing rules."""
        default_rules = [
            RoutingRule(
                rule_id="emergency_rule",
                caller_type=CallerType.EMERGENCY,
                priority=CallPriority.CRITICAL,
                target_providers=["emergency_provider"],
                routing_strategy=RoutingStrategy.PRIORITY_BASED,
                overload_policy=OverloadPolicy.ESCALATE,
                max_queue_size=0
            ),
            RoutingRule(
                rule_id="physician_rule",
                caller_type=CallerType.PHYSICIAN,
                priority=CallPriority.HIGH,
                target_providers=["physician_provider"],
                routing_strategy=RoutingStrategy.SKILL_BASED,
                overload_policy=OverloadPolicy.QUEUE,
                max_queue_size=10
            ),
            RoutingRule(
                rule_id="patient_rule",
                caller_type=CallerType.PATIENT,
                priority=CallPriority.MEDIUM,
                target_providers=["patient_provider"],
                routing_strategy=RoutingStrategy.ROUND_ROBIN,
                overload_policy=OverloadPolicy.QUEUE,
                max_queue_size=50
            ),
            RoutingRule(
                rule_id="pharmacy_rule",
                caller_type=CallerType.PHARMACY,
                priority=CallPriority.MEDIUM,
                target_providers=["pharmacy_provider"],
                routing_strategy=RoutingStrategy.SKILL_BASED,
                overload_policy=OverloadPolicy.QUEUE,
                max_queue_size=20
            ),
            RoutingRule(
                rule_id="insurance_rule",
                caller_type=CallerType.INSURANCE,
                priority=CallPriority.MEDIUM,
                target_providers=["insurance_provider"],
                routing_strategy=RoutingStrategy.LEAST_LOADED,
                overload_policy=OverloadPolicy.QUEUE,
                max_queue_size=30
            ),
            RoutingRule(
                rule_id="default_rule",
                caller_type=CallerType.UNKNOWN,
                priority=CallPriority.LOW,
                target_providers=["general_provider"],
                routing_strategy=RoutingStrategy.ROUND_ROBIN,
                overload_policy=OverloadPolicy.QUEUE,
                max_queue_size=100
            )
        ]
        
        for rule in default_rules:
            self.routing_rules[rule.rule_id] = rule
        
        self.logger.info(f"Initialized {len(default_rules)} default routing rules")
    
    @log_performance("router_route_call")
    async def route_call(self, call_id: str, caller_type: CallerType,
                        caller_info: Optional[Dict[str, Any]] = None,
                        priority_override: Optional[CallPriority] = None) -> RoutingResult:
        """
        Route a call to the appropriate provider.
        
        Args:
            call_id: ID of the call to route
            caller_type: Type of caller
            caller_info: Additional caller information
            priority_override: Override priority for the call
            
        Returns:
            Routing result with provider assignment or queue placement
        """
        try:
            start_time = time.time()
            
            # Validate inputs
            if not call_id:
                raise ValidationError("call_id", call_id, "Call ID cannot be empty")
            
            # Find applicable routing rule
            routing_rule = self._find_routing_rule(caller_type, priority_override)
            if not routing_rule:
                raise CallRoutingError("no_routing_rule", f"No routing rule found for caller type: {caller_type}")
            
            # Check system capacity
            if self._is_system_overloaded():
                return await self._handle_overload(call_id, routing_rule, caller_info)
            
            # Route the call
            routing_result = await self._execute_routing(call_id, routing_rule, caller_info)
            
            # Update statistics
            routing_time_ms = int((time.time() - start_time) * 1000)
            routing_result.routing_time_ms = routing_time_ms
            self._update_routing_stats(routing_result)
            
            self.logger.info(
                f"Call routed: {call_id}",
                LogCategory.CALL_ROUTING,
                extra_data={
                    "call_id": call_id,
                    "caller_type": caller_type.value,
                    "routing_strategy": routing_rule.routing_strategy.value,
                    "success": routing_result.success,
                    "provider_id": routing_result.provider_id,
                    "queue_id": routing_result.queue_id,
                    "routing_time_ms": routing_time_ms
                }
            )
            
            return routing_result
            
        except Exception as e:
            self.logger.error(
                f"Failed to route call {call_id}: {e}",
                LogCategory.CALL_ROUTING,
                exception=e
            )
            raise
    
    def _find_routing_rule(self, caller_type: CallerType, 
                          priority_override: Optional[CallPriority]) -> Optional[RoutingRule]:
        """Find the applicable routing rule for a caller type."""
        # Look for exact match first
        for rule in self.routing_rules.values():
            if rule.caller_type == caller_type and rule.enabled:
                if priority_override:
                    # Create a temporary rule with overridden priority
                    temp_rule = RoutingRule(
                        rule_id=rule.rule_id,
                        caller_type=rule.caller_type,
                        priority=priority_override,
                        target_providers=rule.target_providers,
                        routing_strategy=rule.routing_strategy,
                        overload_policy=rule.overload_policy,
                        max_queue_size=rule.max_queue_size,
                        enabled=rule.enabled
                    )
                    return temp_rule
                return rule
        
        # Fall back to default rule
        return self.routing_rules.get("default_rule")
    
    async def _execute_routing(self, call_id: str, routing_rule: RoutingRule,
                             caller_info: Optional[Dict[str, Any]]) -> RoutingResult:
        """Execute the routing logic based on the rule."""
        try:
            # Filter available providers
            available_providers = self._get_available_providers(routing_rule.target_providers)
            
            if not available_providers:
                # No providers available, handle overload
                return await self._handle_overload(call_id, routing_rule, caller_info)
            
            # Select provider based on strategy
            selected_provider = await self._select_provider(
                available_providers, routing_rule.routing_strategy, caller_info
            )
            
            if selected_provider:
                # Assign call to provider
                await self._assign_call_to_provider(call_id, selected_provider)
                
                return RoutingResult(
                    success=True,
                    provider_id=selected_provider,
                    routing_strategy=routing_rule.routing_strategy,
                    overload_policy=routing_rule.overload_policy
                )
            else:
                # No provider selected, handle overload
                return await self._handle_overload(call_id, routing_rule, caller_info)
                
        except Exception as e:
            self.logger.error(f"Failed to execute routing for call {call_id}: {e}")
            return RoutingResult(
                success=False,
                error_message=str(e)
            )
    
    def _get_available_providers(self, target_providers: List[str]) -> List[str]:
        """Get list of available providers from target list."""
        available = []
        
        for provider_id in target_providers:
            if provider_id in self.provider_capacities:
                capacity = self.provider_capacities[provider_id]
                if capacity.is_available and capacity.available_capacity > 0:
                    available.append(provider_id)
        
        return available
    
    async def _select_provider(self, available_providers: List[str],
                             strategy: RoutingStrategy,
                             caller_info: Optional[Dict[str, Any]]) -> Optional[str]:
        """Select a provider based on the routing strategy."""
        try:
            if not available_providers:
                return None
            
            if strategy == RoutingStrategy.ROUND_ROBIN:
                return self._round_robin_selection(available_providers)
            elif strategy == RoutingStrategy.LEAST_LOADED:
                return self._least_loaded_selection(available_providers)
            elif strategy == RoutingStrategy.SKILL_BASED:
                return self._skill_based_selection(available_providers, caller_info)
            elif strategy == RoutingStrategy.PRIORITY_BASED:
                return self._priority_based_selection(available_providers)
            elif strategy == RoutingStrategy.GEOGRAPHIC:
                return self._geographic_selection(available_providers, caller_info)
            else:
                # Default to round robin
                return self._round_robin_selection(available_providers)
                
        except Exception as e:
            self.logger.error(f"Failed to select provider: {e}")
            return None
    
    def _round_robin_selection(self, available_providers: List[str]) -> str:
        """Select provider using round robin algorithm."""
        if not available_providers:
            return None
        
        # Get or create counter for this provider list
        provider_key = ",".join(sorted(available_providers))
        if provider_key not in self.round_robin_counters:
            self.round_robin_counters[provider_key] = 0
        
        # Select next provider in round robin
        index = self.round_robin_counters[provider_key] % len(available_providers)
        selected_provider = available_providers[index]
        
        # Update counter
        self.round_robin_counters[provider_key] += 1
        
        return selected_provider
    
    def _least_loaded_selection(self, available_providers: List[str]) -> str:
        """Select provider with least current load."""
        if not available_providers:
            return None
        
        least_loaded_provider = None
        min_load = float('inf')
        
        for provider_id in available_providers:
            capacity = self.provider_capacities[provider_id]
            load_ratio = capacity.current_calls / capacity.max_concurrent_calls
            
            if load_ratio < min_load:
                min_load = load_ratio
                least_loaded_provider = provider_id
        
        return least_loaded_provider
    
    def _skill_based_selection(self, available_providers: List[str],
                             caller_info: Optional[Dict[str, Any]]) -> str:
        """Select provider based on skills and caller requirements."""
        if not available_providers:
            return None
        
        # Extract required skills from caller info
        required_skills = []
        if caller_info:
            required_skills = caller_info.get("required_skills", [])
        
        # Find providers with matching skills
        matching_providers = []
        for provider_id in available_providers:
            capacity = self.provider_capacities[provider_id]
            if not required_skills or any(skill in capacity.skills for skill in required_skills):
                matching_providers.append(provider_id)
        
        # If no skill match, fall back to all available providers
        if not matching_providers:
            matching_providers = available_providers
        
        # Select least loaded from matching providers
        return self._least_loaded_selection(matching_providers)
    
    def _priority_based_selection(self, available_providers: List[str]) -> str:
        """Select provider based on priority (emergency providers first)."""
        if not available_providers:
            return None
        
        # Sort providers by priority (lower number = higher priority)
        priority_order = ["emergency_provider", "physician_provider", "patient_provider", "general_provider"]
        
        for priority_provider in priority_order:
            if priority_provider in available_providers:
                return priority_provider
        
        # Fall back to first available
        return available_providers[0]
    
    def _geographic_selection(self, available_providers: List[str],
                            caller_info: Optional[Dict[str, Any]]) -> str:
        """Select provider based on geographic proximity."""
        if not available_providers:
            return None
        
        # For now, fall back to least loaded selection
        # In a real implementation, this would consider geographic data
        return self._least_loaded_selection(available_providers)
    
    async def _assign_call_to_provider(self, call_id: str, provider_id: str):
        """Assign a call to a provider and update capacity."""
        try:
            if provider_id in self.provider_capacities:
                capacity = self.provider_capacities[provider_id]
                capacity.current_calls += 1
                capacity.available_capacity = capacity.max_concurrent_calls - capacity.current_calls
                capacity.last_updated = datetime.utcnow()
                
                # Update total system load
                self.current_load += 1
                
                self.logger.debug(f"Assigned call {call_id} to provider {provider_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to assign call {call_id} to provider {provider_id}: {e}")
    
    async def _handle_overload(self, call_id: str, routing_rule: RoutingRule,
                             caller_info: Optional[Dict[str, Any]]) -> RoutingResult:
        """Handle call routing when system is overloaded."""
        try:
            if routing_rule.overload_policy == OverloadPolicy.QUEUE:
                return await self._queue_call(call_id, routing_rule, caller_info)
            elif routing_rule.overload_policy == OverloadPolicy.REJECT:
                return RoutingResult(
                    success=False,
                    error_message="System overloaded, call rejected",
                    overload_policy=OverloadPolicy.REJECT
                )
            elif routing_rule.overload_policy == OverloadPolicy.ESCALATE:
                return await self._escalate_call(call_id, routing_rule, caller_info)
            elif routing_rule.overload_policy == OverloadPolicy.DEGRADE:
                return await self._degrade_service(call_id, routing_rule, caller_info)
            else:
                # Default to queue
                return await self._queue_call(call_id, routing_rule, caller_info)
                
        except Exception as e:
            self.logger.error(f"Failed to handle overload for call {call_id}: {e}")
            return RoutingResult(
                success=False,
                error_message=f"Overload handling failed: {e}"
            )
    
    async def _queue_call(self, call_id: str, routing_rule: RoutingRule,
                        caller_info: Optional[Dict[str, Any]]) -> RoutingResult:
        """Queue a call for later processing."""
        try:
            queue_id = f"{routing_rule.caller_type.value}_queue"
            
            # Get or create queue
            if queue_id not in self.call_queues:
                self.call_queues[queue_id] = CallQueue(
                    queue_id=queue_id,
                    caller_type=routing_rule.caller_type,
                    priority=routing_rule.priority,
                    max_queue_size=routing_rule.max_queue_size
                )
            
            queue = self.call_queues[queue_id]
            
            # Check queue capacity
            if queue.current_size >= queue.max_queue_size:
                return RoutingResult(
                    success=False,
                    error_message="Queue is full, call rejected",
                    overload_policy=OverloadPolicy.REJECT
                )
            
            # Add call to queue
            queue.calls.append({
                "call_id": call_id,
                "caller_info": caller_info,
                "queued_at": datetime.utcnow(),
                "routing_rule": routing_rule
            })
            queue.current_size += 1
            
            # Calculate estimated wait time
            estimated_wait_time = self._calculate_wait_time(queue)
            
            # Update statistics
            self.routing_stats["queued_calls"] += 1
            
            return RoutingResult(
                success=True,
                queue_id=queue_id,
                estimated_wait_time=estimated_wait_time,
                overload_policy=OverloadPolicy.QUEUE
            )
            
        except Exception as e:
            self.logger.error(f"Failed to queue call {call_id}: {e}")
            return RoutingResult(
                success=False,
                error_message=f"Queueing failed: {e}"
            )
    
    async def _escalate_call(self, call_id: str, routing_rule: RoutingRule,
                           caller_info: Optional[Dict[str, Any]]) -> RoutingResult:
        """Escalate call to human agents or emergency handling."""
        try:
            # For emergency calls, try to find any available provider
            if routing_rule.priority == CallPriority.CRITICAL:
                all_providers = list(self.provider_capacities.keys())
                available_providers = self._get_available_providers(all_providers)
                
                if available_providers:
                    selected_provider = self._least_loaded_selection(available_providers)
                    if selected_provider:
                        await self._assign_call_to_provider(call_id, selected_provider)
                        return RoutingResult(
                            success=True,
                            provider_id=selected_provider,
                            overload_policy=OverloadPolicy.ESCALATE
                        )
            
            # If escalation fails, queue the call
            return await self._queue_call(call_id, routing_rule, caller_info)
            
        except Exception as e:
            self.logger.error(f"Failed to escalate call {call_id}: {e}")
            return RoutingResult(
                success=False,
                error_message=f"Escalation failed: {e}"
            )
    
    async def _degrade_service(self, call_id: str, routing_rule: RoutingRule,
                             caller_info: Optional[Dict[str, Any]]) -> RoutingResult:
        """Degrade service quality to handle overload."""
        try:
            # Find any available provider, even if not optimal
            all_providers = list(self.provider_capacities.keys())
            available_providers = self._get_available_providers(all_providers)
            
            if available_providers:
                selected_provider = self._least_loaded_selection(available_providers)
                if selected_provider:
                    await self._assign_call_to_provider(call_id, selected_provider)
                    return RoutingResult(
                        success=True,
                        provider_id=selected_provider,
                        overload_policy=OverloadPolicy.DEGRADE
                    )
            
            # If degradation fails, queue the call
            return await self._queue_call(call_id, routing_rule, caller_info)
            
        except Exception as e:
            self.logger.error(f"Failed to degrade service for call {call_id}: {e}")
            return RoutingResult(
                success=False,
                error_message=f"Service degradation failed: {e}"
            )
    
    def _calculate_wait_time(self, queue: CallQueue) -> float:
        """Calculate estimated wait time for a queue."""
        if queue.current_size == 0:
            return 0.0
        
        # Simple calculation based on average processing time
        # In a real implementation, this would be more sophisticated
        average_processing_time = 300  # 5 minutes
        return queue.current_size * average_processing_time
    
    def _is_system_overloaded(self) -> bool:
        """Check if the system is overloaded."""
        if self.total_capacity == 0:
            return False
        
        load_ratio = self.current_load / self.total_capacity
        return load_ratio >= self.overload_threshold
    
    def _update_routing_stats(self, routing_result: RoutingResult):
        """Update routing statistics."""
        self.routing_stats["total_routes"] += 1
        
        if routing_result.success:
            self.routing_stats["successful_routes"] += 1
        else:
            self.routing_stats["failed_routes"] += 1
        
        # Update average routing time
        total_time = self.routing_stats["average_routing_time"] * (self.routing_stats["total_routes"] - 1)
        self.routing_stats["average_routing_time"] = (total_time + routing_result.routing_time_ms) / self.routing_stats["total_routes"]
    
    def update_provider_capacity(self, provider_id: str, max_calls: int, 
                               current_calls: int, skills: List[str] = None,
                               languages: List[str] = None, is_available: bool = True):
        """Update provider capacity information."""
        try:
            capacity = ProviderCapacity(
                provider_id=provider_id,
                max_concurrent_calls=max_calls,
                current_calls=current_calls,
                available_capacity=max_calls - current_calls,
                skills=skills or [],
                languages=languages or [],
                last_updated=datetime.utcnow(),
                is_available=is_available
            )
            
            # Update total capacity
            old_capacity = self.provider_capacities.get(provider_id, ProviderCapacity(
                provider_id=provider_id, max_concurrent_calls=0, current_calls=0,
                available_capacity=0, skills=[], languages=[], last_updated=datetime.utcnow()
            ))
            
            self.total_capacity = self.total_capacity - old_capacity.max_concurrent_calls + max_calls
            self.current_load = self.current_load - old_capacity.current_calls + current_calls
            
            self.provider_capacities[provider_id] = capacity
            
            self.logger.debug(f"Updated capacity for provider {provider_id}: {current_calls}/{max_calls}")
            
        except Exception as e:
            self.logger.error(f"Failed to update provider capacity for {provider_id}: {e}")
    
    def remove_provider(self, provider_id: str):
        """Remove a provider from the routing system."""
        try:
            if provider_id in self.provider_capacities:
                capacity = self.provider_capacities[provider_id]
                self.total_capacity -= capacity.max_concurrent_calls
                self.current_load -= capacity.current_calls
                del self.provider_capacities[provider_id]
                
                self.logger.info(f"Removed provider {provider_id} from routing system")
                
        except Exception as e:
            self.logger.error(f"Failed to remove provider {provider_id}: {e}")
    
    def add_routing_rule(self, rule: RoutingRule):
        """Add a new routing rule."""
        self.routing_rules[rule.rule_id] = rule
        self.logger.info(f"Added routing rule: {rule.rule_id}")
    
    def remove_routing_rule(self, rule_id: str):
        """Remove a routing rule."""
        if rule_id in self.routing_rules:
            del self.routing_rules[rule_id]
            self.logger.info(f"Removed routing rule: {rule_id}")
    
    def get_routing_statistics(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "routing_stats": self.routing_stats.copy(),
            "system_capacity": {
                "total_capacity": self.total_capacity,
                "current_load": self.current_load,
                "load_percentage": (self.current_load / self.total_capacity * 100) if self.total_capacity > 0 else 0,
                "is_overloaded": self._is_system_overloaded()
            },
            "provider_capacities": {
                provider_id: {
                    "max_calls": capacity.max_concurrent_calls,
                    "current_calls": capacity.current_calls,
                    "available_capacity": capacity.available_capacity,
                    "is_available": capacity.is_available,
                    "skills": capacity.skills,
                    "languages": capacity.languages
                }
                for provider_id, capacity in self.provider_capacities.items()
            },
            "queue_status": {
                queue_id: {
                    "current_size": queue.current_size,
                    "max_size": queue.max_queue_size,
                    "average_wait_time": queue.average_wait_time,
                    "caller_type": queue.caller_type.value,
                    "priority": queue.priority.value
                }
                for queue_id, queue in self.call_queues.items()
            },
            "routing_rules": {
                rule_id: {
                    "caller_type": rule.caller_type.value,
                    "priority": rule.priority.value,
                    "routing_strategy": rule.routing_strategy.value,
                    "overload_policy": rule.overload_policy.value,
                    "enabled": rule.enabled
                }
                for rule_id, rule in self.routing_rules.items()
            }
        }
    
    async def process_queued_calls(self):
        """Process queued calls when capacity becomes available."""
        try:
            for queue_id, queue in self.call_queues.items():
                if queue.current_size == 0:
                    continue
                
                # Try to route queued calls
                while queue.calls and not self._is_system_overloaded():
                    queued_call = queue.calls.popleft()
                    call_id = queued_call["call_id"]
                    routing_rule = queued_call["routing_rule"]
                    caller_info = queued_call["caller_info"]
                    
                    # Try to route the call
                    routing_result = await self._execute_routing(call_id, routing_rule, caller_info)
                    
                    if routing_result.success and routing_result.provider_id:
                        queue.current_size -= 1
                        self.logger.info(f"Successfully routed queued call {call_id} to provider {routing_result.provider_id}")
                    else:
                        # Put the call back at the front of the queue
                        queue.calls.appendleft(queued_call)
                        break
                
        except Exception as e:
            self.logger.error(f"Failed to process queued calls: {e}")
    
    async def cleanup_expired_queues(self):
        """Clean up expired calls in queues."""
        try:
            current_time = datetime.utcnow()
            
            for queue_id, queue in self.call_queues.items():
                expired_calls = []
                
                for queued_call in queue.calls:
                    queued_at = queued_call["queued_at"]
                    if (current_time - queued_at).total_seconds() > (self.queue_timeout_minutes * 60):
                        expired_calls.append(queued_call)
                
                # Remove expired calls
                for expired_call in expired_calls:
                    queue.calls.remove(expired_call)
                    queue.current_size -= 1
                    self.routing_stats["rejected_calls"] += 1
                    
                    self.logger.warning(f"Removed expired call {expired_call['call_id']} from queue {queue_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired queues: {e}")


# Global service instance
_call_router: Optional[CallRouter] = None


def get_call_router() -> CallRouter:
    """Get the global Call Router instance."""
    global _call_router
    if _call_router is None:
        _call_router = CallRouter()
    return _call_router
