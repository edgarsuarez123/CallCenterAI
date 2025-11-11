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
from .exceptions import (
    CallCenterAIException,
    ErrorCode,
    ExceptionMapper,
    DatabaseError,
    ValidationError,
    ConnectionError,
    AuthenticationFailedError,
    AuthorizationDeniedError,
    RateLimitExceededError,
    ExternalServiceUnavailableError,
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
                error_code=ErrorCode.RESOURCE_NOT_FOUND,
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
                error_code=ErrorCode.VALIDATION_ERROR,
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
        
        # Issue 7.2: Create a generic CallCenterAI exception with user-friendly message
        generic_exc = CallCenterAIException(
            message=f"Internal server error: {type(exc).__name__}",
            error_code=ErrorCode.DATABASE_ERROR,
            http_status=500,
            user_message="We're experiencing technical difficulties. Please try again in a few moments. If the problem persists, please contact support.",
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
