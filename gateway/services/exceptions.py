"""
Custom Exception Hierarchy for CallCenterAI

This module provides a comprehensive exception system that:
- Translates generic database errors into user-friendly messages
- Provides machine-readable error codes for API consumers
- Ensures consistent error responses across the API
- Maps exceptions to appropriate HTTP status codes
- Includes contextual information for debugging
- Prevents security information leakage
- Enables monitoring and alerting on specific error types
"""

from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime, timezone
import traceback


class ErrorCode(Enum):
    """Machine-readable error codes for API consumers."""
    
    # Appointment-related errors
    SLOT_UNAVAILABLE = "slot_unavailable"
    APPOINTMENT_NOT_FOUND = "appointment_not_found"
    APPOINTMENT_ALREADY_EXISTS = "appointment_already_exists"
    INVALID_APPOINTMENT_TIME = "invalid_appointment_time"
    APPOINTMENT_CANCELLATION_FAILED = "appointment_cancellation_failed"
    
    # Patient-related errors
    PATIENT_NOT_FOUND = "patient_not_found"
    PATIENT_ALREADY_EXISTS = "patient_already_exists"
    INVALID_PATIENT_DATA = "invalid_patient_data"
    PATIENT_DELETION_FAILED = "patient_deletion_failed"
    
    # Provider-related errors
    PROVIDER_NOT_FOUND = "provider_not_found"
    PROVIDER_ALREADY_EXISTS = "provider_already_exists"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_PROVIDER_DATA = "invalid_provider_data"
    
    # Clinic-related errors
    CLINIC_NOT_FOUND = "clinic_not_found"
    CLINIC_ALREADY_EXISTS = "clinic_already_exists"
    CLINIC_LICENSE_SUSPENDED = "clinic_license_suspended"
    CLINIC_LICENSE_EXPIRED = "clinic_license_expired"
    INVALID_CLINIC_DATA = "invalid_clinic_data"
    
    # Call-related errors
    CALL_NOT_FOUND = "call_not_found"
    CALL_ALREADY_EXISTS = "call_already_exists"
    INVALID_CALL_STATUS = "invalid_call_status"
    CALL_ROUTING_FAILED = "call_routing_failed"
    CALL_CAPACITY_EXCEEDED = "call_capacity_exceeded"
    
    # Authentication and authorization errors
    AUTHENTICATION_FAILED = "authentication_failed"
    AUTHORIZATION_DENIED = "authorization_denied"
    INVALID_TOKEN = "invalid_token"
    TOKEN_EXPIRED = "token_expired"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    
    # Database and system errors
    DATABASE_ERROR = "database_error"
    CONNECTION_ERROR = "connection_error"
    VALIDATION_ERROR = "validation_error"
    CONCURRENCY_ERROR = "concurrency_error"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    RESOURCE_NOT_FOUND = "resource_not_found"
    
    # External service errors
    GOOGLE_CALENDAR_ERROR = "google_calendar_error"
    AZURE_COMMUNICATION_ERROR = "azure_communication_error"
    EXTERNAL_SERVICE_UNAVAILABLE = "external_service_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"
    
    # Business logic errors
    BUSINESS_RULE_VIOLATION = "business_rule_violation"
    OPERATION_NOT_ALLOWED = "operation_not_allowed"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    MAINTENANCE_MODE = "maintenance_mode"


