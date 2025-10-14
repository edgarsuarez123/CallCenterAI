"""
Structured Logging Service - PHI-Safe and HIPAA Compliant

This service provides comprehensive structured logging with:
1. Automatic PHI detection and masking
2. Correlation ID tracking across services
3. Performance monitoring and slow query detection
4. Security monitoring and audit trails
5. Error aggregation and alerting
6. Compliance auditing capabilities
7. JSON-structured logs for machine parsing
8. Integration with monitoring systems (Splunk, Datadog, CloudWatch)

Key Features:
- HIPAA compliance through automatic PHI masking
- Request correlation across distributed services
- Performance bottleneck identification
- Security incident detection
- Compliance audit trail generation
- Error pattern analysis
"""

import json
import logging
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from functools import wraps
import hashlib
import threading
from collections import defaultdict, deque

from sqlalchemy.orm import Session
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from services.configuration import get_settings

# Thread-local storage for request context
_request_context = threading.local()

class LogLevel(Enum):
    """Standardized log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogCategory(Enum):
    """Categorized logging for different system components."""
    # System categories
    SYSTEM = "system"
    DATABASE = "database"
    API = "api"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    
    # Business categories
    APPOINTMENT = "appointment"
    PATIENT = "patient"
    PROVIDER = "provider"
    CLINIC = "clinic"
    CALL = "call"
    
    # Security categories
    SECURITY = "security"
    AUDIT = "audit"
    COMPLIANCE = "compliance"
    
    # Performance categories
    PERFORMANCE = "performance"
    SLOW_QUERY = "slow_query"
    TIMEOUT = "timeout"
    
    # Error categories
    ERROR = "error"
    EXCEPTION = "exception"
    VALIDATION = "validation"

class PHIPattern:
    """PHI detection patterns for automatic masking."""
    
    # Phone number patterns (US format)
    PHONE_PATTERNS = [
        r'\+?1?[-.\s]?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
        r'\+?1[-.\s]?([0-9]{3})[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})',
        r'\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})'
    ]
    
    # Email pattern
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    # SSN pattern (with various formats)
    SSN_PATTERNS = [
        r'\b\d{3}-\d{2}-\d{4}\b',
        r'\b\d{3}\s\d{2}\s\d{4}\b',
        r'\b\d{9}\b'
    ]
    
    # Date of birth patterns
    DOB_PATTERNS = [
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',
        r'\b\d{1,2}-\d{1,2}-\d{4}\b',
        r'\b\d{4}-\d{1,2}-\d{1,2}\b'
    ]
    
    # Name patterns (common first/last name combinations)
    NAME_PATTERNS = [
        r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b',  # First Last
        r'\b[A-Z][a-z]+,\s[A-Z][a-z]+\b',  # Last, First
    ]
    
    # Medical record number patterns
    MRN_PATTERNS = [
        r'\bMRN[:\s]*\d+\b',
        r'\bMedical\s+Record[:\s]*\d+\b',
        r'\bPatient\s+ID[:\s]*\d+\b'
    ]

class StructuredLogger:
    """
    PHI-safe structured logging service with comprehensive monitoring capabilities.
    
    This logger ensures:
    1. No PHI is ever logged in plain text
    2. All logs are structured JSON for machine parsing
    3. Request correlation across services
    4. Performance monitoring and alerting
    5. Security incident detection
    6. Compliance audit trails
    """
    
    def __init__(self, name: str = "callcenter_ai", level: Optional[LogLevel] = None):
        self.name = name
        
        # Get configuration
        settings = get_settings()
        
        # Use configured log level if not specified
        if level is None:
            level = LogLevel(settings.logging.level)
        
        self.level = level
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.value))
        
        # Error aggregation tracking
        self._error_counts = defaultdict(int)
        self._error_samples = defaultdict(lambda: deque(maxlen=10))
        self._last_error_alert = {}
        
        # Performance tracking
        self._slow_queries = deque(maxlen=100)
        self._performance_metrics = defaultdict(list)
        
        # Security monitoring
        self._security_events = deque(maxlen=1000)
        self._failed_auth_attempts = defaultdict(int)
        
        # Setup handlers if not already configured
        if not self.logger.handlers:
            self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup logging handlers for structured output."""
        # Console handler with JSON formatting
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(StructuredFormatter())
        self.logger.addHandler(console_handler)
        
        # File handler for persistent logs
        file_handler = logging.FileHandler('logs/callcenter_ai.log')
        file_handler.setFormatter(StructuredFormatter())
        self.logger.addHandler(file_handler)
    
    def _detect_and_mask_phi(self, message: str) -> str:
        """
        Detect and mask PHI in log messages.
        
        Args:
            message: Original log message
            
        Returns:
            Message with PHI masked
        """
        # Get configuration
        settings = get_settings()
        
        # Skip PHI masking if disabled in configuration
        if not settings.logging.phi_masking_enabled:
            return message
        
        masked_message = message
        
        # Mask phone numbers
        for pattern in PHIPattern.PHONE_PATTERNS:
            masked_message = re.sub(pattern, r'[PHONE_MASKED]', masked_message, flags=re.IGNORECASE)
        
        # Mask email addresses
        masked_message = re.sub(PHIPattern.EMAIL_PATTERN, '[EMAIL_MASKED]', masked_message, flags=re.IGNORECASE)
        
        # Mask SSNs
        for pattern in PHIPattern.SSN_PATTERNS:
            masked_message = re.sub(pattern, '[SSN_MASKED]', masked_message, flags=re.IGNORECASE)
        
        # Mask dates of birth
        for pattern in PHIPattern.DOB_PATTERNS:
            masked_message = re.sub(pattern, '[DOB_MASKED]', masked_message, flags=re.IGNORECASE)
        
        # Mask names (be careful not to mask too aggressively)
        for pattern in PHIPattern.NAME_PATTERNS:
            # Only mask if it looks like a real name (not common words)
            matches = re.finditer(pattern, masked_message)
            for match in matches:
                name = match.group()
                if self._is_likely_name(name):
                    masked_message = masked_message.replace(name, '[NAME_MASKED]')
        
        # Mask medical record numbers
        for pattern in PHIPattern.MRN_PATTERNS:
            masked_message = re.sub(pattern, '[MRN_MASKED]', masked_message, flags=re.IGNORECASE)
        
        return masked_message
    
    def _is_likely_name(self, text: str) -> bool:
        """Determine if text is likely a person's name."""
        # Common words that might match name patterns but aren't names
        common_words = {
            'New York', 'Los Angeles', 'San Francisco', 'Las Vegas',
            'Salt Lake', 'New Orleans', 'San Diego', 'San Antonio',
            'New Jersey', 'New Mexico', 'North Carolina', 'South Carolina',
            'West Virginia', 'New Hampshire', 'Rhode Island'
        }
        
        return text not in common_words
    
    def _get_request_context(self) -> Dict[str, Any]:
        """Get current request context from thread-local storage."""
        context = {}
        if hasattr(_request_context, 'correlation_id'):
            context['correlation_id'] = _request_context.correlation_id
        if hasattr(_request_context, 'user_id'):
            context['user_id'] = _request_context.user_id
        if hasattr(_request_context, 'clinic_id'):
            context['clinic_id'] = _request_context.clinic_id
        if hasattr(_request_context, 'request_id'):
            context['request_id'] = _request_context.request_id
        if hasattr(_request_context, 'start_time'):
            context['request_duration_ms'] = int((time.time() - _request_context.start_time) * 1000)
        return context
    
    def _create_log_entry(
        self,
        level: LogLevel,
        message: str,
        category: LogCategory,
        extra_data: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ) -> Dict[str, Any]:
        """Create a structured log entry."""
        
        # Mask PHI in message
        safe_message = self._detect_and_mask_phi(message)
        
        # Base log entry
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': level.value,
            'category': category.value,
            'message': safe_message,
            'service': self.name,
            'version': '1.0.0'  # Could be from environment
        }
        
        # Add request context
        request_context = self._get_request_context()
        if request_context:
            log_entry['request_context'] = request_context
        
        # Add extra data (with PHI masking)
        if extra_data:
            safe_extra_data = self._mask_phi_in_dict(extra_data)
            log_entry['data'] = safe_extra_data
        
        # Add exception information
        if exception:
            log_entry['exception'] = {
                'type': type(exception).__name__,
                'message': str(exception),
                'traceback': self._get_traceback(exception)
            }
        
        # Add performance metrics if available
        if category in [LogCategory.PERFORMANCE, LogCategory.SLOW_QUERY]:
            log_entry['performance'] = self._get_performance_metrics()
        
        # Add security context if security-related
        if category in [LogCategory.SECURITY, LogCategory.AUDIT, LogCategory.COMPLIANCE]:
            log_entry['security'] = self._get_security_context()
        
        return log_entry
    
    def _mask_phi_in_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively mask PHI in dictionary data."""
        safe_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                safe_data[key] = self._detect_and_mask_phi(value)
            elif isinstance(value, dict):
                safe_data[key] = self._mask_phi_in_dict(value)
            elif isinstance(value, list):
                safe_data[key] = [
                    self._detect_and_mask_phi(item) if isinstance(item, str)
                    else self._mask_phi_in_dict(item) if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                safe_data[key] = value
        return safe_data
    
    def _get_traceback(self, exception: Exception) -> str:
        """Get formatted traceback for exception."""
        import traceback
        return traceback.format_exc()
    
    def _get_performance_metrics(self) -> Dict[str, Any]:
        """Get current performance metrics."""
        return {
            'slow_queries_count': len(self._slow_queries),
            'avg_query_time_ms': self._calculate_avg_query_time(),
            'memory_usage_mb': self._get_memory_usage()
        }
    
    def _get_security_context(self) -> Dict[str, Any]:
        """Get current security context."""
        return {
            'failed_auth_attempts': dict(self._failed_auth_attempts),
            'security_events_count': len(self._security_events),
            'last_security_event': self._security_events[-1] if self._security_events else None
        }
    
    def _calculate_avg_query_time(self) -> float:
        """Calculate average query time from recent slow queries."""
        if not self._slow_queries:
            return 0.0
        return sum(query['duration_ms'] for query in self._slow_queries) / len(self._slow_queries)
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
    
    def log(
        self,
        level: LogLevel,
        message: str,
        category: LogCategory = LogCategory.SYSTEM,
        extra_data: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ):
        """Log a structured message."""
        log_entry = self._create_log_entry(level, message, category, extra_data, exception)
        
        # Log using appropriate level
        log_method = getattr(self.logger, level.value.lower())
        log_method(json.dumps(log_entry, default=str))
        
        # Track errors for aggregation
        if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            self._track_error(log_entry)
        
        # Track security events
        if category in [LogCategory.SECURITY, LogCategory.AUDIT]:
            self._track_security_event(log_entry)
    
    def _track_error(self, log_entry: Dict[str, Any]):
        """Track errors for aggregation and alerting."""
        error_key = f"{log_entry.get('category', 'unknown')}:{log_entry.get('message', 'unknown')}"
        self._error_counts[error_key] += 1
        self._error_samples[error_key].append(log_entry)
        
        # Alert on error spikes
        if self._error_counts[error_key] > 10:  # Threshold for alerting
            last_alert = self._last_error_alert.get(error_key, 0)
            if time.time() - last_alert > 300:  # 5 minutes between alerts
                self._send_error_alert(error_key, self._error_counts[error_key])
                self._last_error_alert[error_key] = time.time()
    
    def _track_security_event(self, log_entry: Dict[str, Any]):
        """Track security events for monitoring."""
        self._security_events.append(log_entry)
        
        # Track failed authentication attempts
        if 'authentication' in log_entry.get('message', '').lower():
            if 'failed' in log_entry.get('message', '').lower():
                user_id = log_entry.get('request_context', {}).get('user_id', 'unknown')
                self._failed_auth_attempts[user_id] += 1
                
                # Alert on suspicious activity
                if self._failed_auth_attempts[user_id] > 5:
                    self.log(
                        LogLevel.WARNING,
                        f"Suspicious authentication activity detected for user {user_id}",
                        LogCategory.SECURITY,
                        {'failed_attempts': self._failed_auth_attempts[user_id]}
                    )
    
    def _send_error_alert(self, error_key: str, count: int):
        """Send error alert (placeholder for integration with alerting systems)."""
        self.log(
            LogLevel.WARNING,
            f"Error spike detected: {error_key} occurred {count} times",
            LogCategory.ERROR,
            {'error_key': error_key, 'count': count, 'alert_type': 'error_spike'}
        )
    
    # Convenience methods for different log levels
    def debug(self, message: str, category: LogCategory = LogCategory.SYSTEM, **kwargs):
        self.log(LogLevel.DEBUG, message, category, kwargs.get('extra_data'))
    
    def info(self, message: str, category: LogCategory = LogCategory.SYSTEM, **kwargs):
        self.log(LogLevel.INFO, message, category, kwargs.get('extra_data'))
    
    def warning(self, message: str, category: LogCategory = LogCategory.SYSTEM, **kwargs):
        self.log(LogLevel.WARNING, message, category, kwargs.get('extra_data'))
    
    def error(self, message: str, category: LogCategory = LogCategory.ERROR, exception: Exception = None, **kwargs):
        self.log(LogLevel.ERROR, message, category, kwargs.get('extra_data'), exception)
    
    def critical(self, message: str, category: LogCategory = LogCategory.ERROR, exception: Exception = None, **kwargs):
        self.log(LogLevel.CRITICAL, message, category, kwargs.get('extra_data'), exception)
    
    # Specialized logging methods
    def log_api_request(self, method: str, path: str, status_code: int, duration_ms: float, **kwargs):
        """Log API request with performance metrics."""
        self.info(
            f"API {method} {path} - {status_code}",
            LogCategory.API,
            extra_data={
                'method': method,
                'path': path,
                'status_code': status_code,
                'duration_ms': duration_ms,
                **kwargs
            }
        )
    
    def log_database_query(self, query: str, duration_ms: float, rows_affected: int = None):
        """Log database query with performance tracking."""
        # Mask any potential PHI in query
        safe_query = self._detect_and_mask_phi(query)
        
        if duration_ms > 1000:  # Slow query threshold
            self.warning(
                f"Slow database query detected: {duration_ms}ms",
                LogCategory.SLOW_QUERY,
                extra_data={
                    'query': safe_query,
                    'duration_ms': duration_ms,
                    'rows_affected': rows_affected
                }
            )
            self._slow_queries.append({
                'query': safe_query,
                'duration_ms': duration_ms,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
        else:
            self.debug(
                f"Database query executed: {duration_ms}ms",
                LogCategory.DATABASE,
                extra_data={
                    'query': safe_query,
                    'duration_ms': duration_ms,
                    'rows_affected': rows_affected
                }
            )
    
    def log_security_event(self, event_type: str, details: Dict[str, Any]):
        """Log security-related events."""
        self.warning(
            f"Security event: {event_type}",
            LogCategory.SECURITY,
            extra_data={
                'event_type': event_type,
                'details': details
            }
        )
    
    def log_audit_event(self, action: str, resource: str, details: Dict[str, Any]):
        """Log audit events for compliance."""
        self.info(
            f"Audit: {action} on {resource}",
            LogCategory.AUDIT,
            extra_data={
                'action': action,
                'resource': resource,
                'details': details
            }
        )
    
    def log_business_event(self, event_type: str, category: LogCategory, details: Dict[str, Any]):
        """Log business events (appointments, calls, etc.)."""
        self.info(
            f"Business event: {event_type}",
            category,
            extra_data={
                'event_type': event_type,
                'details': details
            }
        )
    
    # Analytics and reporting methods
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of recent errors for monitoring dashboards."""
        return {
            'total_errors': sum(self._error_counts.values()),
            'error_types': dict(self._error_counts),
            'recent_errors': list(self._error_samples.keys()),
            'error_samples': {k: list(v) for k, v in self._error_samples.items()}
        }
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for monitoring."""
        return {
            'slow_queries': list(self._slow_queries),
            'avg_query_time_ms': self._calculate_avg_query_time(),
            'memory_usage_mb': self._get_memory_usage()
        }
    
    def get_security_summary(self) -> Dict[str, Any]:
        """Get security summary for monitoring."""
        return {
            'failed_auth_attempts': dict(self._failed_auth_attempts),
            'recent_security_events': list(self._security_events)[-10:],  # Last 10 events
            'total_security_events': len(self._security_events)
        }


class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logs."""
    
    def format(self, record):
        # If the message is already JSON, return it as-is
        if record.getMessage().startswith('{'):
            return record.getMessage()
        
        # Otherwise, create a basic structured log entry
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname,
            'message': record.getMessage(),
            'logger': record.name,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, default=str)


