"""
Azure Speech-to-Text service for real-time audio transcription.

This service provides:
- Continuous speech recognition
- Bilingual language detection (English/Spanish)
- Real-time transcription with confidence scores
- Language locking after detection
- Integration with audio stream handler
"""

import asyncio
import io
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import (
    SpeechConfig, 
    AudioConfig, 
    SpeechRecognizer, 
    AutoDetectSourceLanguageConfig
)

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ExternalServiceUnavailableError,
    ValidationError,
    AzureCommunicationError
)
from services.audio_stream_handler import AudioChunk, get_audio_stream_handler


logger = get_logger("azure_speech_stt")


class TranscriptionStatus(Enum):
    """Status of transcription process."""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    DETECTING_LANGUAGE = "detecting_language"
    LANGUAGE_LOCKED = "language_locked"
    ERROR = "error"


@dataclass
class TranscriptionResult:
    """Result of speech transcription."""
    text: str
    confidence: float
    language: str
    is_final: bool
    timestamp: datetime
    duration_ms: int
    offset_ms: int
    result_id: str


@dataclass
class LanguageDetectionResult:
    """Result of language detection."""
    detected_language: str
    confidence: float
    alternatives: List[Tuple[str, float]]
    timestamp: datetime
    is_locked: bool = False


class SpeechToTextService:
    """
    Service for Azure Speech-to-Text integration.
    
    Provides continuous speech recognition with bilingual support
    and real-time language detection.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        
        # Speech configuration
        self.speech_key = self.settings.azure.speech.speech_key.get_secret_value()
        self.speech_region = self.settings.azure.speech.speech_region
        self.primary_language = self.settings.azure.speech.stt_language_primary
        self.secondary_language = self.settings.azure.speech.stt_language_secondary
        
        # Active recognizers by call ID
        self.active_recognizers: Dict[str, SpeechRecognizer] = {}
        self.recognition_status: Dict[str, TranscriptionStatus] = {}
        self.language_detection_results: Dict[str, LanguageDetectionResult] = {}
        self.transcription_callbacks: Dict[str, Callable] = {}
        self.language_detection_callbacks: Dict[str, Callable] = {}
        self.audio_streams: Dict[str, speechsdk.audio.PushAudioInputStream] = {}
        
        # Audio processing
        self.audio_buffer_size = 4096
        self.max_audio_buffer = 10  # seconds of audio to buffer
        
        # Performance tracking
        self.transcription_stats: Dict[str, Dict[str, Any]] = {}
        
        # Initialize speech configuration
        self._initialize_speech_config()
    
    def _initialize_speech_config(self):
        """Initialize Azure Speech configuration."""
        try:
            # Create base speech configuration
            self.speech_config = SpeechConfig(
                subscription=self.speech_key,
                region=self.speech_region
            )
            
            # Configure for continuous recognition
            self.speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, 
                "5000"
            )
            self.speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, 
                "1000"
            )
            
            # Enable profanity filtering if configured
            if self.settings.azure.speech.enable_profanity_filter:
                self.speech_config.set_profanity(
                    speechsdk.ProfanityOption.Masked
                )
            
            # Configure language detection
            self.language_config = AutoDetectSourceLanguageConfig(
                languages=[self.primary_language, self.secondary_language]
            )
            
            self.logger.info(
                "Azure Speech-to-Text service initialized",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "region": self.speech_region,
                    "primary_language": self.primary_language,
                    "secondary_language": self.secondary_language,
                    "profanity_filter": self.settings.azure.speech.enable_profanity_filter
                }
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to initialize Azure Speech configuration: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            raise ExternalServiceUnavailableError("Azure Speech Services", str(e))
    
    @log_performance("stt_start_recognition")
    async def start_continuous_recognition(self, call_id: str, 
                                         transcription_callback: Optional[Callable] = None,
                                         language_detection_callback: Optional[Callable] = None) -> bool:
        """
        Start continuous speech recognition for a call.
        
        Args:
            call_id: ID of the call
            transcription_callback: Callback function for transcription results
            language_detection_callback: Callback function for language detection results
            
        Returns:
            True if recognition started successfully
        """
        try:
            if call_id in self.active_recognizers:
                self.logger.warning(f"Recognition already active for call: {call_id}")
                return True
            
            # Store callbacks
            if transcription_callback:
                self.transcription_callbacks[call_id] = transcription_callback
            if language_detection_callback:
                self.language_detection_callbacks[call_id] = language_detection_callback
            
            # Initialize status
            self.recognition_status[call_id] = TranscriptionStatus.DETECTING_LANGUAGE
            self.transcription_stats[call_id] = {
                "start_time": datetime.now(timezone.utc),
                "total_transcriptions": 0,
                "final_transcriptions": 0,
                "language_detections": 0,
                "average_confidence": 0.0,
                "total_audio_duration": 0
            }
            
            # Create audio input stream
            audio_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = AudioConfig(stream=audio_stream)
            
            # Store audio stream for this call
            self.audio_streams[call_id] = audio_stream
            
            # Create recognizer with language detection
            recognizer = SpeechRecognizer(
                speech_config=self.speech_config,
                auto_detect_source_language_config=self.language_config,
                audio_config=audio_config
            )
            
            # Set up event handlers
            self._setup_recognition_handlers(recognizer, call_id, audio_stream)
            
            # Start continuous recognition
            recognizer.start_continuous_recognition()
            
            # Store recognizer
            self.active_recognizers[call_id] = recognizer
            
            self.logger.info(
                f"Continuous speech recognition started for call: {call_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "call_id": call_id,
                    "status": self.recognition_status[call_id].value
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to start continuous recognition for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return False
    
    def _setup_recognition_handlers(self, recognizer: SpeechRecognizer, call_id: str, audio_stream):
        """Set up event handlers for speech recognition."""
        
        def on_session_started(evt):
            self.logger.debug(f"Speech recognition session started for call: {call_id}")
            self.recognition_status[call_id] = TranscriptionStatus.LISTENING
        
        def on_session_stopped(evt):
            self.logger.debug(f"Speech recognition session stopped for call: {call_id}")
            self.recognition_status[call_id] = TranscriptionStatus.IDLE
        
        def on_speech_start_detected(evt):
            self.logger.debug(f"Speech start detected for call: {call_id}")
            self.recognition_status[call_id] = TranscriptionStatus.PROCESSING
        
        def on_speech_end_detected(evt):
            self.logger.debug(f"Speech end detected for call: {call_id}")
            self.recognition_status[call_id] = TranscriptionStatus.LISTENING
        
        def on_recognizing(evt):
            """Handle partial recognition results."""
            try:
                if evt.result.reason == speechsdk.ResultReason.RecognizingSpeech:
                    # Create transcription result
                    result = TranscriptionResult(
                        text=evt.result.text,
                        confidence=evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceResponse_JsonResult, 
                            "{}"
                        ),
                        language=evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult,
                            self.primary_language
                        ),
                        is_final=False,
                        timestamp=datetime.now(timezone.utc),
                        duration_ms=0,  # Will be calculated from audio
                        offset_ms=0,    # Will be calculated from audio
                        result_id=f"partial_{int(time.time() * 1000)}"
                    )
                    
                    # Update stats
                    self._update_transcription_stats(call_id, result)
                    
                    # Call callback if registered
                    if call_id in self.transcription_callbacks:
                        try:
                            self.transcription_callbacks[call_id](result)
                        except Exception as e:
                            self.logger.error(f"Error in transcription callback: {e}")
                    
                    self.logger.debug(
                        f"Partial transcription for call {call_id}: {evt.result.text[:50]}...",
                        LogCategory.AZURE_SPEECH,
                        extra_data={
                            "call_id": call_id,
                            "text_length": len(evt.result.text),
                            "confidence": result.confidence
                        }
                    )
                    
            except Exception as e:
                self.logger.error(f"Error processing partial recognition: {e}")
        
        def on_recognized(evt):
            """Handle final recognition results."""
            try:
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    # Parse confidence from JSON result
                    confidence = 0.0
                    try:
                        json_result = json.loads(evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceResponse_JsonResult, 
                            "{}"
                        ))
                        confidence = json_result.get("Confidence", 0.0)
                    except (json.JSONDecodeError, KeyError):
                        confidence = 0.0
                    
                    # Create transcription result
                    result = TranscriptionResult(
                        text=evt.result.text,
                        confidence=confidence,
                        language=evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult,
                            self.primary_language
                        ),
                        is_final=True,
                        timestamp=datetime.now(timezone.utc),
                        duration_ms=0,  # Will be calculated from audio
                        offset_ms=0,    # Will be calculated from audio
                        result_id=f"final_{int(time.time() * 1000)}"
                    )
                    
                    # Update stats
                    self._update_transcription_stats(call_id, result)
                    
                    # Call callback if registered
                    if call_id in self.transcription_callbacks:
                        try:
                            self.transcription_callbacks[call_id](result)
                        except Exception as e:
                            self.logger.error(f"Error in transcription callback: {e}")
                    
                    self.logger.info(
                        f"Final transcription for call {call_id}: {evt.result.text}",
                        LogCategory.AZURE_SPEECH,
                        extra_data={
                            "call_id": call_id,
                            "text": evt.result.text,
                            "confidence": confidence,
                            "language": result.language
                        }
                    )
                    
            except Exception as e:
                self.logger.error(f"Error processing final recognition: {e}")
        
        def on_canceled(evt):
            """Handle recognition cancellation."""
            self.logger.warning(
                f"Speech recognition canceled for call {call_id}: {evt.result.reason}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "call_id": call_id,
                    "reason": evt.result.reason.name,
                    "error_details": evt.result.error_details
                }
            )
            self.recognition_status[call_id] = TranscriptionStatus.ERROR
        
        # Register event handlers
        recognizer.session_started.connect(on_session_started)
        recognizer.session_stopped.connect(on_session_stopped)
        recognizer.speech_start_detected.connect(on_speech_start_detected)
        recognizer.speech_end_detected.connect(on_speech_end_detected)
        recognizer.recognizing.connect(on_recognizing)
        recognizer.recognized.connect(on_recognized)
        recognizer.canceled.connect(on_canceled)
    
    def _update_transcription_stats(self, call_id: str, result: TranscriptionResult):
        """Update transcription statistics."""
        if call_id not in self.transcription_stats:
            return
        
        stats = self.transcription_stats[call_id]
        stats["total_transcriptions"] += 1
        
        if result.is_final:
            stats["final_transcriptions"] += 1
        
        # Update average confidence
        total_confidence = stats["average_confidence"] * (stats["total_transcriptions"] - 1)
        stats["average_confidence"] = (total_confidence + result.confidence) / stats["total_transcriptions"]
    
    async def process_audio_chunk(self, call_id: str, audio_chunk: AudioChunk) -> bool:
        """
        Process an audio chunk for speech recognition.
        
        Args:
            call_id: ID of the call
            audio_chunk: Audio chunk to process
            
        Returns:
            True if audio was processed successfully
        """
        try:
            if call_id not in self.active_recognizers:
                return False
            
            recognizer = self.active_recognizers[call_id]
            
            # Get the audio input stream from the recognizer
            # Note: In a real implementation, you would need to access the stream
            # This is a simplified version for demonstration
            
            # For now, we'll simulate processing
            self.logger.debug(
                f"Processing audio chunk for call {call_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "call_id": call_id,
                    "chunk_id": audio_chunk.chunk_id,
                    "data_size": len(audio_chunk.data),
                    "sequence_number": audio_chunk.sequence_number
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to process audio chunk for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return False
    
    async def detect_language(self, call_id: str, audio_samples: List[AudioChunk]) -> Optional[LanguageDetectionResult]:
        """
        Detect the primary language from audio samples.
        
        Args:
            call_id: ID of the call
            audio_samples: List of audio chunks to analyze
            
        Returns:
            Language detection result or None if detection fails
        """
        try:
            if not audio_samples:
                return None
            
            # Combine audio samples for analysis
            combined_audio = b''.join(chunk.data for chunk in audio_samples)
            
            # Create a temporary recognizer for language detection
            audio_stream = speechsdk.audio.PushAudioInputStream()
            audio_config = AudioConfig(stream=audio_stream)
            
            recognizer = SpeechRecognizer(
                speech_config=self.speech_config,
                auto_detect_source_language_config=self.language_config,
                audio_config=audio_config
            )
            
            # Set up language detection callback
            detection_result = None
            
            def on_language_detected(evt):
                nonlocal detection_result
                try:
                    if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                        detected_language = evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult,
                            self.primary_language
                        )
                        
                        # Parse confidence from JSON
                        confidence = 0.0
                        try:
                            json_result = json.loads(evt.result.properties.get(
                                speechsdk.PropertyId.SpeechServiceResponse_JsonResult, 
                                "{}"
                            ))
                            confidence = json_result.get("Confidence", 0.0)
                        except (json.JSONDecodeError, KeyError):
                            confidence = 0.0
                        
                        detection_result = LanguageDetectionResult(
                            detected_language=detected_language,
                            confidence=confidence,
                            alternatives=[(self.primary_language, 1.0 - confidence)],
                            timestamp=datetime.now(timezone.utc)
                        )
                        
                        self.logger.info(
                            f"Language detected for call {call_id}: {detected_language} (confidence: {confidence})",
                            LogCategory.AZURE_SPEECH,
                            extra_data={
                                "call_id": call_id,
                                "detected_language": detected_language,
                                "confidence": confidence
                            }
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error in language detection: {e}")
            
            recognizer.recognized.connect(on_language_detected)
            
            # Start recognition
            recognizer.start_continuous_recognition()
            
            # Push audio data
            audio_stream.write(combined_audio)
            
            # Wait for detection (with timeout)
            start_time = time.time()
            while detection_result is None and (time.time() - start_time) < 5.0:
                await asyncio.sleep(0.1)
            
            # Stop recognition
            recognizer.stop_continuous_recognition()
            audio_stream.close()
            
            # Store result
            if detection_result:
                self.language_detection_results[call_id] = detection_result
                
                # Call callback if registered
                if call_id in self.language_detection_callbacks:
                    try:
                        self.language_detection_callbacks[call_id](detection_result)
                    except Exception as e:
                        self.logger.error(f"Error in language detection callback: {e}")
            
            return detection_result
            
        except Exception as e:
            self.logger.error(
                f"Failed to detect language for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return None
    
    def lock_language(self, call_id: str, language: str) -> bool:
        """
        Lock the language for a call after detection.
        
        Args:
            call_id: ID of the call
            language: Language to lock to
            
        Returns:
            True if language was locked successfully
        """
        try:
            if call_id not in self.language_detection_results:
                return False
            
            # Update detection result
            detection_result = self.language_detection_results[call_id]
            detection_result.is_locked = True
            
            # Update recognition status
            self.recognition_status[call_id] = TranscriptionStatus.LANGUAGE_LOCKED
            
            self.logger.info(
                f"Language locked for call {call_id}: {language}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "call_id": call_id,
                    "locked_language": language
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to lock language for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return False
    
    async def stop_continuous_recognition(self, call_id: str) -> bool:
        """
        Stop continuous speech recognition for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            True if recognition was stopped successfully
        """
        try:
            if call_id not in self.active_recognizers:
                return True  # Already stopped
            
            recognizer = self.active_recognizers[call_id]
            
            # Disconnect all event handlers to prevent memory leak
            try:
                recognizer.session_started.disconnect_all()
                recognizer.session_stopped.disconnect_all()
                recognizer.speech_start_detected.disconnect_all()
                recognizer.speech_end_detected.disconnect_all()
                recognizer.recognizing.disconnect_all()
                recognizer.recognized.disconnect_all()
                recognizer.canceled.disconnect_all()
            except Exception as e:
                self.logger.warning(f"Error disconnecting STT handlers: {e}")
            
            # Stop recognition
            recognizer.stop_continuous_recognition()
            
            # Clean up audio stream and close native resources
            if call_id in self.audio_streams:
                audio_stream = self.audio_streams[call_id]
                audio_stream.close()  # Close native resources
                del self.audio_streams[call_id]
            
            # Clean up other resources
            del self.active_recognizers[call_id]
            if call_id in self.recognition_status:
                del self.recognition_status[call_id]
            if call_id in self.transcription_callbacks:
                del self.transcription_callbacks[call_id]
            if call_id in self.language_detection_callbacks:
                del self.language_detection_callbacks[call_id]
            
            self.logger.info(
                f"Continuous speech recognition stopped for call: {call_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={"call_id": call_id}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to stop continuous recognition for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return False
    
    def get_partial_result(self, call_id: str) -> Optional[TranscriptionResult]:
        """
        Get the most recent partial transcription result.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Most recent partial result or None
        """
        # In a real implementation, you would store and return the latest partial result
        # For now, return None as this would require additional state management
        return None
    
    def get_final_result(self, call_id: str) -> Optional[TranscriptionResult]:
        """
        Get the most recent final transcription result.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Most recent final result or None
        """
        # In a real implementation, you would store and return the latest final result
        # For now, return None as this would require additional state management
        return None
    
    def get_recognition_status(self, call_id: str) -> Optional[TranscriptionStatus]:
        """
        Get the current recognition status for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Current recognition status or None
        """
        return self.recognition_status.get(call_id)
    
    def get_language_detection_result(self, call_id: str) -> Optional[LanguageDetectionResult]:
        """
        Get the language detection result for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Language detection result or None
        """
        return self.language_detection_results.get(call_id)
    
    def get_transcription_statistics(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get transcription statistics for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Transcription statistics or None
        """
        if call_id not in self.transcription_stats:
            return None
        
        stats = self.transcription_stats[call_id].copy()
        stats["duration_seconds"] = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds()
        return stats
    
    def get_active_calls_count(self) -> int:
        """Get count of active recognition sessions."""
        return len(self.active_recognizers)
    
    async def process_audio_chunk(self, call_id: str, audio_data: bytes):
        """
        Process audio chunk from WebSocket stream.
        
        Args:
            call_id: ID of the call
            audio_data: Raw audio bytes (PCM 16kHz 16-bit mono)
        """
        try:
            if call_id not in self.active_recognizers:
                self.logger.warning(f"No active recognizer for call {call_id}")
                return
            
            # Get audio stream for this recognizer
            audio_stream = self.audio_streams.get(call_id)
            if audio_stream:
                # Push audio data to recognizer
                audio_stream.write(audio_data)
                
                self.logger.debug(
                    f"Pushed audio chunk to STT",
                    LogCategory.AZURE_SPEECH,
                    extra_data={
                        "call_id": call_id,
                        "chunk_size": len(audio_data)
                    }
                )
            
        except Exception as e:
            self.logger.error(f"Failed to process audio chunk for {call_id}: {e}")
    
    async def cleanup_expired_sessions(self):
        """Clean up expired recognition sessions."""
        try:
            current_time = datetime.now(timezone.utc)
            expired_calls = []
            
            for call_id, stats in self.transcription_stats.items():
                # Clean up sessions older than 1 hour
                if (current_time - stats["start_time"]).total_seconds() > 3600:
                    expired_calls.append(call_id)
            
            for call_id in expired_calls:
                await self.stop_continuous_recognition(call_id)
                self.logger.info(f"Cleaned up expired STT session: {call_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired STT sessions: {e}")


# Global service instance
_speech_to_text_service: Optional[SpeechToTextService] = None


def get_speech_to_text_service() -> SpeechToTextService:
    """Get the global Speech-to-Text Service instance."""
    global _speech_to_text_service
    if _speech_to_text_service is None:
        _speech_to_text_service = SpeechToTextService()
    return _speech_to_text_service


def get_stt_service() -> SpeechToTextService:
    """Get the global Speech-to-Text Service instance (alias)."""
    return get_speech_to_text_service()
