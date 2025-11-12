from fastapi import FastAPI
from fastapi.responses import JSONResponse
import logging
from api.Routes.health import health_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="CallCenterAI API",
    description="API for Call Center AI operations",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


# Root endpoint
@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": "CallCenterAI API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Include routers
app.include_router(health_router)

# Error handler
@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """General exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc)
        }
    )


# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