class CallCenterAIException(Exception):
    """
    Base exception class for all CallCenterAI exceptions.
    
    Provides:
    - User-friendly error messages
    - Machine-readable error codes
    - Contextual information for debugging
    - Proper HTTP status code mapping
    - Security-conscious error handling
    """
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        http_status: int = 500,
        details: Optional[Dict[str, Any]] = None,
        user_message: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status
        self.details = details or {}
        self.user_message = user_message or message
        self.context = context or {}
        self.original_exception = original_exception
        self.timestamp = datetime.now(timezone.utc)
        self.traceback = traceback.format_exc() if original_exception else None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error_code": self.error_code.value,
            "message": self.user_message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context
        }
    
    def to_log_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging (includes sensitive details)."""
        log_dict = self.to_dict()
        log_dict.update({
            "technical_message": str(self),
            "traceback": self.traceback,
            "original_exception": str(self.original_exception) if self.original_exception else None
        })
        return log_dict


# Appointment-related exceptions
class SlotUnavailableError(CallCenterAIException):
    """Raised when an appointment slot is not available."""
    
    def __init__(self, slot_id: str, clinic_id: str, reason: str = "Slot is already booked"):
        super().__init__(
            message=f"Appointment slot {slot_id} is not available",
            error_code=ErrorCode.SLOT_UNAVAILABLE,
            http_status=409,
            details={"slot_id": slot_id, "clinic_id": clinic_id, "reason": reason},
            user_message="This time slot is already booked. Please select another time.",
            context={"slot_id": slot_id, "clinic_id": clinic_id}
        )


class AppointmentNotFoundError(CallCenterAIException):
    """Raised when an appointment cannot be found."""
    
    def __init__(self, appointment_id: str):
        super().__init__(
            message=f"Appointment {appointment_id} not found",
            error_code=ErrorCode.APPOINTMENT_NOT_FOUND,
            http_status=404,
            details={"appointment_id": appointment_id},
            user_message="The requested appointment could not be found.",
            context={"appointment_id": appointment_id}
        )


class AppointmentAlreadyExistsError(CallCenterAIException):
    """Raised when trying to create a duplicate appointment."""
    
    def __init__(self, patient_id: str, slot_id: str):
        super().__init__(
            message=f"Appointment already exists for patient {patient_id} and slot {slot_id}",
            error_code=ErrorCode.APPOINTMENT_ALREADY_EXISTS,
            http_status=409,
            details={"patient_id": patient_id, "slot_id": slot_id},
            user_message="An appointment already exists for this patient and time slot.",
            context={"patient_id": patient_id, "slot_id": slot_id}
        )


class InvalidAppointmentTimeError(CallCenterAIException):
    """Raised when appointment time is invalid."""
    
    def __init__(self, start_time: str, end_time: str, reason: str):
        super().__init__(
            message=f"Invalid appointment time: {start_time} to {end_time} - {reason}",
            error_code=ErrorCode.INVALID_APPOINTMENT_TIME,
            http_status=400,
            details={"start_time": start_time, "end_time": end_time, "reason": reason},
            user_message="The appointment time is invalid. Please check the start and end times.",
            context={"start_time": start_time, "end_time": end_time}
        )


# Patient-related exceptions
class PatientNotFoundError(CallCenterAIException):
    """Raised when a patient cannot be found."""
    
    def __init__(self, patient_id: str):
        super().__init__(
            message=f"Patient {patient_id} not found",
            error_code=ErrorCode.PATIENT_NOT_FOUND,
            http_status=404,
            details={"patient_id": patient_id},
            user_message="The requested patient could not be found.",
            context={"patient_id": patient_id}
        )


class PatientAlreadyExistsError(CallCenterAIException):
    """Raised when trying to create a duplicate patient."""
    
    def __init__(self, email: str, phone: str):
        super().__init__(
            message=f"Patient already exists with email {email} or phone {phone}",
            error_code=ErrorCode.PATIENT_ALREADY_EXISTS,
            http_status=409,
            details={"email": email, "phone": phone},
            user_message="A patient with this email or phone number already exists.",
            context={"email": email, "phone": phone}
        )


class InvalidPatientDataError(CallCenterAIException):
    """Raised when patient data is invalid."""
    
    def __init__(self, field: str, value: Any, reason: str):
        super().__init__(
            message=f"Invalid patient data: {field} = {value} - {reason}",
            error_code=ErrorCode.INVALID_PATIENT_DATA,
            http_status=400,
            details={"field": field, "value": str(value), "reason": reason},
            user_message=f"The {field} field is invalid. {reason}",
            context={"field": field, "value": str(value)}
        )


# Provider-related exceptions
class ProviderNotFoundError(CallCenterAIException):
    """Raised when a provider cannot be found."""
    
    def __init__(self, provider_id: str):
        super().__init__(
            message=f"Provider {provider_id} not found",
            error_code=ErrorCode.PROVIDER_NOT_FOUND,
            http_status=404,
            details={"provider_id": provider_id},
            user_message="The requested provider could not be found.",
            context={"provider_id": provider_id}
        )


class ProviderUnavailableError(CallCenterAIException):
    """Raised when a provider is not available."""
    
    def __init__(self, provider_id: str, reason: str):
        super().__init__(
            message=f"Provider {provider_id} is unavailable: {reason}",
            error_code=ErrorCode.PROVIDER_UNAVAILABLE,
            http_status=409,
            details={"provider_id": provider_id, "reason": reason},
            user_message="The requested provider is not available at this time.",
            context={"provider_id": provider_id}
        )


# Clinic-related exceptions
class ClinicNotFoundError(CallCenterAIException):
    """Raised when a clinic cannot be found."""
    
    def __init__(self, clinic_id: str):
        super().__init__(
            message=f"Clinic {clinic_id} not found",
            error_code=ErrorCode.CLINIC_NOT_FOUND,
            http_status=404,
            details={"clinic_id": clinic_id},
            user_message="The requested clinic could not be found.",
            context={"clinic_id": clinic_id}
        )


class ClinicLicenseSuspendedError(CallCenterAIException):
    """Raised when a clinic's license is suspended."""
    
    def __init__(self, clinic_id: str, reason: str):
        super().__init__(
            message=f"Clinic {clinic_id} license suspended: {reason}",
            error_code=ErrorCode.CLINIC_LICENSE_SUSPENDED,
            http_status=403,
            details={"clinic_id": clinic_id, "reason": reason},
            user_message="This clinic's license has been suspended. Please contact support.",
            context={"clinic_id": clinic_id}
        )