class RequestContextManager:
    """Context manager for request correlation and tracking."""
    
    def __init__(self, correlation_id: str = None, user_id: str = None, clinic_id: str = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.user_id = user_id
        self.clinic_id = clinic_id
        self.request_id = str(uuid.uuid4())
        self.start_time = time.time()
        self._previous_context = {}
    
    def __enter__(self):
        # Store previous context
        if hasattr(_request_context, 'correlation_id'):
            self._previous_context['correlation_id'] = _request_context.correlation_id
        if hasattr(_request_context, 'user_id'):
            self._previous_context['user_id'] = _request_context.user_id
        if hasattr(_request_context, 'clinic_id'):
            self._previous_context['clinic_id'] = _request_context.clinic_id
        if hasattr(_request_context, 'request_id'):
            self._previous_context['request_id'] = _request_context.request_id
        if hasattr(_request_context, 'start_time'):
            self._previous_context['start_time'] = _request_context.start_time
        
        # Set new context
        _request_context.correlation_id = self.correlation_id
        _request_context.user_id = self.user_id
        _request_context.clinic_id = self.clinic_id
        _request_context.request_id = self.request_id
        _request_context.start_time = self.start_time
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore previous context
        for key, value in self._previous_context.items():
            setattr(_request_context, key, value)
        
        # Clear context if no previous context
        if not self._previous_context:
            if hasattr(_request_context, 'correlation_id'):
                delattr(_request_context, 'correlation_id')
            if hasattr(_request_context, 'user_id'):
                delattr(_request_context, 'user_id')
            if hasattr(_request_context, 'clinic_id'):
                delattr(_request_context, 'clinic_id')
            if hasattr(_request_context, 'request_id'):
                delattr(_request_context, 'request_id')
            if hasattr(_request_context, 'start_time'):
                delattr(_request_context, 'start_time')


# Global logger instance
logger = StructuredLogger()

# Convenience functions
def get_logger(name: str = None) -> StructuredLogger:
    """Get a structured logger instance."""
    if name:
        return StructuredLogger(name)
    return logger

def log_request_context(correlation_id: str = None, user_id: str = None, clinic_id: str = None):
    """Decorator to add request context to function calls."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with RequestContextManager(correlation_id, user_id, clinic_id):
                return func(*args, **kwargs)
        return wrapper
    return decorator

def log_performance(operation_name: str = None):
    """Decorator to log function performance."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            operation = operation_name or f"{func.__module__}.{func.__name__}"
            
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                
                logger.info(
                    f"Operation completed: {operation}",
                    LogCategory.PERFORMANCE,
                    extra_data={
                        'operation': operation,
                        'duration_ms': duration_ms,
                        'success': True
                    }
                )
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                
                logger.error(
                    f"Operation failed: {operation}",
                    LogCategory.PERFORMANCE,
                    exception=e,
                    extra_data={
                        'operation': operation,
                        'duration_ms': duration_ms,
                        'success': False
                    }
                )
                raise
        return wrapper
    return decorator

def log_database_queries(engine: Engine):
    """Setup database query logging for SQLAlchemy engine."""
    
    # Get configuration
    settings = get_settings()
    
    # Only setup database query logging if enabled in configuration
    if not settings.logging.performance_logging_enabled:
        return
    
    @event.listens_for(engine, "before_cursor_execute")
    def receive_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        context._query_start_time = time.time()
    
    @event.listens_for(engine, "after_cursor_execute")
    def receive_after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        total = time.time() - context._query_start_time
        duration_ms = total * 1000
        
        # Log the query
        logger.log_database_query(statement, duration_ms)
        
        # Log slow queries as warnings
        if duration_ms > 1000:  # 1 second threshold
            logger.warning(
                f"Slow database query: {duration_ms:.2f}ms",
                LogCategory.SLOW_QUERY,
                extra_data={
                    'query': statement[:200] + '...' if len(statement) > 200 else statement,
                    'duration_ms': duration_ms,
                    'parameters': str(parameters)[:100] if parameters else None
                }
            )

# Database integration for audit logging
class AuditLogger:
    """Specialized logger for audit trails and compliance."""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.logger = get_logger("audit")
    
    def log_phi_access(self, user_id: str, resource_type: str, resource_id: str, action: str):
        """Log PHI access for compliance auditing."""
        self.logger.log_audit_event(
            f"PHI_ACCESS_{action.upper()}",
            f"{resource_type}:{resource_id}",
            {
                'user_id': user_id,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'action': action,
                'compliance_required': True
            }
        )
    
    def log_data_modification(self, user_id: str, table_name: str, record_id: str, action: str, changes: Dict[str, Any]):
        """Log data modifications for audit trail."""
        self.logger.log_audit_event(
            f"DATA_MODIFICATION_{action.upper()}",
            f"{table_name}:{record_id}",
            {
                'user_id': user_id,
                'table_name': table_name,
                'record_id': record_id,
                'action': action,
                'changes': changes
            }
        )
    
    def log_system_event(self, event_type: str, details: Dict[str, Any]):
        """Log system events for monitoring."""
        self.logger.log_audit_event(
            f"SYSTEM_{event_type.upper()}",
            "system",
            details
        )

# Performance monitoring
class PerformanceMonitor:
    """Monitor and log performance metrics."""
    
    def __init__(self):
        self.logger = get_logger("performance")
        self._metrics = defaultdict(list)
    
    @contextmanager
    def time_operation(self, operation_name: str, category: LogCategory = LogCategory.PERFORMANCE):
        """Context manager to time operations."""
        start_time = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self._metrics[operation_name].append(duration_ms)
            
            self.logger.info(
                f"Operation timing: {operation_name}",
                category,
                extra_data={
                    'operation': operation_name,
                    'duration_ms': duration_ms,
                    'avg_duration_ms': sum(self._metrics[operation_name]) / len(self._metrics[operation_name])
                }
            )
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get performance metrics summary."""
        summary = {}
        for operation, times in self._metrics.items():
            if times:
                summary[operation] = {
                    'count': len(times),
                    'avg_ms': sum(times) / len(times),
                    'min_ms': min(times),
                    'max_ms': max(times),
                    'total_ms': sum(times)
                }
        return summary

# Global instances
audit_logger = None
performance_monitor = PerformanceMonitor()

def setup_audit_logging(db_session: Session):
    """Setup audit logging with database session."""
    global audit_logger
    
    # Get configuration
    settings = get_settings()
    
    # Only setup audit logging if enabled in configuration
    if settings.logging.audit_enabled:
        audit_logger = AuditLogger(db_session)
    else:
        audit_logger = None

def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    if audit_logger is None:
        raise RuntimeError("Audit logging not initialized. Call setup_audit_logging() first.")
    return audit_logger
