"""
WebSocket audio stream handler for real-time bidirectional audio communication.

This service provides:
- WebSocket connection management for audio streaming
- Real-time audio processing and buffering
- Integration with Azure Speech Services
- Audio chunk management and streaming
- Connection pooling and lifecycle management
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    CallNotFoundError,
    ValidationError,
    ExternalServiceUnavailableError
)
from services.azure_communication_service import get_azure_communication_service


logger = get_logger("audio_stream_handler")


@dataclass
class AudioChunk:
    """Represents an audio chunk with metadata."""
    data: bytes
    timestamp: datetime
    chunk_id: str
    sequence_number: int
    audio_format: str = "pcm_16khz_16bit_mono"
    language: Optional[str] = None


@dataclass
class AudioStreamConnection:
    """Represents an active audio stream connection."""
    call_id: str
    websocket: WebSocket
    connection_id: str
    connected_at: datetime
    last_activity: datetime
    audio_buffer: List[AudioChunk] = field(default_factory=list)
    buffer_size: int = 100  # Maximum number of chunks to buffer
    is_active: bool = True
    language_detected: Optional[str] = None
    language_locked: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_audio_chunk(self, chunk: AudioChunk):
        """Add audio chunk to buffer, maintaining size limit."""
        self.audio_buffer.append(chunk)
        self.last_activity = datetime.now(timezone.utc)
        
        # Maintain buffer size limit
        if len(self.audio_buffer) > self.buffer_size:
            self.audio_buffer.pop(0)
    
    def get_recent_chunks(self, count: int = 10) -> List[AudioChunk]:
        """Get recent audio chunks."""
        return self.audio_buffer[-count:] if self.audio_buffer else []
    
    def clear_buffer(self):
        """Clear the audio buffer."""
        self.audio_buffer.clear()


class AudioStreamHandler:
    """
    Handles WebSocket audio streaming for real-time communication.
    
    Manages connections, audio buffering, and integration with speech services.
    """
    
    def __init__(self):
        self.logger = logger
        self.active_connections: Dict[str, AudioStreamConnection] = {}
        self.connection_pool: Set[str] = set()
        self.audio_processors: Dict[str, Callable] = {}
        self.max_connections = 100
        self.connection_timeout = 300  # 5 minutes
        self.cleanup_interval = 60  # 1 minute
        self._cleanup_task = None
    
    async def start(self):
        """Start the audio stream handler."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_inactive_connections())
    
    async def stop(self):
        """Stop the audio stream handler."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def connect_audio_stream(self, websocket: WebSocket, call_id: str) -> str:
        """
        Establish audio stream connection for a call.
        
        Args:
            websocket: WebSocket connection
            call_id: ID of the call
            
        Returns:
            Connection ID
            
        Raises:
            CallNotFoundError: If call is not found
            ValidationError: If connection limit exceeded
        """
        try:
            # Validate call exists
            acs_service = get_azure_communication_service()
            call_status = acs_service.get_call_status(call_id)
            if not call_status:
                raise CallNotFoundError(call_id)
            
            # Check connection limit
            if len(self.active_connections) >= self.max_connections:
                raise ValidationError("connection_limit", len(self.active_connections), 
                                    f"Maximum connections ({self.max_connections}) exceeded")
            
            # Accept WebSocket connection
            await websocket.accept()
            
            # Create connection
            connection_id = f"CONN_{call_id}_{uuid.uuid4().hex[:8].upper()}"
            connection = AudioStreamConnection(
                call_id=call_id,
                websocket=websocket,
                connection_id=connection_id,
                connected_at=datetime.now(timezone.utc),
                last_activity=datetime.now(timezone.utc)
            )
            
            # Store connection
            self.active_connections[connection_id] = connection
            self.connection_pool.add(connection_id)
            
            # Start audio streaming for the call
            await acs_service.start_audio_stream(call_id)
            
            self.logger.info(
                f"Audio stream connected: {connection_id} for call {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
                    "call_id": call_id,
                    "total_connections": len(self.active_connections)
                }
            )
            
            return connection_id
            
        except Exception as e:
            self.logger.error(
                f"Failed to connect audio stream for call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            
            if isinstance(e, (CallNotFoundError, ValidationError)):
                raise
            else:
                raise ExternalServiceUnavailableError("Audio Stream Handler", str(e))
    
    async def handle_incoming_audio(self, connection_id: str) -> None:
        """
        Handle incoming audio data from WebSocket.
        
        Args:
            connection_id: ID of the connection
        """
        try:
            connection = self.active_connections.get(connection_id)
            if not connection:
                self.logger.warning(f"Connection not found: {connection_id}")
                return
            
            websocket = connection.websocket
            
            while connection.is_active:
                try:
                    # Receive audio data
                    data = await websocket.receive_bytes()
                    
                    # Create audio chunk
                    chunk = AudioChunk(
                        data=data,
                        timestamp=datetime.now(timezone.utc),
                        chunk_id=str(uuid.uuid4()),
                        sequence_number=len(connection.audio_buffer) + 1
                    )
                    
                    # Add to buffer
                    connection.add_audio_chunk(chunk)
                    
                    # Process audio if processor is registered
                    if connection_id in self.audio_processors:
                        processor = self.audio_processors[connection_id]
                        await processor(chunk, connection)
                    
                    self.logger.debug(
                        f"Received audio chunk: {chunk.chunk_id}",
                        LogCategory.AZURE_COMMUNICATION,
                        extra_data={
                            "connection_id": connection_id,
                            "chunk_id": chunk.chunk_id,
                            "data_size": len(data),
                            "sequence_number": chunk.sequence_number
                        }
                    )
                    
                except WebSocketDisconnect:
                    self.logger.info(f"WebSocket disconnected: {connection_id}")
                    break
                except Exception as e:
                    self.logger.error(
                        f"Error handling incoming audio for {connection_id}: {e}",
                        LogCategory.AZURE_COMMUNICATION,
                        exception=e
                    )
                    break
            
            # Clean up connection
            await self.disconnect_audio_stream(connection_id)
            
        except Exception as e:
            self.logger.error(
                f"Failed to handle incoming audio for {connection_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
    
    async def handle_outgoing_audio(self, connection_id: str, audio_data: bytes, 
                                  audio_format: str = "pcm_16khz_16bit_mono") -> bool:
        """
        Send outgoing audio data via WebSocket.
        
        Args:
            connection_id: ID of the connection
            audio_data: Audio data to send
            audio_format: Format of the audio data
            
        Returns:
            True if audio was sent successfully
        """
        try:
            connection = self.active_connections.get(connection_id)
            if not connection or not connection.is_active:
                return False
            
            # Create audio chunk for outgoing data
            chunk = AudioChunk(
                data=audio_data,
                timestamp=datetime.now(timezone.utc),
                chunk_id=str(uuid.uuid4()),
                sequence_number=len(connection.audio_buffer) + 1,
                audio_format=audio_format
            )
            
            # Send via WebSocket
            await connection.websocket.send_bytes(audio_data)
            
            # Update activity
            connection.last_activity = datetime.now(timezone.utc)
            
            self.logger.debug(
                f"Sent audio chunk: {chunk.chunk_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
                    "chunk_id": chunk.chunk_id,
                    "data_size": len(audio_data),
                    "audio_format": audio_format
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to send outgoing audio for {connection_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    async def send_tts_audio(self, call_id: str, audio_data: bytes, 
                           audio_format: str = "pcm_16khz_16bit_mono") -> bool:
        """
        Send TTS audio to a specific call.
        
        Args:
            call_id: ID of the call
            audio_data: TTS audio data
            audio_format: Format of the audio data
            
        Returns:
            True if audio was sent successfully
        """
        try:
            # Find connection for this call
            connection = None
            for conn in self.active_connections.values():
                if conn.call_id == call_id and conn.is_active:
                    connection = conn
                    break
            
            if not connection:
                self.logger.warning(f"No active connection found for call: {call_id}")
                return False
            
            return await self.handle_outgoing_audio(connection.connection_id, audio_data, audio_format)
            
        except Exception as e:
            self.logger.error(
                f"Failed to send TTS audio for call {call_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    async def disconnect_audio_stream(self, connection_id: str) -> bool:
        """
        Disconnect an audio stream.
        
        Args:
            connection_id: ID of the connection to disconnect
            
        Returns:
            True if disconnected successfully
        """
        try:
            connection = self.active_connections.get(connection_id)
            if not connection:
                return False
            
            # Mark as inactive
            connection.is_active = False
            
            # Close WebSocket if still open
            try:
                await connection.websocket.close()
            except Exception:
                pass  # WebSocket might already be closed
            
            # Remove from active connections
            if connection_id in self.active_connections:
                del self.active_connections[connection_id]
            
            if connection_id in self.connection_pool:
                self.connection_pool.remove(connection_id)
            
            # Remove audio processor if registered
            if connection_id in self.audio_processors:
                del self.audio_processors[connection_id]
            
            self.logger.info(
                f"Audio stream disconnected: {connection_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
                    "call_id": connection.call_id,
                    "total_connections": len(self.active_connections)
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to disconnect audio stream {connection_id}: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )
            return False
    
    def register_audio_processor(self, connection_id: str, processor: Callable):
        """
        Register an audio processor for a connection.
        
        Args:
            connection_id: ID of the connection
            processor: Function to process audio chunks
        """
        self.audio_processors[connection_id] = processor
        
        self.logger.info(
            f"Audio processor registered: {connection_id}",
            LogCategory.AZURE_COMMUNICATION,
            extra_data={"connection_id": connection_id}
        )
    
    def register_stt_callback(self, connection_id: str, callback: Callable):
        """
        Register an STT callback for a connection.
        
        Args:
            connection_id: ID of the connection
            callback: Function to handle STT results
        """
        self.audio_processors[connection_id] = callback
        
        self.logger.info(
            f"STT callback registered: {connection_id}",
            LogCategory.AZURE_COMMUNICATION,
            extra_data={"connection_id": connection_id}
        )
    
    def unregister_audio_processor(self, connection_id: str):
        """
        Unregister an audio processor for a connection.
        
        Args:
            connection_id: ID of the connection
        """
        if connection_id in self.audio_processors:
            del self.audio_processors[connection_id]
            
            self.logger.info(
                f"Audio processor unregistered: {connection_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={"connection_id": connection_id}
            )
    
    def get_connection_status(self, connection_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status of an audio stream connection.
        
        Args:
            connection_id: ID of the connection
            
        Returns:
            Connection status information or None if not found
        """
        connection = self.active_connections.get(connection_id)
        if not connection:
            return None
        
        return {
            "connection_id": connection.connection_id,
            "call_id": connection.call_id,
            "connected_at": connection.connected_at.isoformat(),
            "last_activity": connection.last_activity.isoformat(),
            "is_active": connection.is_active,
            "buffer_size": len(connection.audio_buffer),
            "language_detected": connection.language_detected,
            "language_locked": connection.language_locked,
            "has_processor": connection_id in self.audio_processors
        }
    
    def get_call_connection(self, call_id: str) -> Optional[AudioStreamConnection]:
        """
        Get audio stream connection for a specific call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            AudioStreamConnection or None if not found
        """
        for connection in self.active_connections.values():
            if connection.call_id == call_id and connection.is_active:
                return connection
        return None
    
    def get_active_connections_count(self) -> int:
        """Get count of active connections."""
        return len(self.active_connections)
    
    def get_connection_statistics(self) -> Dict[str, Any]:
        """Get connection statistics."""
        total_connections = len(self.active_connections)
        active_processors = len(self.audio_processors)
        
        # Calculate average buffer size
        total_buffer_size = sum(len(conn.audio_buffer) for conn in self.active_connections.values())
        avg_buffer_size = total_buffer_size / total_connections if total_connections > 0 else 0
        
        # Count connections by call
        call_connections = {}
        for connection in self.active_connections.values():
            call_id = connection.call_id
            call_connections[call_id] = call_connections.get(call_id, 0) + 1
        
        return {
            "total_connections": total_connections,
            "active_processors": active_processors,
            "average_buffer_size": avg_buffer_size,
            "call_connections": call_connections,
            "max_connections": self.max_connections,
            "connection_utilization": (total_connections / self.max_connections) * 100
        }
    
    async def _cleanup_inactive_connections(self):
        """Clean up inactive connections periodically."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                
                current_time = datetime.now(timezone.utc)
                inactive_connections = []
                
                for connection_id, connection in self.active_connections.items():
                    # Check for timeout
                    if (current_time - connection.last_activity).total_seconds() > self.connection_timeout:
                        inactive_connections.append(connection_id)
                    # Check if connection is marked as inactive
                    elif not connection.is_active:
                        inactive_connections.append(connection_id)
                
                # Clean up inactive connections
                for connection_id in inactive_connections:
                    await self.disconnect_audio_stream(connection_id)
                    self.logger.info(f"Cleaned up inactive connection: {connection_id}")
                
                if inactive_connections:
                    self.logger.info(
                        f"Cleaned up {len(inactive_connections)} inactive connections",
                        LogCategory.AZURE_COMMUNICATION,
                        extra_data={
                            "cleaned_connections": len(inactive_connections),
                            "remaining_connections": len(self.active_connections)
                        }
                    )
                
        except asyncio.CancelledError:
            self.logger.info("Cleanup task cancelled")
            raise
        except Exception as e:
            self.logger.error(
                f"Error in connection cleanup task: {e}",
                LogCategory.AZURE_COMMUNICATION,
                exception=e
            )


# Global service instance
_audio_stream_handler: Optional[AudioStreamHandler] = None


def get_audio_stream_handler() -> AudioStreamHandler:
    """Get the global Audio Stream Handler instance."""
    global _audio_stream_handler
    if _audio_stream_handler is None:
        _audio_stream_handler = AudioStreamHandler()
    return _audio_stream_handler