class ClinicLicenseExpiredError(CallCenterAIException):
    """Raised when a clinic's license has expired."""
    
    def __init__(self, clinic_id: str, expiry_date: str):
        super().__init__(
            message=f"Clinic {clinic_id} license expired on {expiry_date}",
            error_code=ErrorCode.CLINIC_LICENSE_EXPIRED,
            http_status=403,
            details={"clinic_id": clinic_id, "expiry_date": expiry_date},
            user_message="This clinic's license has expired. Please renew your license.",
            context={"clinic_id": clinic_id}
        )


# Call-related exceptions
class CallNotFoundError(CallCenterAIException):
    """Raised when a call cannot be found."""
    
    def __init__(self, call_id: str):
        super().__init__(
            message=f"Call {call_id} not found",
            error_code=ErrorCode.CALL_NOT_FOUND,
            http_status=404,
            details={"call_id": call_id},
            user_message="The requested call could not be found.",
            context={"call_id": call_id}
        )


class CallOrchestrationError(CallCenterAIException):
    """Raised when call orchestration fails."""
    
    def __init__(self, error_type: str, reason: str, call_id: Optional[str] = None):
        super().__init__(
            message=f"Call orchestration error ({error_type}): {reason}",
            error_code=ErrorCode.CALL_ROUTING_FAILED,
            http_status=500,
            details={"error_type": error_type, "reason": reason, "call_id": call_id},
            user_message="Call processing failed. Please try again.",
            context={"error_type": error_type, "call_id": call_id}
        )


class InvalidCallStatusError(CallCenterAIException):
    """Raised when call status is invalid."""
    
    def __init__(self, call_id: str, current_status: str, attempted_status: str):
        super().__init__(
            message=f"Invalid call status transition: {current_status} -> {attempted_status}",
            error_code=ErrorCode.INVALID_CALL_STATUS,
            http_status=400,
            details={"call_id": call_id, "current_status": current_status, "attempted_status": attempted_status},
            user_message="The call status cannot be changed in this way.",
            context={"call_id": call_id, "current_status": current_status}
        )


class CallRoutingError(CallCenterAIException):
    """Raised when call routing fails."""
    
    def __init__(self, routing_type: str, reason: str = "Call routing failed"):
        super().__init__(
            message=f"Call routing failed: {reason}",
            error_code=ErrorCode.CALL_ROUTING_FAILED,
            http_status=500,
            details={"routing_type": routing_type, "reason": reason},
            user_message="Unable to route call. Please try again.",
            context={"routing_type": routing_type}
        )


