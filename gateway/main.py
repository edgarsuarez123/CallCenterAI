from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from services.database import Base, engine, get_database_health, test_database_connection, ConnectionPoolMonitor
from services.structured_logging import (
    get_logger, RequestContextManager, log_performance, 
    setup_audit_logging, get_audit_logger, log_database_queries,
    LogCategory
)
from services.background_jobs import start_background_jobs, stop_background_jobs
from services.configuration import get_settings, validate_configuration, validate_required_settings, ConfigurationError
from services.exception_handler import register_exception_handlers
from routes.tokens import router as tokens_router
from routes import api_router

# Get configuration
settings = get_settings()

# Configure structured logging
logger = get_logger("gateway")

app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.security.cors_origins,
    allow_credentials=True,
    allow_methods=settings.security.cors_methods,
    allow_headers=settings.security.cors_headers,
)

# Simple in-memory rate limiting
request_counts = defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple rate limiting middleware - 100 requests per minute per IP."""
    client_ip = request.client.host
    current_time = datetime.now(timezone.utc)
    
    # Clean old requests (older than 1 minute)
    request_counts[client_ip] = [
        req_time for req_time in request_counts[client_ip] 
        if current_time - req_time < timedelta(minutes=1)
    ]
    
    # Check if rate limit exceeded
    if len(request_counts[client_ip]) >= 100:
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 100 requests per minute."
        )
    
    # Add current request
    request_counts[client_ip].append(current_time)
    
    response = await call_next(request)
    return response

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Set request context for audit logging."""
    from services.auth_context import set_request_context
    import uuid
    
    request_id = str(uuid.uuid4())
    client_ip = request.client.host if request.client else "unknown"
    user_id = "anonymous"  # TODO: Extract from JWT token when auth is implemented
    
    set_request_context(user_id=user_id, ip_address=client_ip, request_id=request_id)
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# Add request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with performance metrics."""
    start_time = time.time()
    
    # Extract correlation ID from headers or generate one
    correlation_id = request.headers.get("X-Correlation-ID")
    user_id = request.headers.get("X-User-ID")
    clinic_id = request.headers.get("X-Clinic-ID")
    
    # Create request context
    with RequestContextManager(correlation_id, user_id, clinic_id):
        # Log request start
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            LogCategory.API,
            extra_data={
                'method': request.method,
                'path': request.url.path,
                'query_params': dict(request.query_params),
                'client_ip': request.client.host if request.client else None,
                'user_agent': request.headers.get("User-Agent")
            }
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log request completion
            logger.log_api_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                client_ip=request.client.host if request.client else None
            )
            
            # Add correlation ID to response headers
            from services.structured_logging import _request_context
            response.headers["X-Correlation-ID"] = correlation_id or getattr(_request_context, 'correlation_id', None)
            
            return response
            
        except Exception as e:
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log request error
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                LogCategory.API,
                exception=e,
                extra_data={
                    'method': request.method,
                    'path': request.url.path,
                    'duration_ms': duration_ms,
                    'client_ip': request.client.host if request.client else None
                }
            )
            raise

@app.on_event("startup")
def on_startup():
    """Application startup - database migrations should be run separately."""
    # Database schema is now managed by Alembic migrations
    # Run migrations with: alembic upgrade head
    
    try:
        # Validate critical configuration first
        validate_required_settings(settings)
        logger.info("Critical configuration validation passed")
    except ConfigurationError as e:
        logger.error(f"Configuration validation failed: {e}")
        raise
    
    # Validate configuration
    validation_results = validate_configuration()
    if not validation_results["valid"]:
        logger.error("Configuration validation failed", LogCategory.SYSTEM, extra_data=validation_results)
        raise RuntimeError(f"Configuration validation failed: {validation_results['errors']}")
    
    if validation_results["warnings"]:
        logger.warning("Configuration validation warnings", LogCategory.SYSTEM, extra_data=validation_results)
    
    # Setup structured logging
    logger.info("Starting CallCenterAI Gateway", LogCategory.SYSTEM, extra_data={
        "environment": settings.environment,
        "debug": settings.debug,
        "api_version": settings.api_version,
        "database_host": settings.database.host,
        "database_port": settings.database.port,
        "pool_size": settings.database.pool_size
    })
    
    # Log expected callback URLs for deployment verification
    logger.info("Expected callback URLs for deployment", LogCategory.SYSTEM, extra_data={
        "acs_callback_url": settings.azure.communication.callback_url,
        "google_redirect_uri": settings.google_calendar.redirect_uri,
        "api_base_url": f"http://{settings.host}:{settings.port}{settings.api_prefix}",
        "health_check_url": f"http://{settings.host}:{settings.port}/healthz"
    })
    
    # Setup database query logging
    log_database_queries(engine)
    
    # Setup audit logging (will be initialized when database session is available)
    logger.info("Structured logging initialized", LogCategory.SYSTEM)
    
    # Start background jobs
    start_background_jobs()
    logger.info("Background job manager started", LogCategory.SYSTEM)

