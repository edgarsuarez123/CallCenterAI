"""
Azure Text-to-Speech service for real-time audio synthesis.

This service provides:
- Text-to-speech synthesis
- Bilingual voice support (English/Spanish)
- SSML support for natural-sounding speech
- Voice selection based on detected language
- Integration with audio stream handler
"""

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum

import azure.cognitiveservices.speech as speechsdk
from azure.cognitiveservices.speech import (
    SpeechConfig, 
    AudioConfig, 
    SpeechSynthesizer,
    SpeechSynthesisOutputFormat,
    SpeechSynthesisResult
)

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ExternalServiceUnavailableError,
    ValidationError,
    AzureCommunicationError
)


logger = get_logger("azure_speech_tts")


class SynthesisStatus(Enum):
    """Status of TTS synthesis process."""
    IDLE = "idle"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class SynthesisResult:
    """Result of text-to-speech synthesis."""
    audio_data: bytes
    duration_ms: int
    voice: str
    language: str
    text: str
    ssml: Optional[str]
    timestamp: datetime
    result_id: str
    success: bool
    error_message: Optional[str] = None


@dataclass
class VoiceConfig:
    """Configuration for TTS voice."""
    name: str
    language: str
    gender: str
    style: Optional[str] = None
    rate: str = "medium"
    pitch: str = "medium"
    volume: str = "medium"


