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
        # Extract call information (with validation)
        call_id = payload.get('callId')
        if not call_id:
            logger.error("Missing callId in incoming call event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callId in payload"
            )
        
        from_number = payload.get('from', {}).get('phoneNumber', {}).get('value')
        to_number = payload.get('to', {}).get('phoneNumber', {}).get('value')
        
        # Validate phone numbers
        if not from_number:
            logger.warning(f"Missing from_number in incoming call event for {call_id}", LogCategory.API)
        
        if not to_number:
            logger.warning(f"Missing to_number in incoming call event for {call_id}", LogCategory.API)
        
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
        
        # Get clinic_id from phone routing (with error handling)
        clinic_id = 'default-clinic'  # Default fallback
        try:
            if to_number:
                from services.phone_routing_service import get_phone_routing_service
                phone_routing = get_phone_routing_service(db)
                clinic_id = phone_routing.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
            clinic_id = 'default-clinic'
        
        # Issue 101, 105: Check if call already exists before initializing
        from services.call_orchestrator import get_call_orchestrator
        from models.enums import CallType
        orchestrator = get_call_orchestrator()
        
        # Issue 101: Check if call already exists in orchestrator before starting
        async with orchestrator._calls_lock:
            if call_id in orchestrator.active_calls:
                logger.info(f"Call {call_id} already exists, skipping initialization", LogCategory.API)
                return {
                    "status": "call_already_exists",
                    "message": f"Call {call_id} already initialized",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # Issue 113: Check if call is already answered before attempting to answer
        try:
            # Check call status first
            call_status = await acs_service.get_call_status(call_id)
            if call_status and call_status.get('status') in ['answered', 'connected', 'active']:
                logger.info(f"Call {call_id} already answered, skipping answer", LogCategory.API)
            else:
                # Answer the call automatically (with error handling)
                await acs_service.answer_call(call_id)
        except Exception as e:
            logger.error(f"Failed to answer call {call_id}: {e}", LogCategory.API, exception=e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to answer call: {e}"
            )
        
        # Initialize AI call handling
        await orchestrator.start_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id=clinic_id,
            call_type=CallType.INBOUND,  # Use enum instead of string
            call_metadata={'acs_call_id': call_id}  # Issue 112: Store ACS call ID in metadata
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
        
        # Issue 133: Verify call state before performing operations
        # Issue 142: Check if call is already ended
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator for starting event", LogCategory.API)
                return {
                    "status": "call_not_found",
                    "message": f"Call {call_id} not found",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
            
            call_context = orchestrator.active_calls[call_id]
            # Issue 142: Check if call is already ended
            from services.call_orchestrator import CallState
            if call_context.state in [CallState.ENDING, CallState.ENDED, CallState.ERROR]:
                logger.info(f"Call {call_id} already in state {call_context.state.value}, skipping start", LogCategory.API)
                return {
                    "status": "call_already_ended",
                    "message": f"Call {call_id} already ended",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # Issue 113: Check if call is already answered before attempting to answer
        try:
            call_status = await acs_service.get_call_status(call_id)
            if call_status and call_status.get('status') in ['answered', 'connected', 'active']:
                logger.info(f"Call {call_id} already answered, skipping answer", LogCategory.API)
            else:
                # Answer the call
                await acs_service.answer_call(call_id)
        except Exception as answer_error:
            logger.error(f"Failed to answer call {call_id}: {answer_error}", LogCategory.API, exception=answer_error)
            # Continue - answer failure shouldn't stop the event handling
        
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
        if not call_connection_id:
            logger.error("Missing callConnectionId in IncomingCallReceived event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callConnectionId in payload"
            )
        
        from_number = payload.get('from', {}).get('phoneNumber', {}).get('value')
        to_number = payload.get('to', {}).get('phoneNumber', {}).get('value')
        
        # Validate phone numbers
        if not from_number:
            logger.warning(f"Missing from_number in IncomingCallReceived event for {call_connection_id}", LogCategory.API)
        
        if not to_number:
            logger.warning(f"Missing to_number in IncomingCallReceived event for {call_connection_id}", LogCategory.API)
        
        # Use call_connection_id consistently as call_id
        call_id = call_connection_id
        
        logger.info(
            f"IncomingCallReceived event: {call_id} from {from_number} to {to_number}",
            LogCategory.API,
            extra_data={
                "call_id": call_id,
                "from_number": from_number,
                "to_number": to_number,
                "payload": payload
            }
        )
        
        # Get clinic_id from phone routing (with error handling)
        clinic_id = 'default-clinic'  # Default fallback
        try:
            if to_number:
                from services.phone_routing_service import get_phone_routing_service
                phone_routing = get_phone_routing_service(db)
                clinic_id = phone_routing.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
            clinic_id = 'default-clinic'
        
        # Issue 101, 105: Check if call already exists before initializing
        from services.call_orchestrator import get_call_orchestrator
        from models.enums import CallType
        orchestrator = get_call_orchestrator()
        
        # Issue 101: Check if call already exists in orchestrator before starting
        async with orchestrator._calls_lock:
            if call_id in orchestrator.active_calls:
                logger.info(f"Call {call_id} already exists, skipping initialization", LogCategory.API)
                return {
                    "status": "call_already_exists",
                    "message": f"Call {call_id} already initialized",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # Issue 104: Store call ID mapping BEFORE calling orchestrator.start_call
        # Store mapping for CallConnected event (with error handling)
        try:
            await acs_service.store_call_id_mapping(call_id, call_connection_id)
        except Exception as e:
            logger.warning(f"Failed to store call ID mapping for {call_id}: {e}", LogCategory.API)
            # Issue 147: Handle mapping storage failures - retry or fail call if required
            # For now, log warning but continue - mapping might be stored later
        
        # Register the incoming call in ACS service (with error handling)
        try:
            await acs_service.register_incoming_call(
                call_id=call_id,
                caller_phone=from_number,
                clinic_id=clinic_id,
                acs_call_id=call_connection_id
            )
        except Exception as e:
            # Issue 110: Check if call already registered (duplicate registration)
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                logger.info(f"Call {call_id} already registered, continuing", LogCategory.API)
            else:
                logger.error(f"Failed to register incoming call {call_id}: {e}", LogCategory.API, exception=e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to register incoming call: {e}"
                )
        
        # Issue 113: Check if call is already answered before attempting to answer
        try:
            # Check call status first
            call_status = await acs_service.get_call_status(call_id)
            if call_status and call_status.get('status') in ['answered', 'connected', 'active']:
                logger.info(f"Call {call_id} already answered, skipping answer", LogCategory.API)
            else:
                # Answer the call (with error handling)
                await acs_service.answer_call(call_id)
        except Exception as e:
            logger.error(f"Failed to answer call {call_id}: {e}", LogCategory.API, exception=e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to answer call: {e}"
            )
        
        # Initialize AI call handling
        await orchestrator.start_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id=clinic_id,
            call_type=CallType.INBOUND,  # Use enum instead of string
            call_metadata={'acs_call_id': call_connection_id}  # Issue 112: Store ACS call ID in metadata
        )
        
        # Play greeting after call starts (Issue 3: Missing Greeting in Some Call Paths)
        try:
            await orchestrator.play_greeting(call_id)
        except Exception as e:
            logger.error(f"Failed to play greeting for call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - greeting failure shouldn't stop the call
        
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
        if not call_connection_id:
            logger.error("Missing callConnectionId in CallConnected event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callConnectionId in payload"
            )
        
        logger.info(
            f"CallConnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # Get call_id from mapping (call_connection_id is the ACS ID, we need our call_id)
        acs_service = get_azure_communication_service()
        call_id = await acs_service.get_call_id_from_mapping(call_connection_id) or call_connection_id
        
        # Issue 125: Coordinate state updates between handlers
        # Issue 133: Verify call state before performing operations
        # Issue 142: Check if call is already ended
        from services.call_orchestrator import get_call_orchestrator, CallState
        orchestrator = get_call_orchestrator()
        
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator for connected event", LogCategory.API)
                return {
                    "status": "call_not_found",
                    "message": f"Call {call_id} not found",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
            
            call_context = orchestrator.active_calls[call_id]
            # Issue 142: Check if call is already ended
            if call_context.state in [CallState.ENDING, CallState.ENDED, CallState.ERROR]:
                logger.info(f"Call {call_id} already in state {call_context.state.value}, skipping connected event", LogCategory.API)
                return {
                    "status": "call_already_ended",
                    "message": f"Call {call_id} already ended",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
            
            # Issue 125: Update call state to CONNECTED if not already
            if call_context.state != CallState.CONNECTED:
                call_context.state = CallState.CONNECTED
                call_context.last_activity = datetime.now(AST)
        
        # Play greeting (with error handling)
        try:
            await orchestrator.play_greeting(call_id)
        except Exception as e:
            logger.error(f"Failed to play greeting for call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - greeting failure shouldn't stop the call
        
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
        if not call_connection_id:
            logger.error("Missing callConnectionId in CallDisconnected event payload", LogCategory.API)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing callConnectionId in payload"
            )
        
        logger.info(
            f"CallDisconnected event: {call_connection_id}",
            LogCategory.API,
            extra_data={"call_connection_id": call_connection_id, "payload": payload}
        )
        
        # Get call_id from mapping (call_connection_id is the ACS ID, we need our call_id)
        acs_service = get_azure_communication_service()
        call_id = await acs_service.get_call_id_from_mapping(call_connection_id) or call_connection_id
        
        # Issue 125: Coordinate state updates between handlers
        # Issue 133: Verify call state before performing operations
        # Issue 142: Check if call is already ended
        from services.call_orchestrator import get_call_orchestrator, CallState
        orchestrator = get_call_orchestrator()
        
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator for disconnected event", LogCategory.API)
                return {
                    "status": "call_not_found",
                    "message": f"Call {call_id} not found",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
            
            call_context = orchestrator.active_calls[call_id]
            # Issue 142: Check if call is already ended
            if call_context.state in [CallState.ENDING, CallState.ENDED]:
                logger.info(f"Call {call_id} already in state {call_context.state.value}, skipping disconnect", LogCategory.API)
                return {
                    "status": "call_already_ended",
                    "message": f"Call {call_id} already ended",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # End AI call handling (with error handling)
        try:
            await orchestrator.end_call(call_id)
        except Exception as e:
            logger.error(f"Failed to end call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - end call failure shouldn't raise exception
        
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
        if not call_id:
            logger.warning("Missing callId in Event Grid CallStarted event payload", LogCategory.API)
            call_id = payload.get('id', 'unknown')
        
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
        if not call_id:
            logger.warning("Missing callId in Event Grid CallEnded event payload", LogCategory.API)
            call_id = payload.get('id', 'unknown')
        
        # Validate call_id
        if not call_id or call_id == 'unknown':
            logger.warning("Invalid call_id in Event Grid CallEnded event", LogCategory.API)
            # Continue with processing even if call_id is invalid
        
        logger.info(
            f"Event Grid CallEnded event: {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "payload": payload}
        )
        
        # Get call_id from mapping if available (with error handling)
        try:
            acs_service = get_azure_communication_service()
            mapped_call_id = await acs_service.get_call_id_from_mapping(call_id)
            if mapped_call_id:
                call_id = mapped_call_id
        except Exception as e:
            logger.warning(f"Failed to get call_id from mapping for {call_id}: {e}", LogCategory.API)
            # Continue with original call_id
        
        # End AI call handling (with error handling)
        try:
            from services.call_orchestrator import get_call_orchestrator
            orchestrator = get_call_orchestrator()
            await orchestrator.end_call(call_id)
        except Exception as e:
            logger.error(f"Failed to end call {call_id}: {e}", LogCategory.API, exception=e)
            # Continue - end call failure shouldn't raise exception
        
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
        
        # Validate phone numbers
        if not from_number or not isinstance(from_number, str) or len(from_number.strip()) == 0:
            logger.error(f"Invalid from_number in Event Grid payload: {from_number}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid from_number in Event Grid payload"
            )
        
        if not to_number or not isinstance(to_number, str) or len(to_number.strip()) == 0:
            logger.error(f"Invalid to_number in Event Grid payload: {to_number}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid to_number in Event Grid payload"
            )
        
        # Use serverCallId as the call_id (it's base64 encoded)
        import base64
        if server_call_id:
            try:
                # Decode the base64 serverCallId to get a readable call ID
                decoded_id = base64.b64decode(server_call_id).decode('utf-8')
                # Extract a shorter ID from the decoded string (with bounds check)
                parts = decoded_id.split('/')
                if parts and len(parts) > 0:
                    last_part = parts[-1].split('?')[0]
                    call_id = f"EVENT_GRID_{last_part[:12] if len(last_part) > 12 else last_part}"
                else:
                    call_id = f"EVENT_GRID_{decoded_id[:12] if len(decoded_id) > 12 else decoded_id}"
            except Exception as e:
                logger.warning(f"Failed to decode serverCallId {server_call_id}: {e}", LogCategory.API)
                # Fallback to using the base64 string directly (with bounds check)
                call_id = f"EVENT_GRID_{server_call_id[:12] if len(server_call_id) > 12 else server_call_id}"
        else:
            # Generate a fallback call ID (with bounds check)
            payload_id = payload.get('id', 'unknown')
            call_id = f"EVENT_GRID_{payload_id[:12] if len(payload_id) > 12 else payload_id}"

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

        if not answer_result or not answer_result.get('call_connection_id'):
            logger.error(f"Failed to answer incoming call {call_id}: {answer_result}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to answer incoming call"
            )
        
        call_connection_id = answer_result.get('call_connection_id')
        if not call_connection_id:
            logger.error(f"Missing call_connection_id in answer_result for {call_id}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing call_connection_id in answer result"
            )
        
        logger.info(f"Call answered with connection ID: {call_connection_id}")
        
        # Determine clinic from phone number mapping (with proper database session management)
        clinic_id = 'default-clinic'  # Default fallback
        try:
            if to_number:
                from services.phone_routing_service import get_phone_routing_service
                phone_routing = get_phone_routing_service(db)
                clinic_id = phone_routing.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Failed to get clinic_id for {to_number}, using default: {e}", LogCategory.API)
            clinic_id = 'default-clinic'

        # Issue 101, 105: Check if call already exists before initializing
        from services.call_orchestrator import get_call_orchestrator
        from models.enums import CallType
        orchestrator = get_call_orchestrator()
        
        # Issue 101: Check if call already exists in orchestrator before starting
        async with orchestrator._calls_lock:
            if call_id in orchestrator.active_calls:
                logger.info(f"Call {call_id} already exists, skipping initialization", LogCategory.API)
                return {
                    "status": "call_already_exists",
                    "message": f"Call {call_id} already initialized",
                    "call_id": call_id,
                    "timestamp": datetime.now(AST).isoformat()
                }
        
        # Issue 104: Store call ID mapping BEFORE calling orchestrator.start_call
        try:
            await acs_service.store_call_id_mapping(call_id, call_connection_id)
        except Exception as e:
            logger.warning(f"Failed to store call ID mapping for {call_id}: {e}", LogCategory.API)
            # Issue 147: Handle mapping storage failures - retry or fail call if required
        
        # Register the incoming call in ACS service
        try:
            await acs_service.register_incoming_call(
                call_id=call_id,
                caller_phone=from_number,
                clinic_id=clinic_id,
                acs_call_id=call_connection_id  # Use the actual call connection ID
            )
        except Exception as e:
            # Issue 110: Check if call already registered (duplicate registration)
            if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                logger.info(f"Call {call_id} already registered, continuing", LogCategory.API)
            else:
                logger.error(f"Failed to register incoming call {call_id}: {e}", LogCategory.API, exception=e)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to register incoming call: {e}"
                )

        # Initialize call orchestrator
        # Start AI conversation with the Event Grid call ID
        await orchestrator.start_call(
            call_id=call_id,
            caller_phone=from_number,
            clinic_id=clinic_id,
            call_type=CallType.INBOUND,  # Use enum instead of string
            call_metadata={'acs_call_id': call_connection_id}  # Issue 112: Store ACS call ID in metadata
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
from fastapi import Request, Body, Depends
from fastapi.exceptions import RequestValidationError

MAX_WEBHOOK_BODY_SIZE = 1_048_576  # 1MB

async def validate_request_size(request: Request):
    """Validate webhook request body size to prevent DoS attacks."""
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > MAX_WEBHOOK_BODY_SIZE:
        raise RequestValidationError("Request body too large")

@router.post("/webhooks/events", response_model=Dict[str, Any], dependencies=[Depends(validate_request_size)])
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
        
        # Extract clinic_id from phone number for rate limiting
        clinic_id = 'default-clinic'  # Default fallback
        try:
            # Try to extract phone number from payload
            if isinstance(payload, list) and len(payload) > 0:
                # For Event Grid events, look in the first event
                first_event = payload[0]
                to_number = first_event.get('data', {}).get('to', {}).get('phoneNumber', {}).get('value')
            elif isinstance(payload, dict):
                to_number = payload.get('data', {}).get('to', {}).get('phoneNumber', {}).get('value')
            else:
                to_number = None
            
            if to_number:
                # Use phone routing service to get clinic_id
                from services.phone_routing_service import get_phone_routing_service
                phone_routing = get_phone_routing_service(db)
                clinic_id = phone_routing.get_clinic_by_phone(to_number) or 'default-clinic'
        except Exception as e:
            logger.warning(f"Could not determine clinic_id for rate limiting: {e}")
            clinic_id = 'default-clinic'
        
        # Check webhook rate limit (DoS protection)
        try:
            from services.rate_limiter import get_rate_limiter
            rate_limiter = get_rate_limiter()
            if not await rate_limiter.check_webhook_limit(clinic_id):
                logger.warning(f"Webhook rate limit exceeded for clinic {clinic_id}")
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        except Exception as e:
            logger.error(f"Rate limiting check failed: {e}")
            # Continue processing if rate limiting fails
        
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

            # Check if this is a Call Automation event (signed with ACS webhook secret)
            is_call_automation_event = event_type.startswith('Microsoft.Communication.CallAutomation.')
            
            # Check if this is an Event Grid event (not signed with ACS webhook secret)
            is_event_grid_event = (
                event_type.startswith('Microsoft.Communication.') and
                not event_type.startswith('Microsoft.Communication.CallAutomation.')
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
                            "event_type": event_type
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
                    extra_data={"event_type": event_type}
                )
            else:
                logger.info(
                    "Non-Call Automation event received, skipping ACS signature verification",
                    LogCategory.API,
                    extra_data={"event_type": event_type}
                )

            # Handle different types of call events

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
        # Issue 111: Verify call exists in orchestrator before connecting audio stream
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        # Issue 111: Check if call exists before connecting
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator, closing WebSocket", LogCategory.API)
                await websocket.close(code=1008, reason="Call not found")
                return
        
        audio_handler = get_audio_stream_handler()
        
        # Issue 137: Check if connection already exists for this call
        # Check for existing connections before creating new ones
        async with audio_handler._connections_lock:
            existing_connections = [
                conn_id for conn_id, conn in audio_handler.active_connections.items()
                if conn.call_id == call_id and conn.is_active
            ]
            if existing_connections:
                logger.warning(
                    f"Existing audio connection(s) found for call {call_id}: {existing_connections}",
                    LogCategory.API
                )
                # Issue 137: Close existing connections or handle multiple connections gracefully
                # For now, close existing connections to prevent conflicts
                for existing_conn_id in existing_connections:
                    try:
                        await audio_handler.disconnect_audio_stream(existing_conn_id)
                    except Exception as e:
                        logger.warning(f"Failed to close existing connection {existing_conn_id}: {e}")
        
        # Issue 132: Verify connection succeeds before continuing
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        if not connection_id:
            logger.error(f"Failed to connect audio stream for call {call_id}", LogCategory.API)
            await websocket.close(code=1011, reason="Failed to connect audio stream")
            return
        
        logger.info(
            f"Audio stream connected for call {call_id}",
            LogCategory.API,
            extra_data={"call_id": call_id, "connection_id": connection_id}
        )
        
        # Issue 4: Audio Stream Handler Not Connected - Ensure audio stream handler is connected to call context
        # Update call context with audio stream handler if not already set
        async with orchestrator._calls_lock:
            if call_id in orchestrator.active_calls:
                call_context = orchestrator.active_calls[call_id]
                if not call_context.audio_stream_handler:
                    call_context.audio_stream_handler = audio_handler
                    # Initialize audio stream for the call context
                    await orchestrator._initialize_audio_stream(call_context)
        
        # Issue 124: Verify STT service availability before starting recognition
        from services.azure_speech_stt import get_speech_to_text_service
        stt_service = get_speech_to_text_service()
        
        # Issue 124: Check if STT service is available
        if not stt_service:
            logger.warning(f"STT service not available for call {call_id}, continuing without STT", LogCategory.API)
        else:
            # Issue 128: Check if STT recognition is already started before starting it again
            try:
                # Check if recognition is already active for this call
                # Note: This assumes STT service has a method to check active recognitions
                # If not available, we'll catch the error when starting
                recognition_active = False
                if hasattr(stt_service, 'is_recognition_active'):
                    recognition_active = await stt_service.is_recognition_active(call_id)
                
                if not recognition_active:
                    # Register audio processor to feed STT
                    async def audio_processor(chunk, connection):
                        # Push audio to STT recognizer
                        await stt_service.process_audio_chunk(call_id, chunk.data)
                    
                    # Issue 141: Verify audio processor registration succeeds
                    try:
                        audio_handler.register_audio_processor(connection_id, audio_processor)
                    except Exception as reg_error:
                        logger.error(f"Failed to register audio processor for call {call_id}: {reg_error}", LogCategory.API)
                        # Continue without audio processor - STT won't work but call can continue
                    
                    # Start STT continuous recognition
                    try:
                        await stt_service.start_continuous_recognition(call_id, primary_language="en-US", secondary_language="es-ES")
                        logger.info(f"Started STT recognition for call {call_id}", LogCategory.API)
                    except Exception as e:
                        # Issue 128: Handle case where recognition is already started
                        if "already" in str(e).lower() or "active" in str(e).lower():
                            logger.info(f"STT recognition already active for call {call_id}", LogCategory.API)
                        else:
                            logger.error(f"Failed to start STT recognition for call {call_id}: {e}", LogCategory.API, exception=e)
                            # Continue - STT failure shouldn't stop the call
                else:
                    logger.info(f"STT recognition already active for call {call_id}, skipping start", LogCategory.API)
            except Exception as e:
                logger.error(f"Error checking STT recognition status for call {call_id}: {e}", LogCategory.API)
                # Continue - STT failure shouldn't stop the call
        
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
        
        stats = await cache_service.get_cache_statistics()
        
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
        
        cleared_count = await cache_service.clear_cache(pattern)
        
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
        
        health_status = await cache_service.health_check()
        
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
    connection_id = None
    
    try:
        # Issue 146: Verify WebSocket acceptance succeeds before continuing
        await websocket.accept()
        
        audio_handler = get_audio_stream_handler()
        acs_service = get_azure_communication_service()
        
        # Issue 103: Find call by ACS connection ID with reliable mapping lookup
        # Issue 104: Use mapping stored before call starts
        call_id = None
        try:
            # Try to get call_id from mapping first
            if hasattr(acs_service, 'get_call_id_from_connection_id'):
                call_id = await acs_service.get_call_id_from_connection_id(call_connection_id)
            
            # Issue 103: Fallback: search in orchestrator by acs_call_id in metadata
            if not call_id:
                from services.call_orchestrator import get_call_orchestrator
                orchestrator = get_call_orchestrator()
                async with orchestrator._calls_lock:
                    for cid, call_context in orchestrator.active_calls.items():
                        metadata = call_context.metadata or {}
                        if metadata.get('acs_call_id') == call_connection_id:
                            call_id = cid
                            break
            
            # Issue 103: Additional fallback: search in ACS service active calls
            if not call_id:
                active_calls = await acs_service.get_active_calls()
                for cid, call_state in active_calls.items():
                    if hasattr(call_state, 'acs_call_id') and call_state.acs_call_id == call_connection_id:
                        call_id = cid
                        break
        except Exception as e:
            logger.warning(f"Failed to find call for connection {call_connection_id}: {e}", LogCategory.API)
        
        # Issue 103: Handle missing mapping gracefully
        if not call_id:
            logger.warning(f"No call found for connection {call_connection_id}")
            await websocket.close(code=1008, reason="Call not found")
            return
        
        # Issue 111: Verify call exists in orchestrator before connecting audio stream
        from services.call_orchestrator import get_call_orchestrator
        orchestrator = get_call_orchestrator()
        
        async with orchestrator._calls_lock:
            if call_id not in orchestrator.active_calls:
                logger.warning(f"Call {call_id} not found in orchestrator, closing WebSocket", LogCategory.API)
                await websocket.close(code=1008, reason="Call not found")
                return
        
        # Issue 137: Check if connection already exists for this call
        async with audio_handler._connections_lock:
            existing_connections = [
                conn_id for conn_id, conn in audio_handler.active_connections.items()
                if conn.call_id == call_id and conn.is_active
            ]
            if existing_connections:
                logger.warning(
                    f"Existing audio connection(s) found for call {call_id}: {existing_connections}",
                    LogCategory.API
                )
                # Close existing connections to prevent conflicts
                for existing_conn_id in existing_connections:
                    try:
                        await audio_handler.disconnect_audio_stream(existing_conn_id)
                    except Exception as e:
                        logger.warning(f"Failed to close existing connection {existing_conn_id}: {e}")
        
        # Issue 132: Verify connection succeeds before continuing
        connection_id = await audio_handler.connect_audio_stream(websocket, call_id)
        if not connection_id:
            logger.error(f"Failed to connect audio stream for call {call_id}", LogCategory.API)
            await websocket.close(code=1011, reason="Failed to connect audio stream")
            return
        
        # Update call context with audio stream handler if not already set
        async with orchestrator._calls_lock:
            if call_id in orchestrator.active_calls:
                call_context = orchestrator.active_calls[call_id]
                if not call_context.audio_stream_handler:
                    call_context.audio_stream_handler = audio_handler
                    # Initialize audio stream for the call context
                    await orchestrator._initialize_audio_stream(call_context)
        
        # Issue 124: Verify STT service availability before starting recognition
        from services.azure_speech_stt import get_speech_to_text_service
        stt_service = get_speech_to_text_service()
        
        if not stt_service:
            logger.warning(f"STT service not available for call {call_id}, continuing without STT", LogCategory.API)
        else:
            # Issue 128: Check if STT recognition is already started
            recognition_active = False
            if hasattr(stt_service, 'is_recognition_active'):
                recognition_active = await stt_service.is_recognition_active(call_id)
            
            if not recognition_active:
                # Register audio processor to feed STT
                async def audio_processor(chunk, connection):
                    # Push audio to STT recognizer
                    await stt_service.process_audio_chunk(call_id, chunk.data)
                
                # Issue 141: Verify audio processor registration succeeds
                try:
                    audio_handler.register_audio_processor(connection_id, audio_processor)
                except Exception as reg_error:
                    logger.error(f"Failed to register audio processor for call {call_id}: {reg_error}", LogCategory.API)
                
                # Start STT continuous recognition
                try:
                    await stt_service.start_continuous_recognition(call_id, primary_language="en-US", secondary_language="es-ES")
                    logger.info(f"Started STT recognition for call {call_id}", LogCategory.API)
                except Exception as e:
                    # Issue 128: Handle case where recognition is already started
                    if "already" in str(e).lower() or "active" in str(e).lower():
                        logger.info(f"STT recognition already active for call {call_id}", LogCategory.API)
                    else:
                        logger.error(f"Failed to start STT recognition for call {call_id}: {e}", LogCategory.API, exception=e)
            else:
                logger.info(f"STT recognition already active for call {call_id}, skipping start", LogCategory.API)
        
        # Handle incoming audio from ACS
        await audio_handler.handle_incoming_audio(connection_id)
        
    except Exception as e:
        logger.error(f"WebSocket audio error: {e}", exc_info=True)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except:
            pass
    finally:
        # Issue 118: Ensure all resources are properly cleaned up on connection failure
        if connection_id:
            try:
                audio_handler = get_audio_stream_handler()
                await audio_handler.disconnect_audio_stream(connection_id)
            except Exception as e:
                logger.error(f"Error cleaning up audio stream for call_connection_id {call_connection_id}: {e}")