@app.on_event("shutdown")
async def on_shutdown():
    """Application shutdown - cleanup resources."""
    logger.info("Shutting down CallCenterAI Gateway", LogCategory.SYSTEM)
    
    # Stop background jobs
    stop_background_jobs()
    logger.info("Background job manager stopped", LogCategory.SYSTEM)
    
    # Close Redis connection pool
    try:
        from services.response_cache import get_response_cache_service
        response_cache = get_response_cache_service()
        await response_cache.close()
        logger.info("Redis connection pool closed", LogCategory.SYSTEM)
    except Exception as e:
        logger.error(f"Error closing Redis connection pool: {e}", LogCategory.SYSTEM, exception=e)
    
    # Close ACS HTTP client
    try:
        from services.azure_communication_service import get_azure_communication_service
        acs_service = get_azure_communication_service()
        await acs_service.close()
        logger.info("ACS HTTP client closed", LogCategory.SYSTEM)
    except Exception as e:
        logger.error(f"Error closing ACS HTTP client: {e}", LogCategory.SYSTEM, exception=e)
    
    # Close audio stream handler
    try:
        from services.audio_stream_handler import get_audio_stream_handler
        audio_handler = get_audio_stream_handler()
        await audio_handler.stop()
        logger.info("Audio stream handler stopped", LogCategory.SYSTEM)
    except Exception as e:
        logger.error(f"Error stopping audio handler: {e}", LogCategory.SYSTEM, exception=e)

@app.get("/healthz")
def healthz():
    """Basic health check endpoint."""
    logger.debug("Health check requested", LogCategory.SYSTEM)
    return {
        "ok": True, 
        "service": "gateway",
        "version": settings.api_version,
        "environment": settings.environment,
        "status": "healthy"
    }

@app.get("/health/database")
def database_health():
    """Comprehensive database health check including connection pool status."""
    try:
        logger.debug("Database health check requested", LogCategory.SYSTEM)
        
        health_info = get_database_health()
        
        # Determine overall health status
        if health_info["database_connection"] == "healthy" and health_info["connection_pool"] == "healthy":
            logger.info("Database health check completed successfully", LogCategory.DATABASE, extra_data=health_info)
            status_code = 200
        else:
            logger.warning("Database health check found issues", LogCategory.DATABASE, extra_data=health_info)
            status_code = 503  # Service Unavailable
        
        return health_info
    except Exception as e:
        logger.error("Database health check failed", LogCategory.DATABASE, exception=e)
        raise HTTPException(status_code=503, detail=f"Database health check failed: {str(e)}")

@app.get("/health/pool")
def pool_health():
    """Connection pool specific health check."""
    try:
        logger.debug("Pool health check requested", LogCategory.SYSTEM)
        
        pool_status = ConnectionPoolMonitor.get_pool_status()
        pool_healthy = ConnectionPoolMonitor.is_pool_healthy()
        warnings = ConnectionPoolMonitor.get_pool_warnings()
        
        result = {
            "pool_healthy": pool_healthy,
            "status": pool_status,
            "warnings": warnings,
            "recommendations": _get_pool_recommendations(pool_status)
        }
        
        if pool_healthy:
            logger.info("Pool health check completed successfully", LogCategory.DATABASE, extra_data=result)
        else:
            logger.warning("Pool health check found issues", LogCategory.DATABASE, extra_data=result)
        
        return result
    except Exception as e:
        logger.error("Pool health check failed", LogCategory.DATABASE, exception=e)
        raise HTTPException(status_code=503, detail=f"Pool health check failed: {str(e)}")

def _get_pool_recommendations(pool_status: dict) -> list:
    """Get recommendations based on pool status."""
    recommendations = []
    
    if pool_status["utilization_percent"] > 80:
        recommendations.append("Consider increasing pool_size or max_overflow")
    
    if pool_status["checked_out"] > pool_status["pool_size"]:
        recommendations.append("Currently using overflow connections - monitor for performance impact")
    
    if pool_status["utilization_percent"] < 20:
        recommendations.append("Pool utilization is low - consider reducing pool_size for resource efficiency")
    
    return recommendations

@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": settings.api_title,
        "version": settings.api_version,
        "environment": settings.environment,
        "docs": "/docs",
        "health": "/healthz",
        "call_simulator": "/call-simulator",
        "endpoints": {
            "clinics": f"{settings.api_prefix}/clinics",
            "providers": f"{settings.api_prefix}/providers", 
            "appointments": f"{settings.api_prefix}/appointments",
            "google_calendar": f"{settings.api_prefix}/google-calendar",
            "call_simulator": "/api/call-simulator",
            "tokenization": "/v1/tokens"
        }
    }

@app.get("/call-simulator", response_class=HTMLResponse)
def call_simulator():
    """Serve the call simulator HTML interface."""
    try:
        with open("templates/call_simulator.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Call Simulator not found</h1><p>The call simulator template file is missing.</p>",
            status_code=404
        )

# Register exception handlers
register_exception_handlers(app)

# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with database and service status."""
    try:
        db_healthy = test_database_connection()
        return {
            "status": "healthy" if db_healthy else "degraded",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database": "connected" if db_healthy else "disconnected",
            "services": {
                "database": db_healthy,
                "background_jobs": "running"
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

@app.get("/ping")
async def ping():
    """Simple ping endpoint for load balancers."""
    return {"pong": datetime.now(timezone.utc).isoformat()}

# Include all routers
app.include_router(api_router)     # Comprehensive API endpoints
