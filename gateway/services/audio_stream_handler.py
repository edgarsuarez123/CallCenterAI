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
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect

from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    CallNotFoundError,
    ValidationError,
    ExternalServiceUnavailableError
)
# Import azure_communication_service and call_orchestrator inside functions to avoid circular imports


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
    buffer_size: int = 20  # Maximum number of chunks to buffer
    is_active: bool = True
    language_detected: Optional[str] = None
    
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
        self.audio_processors: Dict[str, Callable] = {}
        self.max_connections = 100
        self.connection_timeout = 300  # 5 minutes
        self.cleanup_interval = 60  # 1 minute
        self._cleanup_task = None
        # Initialize lock for thread safety
        self._connections_lock = asyncio.Lock()
    
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
            # Validate call exists using call_orchestrator (single source of truth)
            # Import here to avoid circular import
            from services.call_orchestrator import get_call_orchestrator
            call_orchestrator = get_call_orchestrator()
            call_context = await call_orchestrator.get_call_context(call_id)
            if not call_context:
                raise CallNotFoundError(call_id)
            
            # Check connection limit and store connection with lock
            async with self._connections_lock:
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
            
            # Start audio streaming for the call
            # Import here to avoid circular import
            from services.azure_communication_service import get_azure_communication_service
            acs_service = get_azure_communication_service()
            await acs_service.start_audio_stream(call_id)
            
            # Get total connections count with lock (thread-safe)
            async with self._connections_lock:
                total_connections = len(self.active_connections)
            
            self.logger.info(
                f"Audio stream connected: {connection_id} for call {call_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
                    "call_id": call_id,
                    "total_connections": total_connections
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
    
    async def handle_incoming_audio(self, connection_id: str, data: Optional[bytes] = None) -> None:
        """
        Handle incoming audio data from WebSocket.
        
        Args:
            connection_id: ID of the connection
            data: Optional audio data (if provided, process it directly; otherwise receive from websocket)
        """
        try:
            # Get connection with lock
            async with self._connections_lock:
                connection = self.active_connections.get(connection_id)
                if not connection:
                    self.logger.warning(f"Connection not found: {connection_id}")
                    return
            
            websocket = connection.websocket
            MAX_AUDIO_CHUNK_SIZE = 64 * 1024  # 64KB max chunk size
            
            # If data is provided, process it directly; otherwise receive from websocket
            if data is not None:
                # Process provided data directly
                if not data or len(data) == 0:
                    self.logger.warning(f"Received empty audio data for connection {connection_id}")
                    return
                
                # Validate audio data size
                if len(data) > MAX_AUDIO_CHUNK_SIZE:
                    self.logger.warning(
                        f"Audio chunk too large ({len(data)} bytes) for connection {connection_id}, skipping",
                        LogCategory.AZURE_COMMUNICATION
                    )
                    return
                
                # Create audio chunk and process
                chunk = AudioChunk(
                    data=data,
                    timestamp=datetime.now(timezone.utc),
                    chunk_id=str(uuid.uuid4()),
                    sequence_number=len(connection.audio_buffer) + 1
                )
                connection.add_audio_chunk(chunk)
                
                # Process audio if processor is registered
                if connection_id in self.audio_processors:
                    await self.audio_processors[connection_id](chunk, connection)
                
                return
            
            # Receive audio data from websocket in a loop
            while connection.is_active:
                try:
                    # Check connection status before receiving data
                    async with self._connections_lock:
                        if connection_id not in self.active_connections or not connection.is_active:
                            self.logger.info(f"Connection {connection_id} is no longer active, stopping audio processing")
                            break
                    
                    # Receive audio data
                    data = await websocket.receive_bytes()
                    
                    # Validate audio data
                    if not data or len(data) == 0:
                        self.logger.warning(f"Received empty audio data for connection {connection_id}")
                        continue
                    
                    if len(data) > MAX_AUDIO_CHUNK_SIZE:
                        self.logger.warning(
                            f"Audio chunk too large ({len(data)} bytes) for connection {connection_id}, skipping",
                            LogCategory.AZURE_COMMUNICATION
                        )
                        continue
                    
                    # Create audio chunk and process
                    chunk = AudioChunk(
                        data=data,
                        timestamp=datetime.now(timezone.utc),
                        chunk_id=str(uuid.uuid4()),
                        sequence_number=len(connection.audio_buffer) + 1
                    )
                    connection.add_audio_chunk(chunk)
                    
                    # Process audio if processor is registered
                    if connection_id in self.audio_processors:
                        await self.audio_processors[connection_id](chunk, connection)
                    
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
            # Get connection with lock
            async with self._connections_lock:
                connection = self.active_connections.get(connection_id)
                if not connection or not connection.is_active:
                    return False
            
            # Check buffer size before sending - split large buffers into smaller chunks
            MAX_AUDIO_BUFFER_SIZE = 128 * 1024  # 128KB max buffer size
            if len(audio_data) > MAX_AUDIO_BUFFER_SIZE:
                self.logger.debug(
                    f"Audio buffer too large ({len(audio_data)} bytes), splitting into chunks",
                    LogCategory.AZURE_COMMUNICATION
                )
                chunk_size = MAX_AUDIO_BUFFER_SIZE
                for i in range(0, len(audio_data), chunk_size):
                    chunk_data = audio_data[i:i + chunk_size]
                    try:
                        await connection.websocket.send_bytes(chunk_data)
                    except Exception as chunk_error:
                        self.logger.error(f"Failed to send audio chunk: {chunk_error}")
                        return False
                return True
            
            # Send via WebSocket
            await connection.websocket.send_bytes(audio_data)
            
            # Update activity (with lock)
            async with self._connections_lock:
                if connection_id in self.active_connections:
                    connection.last_activity = datetime.now(timezone.utc)
            
            self.logger.debug(
                f"Sent audio data for connection {connection_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
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
            # Find connection for this call (with lock)
            connection = None
            async with self._connections_lock:
                for conn in self.active_connections.values():
                    if conn.call_id == call_id and conn.is_active:
                        connection = conn
                        break
            
            if not connection or not connection.is_active:
                self.logger.warning(f"No active connection found for call: {call_id}")
                return False
            
            # Verify connection is still active before sending
            async with self._connections_lock:
                if connection.connection_id not in self.active_connections or not connection.is_active:
                    self.logger.warning(f"Connection {connection.connection_id} is no longer active")
                    return False
            
            # Send audio
            try:
                result = await self.handle_outgoing_audio(connection.connection_id, audio_data, audio_format)
                
                # Verify connection is still active after send
                async with self._connections_lock:
                    if connection.connection_id not in self.active_connections or not connection.is_active:
                        self.logger.warning(f"Connection {connection.connection_id} became inactive during send")
                        return False
                
                return result
            except Exception as conn_error:
                self.logger.error(f"Connection error while sending audio: {conn_error}")
                # Mark connection as inactive on error
                async with self._connections_lock:
                    if connection.connection_id in self.active_connections:
                        self.active_connections[connection.connection_id].is_active = False
                return False
            
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
            # Get connection with lock
            async with self._connections_lock:
                connection = self.active_connections.get(connection_id)
                if not connection:
                    return False
                
                # Mark as inactive
                connection.is_active = False
            
            # Close WebSocket if still open (outside lock to avoid blocking)
            try:
                await connection.websocket.close()
            except Exception:
                pass  # WebSocket might already be closed
            
            # Issue 198: Clean up all resources (processors, buffers) on disconnect
            # Remove audio processors for this connection
            if connection_id in self.audio_processors:
                del self.audio_processors[connection_id]
            
            # Clear audio buffer for this connection
            if hasattr(connection, 'audio_buffer') and connection.audio_buffer:
                connection.audio_buffer.clear()
            
            # Remove from active connections (with lock)
            async with self._connections_lock:
                if connection_id in self.active_connections:
                    del self.active_connections[connection_id]
            
            # Get total connections with lock
            async with self._connections_lock:
                total_connections = len(self.active_connections)
            
            self.logger.info(
                f"Audio stream disconnected: {connection_id}",
                LogCategory.AZURE_COMMUNICATION,
                extra_data={
                    "connection_id": connection_id,
                    "call_id": connection.call_id,
                    "total_connections": total_connections
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
        # Issue 18: Check if processor already exists and merge instead of overwriting
        if connection_id in self.audio_processors:
            existing_processor = self.audio_processors[connection_id]
            # Issue 18: Create wrapper that calls both processors
            async def combined_processor(chunk, connection):
                # Call existing processor
                try:
                    if asyncio.iscoroutinefunction(existing_processor):
                        await existing_processor(chunk, connection)
                    else:
                        existing_processor(chunk, connection)
                except Exception as e:
                    self.logger.error(f"Error in existing processor for {connection_id}: {e}")
                # Call new STT callback
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(chunk, connection)
                    else:
                        callback(chunk, connection)
                except Exception as e:
                    self.logger.error(f"Error in STT callback for {connection_id}: {e}")
            self.audio_processors[connection_id] = combined_processor
            self.logger.warning(
                f"STT callback already exists for connection {connection_id}, merging with existing processor",
                LogCategory.AZURE_COMMUNICATION
            )
        else:
            self.audio_processors[connection_id] = callback
        
        self.logger.info(
            f"STT callback registered: {connection_id}",
            LogCategory.AZURE_COMMUNICATION,
            extra_data={"connection_id": connection_id}
        )
    
    async def _cleanup_inactive_connections(self):
        """Clean up inactive connections periodically."""
        try:
            while True:
                await asyncio.sleep(self.cleanup_interval)
                
                current_time = datetime.now(timezone.utc)
                inactive_connections = []
                
                # Get connections with lock
                async with self._connections_lock:
                    connections_copy = dict(self.active_connections)
                
                for connection_id, connection in connections_copy.items():
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
                    # Get remaining connections count with lock
                    async with self._connections_lock:
                        remaining_connections = len(self.active_connections)
                    
                    self.logger.info(
                        f"Cleaned up {len(inactive_connections)} inactive connections",
                        LogCategory.AZURE_COMMUNICATION,
                        extra_data={
                            "cleaned_connections": len(inactive_connections),
                            "remaining_connections": remaining_connections
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
