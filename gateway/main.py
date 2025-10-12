from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
from services.database import Base, engine
from routes.tokens import router as tokens_router
from routes import api_router

app = FastAPI(
    title="CallCenterAI Gateway API",
    description="Comprehensive API for CallCenterAI system including clinic management, provider scheduling, appointment booking, and Google Calendar integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    """Initialize database tables on startup."""
    Base.metadata.create_all(bind=engine)

@app.get("/healthz")
def healthz():
    """Health check endpoint."""
    return {
        "ok": True, 
        "service": "gateway",
        "version": "1.0.0",
        "status": "healthy"
    }

@app.get("/")
def root():
    """Root endpoint with API information."""
    return {
        "message": "CallCenterAI Gateway API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/healthz",
        "call_simulator": "/call-simulator",
        "endpoints": {
            "clinics": "/api/v1/clinics",
            "providers": "/api/v1/providers", 
            "appointments": "/api/v1/appointments",
            "google_calendar": "/api/v1/google-calendar",
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

# Include all routers
app.include_router(tokens_router)  # Existing tokenization endpoints
app.include_router(api_router)     # New comprehensive API endpoints
