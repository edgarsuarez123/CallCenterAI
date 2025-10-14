"""
Azure Text-to-Speech service for real-time audio synthesis.

This service provides:
- Text-to-speech synthesis with streaming
- Bilingual voice support (English/Spanish)
- SSML support for natural-sounding speech
- Voice selection based on detected language
- Integration with audio stream handler
"""

import asyncio
import io
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
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
from services.audio_stream_handler import get_audio_stream_handler


logger = get_logger("azure_speech_tts")


class SynthesisStatus(Enum):
    """Status of TTS synthesis process."""
    IDLE = "idle"
    SYNTHESIZING = "synthesizing"
    STREAMING = "streaming"
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
        
        # Active synthesis sessions by call ID
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.synthesis_status: Dict[str, SynthesisStatus] = {}
        self.synthesis_callbacks: Dict[str, Callable] = {}
        
        # Audio streaming
        self.audio_buffer_size = 4096
        self.streaming_chunk_size = 1024
        
        # Performance tracking
        self.synthesis_stats: Dict[str, Dict[str, Any]] = {}
        
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
            
            # Update status
            if call_id:
                self.synthesis_status[call_id] = SynthesisStatus.SYNTHESIZING
                if synthesis_callback:
                    self.synthesis_callbacks[call_id] = synthesis_callback
            
            # Create SSML
            ssml = self._create_ssml(text, voice_config)
            
            # Synthesize speech
            audio_data = await self._perform_synthesis(ssml, voice_config)
            
            # Create result
            result = SynthesisResult(
                audio_data=audio_data,
                duration_ms=len(audio_data) // 32,  # Approximate duration (16kHz, 16-bit)
                voice=voice_config.name,
                language=voice_config.language,
                text=text,
                ssml=ssml,
                timestamp=datetime.utcnow(),
                result_id=result_id,
                success=True
            )
            
            # Update stats
            if call_id:
                self._update_synthesis_stats(call_id, result)
                self.synthesis_status[call_id] = SynthesisStatus.COMPLETED
            
            # Call callback if registered
            if call_id and call_id in self.synthesis_callbacks:
                try:
                    self.synthesis_callbacks[call_id](result)
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
                timestamp=datetime.utcnow(),
                result_id=f"tts_error_{int(time.time() * 1000)}",
                success=False,
                error_message=str(e)
            )
            
            if call_id:
                self.synthesis_status[call_id] = SynthesisStatus.ERROR
            
            return result
    
    def _create_ssml(self, text: str, voice_config: VoiceConfig) -> str:
        """
        Create SSML markup for natural-sounding speech.
        
        Args:
            text: Text to synthesize
            voice_config: Voice configuration
            
        Returns:
            SSML markup string
        """
        # Escape special characters
        escaped_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Create SSML with voice configuration
        ssml = f"""
        <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{voice_config.language}">
            <voice name="{voice_config.name}">
                <prosody rate="{voice_config.rate}" pitch="{voice_config.pitch}" volume="{voice_config.volume}">
                    {escaped_text}
                </prosody>
            </voice>
        </speak>
        """.strip()
        
        return ssml
    
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
    
    @log_performance("tts_stream_synthesis")
    async def stream_synthesis(self, text: str, language: str = "en", 
                             call_id: str, chunk_callback: Optional[Callable] = None) -> bool:
        """
        Stream text-to-speech synthesis in chunks.
        
        Args:
            text: Text to synthesize
            language: Language code (en/es)
            call_id: ID of the call
            chunk_callback: Callback for audio chunks
            
        Returns:
            True if streaming started successfully
        """
        try:
            # Validate inputs
            if not text or not text.strip():
                raise ValidationError("text", text, "Text cannot be empty")
            
            if language not in self.voice_configs:
                raise ValidationError("language", language, f"Unsupported language: {language}")
            
            # Get voice configuration
            voice_config = self.voice_configs[language]
            
            # Create SSML
            ssml = self._create_ssml(text, voice_config)
            
            # Update status
            self.synthesis_status[call_id] = SynthesisStatus.STREAMING
            
            # Store session info
            self.active_sessions[call_id] = {
                "text": text,
                "language": language,
                "voice_config": voice_config,
                "ssml": ssml,
                "start_time": datetime.utcnow(),
                "chunk_callback": chunk_callback
            }
            
            # Start streaming synthesis
            await self._perform_streaming_synthesis(call_id, ssml, voice_config)
            
            self.logger.info(
                f"Streaming synthesis started for call: {call_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "call_id": call_id,
                    "text_length": len(text),
                    "language": language,
                    "voice": voice_config.name
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to start streaming synthesis for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            
            if call_id in self.synthesis_status:
                self.synthesis_status[call_id] = SynthesisStatus.ERROR
            
            return False
    
    async def _perform_streaming_synthesis(self, call_id: str, ssml: str, voice_config: VoiceConfig):
        """
        Perform streaming synthesis with chunk delivery.
        
        Args:
            call_id: ID of the call
            ssml: SSML markup
            voice_config: Voice configuration
        """
        try:
            # Create audio output stream
            audio_stream = speechsdk.audio.PushAudioOutputStream()
            audio_config = AudioConfig(stream=audio_stream)
            
            # Create synthesizer
            synthesizer = SpeechSynthesizer(
                speech_config=self.speech_config,
                audio_config=audio_config
            )
            
            # Set up event handlers
            def on_synthesizing(evt):
                """Handle synthesizing events (partial audio)."""
                try:
                    if call_id in self.active_sessions:
                        session = self.active_sessions[call_id]
                        
                        # Create synthesis result for chunk
                        chunk_result = SynthesisResult(
                            audio_data=bytes(evt.result.audio_data),
                            duration_ms=len(evt.result.audio_data) // 32,
                            voice=voice_config.name,
                            language=voice_config.language,
                            text=session["text"],
                            ssml=ssml,
                            timestamp=datetime.utcnow(),
                            result_id=f"chunk_{int(time.time() * 1000)}",
                            success=True
                        )
                        
                        # Call chunk callback if registered
                        if session.get("chunk_callback"):
                            try:
                                session["chunk_callback"](chunk_result)
                            except Exception as e:
                                self.logger.error(f"Error in chunk callback: {e}")
                        
                        self.logger.debug(
                            f"TTS chunk synthesized for call {call_id}",
                            LogCategory.AZURE_SPEECH,
                            extra_data={
                                "call_id": call_id,
                                "chunk_size": len(evt.result.audio_data)
                            }
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error processing TTS chunk: {e}")
            
            def on_synthesized(evt):
                """Handle synthesized events (final audio)."""
                try:
                    if call_id in self.active_sessions:
                        session = self.active_sessions[call_id]
                        
                        # Create final synthesis result
                        final_result = SynthesisResult(
                            audio_data=bytes(evt.result.audio_data),
                            duration_ms=len(evt.result.audio_data) // 32,
                            voice=voice_config.name,
                            language=voice_config.language,
                            text=session["text"],
                            ssml=ssml,
                            timestamp=datetime.utcnow(),
                            result_id=f"final_{int(time.time() * 1000)}",
                            success=True
                        )
                        
                        # Update stats
                        self._update_synthesis_stats(call_id, final_result)
                        
                        # Call chunk callback if registered
                        if session.get("chunk_callback"):
                            try:
                                session["chunk_callback"](final_result)
                            except Exception as e:
                                self.logger.error(f"Error in final chunk callback: {e}")
                        
                        self.logger.info(
                            f"TTS synthesis completed for call {call_id}",
                            LogCategory.AZURE_SPEECH,
                            extra_data={
                                "call_id": call_id,
                                "final_audio_size": len(evt.result.audio_data),
                                "total_duration_ms": final_result.duration_ms
                            }
                        )
                        
                except Exception as e:
                    self.logger.error(f"Error processing final TTS result: {e}")
            
            def on_canceled(evt):
                """Handle synthesis cancellation."""
                self.logger.warning(
                    f"TTS synthesis canceled for call {call_id}",
                    LogCategory.AZURE_SPEECH,
                    extra_data={
                        "call_id": call_id,
                        "reason": evt.result.cancellation_details.reason,
                        "error": evt.result.cancellation_details.error_details
                    }
                )
                self.synthesis_status[call_id] = SynthesisStatus.ERROR
            
            # Register event handlers
            synthesizer.synthesizing.connect(on_synthesizing)
            synthesizer.synthesized.connect(on_synthesized)
            synthesizer.canceled.connect(on_canceled)
            
            # Start synthesis
            synthesizer.speak_ssml_async(ssml).get()
            
            # Clean up
            audio_stream.close()
            
            # Update status
            if call_id in self.synthesis_status:
                self.synthesis_status[call_id] = SynthesisStatus.COMPLETED
            
            # Remove session
            if call_id in self.active_sessions:
                del self.active_sessions[call_id]
            
        except Exception as e:
            self.logger.error(
                f"Error in streaming synthesis for call {call_id}: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            
            if call_id in self.synthesis_status:
                self.synthesis_status[call_id] = SynthesisStatus.ERROR
            
            if call_id in self.active_sessions:
                del self.active_sessions[call_id]
    
    async def synthesize_ssml(self, ssml: str, language: str = "en", 
                            call_id: Optional[str] = None) -> SynthesisResult:
        """
        Synthesize speech from SSML markup.
        
        Args:
            ssml: SSML markup to synthesize
            language: Language code (en/es)
            call_id: ID of the call
            
        Returns:
            Synthesis result with audio data
        """
        try:
            # Validate inputs
            if not ssml or not ssml.strip():
                raise ValidationError("ssml", ssml, "SSML cannot be empty")
            
            if language not in self.voice_configs:
                raise ValidationError("language", language, f"Unsupported language: {language}")
            
            # Get voice configuration
            voice_config = self.voice_configs[language]
            
            # Create synthesis result ID
            result_id = f"ssml_{int(time.time() * 1000)}"
            
            # Update status
            if call_id:
                self.synthesis_status[call_id] = SynthesisStatus.SYNTHESIZING
            
            # Perform synthesis
            audio_data = await self._perform_synthesis(ssml, voice_config)
            
            # Create result
            result = SynthesisResult(
                audio_data=audio_data,
                duration_ms=len(audio_data) // 32,  # Approximate duration
                voice=voice_config.name,
                language=voice_config.language,
                text="",  # No plain text for SSML
                ssml=ssml,
                timestamp=datetime.utcnow(),
                result_id=result_id,
                success=True
            )
            
            # Update stats
            if call_id:
                self._update_synthesis_stats(call_id, result)
                self.synthesis_status[call_id] = SynthesisStatus.COMPLETED
            
            self.logger.info(
                f"SSML synthesis completed: {result_id}",
                LogCategory.AZURE_SPEECH,
                extra_data={
                    "result_id": result_id,
                    "call_id": call_id,
                    "ssml_length": len(ssml),
                    "audio_size": len(audio_data),
                    "voice": voice_config.name
                }
            )
            
            return result
            
        except Exception as e:
            self.logger.error(
                f"Failed to synthesize SSML: {e}",
                LogCategory.AZURE_SPEECH,
                exception=e
            )
            
            # Create error result
            result = SynthesisResult(
                audio_data=b'',
                duration_ms=0,
                voice="",
                language=language,
                text="",
                ssml=ssml,
                timestamp=datetime.utcnow(),
                result_id=f"ssml_error_{int(time.time() * 1000)}",
                success=False,
                error_message=str(e)
            )
            
            if call_id:
                self.synthesis_status[call_id] = SynthesisStatus.ERROR
            
            return result
    
    def _update_synthesis_stats(self, call_id: str, result: SynthesisResult):
        """Update synthesis statistics."""
        if call_id not in self.synthesis_stats:
            self.synthesis_stats[call_id] = {
                "start_time": datetime.utcnow(),
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
    
    def get_voice_for_language(self, language: str) -> Optional[VoiceConfig]:
        """
        Get voice configuration for a language.
        
        Args:
            language: Language code (en/es)
            
        Returns:
            Voice configuration or None
        """
        return self.voice_configs.get(language)
    
    def get_synthesis_status(self, call_id: str) -> Optional[SynthesisStatus]:
        """
        Get the current synthesis status for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Current synthesis status or None
        """
        return self.synthesis_status.get(call_id)
    
    def get_synthesis_statistics(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get synthesis statistics for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Synthesis statistics or None
        """
        if call_id not in self.synthesis_stats:
            return None
        
        stats = self.synthesis_stats[call_id].copy()
        stats["duration_seconds"] = (datetime.utcnow() - stats["start_time"]).total_seconds()
        
        if stats["total_syntheses"] > 0:
            stats["success_rate"] = stats["successful_syntheses"] / stats["total_syntheses"]
        else:
            stats["success_rate"] = 0.0
        
        return stats
    
    def get_active_sessions_count(self) -> int:
        """Get count of active synthesis sessions."""
        return len(self.active_sessions)
    
    async def stop_synthesis(self, call_id: str) -> bool:
        """
        Stop synthesis for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            True if synthesis was stopped successfully
        """
        try:
            if call_id in self.active_sessions:
                del self.active_sessions[call_id]
            
            if call_id in self.synthesis_status:
                del self.synthesis_status[call_id]
            
            if call_id in self.synthesis_callbacks:
                del self.synthesis_callbacks[call_id]
            
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
            current_time = datetime.utcnow()
            expired_calls = []
            
            for call_id, stats in self.synthesis_stats.items():
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