class CallCapacityExceededError(CallCenterAIException):
    """Raised when clinic call capacity is exceeded."""
    
    def __init__(self, clinic_id: str, current_calls: int, max_calls: int):
        super().__init__(
            message=f"Clinic {clinic_id} call capacity exceeded: {current_calls}/{max_calls}",
            error_code=ErrorCode.CALL_CAPACITY_EXCEEDED,
            http_status=503,
            details={"clinic_id": clinic_id, "current_calls": current_calls, "max_calls": max_calls},
            user_message="All lines are currently busy. Please try again later.",
            context={"clinic_id": clinic_id}
        )


class CapacityExceededError(CallCenterAIException):
    """Raised when resource capacity is exceeded."""
    
    def __init__(self, resource_type: str, reason: str = "Capacity exceeded"):
        super().__init__(
            message=f"{resource_type} capacity exceeded: {reason}",
            error_code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
            http_status=503,
            details={"resource_type": resource_type, "reason": reason},
            user_message="Service is currently at capacity. Please try again later.",
            context={"resource_type": resource_type}
        )


# Authentication and authorization exceptions
class AuthenticationFailedError(CallCenterAIException):
    """Raised when authentication fails."""
    
    def __init__(self, reason: str = "Invalid credentials"):
        super().__init__(
            message=f"Authentication failed: {reason}",
            error_code=ErrorCode.AUTHENTICATION_FAILED,
            http_status=401,
            details={"reason": reason},
            user_message="Authentication failed. Please check your credentials.",
            context={"reason": reason}
        )


class AuthorizationDeniedError(CallCenterAIException):
    """Raised when authorization is denied."""
    
    def __init__(self, resource: str, action: str, reason: str = "Insufficient permissions"):
        super().__init__(
            message=f"Authorization denied for {action} on {resource}: {reason}",
            error_code=ErrorCode.AUTHORIZATION_DENIED,
            http_status=403,
            details={"resource": resource, "action": action, "reason": reason},
            user_message="You don't have permission to perform this action.",
            context={"resource": resource, "action": action}
        )


class InvalidTokenError(CallCenterAIException):
    """Raised when a token is invalid."""
    
    def __init__(self, reason: str = "Invalid token format"):
        super().__init__(
            message=f"Invalid token: {reason}",
            error_code=ErrorCode.INVALID_TOKEN,
            http_status=401,
            details={"reason": reason},
            user_message="The provided token is invalid.",
            context={"reason": reason}
        )


class TokenExpiredError(CallCenterAIException):
    """Raised when a token has expired."""
    
    def __init__(self, expiry_time: str):
        super().__init__(
            message=f"Token expired at {expiry_time}",
            error_code=ErrorCode.TOKEN_EXPIRED,
            http_status=401,
            details={"expiry_time": expiry_time},
            user_message="Your session has expired. Please log in again.",
            context={"expiry_time": expiry_time}
        )


# Database and system exceptions
class DatabaseError(CallCenterAIException):
    """Raised when a database operation fails."""
    
    def __init__(self, operation: str, reason: str, original_exception: Optional[Exception] = None):
        super().__init__(
            message=f"Database operation failed: {operation} - {reason}",
            error_code=ErrorCode.DATABASE_ERROR,
            http_status=500,
            details={"operation": operation, "reason": reason},
            user_message="A database error occurred. Please try again later.",
            context={"operation": operation},
            original_exception=original_exception
        )


class ConnectionError(CallCenterAIException):
    """Raised when a database connection fails."""
    
    def __init__(self, service: str, reason: str):
        super().__init__(
            message=f"Connection to {service} failed: {reason}",
            error_code=ErrorCode.CONNECTION_ERROR,
            http_status=503,
            details={"service": service, "reason": reason},
            user_message="Unable to connect to the service. Please try again later.",
            context={"service": service}
        )


class ValidationError(CallCenterAIException):
    """Raised when data validation fails."""
    
    def __init__(self, field: str, value: Any, reason: str):
        super().__init__(
            message=f"Validation failed for {field}: {value} - {reason}",
            error_code=ErrorCode.VALIDATION_ERROR,
            http_status=400,
            details={"field": field, "value": str(value), "reason": reason},
            user_message=f"The {field} field is invalid. {reason}",
            context={"field": field, "value": str(value)}
        )


