"""
Exception Handler Middleware for CallCenterAI

This module provides centralized exception handling for the FastAPI application,
ensuring consistent error responses and proper logging of exceptions.
"""

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
from typing import Union
import traceback
import logging

from .exceptions import (
    CallCenterAIException,
    ExceptionMapper,
    DatabaseError,
    ValidationError,
    ConnectionError,
    ConcurrencyError,
    AuthenticationFailedError,
    AuthorizationDeniedError,
    InvalidTokenError,
    TokenExpiredError,
    RateLimitExceededError,
    GoogleCalendarError,
    AzureCommunicationError,
    ExternalServiceUnavailableError,
    BusinessRuleViolationError,
    OperationNotAllowedError,
    ResourceLimitExceededError,
    MaintenanceModeError
)
from .structured_logging import get_logger, LogCategory


logger = get_logger("exception_handler")


class ExceptionHandler:
    """Centralized exception handler for the CallCenterAI application."""
    
    def __init__(self):
        self.logger = logger
    
    def handle_callcenter_exception(self, request: Request, exc: CallCenterAIException) -> JSONResponse:
        """Handle CallCenterAI exceptions."""
        # Log the exception with full context
        self.logger.error(
            f"CallCenterAI exception: {exc.error_code.value}",
            LogCategory.ERROR,
            exception=exc,
            extra_data={
                'error_code': exc.error_code.value,
                'http_status': exc.http_status,
                'details': exc.details,
                'context': exc.context,
                'method': request.method,
                'path': request.url.path,
                'client_ip': request.client.host if request.client else None,
                'user_agent': request.headers.get("User-Agent")
            }
        )
        
        # Return user-friendly error response
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict()
        )
    
    def handle_http_exception(self, request: Request, exc: Union[HTTPException, StarletteHTTPException]) -> JSONResponse:
        """Handle HTTP exceptions."""
        # Map HTTP exceptions to CallCenterAI exceptions when possible
        if exc.status_code == 401:
            callcenter_exc = AuthenticationFailedError("Invalid or missing authentication")
        elif exc.status_code == 403:
            callcenter_exc = AuthorizationDeniedError("resource", "access", "Insufficient permissions")
        elif exc.status_code == 404:
            callcenter_exc = CallCenterAIException(
                message=str(exc.detail),
                error_code=CallCenterAIException.error_code,
                http_status=404,
                user_message="The requested resource could not be found."
            )
        elif exc.status_code == 429:
            callcenter_exc = RateLimitExceededError(100, "minute", 60)
        elif exc.status_code == 503:
            callcenter_exc = MaintenanceModeError("unknown", "Service temporarily unavailable")
        else:
            callcenter_exc = CallCenterAIException(
                message=str(exc.detail),
                error_code=CallCenterAIException.error_code,
                http_status=exc.status_code,
                user_message=str(exc.detail)
            )
        
        return self.handle_callcenter_exception(request, callcenter_exc)
    
    def handle_validation_error(self, request: Request, exc: RequestValidationError) -> JSONResponse:
        """Handle request validation errors."""
        # Extract validation errors
        errors = []
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            errors.append(f"{field}: {message}")
        
        validation_exc = ValidationError(
            field="request",
            value="request_data",
            reason="; ".join(errors)
        )
        
        return self.handle_callcenter_exception(request, validation_exc)
    
    def handle_sqlalchemy_error(self, request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Handle SQLAlchemy database errors."""
        # Map SQLAlchemy errors to CallCenterAI exceptions
        if isinstance(exc, IntegrityError):
            callcenter_exc = ExceptionMapper.map_database_exception(exc, "database_operation")
        elif isinstance(exc, OperationalError):
            callcenter_exc = ConnectionError("database", str(exc))
        else:
            callcenter_exc = DatabaseError("database_operation", str(exc), exc)
        
        return self.handle_callcenter_exception(request, callcenter_exc)
    
    def handle_generic_exception(self, request: Request, exc: Exception) -> JSONResponse:
        """Handle generic exceptions."""
        # Log the full exception with traceback
        self.logger.error(
            f"Unhandled exception: {type(exc).__name__}",
            LogCategory.ERROR,
            exception=exc,
            extra_data={
                'exception_type': type(exc).__name__,
                'method': request.method,
                'path': request.url.path,
                'client_ip': request.client.host if request.client else None,
                'user_agent': request.headers.get("User-Agent"),
                'traceback': traceback.format_exc()
            }
        )
        
        # Create a generic CallCenterAI exception
        generic_exc = CallCenterAIException(
            message=f"Internal server error: {type(exc).__name__}",
            error_code=CallCenterAIException.error_code,
            http_status=500,
            user_message="An unexpected error occurred. Please try again later.",
            original_exception=exc
        )
        
        return self.handle_callcenter_exception(request, generic_exc)


# Global exception handler instance
exception_handler = ExceptionHandler()


def register_exception_handlers(app):
    """Register all exception handlers with the FastAPI app."""
    
    @app.exception_handler(CallCenterAIException)
    async def callcenter_exception_handler(request: Request, exc: CallCenterAIException):
        return exception_handler.handle_callcenter_exception(request, exc)
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return exception_handler.handle_http_exception(request, exc)
    
    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        return exception_handler.handle_http_exception(request, exc)
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return exception_handler.handle_validation_error(request, exc)
    
    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        return exception_handler.handle_sqlalchemy_error(request, exc)
    
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return exception_handler.handle_generic_exception(request, exc)


# Exception handling decorators for route handlers
def handle_route_exceptions(func):
    """Decorator to handle exceptions in route handlers."""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except CallCenterAIException:
            # Re-raise CallCenterAI exceptions as-is
            raise
        except SQLAlchemyError as e:
            # Map SQLAlchemy errors to CallCenterAI exceptions
            raise ExceptionMapper.map_database_exception(e, func.__name__)
        except Exception as e:
            # Map generic exceptions to CallCenterAI exceptions
            if "validation" in str(e).lower():
                raise ExceptionMapper.map_validation_exception(e)
            else:
                raise DatabaseError(func.__name__, str(e), e)
    return wrapper


def handle_external_service_exceptions(service: str):
    """Decorator to handle external service exceptions in route handlers."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except CallCenterAIException:
                raise
            except Exception as e:
                raise ExceptionMapper.map_external_service_exception(e, service, func.__name__)
        return wrapper
    return decorator


# Utility functions for common exception scenarios
def raise_slot_unavailable(slot_id: str, clinic_id: str, reason: str = "Slot is already booked"):
    """Raise a slot unavailable exception."""
    from .exceptions import SlotUnavailableError
    raise SlotUnavailableError(slot_id, clinic_id, reason)


def raise_appointment_not_found(appointment_id: str):
    """Raise an appointment not found exception."""
    from .exceptions import AppointmentNotFoundError
    raise AppointmentNotFoundError(appointment_id)


def raise_patient_not_found(patient_id: str):
    """Raise a patient not found exception."""
    from .exceptions import PatientNotFoundError
    raise PatientNotFoundError(patient_id)


def raise_provider_not_found(provider_id: str):
    """Raise a provider not found exception."""
    from .exceptions import ProviderNotFoundError
    raise ProviderNotFoundError(provider_id)


def raise_clinic_not_found(clinic_id: str):
    """Raise a clinic not found exception."""
    from .exceptions import ClinicNotFoundError
    raise ClinicNotFoundError(clinic_id)


def raise_clinic_license_suspended(clinic_id: str, reason: str):
    """Raise a clinic license suspended exception."""
    from .exceptions import ClinicLicenseSuspendedError
    raise ClinicLicenseSuspendedError(clinic_id, reason)


def raise_clinic_license_expired(clinic_id: str, expiry_date: str):
    """Raise a clinic license expired exception."""
    from .exceptions import ClinicLicenseExpiredError
    raise ClinicLicenseExpiredError(clinic_id, expiry_date)


def raise_authentication_failed(reason: str = "Invalid credentials"):
    """Raise an authentication failed exception."""
    from .exceptions import AuthenticationFailedError
    raise AuthenticationFailedError(reason)


def raise_authorization_denied(resource: str, action: str, reason: str = "Insufficient permissions"):
    """Raise an authorization denied exception."""
    from .exceptions import AuthorizationDeniedError
    raise AuthorizationDeniedError(resource, action, reason)


def raise_validation_error(field: str, value: any, reason: str):
    """Raise a validation error exception."""
    from .exceptions import ValidationError
    raise ValidationError(field, value, reason)


def raise_business_rule_violation(rule: str, reason: str, context: dict = None):
    """Raise a business rule violation exception."""
    from .exceptions import BusinessRuleViolationError
    raise BusinessRuleViolationError(rule, reason, context)


def raise_concurrency_error(resource: str, reason: str):
    """Raise a concurrency error exception."""
    from .exceptions import ConcurrencyError
    raise ConcurrencyError(resource, reason)


def raise_rate_limit_exceeded(limit: int, window: str, retry_after: int):
    """Raise a rate limit exceeded exception."""
    from .exceptions import RateLimitExceededError
    raise RateLimitExceededError(limit, window, retry_after)


def raise_google_calendar_error(operation: str, reason: str, original_exception: Exception = None):
    """Raise a Google Calendar error exception."""
    from .exceptions import GoogleCalendarError
    raise GoogleCalendarError(operation, reason, original_exception)


def raise_azure_communication_error(operation: str, reason: str, original_exception: Exception = None):
    """Raise an Azure Communication error exception."""
    from .exceptions import AzureCommunicationError
    raise AzureCommunicationError(operation, reason, original_exception)


def raise_external_service_unavailable(service: str, reason: str):
    """Raise an external service unavailable exception."""
    from .exceptions import ExternalServiceUnavailableError
    raise ExternalServiceUnavailableError(service, reason)


def raise_maintenance_mode(maintenance_window: str, reason: str):
    """Raise a maintenance mode exception."""
    from .exceptions import MaintenanceModeError
    raise MaintenanceModeError(maintenance_window, reason)