class TextToSpeechService:
    """
    Service for Azure Text-to-Speech integration.
    
    Provides text-to-speech synthesis with bilingual support
    and streaming capabilities.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        
        # Speech configuration
        self.speech_key = self.settings.azure.speech.speech_key.get_secret_value()
        self.speech_region = self.settings.azure.speech.speech_region
        self.voice_en = self.settings.azure.speech.tts_voice_en
        self.voice_es = self.settings.azure.speech.tts_voice_es
        
        # Voice configurations
        self.voice_configs = {
            "en": VoiceConfig(
                name=self.voice_en,
                language="en-US",
                gender="female",
                style="friendly"
            ),
            "es": VoiceConfig(
                name=self.voice_es,
                language="es-MX",
                gender="female",
                style="friendly"
            )
        }
        
        # Active synthesis status by call ID
        self.synthesis_status: Dict[str, SynthesisStatus] = {}
        self.synthesis_callbacks: Dict[str, Callable] = {}
        
        # Performance tracking
        self.synthesis_stats: Dict[str, Dict[str, Any]] = {}
        
        # Thread safety locks (both async and sync for different contexts)
        self._synthesis_lock = asyncio.Lock()  # For async operations
        self._sync_lock = threading.Lock()  # For sync event handlers
        
        # Initialize speech configuration
        self._initialize_speech_config()
    
    def _initialize_speech_config(self):
        """Initialize Azure Speech configuration for TTS."""
        try:
            # Create base speech configuration
            self.speech_config = SpeechConfig(
                subscription=self.speech_key,
                region=self.speech_region
            )
            
            # Set output format for streaming
            self.speech_config.set_speech_synthesis_output_format(
                SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
            )
            
            self.logger.info(
                "Azure Text-to-Speech service initialized",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "region": self.speech_region,
                    "voice_en": self.voice_en,
                    "voice_es": self.voice_es
                }
            )
            
        except Exception as e:
            self.logger.error(
                f"Failed to initialize Azure TTS configuration: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            raise ExternalServiceUnavailableError("Azure Speech Services", str(e))
    
    @log_performance("tts_synthesize_speech")
    async def synthesize_speech(self, text: str, language: str = "en", 
                              call_id: Optional[str] = None,
                              synthesis_callback: Optional[Callable] = None) -> SynthesisResult:
        """
        Synthesize speech from text.
        
        Args:
            text: Text to synthesize
            language: Language code (en/es)
            call_id: ID of the call (for streaming)
            synthesis_callback: Callback for synthesis events
            
        Returns:
            Synthesis result with audio data
        """
        try:
            # Validate inputs
            if not text or not text.strip():
                raise ValidationError("text", text, "Text cannot be empty")
            
            if language not in self.voice_configs:
                raise ValidationError("language", language, f"Unsupported language: {language}")
            
            # Get voice configuration
            voice_config = self.voice_configs[language]
            
            # Create synthesis result ID
            result_id = f"tts_{int(time.time() * 1000)}"
            
            # Issue 49, 163: Queue synthesis requests or cancel previous requests for same call
            if call_id:
                async with self._synthesis_lock:
                    # Issue 49: Check if synthesis is already in progress for this call
                    if call_id in self.synthesis_status and self.synthesis_status[call_id] == SynthesisStatus.SYNTHESIZING:
                        # Issue 49: Since synthesis is synchronous, we can't cancel it mid-execution
                        # Instead, we'll skip the new request and log a warning
                        self.logger.warning(
                            f"Synthesis already in progress for call {call_id}, skipping new request",
                            LogCategory.AZURE_SPEECH,
                            extra_data={"call_id": call_id, "text_length": len(text)}
                        )
                        # Return a result indicating the request was skipped
                        return SynthesisResult(
                            audio_data=b'',
                            duration_ms=0,
                            voice="",
                            language=language,
                            text=text,
                            ssml=None,
                            timestamp=datetime.now(timezone.utc),
                            result_id=f"tts_skipped_{int(time.time() * 1000)}",
                            success=False,
                            error_message="Synthesis already in progress for this call"
                        )
                    
                    # Issue 49: Mark synthesis as in progress
                    self.synthesis_status[call_id] = SynthesisStatus.SYNTHESIZING
                    if synthesis_callback:
                        self.synthesis_callbacks[call_id] = synthesis_callback
            
            # Create SSML
            ssml = self._create_ssml(text, voice_config)
            
            # Synthesize speech with latency measurement
            synthesis_start = time.time()
            audio_data = await self._perform_synthesis(ssml, voice_config)
            synthesis_latency_ms = (time.time() - synthesis_start) * 1000
            
            # Record TTS latency metric
            try:
                from services.metrics import get_metrics_service
                metrics_service = get_metrics_service()
                # Get clinic_id from call_id if available (call_id format may include clinic_id)
                clinic_id = call_id.split('_')[0] if call_id and '_' in call_id else 'unknown'
                metrics_service.record_tts_latency(clinic_id, synthesis_latency_ms)
            except Exception as metrics_error:
                self.logger.warning(f"Failed to record TTS latency metric: {metrics_error}")
            
            # Create result
            result = SynthesisResult(
                audio_data=audio_data,
                duration_ms=len(audio_data) // 32,  # Approximate duration (16kHz, 16-bit)
                voice=voice_config.name,
                language=voice_config.language,
                text=text,
                ssml=ssml,
                timestamp=datetime.now(timezone.utc),
                result_id=result_id,
                success=True
            )
            
            # Update stats (with lock)
            if call_id:
                self._update_synthesis_stats(call_id, result)
                # Call callback if registered (with lock)
                async with self._synthesis_lock:
                    callback = self.synthesis_callbacks.get(call_id)
                    # Issue 49: Clear synthesis status and callback when complete
                    self.synthesis_status[call_id] = SynthesisStatus.COMPLETED
                    if call_id in self.synthesis_callbacks:
                        del self.synthesis_callbacks[call_id]
                if callback:
                    try:
                        callback(result)
                    except Exception as e:
                        self.logger.error(f"Error in synthesis callback: {e}")
            
            self.logger.info(
                f"Speech synthesized successfully: {result_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "result_id": result_id,
                    "call_id": call_id,
                    "text_length": len(text),
                    "audio_size": len(audio_data),
                    "voice": voice_config.name,
                    "language": language
                }
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"Failed to synthesize speech: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            
            # Create error result
            result = SynthesisResult(
                audio_data=b'',
                duration_ms=0,
                voice="",
                language=language,
                text=text,
                ssml=None,
                timestamp=datetime.now(timezone.utc),
                result_id=f"tts_error_{int(time.time() * 1000)}",
                success=False,
                error_message=str(e)
            )
            
            if call_id:
                async with self._synthesis_lock:
                    # Issue 49: Clear synthesis status and callback on error
                    self.synthesis_status[call_id] = SynthesisStatus.ERROR
                    if call_id in self.synthesis_callbacks:
                        del self.synthesis_callbacks[call_id]
            
            return result
    
    def _create_ssml(self, text: str, voice_config: VoiceConfig) -> str:
        """
        Create SSML markup for natural-sounding speech with proper XML escaping.
        
        Args:
            text: Text to synthesize
            voice_config: Voice configuration
            
        Returns:
            SSML markup string
        """
        import xml.etree.ElementTree as ET
        
        # Create SSML structure using ElementTree for proper escaping
        speak = ET.Element('speak', {
            'version': '1.0',
            'xmlns': 'http://www.w3.org/2001/10/synthesis',
            'xml:lang': voice_config.language
        })
        
        voice = ET.SubElement(speak, 'voice', {'name': voice_config.name})
        prosody = ET.SubElement(voice, 'prosody', {
            'rate': voice_config.rate,
            'pitch': voice_config.pitch,
            'volume': voice_config.volume
        })
        
        # ElementTree automatically escapes text content
        prosody.text = text
        
        # Convert to string with proper formatting
        ssml_str = ET.tostring(speak, encoding='unicode')
        
        # Add proper indentation for readability
        return ssml_str.replace('><', '>\n<')
    
    async def _perform_synthesis(self, ssml: str, voice_config: VoiceConfig) -> bytes:
        """
        Perform the actual speech synthesis.
        
        Args:
            ssml: SSML markup
            voice_config: Voice configuration
            
        Returns:
            Audio data as bytes
        """
        try:
            # Create synthesizer
            synthesizer = SpeechSynthesizer(
                speech_config=self.speech_config,
                audio_config=None  # We'll get the audio data directly
            )
            
            # Perform synthesis
            result = synthesizer.speak_ssml_async(ssml).get()
            
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                return bytes(result.audio_data)
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                raise AzureCommunicationError(
                    "synthesis_canceled",
                    f"Synthesis canceled: {cancellation_details.reason} - {cancellation_details.error_details}"
                )
            else:
                raise AzureCommunicationError(
                    "synthesis_failed",
                    f"Synthesis failed with reason: {result.reason}"
                )
                
        except Exception as e:
            if isinstance(e, AzureCommunicationError):
                raise
            raise AzureCommunicationError("synthesis_error", str(e))
    
    def _update_synthesis_stats(self, call_id: str, result: SynthesisResult):
        """Update synthesis statistics."""
        # Note: This is called from event handlers which are synchronous
        # Use sync lock for thread safety
        try:
            with self._sync_lock:
                if call_id not in self.synthesis_stats:
                    self.synthesis_stats[call_id] = {
                        "start_time": datetime.now(timezone.utc),
                        "total_syntheses": 0,
                        "successful_syntheses": 0,
                        "total_audio_duration": 0,
                        "total_audio_size": 0
                    }
                
                stats = self.synthesis_stats[call_id]
                stats["total_syntheses"] += 1
                
                if result.success:
                    stats["successful_syntheses"] += 1
                    stats["total_audio_duration"] += result.duration_ms
                    stats["total_audio_size"] += len(result.audio_data)
        except Exception as e:
            self.logger.error(f"Error updating synthesis stats: {e}")
    
    async def stop_synthesis(self, call_id: str) -> bool:
        """
        Stop synthesis for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            True if synthesis was stopped successfully
        """
        try:
            async with self._synthesis_lock:
                if call_id in self.synthesis_status:
                    del self.synthesis_status[call_id]
                if call_id in self.synthesis_callbacks:
                    del self.synthesis_callbacks[call_id]
                if call_id in self.synthesis_stats:
                    del self.synthesis_stats[call_id]
            
            self.logger.info(
                f"Synthesis stopped for call: {call_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={"call_id": call_id}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to stop synthesis for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            return False
    
    async def cleanup_expired_sessions(self):
        """Clean up expired synthesis sessions."""
        try:
            current_time = datetime.now(timezone.utc)
            expired_calls = []
            
            # Get expired calls (with lock)
            async with self._synthesis_lock:
                for call_id, stats in list(self.synthesis_stats.items()):
                    # Clean up sessions older than 1 hour
                    if (current_time - stats["start_time"]).total_seconds() > 3600:
                        expired_calls.append(call_id)
            
            for call_id in expired_calls:
                await self.stop_synthesis(call_id)
                self.logger.info(f"Cleaned up expired TTS session: {call_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired TTS sessions: {e}")


# Global service instance
_text_to_speech_service: Optional[TextToSpeechService] = None


def get_text_to_speech_service() -> TextToSpeechService:
    """Get the global Text-to-Speech Service instance."""
    global _text_to_speech_service
    if _text_to_speech_service is None:
        _text_to_speech_service = TextToSpeechService()
    return _text_to_speech_service