class ConcurrencyError(CallCenterAIException):
    """Raised when a concurrency conflict occurs."""
    
    def __init__(self, resource: str, reason: str):
        super().__init__(
            message=f"Concurrency conflict on {resource}: {reason}",
            error_code=ErrorCode.CONCURRENCY_ERROR,
            http_status=409,
            details={"resource": resource, "reason": reason},
            user_message="The resource was modified by another user. Please refresh and try again.",
            context={"resource": resource}
        )


class RateLimitExceededError(CallCenterAIException):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, limit: int, window: str, retry_after: int):
        super().__init__(
            message=f"Rate limit exceeded: {limit} requests per {window}",
            error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
            http_status=429,
            details={"limit": limit, "window": window, "retry_after": retry_after},
            user_message="Too many requests. Please wait before trying again.",
            context={"limit": limit, "window": window, "retry_after": retry_after}
        )


# External service exceptions
class GoogleCalendarError(CallCenterAIException):
    """Raised when Google Calendar integration fails."""
    
    def __init__(self, operation: str, reason: str, original_exception: Optional[Exception] = None):
        super().__init__(
            message=f"Google Calendar operation failed: {operation} - {reason}",
            error_code=ErrorCode.GOOGLE_CALENDAR_ERROR,
            http_status=502,
            details={"operation": operation, "reason": reason},
            user_message="Calendar integration is temporarily unavailable. Please try again later.",
            context={"operation": operation},
            original_exception=original_exception
        )


class AzureCommunicationError(CallCenterAIException):
    """Raised when Azure Communication Services fails."""
    
    def __init__(self, operation: str, reason: str, original_exception: Optional[Exception] = None):
        super().__init__(
            message=f"Azure Communication operation failed: {operation} - {reason}",
            error_code=ErrorCode.AZURE_COMMUNICATION_ERROR,
            http_status=502,
            details={"operation": operation, "reason": reason},
            user_message="Communication service is temporarily unavailable. Please try again later.",
            context={"operation": operation},
            original_exception=original_exception
        )


class ExternalServiceUnavailableError(CallCenterAIException):
    """Raised when an external service is unavailable."""
    
    def __init__(self, service: str, reason: str):
        super().__init__(
            message=f"External service {service} unavailable: {reason}",
            error_code=ErrorCode.EXTERNAL_SERVICE_UNAVAILABLE,
            http_status=503,
            details={"service": service, "reason": reason},
            user_message="An external service is temporarily unavailable. Please try again later.",
            context={"service": service}
        )


class ServiceUnavailableError(CallCenterAIException):
    """Raised when a service is unavailable."""
    
    def __init__(self, message: str = "Service is temporarily unavailable"):
        super().__init__(
            message=message,
            error_code=ErrorCode.SERVICE_UNAVAILABLE,
            http_status=503,
            details={"service": "internal"},
            user_message="The service is temporarily unavailable. Please try again later.",
            context={"service": "internal"}
        )


# Business logic exceptions
class BusinessRuleViolationError(CallCenterAIException):
    """Raised when a business rule is violated."""
    
    def __init__(self, rule: str, reason: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Business rule violation: {rule} - {reason}",
            error_code=ErrorCode.BUSINESS_RULE_VIOLATION,
            http_status=400,
            details={"rule": rule, "reason": reason},
            user_message=f"Business rule violation: {reason}",
            context=context or {}
        )


class OperationNotAllowedError(CallCenterAIException):
    """Raised when an operation is not allowed."""
    
    def __init__(self, operation: str, reason: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=f"Operation not allowed: {operation} - {reason}",
            error_code=ErrorCode.OPERATION_NOT_ALLOWED,
            http_status=403,
            details={"operation": operation, "reason": reason},
            user_message=f"This operation is not allowed: {reason}",
            context=context or {}
        )


class ResourceLimitExceededError(CallCenterAIException):
    """Raised when a resource limit is exceeded."""
    
    def __init__(self, resource: str, limit: int, current: int):
        super().__init__(
            message=f"Resource limit exceeded: {resource} (limit: {limit}, current: {current})",
            error_code=ErrorCode.RESOURCE_LIMIT_EXCEEDED,
            http_status=429,
            details={"resource": resource, "limit": limit, "current": current},
            user_message=f"The {resource} limit has been exceeded. Please contact support.",
            context={"resource": resource, "limit": limit, "current": current}
        )


class MaintenanceModeError(CallCenterAIException):
    """Raised when the system is in maintenance mode."""
    
    def __init__(self, maintenance_window: str, reason: str):
        super().__init__(
            message=f"System in maintenance mode: {maintenance_window} - {reason}",
            error_code=ErrorCode.MAINTENANCE_MODE,
            http_status=503,
            details={"maintenance_window": maintenance_window, "reason": reason},
            user_message="The system is currently under maintenance. Please try again later.",
            context={"maintenance_window": maintenance_window}
        )


# Exception mapping utilities
class ExceptionMapper:
    """Maps generic exceptions to CallCenterAI exceptions."""
    
    @staticmethod
    def map_database_exception(exception: Exception, operation: str) -> CallCenterAIException:
        """Map generic database exceptions to CallCenterAI exceptions."""
        if "unique constraint" in str(exception).lower():
            if "appointment" in str(exception).lower():
                return AppointmentAlreadyExistsError("unknown", "unknown")
            elif "patient" in str(exception).lower():
                return PatientAlreadyExistsError("unknown", "unknown")
            elif "provider" in str(exception).lower():
                return BusinessRuleViolationError("unique_constraint", f"Provider already exists: {str(exception)}")
            elif "clinic" in str(exception).lower():
                return BusinessRuleViolationError("unique_constraint", f"Clinic already exists: {str(exception)}")
            else:
                return BusinessRuleViolationError("unique_constraint", str(exception))
        
        elif "foreign key constraint" in str(exception).lower():
            return BusinessRuleViolationError("foreign_key_constraint", str(exception))
        
        elif "check constraint" in str(exception).lower():
            return ValidationError("constraint", "unknown", str(exception))
        
        elif "deadlock" in str(exception).lower():
            return ConcurrencyError("database", "deadlock detected")
        
        elif "connection" in str(exception).lower():
            return ConnectionError("database", str(exception))
        
        else:
            return DatabaseError(operation, str(exception), exception)
    
    @staticmethod
    def map_validation_exception(exception: Exception, field: str = "unknown") -> CallCenterAIException:
        """Map validation exceptions to CallCenterAI exceptions."""
        if "required" in str(exception).lower():
            return ValidationError(field, "missing", "This field is required")
        elif "invalid" in str(exception).lower():
            return ValidationError(field, "invalid", str(exception))
        elif "format" in str(exception).lower():
            return ValidationError(field, "format", "Invalid format")
        else:
            return ValidationError(field, "unknown", str(exception))
    
    @staticmethod
    def map_external_service_exception(exception: Exception, service: str, operation: str) -> CallCenterAIException:
        """Map external service exceptions to CallCenterAI exceptions."""
        if "google" in service.lower() or "calendar" in service.lower():
            return GoogleCalendarError(operation, str(exception), exception)
        elif "azure" in service.lower() or "communication" in service.lower():
            return AzureCommunicationError(operation, str(exception), exception)
        else:
            return ExternalServiceUnavailableError(service, str(exception))


# Exception handling decorators
def handle_exceptions(func):
    """Decorator to handle exceptions and convert them to CallCenterAI exceptions."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except CallCenterAIException:
            # Re-raise CallCenterAI exceptions as-is
            raise
        except Exception as e:
            # Map generic exceptions to CallCenterAI exceptions
            if "database" in str(e).lower() or "sql" in str(e).lower():
                raise ExceptionMapper.map_database_exception(e, func.__name__)
            elif "validation" in str(e).lower():
                raise ExceptionMapper.map_validation_exception(e)
            else:
                raise DatabaseError(func.__name__, str(e), e)
    return wrapper


def handle_external_service_exceptions(service: str):
    """Decorator to handle external service exceptions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except CallCenterAIException:
                raise
            except Exception as e:
                raise ExceptionMapper.map_external_service_exception(e, service, func.__name__)
        return wrapper
    return decorator
