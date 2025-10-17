"""
Azure Communication Services API routes.

Provides REST endpoints for:
- Call initiation and management
- Webhook handling for ACS events
- Call status and monitoring
- WebSocket endpoint for audio streaming
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from services.azure_communication_service import get_azure_communication_service
from services.audio_stream_handler import get_audio_stream_handler
from services.structured_logging import get_logger, LogCategory
from services.exceptions import (
    AzureCommunicationError,
    CallNotFoundError,
    ValidationError,
    ExternalServiceUnavailableError
)
from models.enums import CallStatus
from services.database import get_db


logger = get_logger("azure_communication_routes")
router = APIRouter(prefix="/acs", tags=["Azure Communication Services"])


# Request/Response Models
class CallInitiateRequest(BaseModel):
    """Request model for initiating a call."""
    phone_number: str = Field(..., description="Phone number to call")
    clinic_id: str = Field(..., description="ID of the clinic handling the call")
    call_type: str = Field(default="outbound", description="Type of call (inbound/outbound)")
    
    @field_validator('phone_number')
    @classmethod
    def validate_phone_number(cls, v):
        if not v.startswith('+'):
            raise ValueError('Phone number must include country code (e.g., +1234567890)')
        return v
    
    @field_validator('call_type')
    @classmethod
    def validate_call_type(cls, v):
        if v not in ['inbound', 'outbound']:
            raise ValueError('Call type must be either "inbound" or "outbound"')
        return v


class CallInitiateResponse(BaseModel):
    """Response model for call initiation."""
    call_id: str
    acs_call_id: str
    status: str
    message: str


class AzureCallStatusResponse(BaseModel):
    """Response model for Azure call status."""
    call_id: str
    acs_call_id: Optional[str]
    clinic_id: str
    status: str
    start_time: str
    end_time: Optional[str]
    websocket_connected: bool
    audio_stream_active: bool
    language_detected: Optional[str]
    language_locked: bool
    recording_id: Optional[str]


class WebhookEventRequest(BaseModel):
    """Request model for webhook events."""
    eventType: str
    callConnectionId: Optional[str] = None
    state: Optional[str] = None
    recordingState: Optional[str] = None
    recordingId: Optional[str] = None
    timestamp: Optional[str] = None


class CallAnswerRequest(BaseModel):
    """Request model for answering a call."""
    call_id: str


class CallEndRequest(BaseModel):
    """Request model for ending a call."""
    call_id: str
    reason: str = Field(default="completed", description="Reason for ending the call")


# REST API Endpoints
@router.post("/calls/initiate", response_model=CallInitiateResponse, status_code=status.HTTP_201_CREATED)
async def initiate_call(
    request: CallInitiateRequest,
    db: Session = Depends(get_db)
):
    """
    Initiate a new call with Azure Communication Services.
    
    This endpoint starts either an inbound or outbound call and returns
    the call identifiers for tracking and management.
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Initiate the call
        call_id, acs_call_id = await acs_service.initialize_call(
            phone_number=request.phone_number,
            clinic_id=request.clinic_id,
            call_type=request.call_type
        )
        
        logger.info(
            f"Call initiated successfully: {call_id}",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "acs_call_id": acs_call_id,
                "clinic_id": request.clinic_id,
                "call_type": request.call_type
            }
        )
        
        return CallInitiateResponse(
            call_id=call_id,
            acs_call_id=acs_call_id,
            status=CallStatus.INITIATED.value,
            message="Call initiated successfully"
        )
        
    except ValidationError as e:
        logger.warning(
            f"Validation error in call initiation: {e}",
            LogCategory.API,
            extra_data={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {e}"
        )
    
    except AzureCommunicationError as e:
        logger.error(
            f"ACS error in call initiation: {e}",
            LogCategory.API,
            extra_data={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Communication service error: {e}"
        )
    
    except Exception as e:
        logger.error(
            f"Unexpected error in call initiation: {e}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/calls/{call_id}/answer", response_model=Dict[str, str])
async def answer_call(
    call_id: str,
    request: CallAnswerRequest,
    db: Session = Depends(get_db)
):
    """
    Answer an inbound call.
    
    This endpoint answers a call that has been initiated and is waiting
    for connection.
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Answer the call
        success = await acs_service.answer_call(call_id)
        
        if success:
            logger.info(
                f"Call answered successfully: {call_id}",
                LogCategory.API,
                extra_data={"call_id": call_id}
            )
            
            return {
                "status": "success",
                "message": "Call answered successfully",
                "call_id": call_id
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to answer call"
            )
        
    except CallNotFoundError as e:
        logger.warning(
            f"Call not found for answering: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id}
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call not found: {call_id}"
        )
    
    except AzureCommunicationError as e:
        logger.error(
            f"ACS error in call answering: {e}",
            LogCategory.API,
            extra_data={"call_id": call_id, "error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Communication service error: {e}"
        )
    
    except Exception as e:
        logger.error(
            f"Unexpected error in call answering: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/calls/{call_id}/end", response_model=Dict[str, str])
async def end_call(
    call_id: str,
    request: CallEndRequest,
    db: Session = Depends(get_db)
):
    """
    End an active call.
    
    This endpoint terminates a call and cleans up associated resources.
    """
    try:
        acs_service = get_azure_communication_service()
        
        # End the call
        success = await acs_service.end_call(call_id, request.reason)
        
        if success:
            logger.info(
                f"Call ended successfully: {call_id}",
                LogCategory.API,
                extra_data={
                    "call_id": call_id,
                    "reason": request.reason
                }
            )
            
            return {
                "status": "success",
                "message": "Call ended successfully",
                "call_id": call_id,
                "reason": request.reason
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to end call"
            )
        
    except Exception as e:
        logger.error(
            f"Unexpected error in call ending: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/calls/{call_id}/status", response_model=AzureCallStatusResponse)
async def get_call_status(
    call_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the status of a call.
    
    Returns detailed information about the call including its current state,
    connection status, and metadata.
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get call status
        call_status = acs_service.get_call_status(call_id)
        
        if not call_status:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Call not found: {call_id}"
            )
        
        return AzureCallStatusResponse(**call_status)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error getting call status: {e}",
            LogCategory.API,
            exception=e,
            extra_data={"call_id": call_id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/calls/active", response_model=Dict[str, Any])
async def get_active_calls(
    clinic_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get information about active calls.
    
    Returns a summary of all active calls, optionally filtered by clinic.
    """
    try:
        acs_service = get_azure_communication_service()
        audio_handler = get_audio_stream_handler()
        
        # Get active calls count
        total_active = acs_service.get_active_calls_count()
        
        # Get clinic-specific count if requested
        clinic_active = None
        if clinic_id:
            clinic_active = acs_service.get_clinic_active_calls_count(clinic_id)
        
        # Get connection statistics
        connection_stats = audio_handler.get_connection_statistics()
        
        return {
            "total_active_calls": total_active,
            "clinic_active_calls": clinic_active,
            "connection_statistics": connection_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Unexpected error getting active calls: {e}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/webhooks/events", response_model=Dict[str, Any])
async def handle_webhook_events(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle webhook events from Azure Communication Services.
    
    This endpoint receives and processes events from ACS including
    call state changes, recording events, and media streaming events.
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get raw payload
        payload_bytes = await request.body()
        
        # Verify webhook signature
        if not acs_service.verify_webhook_signature(request, payload_bytes):
            logger.warning(
                "Invalid webhook signature received",
                LogCategory.API,
                extra_data={
                    "client_ip": request.client.host if request.client else "unknown",
                    "user_agent": request.headers.get("user-agent", "unknown")
                }
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
        
        # Parse payload
        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Handle the webhook event
        result = await acs_service.handle_webhook_event(request, payload)
        
        logger.info(
            f"Webhook event processed: {payload.get('eventType', 'unknown')}",
            LogCategory.API,
            extra_data={
                "event_type": payload.get('eventType'),
                "call_connection_id": payload.get('callConnectionId'),
                "result": result
            }
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error handling webhook: {e}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/webhooks/recording", response_model=Dict[str, Any])
async def handle_recording_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle recording-specific webhook events from ACS.
    
    This endpoint processes recording events separately from general
    call events for better organization and processing.
    """
    try:
        # Get raw payload
        payload_bytes = await request.body()
        
        # Parse payload
        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in recording webhook payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        logger.info(
            f"Recording webhook received: {payload.get('eventType', 'unknown')}",
            LogCategory.API,
            extra_data={
                "event_type": payload.get('eventType'),
                "recording_id": payload.get('recordingId'),
                "recording_state": payload.get('recordingState')
            }
        )
        
        # For now, just acknowledge the webhook
        # In a full implementation, you would process the recording data
        return {
            "status": "received",
            "message": "Recording webhook processed",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error handling recording webhook: {e}",
            LogCategory.API,
            exception=e
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


# WebSocket Endpoint
@router.websocket("/ws/audio/{call_id}")
async def websocket_audio_stream(
    websocket: WebSocket,
    call_id: str
):
    """
    WebSocket endpoint for real-time audio streaming.
    
    This endpoint establishes a WebSocket connection for bidirectional
    audio streaming between the client and Azure Communication Services.
    """
    connection_id = None
    
    try:
        audio_handler = get_audio_stream_handler()
        
        # Connect audio stream
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        
        logger.info(
            f"WebSocket audio stream established: {connection_id} for call {call_id}",
            LogCategory.API,
            extra_data={
                "connection_id": connection_id,
                "call_id": call_id
            }
        )
        
        # Handle incoming audio
        await audio_handler.handle_incoming_audio(connection_id)
        
    except CallNotFoundError as e:
        logger.warning(
            f"Call not found for WebSocket connection: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id}
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Call not found")
    
    except ValidationError as e:
        logger.warning(
            f"Validation error in WebSocket connection: {e}",
            LogCategory.API,
            extra_data={"call_id": call_id, "error": str(e)}
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Validation error")
    
    except WebSocketDisconnect:
        logger.info(
            f"WebSocket disconnected: {connection_id} for call {call_id}",
            LogCategory.API,
            extra_data={
                "connection_id": connection_id,
                "call_id": call_id
            }
        )
    
    except Exception as e:
        logger.error(
            f"Unexpected error in WebSocket audio stream: {e}",
            LogCategory.API,
            exception=e,
            extra_data={
                "connection_id": connection_id,
                "call_id": call_id
            }
        )
        
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="Internal error")
        except Exception:
            pass  # WebSocket might already be closed


# Health and Monitoring Endpoints
@router.get("/health", response_model=Dict[str, Any])
async def get_acs_health():
    """
    Get health status of Azure Communication Services integration.
    
    Returns the current status of ACS connections and services.
    """
    try:
        acs_service = get_azure_communication_service()
        audio_handler = get_audio_stream_handler()
        
        # Get service statistics
        active_calls = acs_service.get_active_calls_count()
        connection_stats = audio_handler.get_connection_statistics()
        
        return {
            "status": "healthy",
            "active_calls": active_calls,
            "connection_statistics": connection_stats,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(
            f"Error checking ACS health: {e}",
            LogCategory.API,
            exception=e
        )
        
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/cache/statistics", response_model=Dict[str, Any])
async def get_cache_statistics():
    """
    Get cache performance statistics.
    
    Returns:
        Dict[str, Any]: Cache statistics including hit rates, memory usage, and performance metrics
    """
    try:
        from services.response_cache import get_response_cache_service
        from services.hybrid_nlp_service import get_hybrid_nlp_service
        
        # Get response cache statistics
        response_cache = get_response_cache_service()
        await response_cache.initialize()
        cache_stats = await response_cache.get_cache_statistics()
        
        # Get NLP cache statistics
        nlp_service = get_hybrid_nlp_service()
        nlp_stats = nlp_service.get_processing_statistics()
        
        # Calculate estimated token savings
        total_requests = cache_stats.get("statistics", {}).get("total_requests", 0)
        cache_hits = cache_stats.get("statistics", {}).get("hits", 0)
        hit_rate = cache_stats.get("statistics", {}).get("hit_rate", 0.0)
        
        # Estimate token savings (rough calculation)
        estimated_tokens_saved = cache_hits * 50  # Assume 50 tokens saved per cache hit
        estimated_cost_savings = estimated_tokens_saved * 0.0001  # Rough cost per token
        
        return {
            "response_cache": cache_stats,
            "nlp_cache": nlp_stats,
            "performance_metrics": {
                "total_requests": total_requests,
                "cache_hits": cache_hits,
                "hit_rate": hit_rate,
                "estimated_tokens_saved": estimated_tokens_saved,
                "estimated_cost_savings_usd": round(estimated_cost_savings, 4)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}", LogCategory.CACHE)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve cache statistics: {str(e)}"
        )


@router.post("/cache/clear", response_model=Dict[str, Any])
async def clear_cache(pattern: Optional[str] = None):
    """
    Clear cache entries (admin only).
    
    Args:
        pattern: Optional pattern to match keys (default: all response keys)
        
    Returns:
        Dict[str, Any]: Clear operation results
    """
    try:
        from services.response_cache import get_response_cache_service
        
        response_cache = get_response_cache_service()
        await response_cache.initialize()
        
        # Clear cache
        success = await response_cache.clear_cache(pattern)
        
        if success:
            return {
                "message": "Cache cleared successfully",
                "pattern": pattern,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to clear cache"
            )
            
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}", LogCategory.CACHE)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )


@router.get("/cache/health", response_model=Dict[str, Any])
async def get_cache_health():
    """
    Get cache service health status.
    
    Returns:
        Dict[str, Any]: Cache health information
    """
    try:
        from services.response_cache import get_response_cache_service
        
        response_cache = get_response_cache_service()
        await response_cache.initialize()
        
        health_status = await response_cache.health_check()
        
        return health_status
        
    except Exception as e:
        logger.error(f"Failed to get cache health: {e}", LogCategory.CACHE)
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }