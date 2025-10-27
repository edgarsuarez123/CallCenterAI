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
from datetime import datetime, timezone, timedelta

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from services.azure_communication_service import get_azure_communication_service
from services.audio_stream_handler import get_audio_stream_handler
from services.database import get_db_session
from services.structured_logging import get_logger, LogCategory
from services.configuration import get_settings

# Initialize router
router = APIRouter(prefix="/acs", tags=["Azure Communication Services"])

# Get logger
logger = get_logger("azure_communication_routes")


# Pydantic models for request/response validation
class CallInitiateRequest(BaseModel):
    """Request model for call initiation."""
    to_phone_number: str = Field(..., description="Phone number to call")
    from_phone_number: Optional[str] = Field(None, description="Phone number to call from")
    call_type: str = Field(default="outbound", description="Type of call")
    
    @field_validator('to_phone_number')
    @classmethod
    def validate_phone_number(cls, v):
        if not v or len(v) < 10:
            raise ValueError('Phone number must be at least 10 digits')
        return v


class CallInitiateResponse(BaseModel):
    """Response model for call initiation."""
    call_id: str
    status: str
    message: str
    timestamp: str


class AzureCallStatusResponse(BaseModel):
    """Response model for call status."""
    call_id: str
    status: str
    duration_seconds: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    caller_phone: Optional[str] = None
    callee_phone: Optional[str] = None


# REST API endpoints
@router.post("/calls/initiate", response_model=CallInitiateResponse, status_code=status.HTTP_201_CREATED)
async def initiate_call(
    request: CallInitiateRequest,
    db: Session = Depends(get_db_session)
) -> CallInitiateResponse:
    """
    Initiate a new call using Azure Communication Services.
    
    Args:
        request: Call initiation request
        db: Database session
        
    Returns:
        CallInitiateResponse: Call initiation result
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Initiate the call
        result = await acs_service.initiate_call(
            to_phone_number=request.to_phone_number,
            from_phone_number=request.from_phone_number,
            call_type=request.call_type
        )
        
        logger.info(
            f"Call initiated successfully: {result['call_id']}",
            LogCategory.API,
            extra_data={
                "call_id": result['call_id'],
                "to_phone": request.to_phone_number,
                "from_phone": request.from_phone_number,
                "call_type": request.call_type
            }
        )
        
        return CallInitiateResponse(
            call_id=result['call_id'],
            status=result['status'],
            message=result['message'],
            timestamp=datetime.now(AST).isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to initiate call: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate call: {e}"
        )


@router.post("/calls/{call_id}/answer", response_model=Dict[str, str])
async def answer_call(
    call_id: str,
    db: Session = Depends(get_db_session)
) -> Dict[str, str]:
    """
    Answer an incoming call.
    
    Args:
        call_id: ID of the call to answer
        db: Database session
        
    Returns:
        Dict[str, str]: Answer result
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Answer the call
        result = await acs_service.answer_call(call_id)
        
        logger.info(
            f"Call answered successfully: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id}
        )
        
        return {
            "status": "answered",
            "message": f"Call {call_id} answered successfully",
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to answer call {call_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to answer call: {e}"
        )


@router.post("/calls/{call_id}/end", response_model=Dict[str, str])
async def end_call(
    call_id: str,
    db: Session = Depends(get_db_session)
) -> Dict[str, str]:
    """
    End a call.
    
    Args:
        call_id: ID of the call to end
        db: Database session
        
    Returns:
        Dict[str, str]: End result
    """
    try:
        acs_service = get_azure_communication_service()
        
        # End the call
        result = await acs_service.end_call(call_id)
        
        logger.info(
            f"Call ended successfully: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id}
        )
        
        return {
            "status": "ended",
            "message": f"Call {call_id} ended successfully",
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to end call {call_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to end call: {e}"
        )


@router.get("/calls/{call_id}/status", response_model=AzureCallStatusResponse)
async def get_call_status(
    call_id: str,
    db: Session = Depends(get_db_session)
) -> AzureCallStatusResponse:
    """
    Get the status of a call.
    
    Args:
        call_id: ID of the call
        db: Database session
        
    Returns:
        AzureCallStatusResponse: Call status information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get call status
        status_info = await acs_service.get_call_status(call_id)
        
        return AzureCallStatusResponse(
            call_id=call_id,
            status=status_info.get('status', 'unknown'),
            duration_seconds=status_info.get('duration_seconds'),
            start_time=status_info.get('start_time'),
            end_time=status_info.get('end_time'),
            caller_phone=status_info.get('caller_phone'),
            callee_phone=status_info.get('callee_phone')
        )
        
    except Exception as e:
        logger.error(f"Failed to get call status for {call_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get call status: {e}"
        )


@router.get("/calls/active", response_model=Dict[str, Any])
async def get_active_calls(
    db: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Get all active calls.
    
    Args:
        db: Database session
        
    Returns:
        Dict[str, Any]: Active calls information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Get active calls
        active_calls = await acs_service.get_active_calls()
        
        return {
            "active_calls": active_calls,
            "count": len(active_calls),
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get active calls: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get active calls: {e}"
        )


# Event handlers
async def handle_incoming_call_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle incoming call event from Azure Communication Services.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        # Extract call information
        call_id = payload.get('callId')
        from_number = payload.get('from', {}).get('phoneNumber', {}).get('value')
        to_number = payload.get('to', {}).get('phoneNumber', {}).get('value')
        
        logger.info(
            f"Incoming call event: {call_id} from {from_number} to {to_number}",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "from_number": from_number,
                "to_number": to_number,
                "payload": payload
            }
        )
        
        # Answer the call automatically
        await acs_service.answer_call(call_id)
        
        # Initialize AI call handling
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        await orchestrator.start_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id='default-clinic',
            call_type='inbound'
        )
        
        return {
            "status": "call_answered",
            "message": f"Call {call_id} answered and AI handling initialized",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling incoming call event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling incoming call event: {e}"
        )


async def handle_call_starting_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle call starting event.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_id = payload.get('callId')
        
        logger.info(
            f"Call starting event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        # Answer the call
        await acs_service.answer_call(call_id)
        
        return {
            "status": "call_starting",
            "message": f"Call {call_id} is starting",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling call starting event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling call starting event: {e}"
        )


async def handle_call_ending_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle call ending event.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_id = payload.get('callId')
        
        logger.info(
            f"Call ending event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        # End AI call handling
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        await orchestrator.end_call(call_id)
        
        return {
            "status": "call_ending",
            "message": f"Call {call_id} is ending",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling call ending event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling call ending event: {e}"
        )


async def handle_incoming_call_received_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle IncomingCallReceived event from Call Automation.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_connection_id = payload.get('callConnectionId')
        from_number = payload.get('from', {}).get('phoneNumber', {}).get('value')
        to_number = payload.get('to', {}).get('phoneNumber', {}).get('value')
        
        logger.info(
            f"IncomingCallReceived event: {call_connection_id} from {from_number} to {to_number}",
            LogCategory.API,
            extra_data={
                "call_connection_id": call_connection_id,
                "from_number": from_number,
                "to_number": to_number,
                "payload": payload
            }
        )
        
        # Register the incoming call in ACS service
        await acs_service.register_incoming_call(
            call_id=call_connection_id,
            caller_phone=from_number,
            clinic_id='default-clinic',
            acs_call_id=call_connection_id
        )
        
        # Answer the call
        await acs_service.answer_call(call_connection_id)
        
        # Initialize AI call handling
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        await orchestrator.start_call(
            call_id=call_connection_id,
            caller_phone=from_number,
            clinic_id='default-clinic',
            call_type='inbound'
        )
        
        return {
            "status": "call_received",
            "message": f"Call {call_connection_id} received and answered",
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling IncomingCallReceived event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling IncomingCallReceived event: {e}"
        )


async def handle_call_connected_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle CallConnected event from Call Automation.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_connection_id = payload.get('callConnectionId')
        
        logger.info(
            f"CallConnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # Play greeting
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        await orchestrator.play_greeting(call_connection_id)
        
        return {
            "status": "call_connected",
            "message": f"Call {call_connection_id} connected",
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling CallConnected event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling CallConnected event: {e}"
        )


async def handle_call_disconnected_event(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle CallDisconnected event from Call Automation.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_connection_id = payload.get('callConnectionId')
        
        logger.info(
            f"CallDisconnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # End AI call handling
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        await orchestrator.end_call(call_connection_id)
        
        return {
            "status": "call_disconnected",
            "message": f"Call {call_connection_id} disconnected",
            "call_connection_id": call_connection_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling CallDisconnected event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling CallDisconnected event: {e}"
        )


async def handle_event_grid_call_started(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle CallStarted event from Event Grid.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_id = payload.get('data', {}).get('callId')
        
        logger.info(
            f"Event Grid CallStarted event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        return {
            "status": "call_started",
            "message": f"Event Grid call {call_id} started",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling Event Grid CallStarted event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Event Grid CallStarted event: {e}"
        )


async def handle_event_grid_call_ended(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle CallEnded event from Event Grid.
    
    Args:
        acs_service: Azure Communication Service instance
        payload: Event payload
        db: Database session
        
    Returns:
        Dict[str, Any]: Event handling result
    """
    try:
        call_id = payload.get('data', {}).get('callId')
        
        logger.info(
            f"Event Grid CallEnded event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        return {
            "status": "call_ended",
            "message": f"Event Grid call {call_id} ended",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error handling Event Grid CallEnded event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Event Grid CallEnded event: {e}"
        )


async def handle_event_grid_incoming_call(acs_service, payload: Dict[str, Any], db: Session) -> Dict[str, Any]:
    """
    Handle IncomingCall event from Event Grid.
    This event comes when someone calls the phone number.
    We need to answer the call to establish the connection.
    """
    try:
        # Extract call details from Event Grid payload
        from_number = payload.get('data', {}).get('from', {}).get('phoneNumber', {}).get('value')
        to_number = payload.get('data', {}).get('to', {}).get('phoneNumber', {}).get('value')
        server_call_id = payload.get('data', {}).get('serverCallId')
        
        # Use serverCallId as the call_id (it's base64 encoded)
        import base64
        if server_call_id:
            try:
                # Decode the base64 serverCallId to get a readable call ID
                decoded_id = base64.b64decode(server_call_id).decode('utf-8')
                # Extract a shorter ID from the decoded string
                call_id = f"EVENT_GRID_{decoded_id.split('/')[-1].split('?')[0][:12]}"
            except:
                # Fallback to using the base64 string directly
                call_id = f"EVENT_GRID_{server_call_id[:12]}"
        else:
            # Generate a fallback call ID
            call_id = f"EVENT_GRID_{payload.get('id', 'unknown')[:12]}"

        logger.info(
            f"Event Grid IncomingCall event from {from_number} to {to_number}",
            LogCategory.API,
            extra_data={
                "from_number": from_number,
                "to_number": to_number,
                "call_id": call_id,
                "payload": payload
            }
        )

        # Get the callback URL from environment variables
        from services.configuration import get_settings
        settings = get_settings()
        callback_url = settings.azure.communication.callback_url

        if not callback_url:
            logger.error("ACS_CALLBACK_URL is not configured. Cannot answer call.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="ACS_CALLBACK_URL is not configured"
            )

        # Extract incomingCallContext from Event Grid payload
        incoming_call_context = payload.get('data', {}).get('incomingCallContext')
        
        if not incoming_call_context:
            logger.error("No incomingCallContext in Event Grid payload")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing incomingCallContext in Event Grid payload"
            )

        # Answer the call using Call Automation SDK
        answer_result = await acs_service.answer_incoming_call(
            incoming_call_context=incoming_call_context,
            callback_url=callback_url
        )

        call_connection_id = answer_result.get('call_connection_id')
        logger.info(f"Call answered with connection ID: {call_connection_id}")
        
        # Determine clinic (default to 'default-clinic' for now)
        clinic_id = 'default-clinic'

        # Register the incoming call in ACS service
        await acs_service.register_incoming_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id=clinic_id,
            acs_call_id=call_connection_id  # Use the actual call connection ID
        )

        # Initialize call orchestrator
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()

        # Start AI conversation with the Event Grid call ID
        await orchestrator.start_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id=clinic_id,
            call_type='inbound'
        )

        # Play initial greeting
        await orchestrator.play_greeting(call_id)

        logger.info(f"AI call handling initialized for Event Grid call {call_id}")

        return {
            "status": "call_received",
            "message": f"Event Grid call received and AI handling initialized for {call_id}",
            "call_id": call_id,
            "timestamp": datetime.now(AST).isoformat(),
            "ai_ready": True
        }

    except Exception as e:
        logger.error(f"Error handling Event Grid IncomingCall event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error handling Event Grid IncomingCall event: {e}"
        )


# Webhook endpoints
@router.post("/webhooks/events", response_model=Dict[str, Any])
@router.get("/webhooks/events", response_model=Dict[str, Any])
@router.options("/webhooks/events", response_model=Dict[str, Any])
async def handle_webhook_events(
    request: Request,
    db: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Handle Azure Communication Services webhook events.
    
    Args:
        request: FastAPI request object
        db: Database session
        
    Returns:
        Dict[str, Any]: Webhook handling result
    """
    try:
        # Handle OPTIONS request for CORS preflight
        if request.method == "OPTIONS":
            # Check if this is a CloudEvents v1.0 validation request
            webhook_request_origin = request.headers.get("WebHook-Request-Origin")
            webhook_request_callback = request.headers.get("WebHook-Request-Callback")
            
            if webhook_request_origin and webhook_request_callback:
                logger.info(
                    f"CloudEvents v1.0 validation request from {webhook_request_origin}",
                    LogCategory.API,
                    extra_data={
                        "webhook_request_origin": webhook_request_origin,
                        "webhook_request_callback": webhook_request_callback,
                        "client_ip": request.client.host if request.client else "unknown"
                    }
                )
                
                # Return required headers for CloudEvents v1.0 validation
                return JSONResponse(
                    content={"message": "CloudEvents v1.0 validation successful"},
                    headers={
                        "WebHook-Allowed-Origin": webhook_request_origin,
                        "WebHook-Allowed-Rate": "120"
                    }
                )
            else:
                # Regular CORS preflight
                return JSONResponse(
                    content={"message": "CORS preflight request handled"},
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Request-ID, WebHook-Request-Origin, WebHook-Request-Callback"
                    }
                )
        
        # Handle ACS webhook events (POST requests)
        acs_service = get_azure_communication_service()
        
        # Parse payload first to check if it's an Event Grid validation event
        try:
            payload_bytes = await request.body()
            payload = json.loads(payload_bytes.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook payload: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Handle Event Grid validation handshake (SubscriptionValidationEvent)
        # Skip signature verification for Event Grid validation events
        # Event Grid sends an array of events, so we need to check each one
        if isinstance(payload, list) and len(payload) > 0:
            # Check if any event in the array is a validation event
            for event in payload:
                if event.get('eventType') == 'Microsoft.EventGrid.SubscriptionValidationEvent':
                    validation_code = event.get('data', {}).get('validationCode')
                    if validation_code:
                        logger.info(
                            f"Event Grid validation handshake received: {validation_code}",
                            LogCategory.API,
                            extra_data={
                                "validation_code": validation_code,
                                "client_ip": request.client.host if request.client else "unknown"
                            }
                        )
                        return {"validationResponse": validation_code}
                    else:
                        logger.warning("Event Grid validation event missing validationCode")
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Missing validationCode in Event Grid validation event"
                        )
        elif isinstance(payload, dict) and payload.get('eventType') == 'Microsoft.EventGrid.SubscriptionValidationEvent':
            validation_code = payload.get('data', {}).get('validationCode')
            if validation_code:
                logger.info(
                    f"Event Grid validation handshake received: {validation_code}",
                    LogCategory.API,
                    extra_data={
                        "validation_code": validation_code,
                        "client_ip": request.client.host if request.client else "unknown"
                    }
                )
                return {"validationResponse": validation_code}
            else:
                logger.warning("Event Grid validation event missing validationCode")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing validationCode in Event Grid validation event"
                )

        # Check if this is a Call Automation event (signed with ACS webhook secret)
        # Event Grid uses 'type' field, Call Automation uses 'eventType' field
        event_type_field = payload.get('type') or payload.get('eventType', '')
        is_call_automation_event = event_type_field.startswith('Microsoft.Communication.CallAutomation.')
        
        # Check if this is an Event Grid event (not signed with ACS webhook secret)
        is_event_grid_event = (
            event_type_field.startswith('Microsoft.Communication.') and
            not event_type_field.startswith('Microsoft.Communication.CallAutomation.')
        )

        # Only verify ACS webhook signature for Call Automation events
        if is_call_automation_event:
            if not acs_service.verify_webhook_signature(request, payload_bytes):
                logger.warning(
                    "Invalid webhook signature received for Call Automation event",
                    LogCategory.API,
                    extra_data={
                        "client_ip": request.client.host if request.client else "unknown",
                        "user_agent": request.headers.get("user-agent", "unknown"),
                        "event_type": event_type_field
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature"
                )
        elif is_event_grid_event:
            logger.info(
                "Event Grid event received, skipping ACS signature verification",
                LogCategory.API,
                extra_data={"event_type": event_type_field}
            )
        else:
            logger.info(
                "Non-Call Automation event received, skipping ACS signature verification",
                LogCategory.API,
                extra_data={"event_type": event_type_field}
            )

        # Handle different types of call events
        # Process events - handle both single event and array of events
        events_to_process = payload if isinstance(payload, list) else [payload]
        
        results = []
        for event_payload in events_to_process:
            if not isinstance(event_payload, dict):
                logger.warning(f"Skipping non-dict event: {event_payload}")
                continue
                
            # Event Grid uses 'type' field, Call Automation uses 'eventType' field
            event_type = event_payload.get('type') or event_payload.get('eventType', 'unknown')
            call_connection_id = event_payload.get('callConnectionId')

            logger.info(
                f"Processing webhook event: {event_type}",
                LogCategory.API,
                extra_data={
                    "event_type": event_type,
                    "call_connection_id": call_connection_id,
                    "payload": event_payload
                }
            )

            # Handle IncomingCallReceived event from Call Automation (when someone calls)
            if event_type == 'Microsoft.Communication.CallAutomation.IncomingCallReceived':
                result = await handle_incoming_call_received_event(acs_service, event_payload, db)

            # Handle CallConnected event from Call Automation (when call is answered)
            elif event_type == 'Microsoft.Communication.CallAutomation.CallConnected':
                result = await handle_call_connected_event(acs_service, event_payload, db)

            # Handle CallDisconnected event from Call Automation (when call ends)
            elif event_type == 'Microsoft.Communication.CallAutomation.CallDisconnected':
                result = await handle_call_disconnected_event(acs_service, event_payload, db)

            # Handle Event Grid IncomingCall event (when someone calls via Event Grid)
            elif event_type == 'Microsoft.Communication.IncomingCall':
                result = await handle_event_grid_incoming_call(acs_service, event_payload, db)

            # Handle Event Grid CallStarted event (when call starts via Event Grid)
            elif event_type == 'Microsoft.Communication.CallStarted':
                result = await handle_event_grid_call_started(acs_service, event_payload, db)

            # Handle Event Grid CallEnded event (when call ends via Event Grid)
            elif event_type == 'Microsoft.Communication.CallEnded':
                result = await handle_event_grid_call_ended(acs_service, event_payload, db)

            # Handle other Call Automation events
            else:
                result = await acs_service.handle_webhook_event(request, event_payload)
            
            results.append(result)
        
        # Return results - single result if single event, array if multiple events
        return results[0] if len(results) == 1 else {"results": results}

    except Exception as e:
        logger.error(f"Error processing webhook event: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing webhook event: {e}"
        )


# WebSocket endpoint for audio streaming
@router.websocket("/ws/audio/{call_id}")
async def websocket_audio_stream(
    websocket: WebSocket,
    call_id: str,
    db: Session = Depends(get_db_session)
):
    """
    WebSocket endpoint for real-time audio streaming.
    
    Args:
        websocket: WebSocket connection
        call_id: ID of the call
        db: Database session
    """
    connection_id = None
    
    try:
        audio_handler = get_audio_stream_handler()
        
        # Connect audio stream
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        
        logger.info(
            f"Audio stream connected for call {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "connection_id": connection_id}
        )
        
        # Keep connection alive
        while True:
            try:
                # Wait for messages from client
                data = await websocket.receive_text()
                
                # Process audio data
                await audio_handler.handle_incoming_audio(connection_id)
                
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected for call {call_id}")
                break
            except Exception as e:
                logger.error(f"Error in WebSocket for call {call_id}: {e}")
                break
                
    except Exception as e:
        logger.error(f"Failed to establish audio stream for call {call_id}: {e}", exc_info=True)
        await websocket.close(code=1011, reason="Internal server error")
    finally:
        # Clean up connection
        if connection_id:
            try:
                audio_handler = get_audio_stream_handler()
                await audio_handler.disconnect_audio_stream(connection_id)
            except Exception as e:
                logger.error(f"Error cleaning up audio stream for call {call_id}: {e}")


# Health and monitoring endpoints
@router.get("/health", response_model=Dict[str, Any])
async def get_acs_health():
    """
    Get Azure Communication Services health status.
    
    Returns:
        Dict[str, Any]: Health status information
    """
    try:
        acs_service = get_azure_communication_service()
        
        # Check ACS service health
        health_status = await acs_service.get_health_status()
        
        return {
            "status": "healthy",
            "acs_service": health_status,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"ACS health check failed: {e}", exc_info=True)
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now(AST).isoformat()
        }


@router.get("/cache/statistics", response_model=Dict[str, Any])
async def get_cache_statistics():
    """
    Get cache statistics.
    
    Returns:
        Dict[str, Any]: Cache statistics
    """
    try:
        from services.response_cache import get_response_cache_service
        cache_service = get_response_cache_service()
        
        stats = cache_service.get_statistics()
        
        return {
            "cache_statistics": stats,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache statistics: {e}"
        )


@router.post("/cache/clear", response_model=Dict[str, Any])
async def clear_cache(pattern: Optional[str] = None):
    """
    Clear cache entries.
    
    Args:
        pattern: Optional pattern to match cache keys
        
    Returns:
        Dict[str, Any]: Cache clear result
    """
    try:
        from services.response_cache import get_response_cache_service
        cache_service = get_response_cache_service()
        
        cleared_count = cache_service.clear_cache(pattern)
        
        return {
            "status": "success",
            "cleared_entries": cleared_count,
            "pattern": pattern,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {e}"
        )


@router.get("/cache/health", response_model=Dict[str, Any])
async def get_cache_health():
    """
    Get cache health status.
    
    Returns:
        Dict[str, Any]: Cache health information
    """
    try:
        from services.response_cache import get_response_cache_service
        cache_service = get_response_cache_service()
        
        health_status = cache_service.get_health_status()
        
        return {
            "cache_health": health_status,
            "timestamp": datetime.now(AST).isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get cache health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache health: {e}"
        )


@router.websocket("/ws/audio/{call_connection_id}")
async def websocket_audio_stream(
    websocket: WebSocket,
    call_connection_id: str
):
    """WebSocket endpoint for ACS media streaming."""
    try:
        await websocket.accept()
        
        audio_handler = get_audio_stream_handler()
        acs_service = get_azure_communication_service()
        
        # Find call by ACS connection ID
        call_id = None
        for cid, call_state in acs_service.active_calls.items():
            if call_state.acs_call_id == call_connection_id:
                call_id = cid
                break
        
        if not call_id:
            logger.warning(f"No call found for connection {call_connection_id}")
            await websocket.close(code=1008, reason="Call not found")
            return
        
        # Connect audio stream
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        
        # Start STT recognition for this call
        from services.azure_speech_stt import get_stt_service
        stt_service = get_stt_service()
        
        # Register audio processor to feed STT
        async def audio_processor(chunk, connection):
            # Push audio to STT recognizer
            await stt_service.process_audio_chunk(call_id, chunk.data)
        
        audio_handler.register_audio_processor(connection_id, audio_processor)
        
        # Handle incoming audio from ACS
        await audio_handler.handle_incoming_audio(connection_id)
        
    except Exception as e:
        logger.error(f"WebSocket audio error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except:
            pass