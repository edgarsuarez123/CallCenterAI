"""
Bilingual support manager for language detection and locking.

This service provides:
- Language detection and switching
- Thread-safe language locking
- Bilingual conversation management
- Language preference persistence
- Automatic language fallback
"""

import asyncio
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from services.configuration import get_settings
from services.structured_logging import get_logger, LogCategory, log_performance
from services.exceptions import (
    ValidationError,
    ExternalServiceUnavailableError,
    ConcurrencyError
)


logger = get_logger("bilingual_manager")


class LanguageCode(Enum):
    """Supported language codes."""
    ENGLISH = "en"
    SPANISH = "es"
    AUTO = "auto"


class LanguageConfidence(Enum):
    """Language detection confidence levels."""
    HIGH = "high"      # > 0.8
    MEDIUM = "medium"  # 0.5 - 0.8
    LOW = "low"        # < 0.5


@dataclass
class LanguageDetection:
    """Result of language detection."""
    detected_language: LanguageCode
    confidence: float
    confidence_level: LanguageConfidence
    detection_method: str
    timestamp: datetime
    context: Optional[str] = None
    fallback_used: bool = False


@dataclass
class LanguageLock:
    """Language lock for a conversation."""
    call_id: str
    locked_language: LanguageCode
    lock_timestamp: datetime
    lock_duration: int  # seconds
    lock_reason: str
    locked_by: str  # service or user
    auto_release: bool = True


@dataclass
class ConversationContext:
    """Context for a bilingual conversation."""
    call_id: str
    primary_language: LanguageCode
    detected_language: Optional[LanguageCode]
    language_history: List[LanguageDetection]
    user_preference: Optional[LanguageCode]
    system_preference: Optional[LanguageCode]
    lock: Optional[LanguageLock]
    created_at: datetime
    updated_at: datetime
    total_switches: int = 0
    last_switch_time: Optional[datetime] = None


class BilingualManager:
    """
    Manages bilingual support for the call center.
    
    Provides language detection, switching, and locking capabilities
    for seamless bilingual conversations.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        
        # Language detection settings
        self.detection_threshold_high = 0.8
        self.detection_threshold_medium = 0.5
        self.min_detection_samples = 3
        self.detection_window_seconds = 30
        
        # Language switching settings
        self.max_switches_per_minute = 3
        self.switch_cooldown_seconds = 10
        self.auto_lock_after_switches = 5
        
        # Conversation contexts by call ID
        self.conversations: Dict[str, ConversationContext] = {}
        
        # Language locks
        self.language_locks: Dict[str, LanguageLock] = {}
        
        # Detection history for pattern analysis
        self.detection_history: Dict[str, List[LanguageDetection]] = defaultdict(list)
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Language detection callbacks
        self.detection_callbacks: List[Callable] = []
        
        # Performance tracking
        self.detection_stats: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info(
            "Bilingual Manager initialized",
            LogCategory.LANGUAGE_DETECTION,
            extra_data={
                "detection_threshold_high": self.detection_threshold_high,
                "detection_threshold_medium": self.detection_threshold_medium,
                "max_switches_per_minute": self.max_switches_per_minute
            }
        )
    
    @log_performance("bilingual_detect_language")
    async def detect_language(self, text: str, call_id: str, 
                            detection_method: str = "text_analysis",
                            context: Optional[str] = None) -> LanguageDetection:
        """
        Detect the language of the given text.
        
        Args:
            text: Text to analyze
            call_id: ID of the call
            detection_method: Method used for detection
            context: Additional context for detection
            
        Returns:
            Language detection result
        """
        try:
            # Validate inputs
            if not text or not text.strip():
                raise ValidationError("text", text, "Text cannot be empty")
            
            if not call_id:
                raise ValidationError("call_id", call_id, "Call ID cannot be empty")
            
            # Perform language detection
            detected_language, confidence = await self._analyze_text_language(text)
            
            # Determine confidence level
            if confidence >= self.detection_threshold_high:
                confidence_level = LanguageConfidence.HIGH
            elif confidence >= self.detection_threshold_medium:
                confidence_level = LanguageConfidence.MEDIUM
            else:
                confidence_level = LanguageConfidence.LOW
            
            # Create detection result
            detection = LanguageDetection(
                detected_language=detected_language,
                confidence=confidence,
                confidence_level=confidence_level,
                detection_method=detection_method,
                timestamp=datetime.now(timezone.utc),
                context=context
            )
            
            # Store detection history
            with self._lock:
                self.detection_history[call_id].append(detection)
                
                # Limit history size
                if len(self.detection_history[call_id]) > 100:
                    self.detection_history[call_id] = self.detection_history[call_id][-50:]
            
            # Update conversation context
            await self._update_conversation_context(call_id, detection)
            
            # Update statistics
            self._update_detection_stats(call_id, detection)
            
            # Call detection callbacks
            for callback in self.detection_callbacks:
                try:
                    await callback(call_id, detection)
                except Exception as e:
                    self.logger.error(f"Error in language detection callback: {e}")
            
            self.logger.info(
                f"Language detected for call {call_id}",
                LogCategory.LANGUAGE_DETECTION,
                extra_data={
                    "call_id": call_id,
                    "detected_language": detected_language.value,
                    "confidence": confidence,
                    "confidence_level": confidence_level.value,
                    "detection_method": detection_method,
                    "text_length": len(text)
                }
            )
            
            return detection
            
        except Exception as e:
            self.logger.error(
                f"Failed to detect language for call {call_id}: {e}",
                LogCategory.LANGUAGE_DETECTION,
                exception=e
            )
            raise
    
    async def _analyze_text_language(self, text: str) -> tuple[LanguageCode, float]:
        """
        Analyze text to determine language and confidence.
        
        Args:
            text: Text to analyze
            
        Returns:
            Tuple of (language_code, confidence)
        """
        try:
            # Simple language detection based on character patterns
            # In a real implementation, this would use Azure Cognitive Services
            # or other language detection APIs
            
            text_lower = text.lower()
            
            # English indicators
            english_indicators = [
                "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
                "by", "from", "up", "about", "into", "through", "during", "before",
                "after", "above", "below", "between", "among", "is", "are", "was",
                "were", "be", "been", "being", "have", "has", "had", "do", "does",
                "did", "will", "would", "could", "should", "may", "might", "can"
            ]
            
            # Spanish indicators
            spanish_indicators = [
                "el", "la", "los", "las", "un", "una", "de", "del", "en", "con",
                "por", "para", "sobre", "entre", "durante", "después", "antes",
                "es", "son", "está", "están", "ser", "estar", "tener", "haber",
                "hacer", "poder", "deber", "querer", "saber", "conocer", "ver",
                "oír", "decir", "ir", "venir", "salir", "entrar", "llegar"
            ]
            
            # Count indicators
            english_count = sum(1 for word in english_indicators if word in text_lower)
            spanish_count = sum(1 for word in spanish_indicators if word in text_lower)
            
            # Calculate confidence based on word matches
            total_words = len(text.split())
            if total_words == 0:
                return LanguageCode.ENGLISH, 0.5  # Default fallback
            
            english_ratio = english_count / total_words
            spanish_ratio = spanish_count / total_words
            
            # Determine language and confidence
            if english_ratio > spanish_ratio:
                confidence = min(english_ratio * 2, 1.0)  # Scale up confidence
                return LanguageCode.ENGLISH, confidence
            elif spanish_ratio > english_ratio:
                confidence = min(spanish_ratio * 2, 1.0)  # Scale up confidence
                return LanguageCode.SPANISH, confidence
            else:
                # Ambiguous, default to English with low confidence
                return LanguageCode.ENGLISH, 0.3
            
        except Exception as e:
            self.logger.error(f"Error analyzing text language: {e}")
            return LanguageCode.ENGLISH, 0.5  # Safe fallback
    
    async def _update_conversation_context(self, call_id: str, detection: LanguageDetection):
        """Update conversation context with new language detection."""
        try:
            with self._lock:
                if call_id not in self.conversations:
                    # Create new conversation context
                    self.conversations[call_id] = ConversationContext(
                        call_id=call_id,
                        primary_language=LanguageCode.ENGLISH,  # Default
                        detected_language=detection.detected_language,
                        language_history=[detection],
                        user_preference=None,
                        system_preference=None,
                        lock=None,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                else:
                    # Update existing context
                    context = self.conversations[call_id]
                    context.detected_language = detection.detected_language
                    context.language_history.append(detection)
                    context.updated_at = datetime.now(timezone.utc)
                    
                    # Limit history size
                    if len(context.language_history) > 50:
                        context.language_history = context.language_history[-25:]
                    
                    # Check for language switches
                    if len(context.language_history) >= 2:
                        last_detection = context.language_history[-2]
                        if (last_detection.detected_language != detection.detected_language and
                            detection.confidence >= self.detection_threshold_medium):
                            context.total_switches += 1
                            context.last_switch_time = datetime.now(timezone.utc)
                            
                            self.logger.info(
                                f"Language switch detected for call {call_id}",
                                LogCategory.LANGUAGE_DETECTION,
                                extra_data={
                                    "call_id": call_id,
                                    "from_language": last_detection.detected_language.value,
                                    "to_language": detection.detected_language.value,
                                    "total_switches": context.total_switches
                                }
                            )
                            
                            # Auto-lock if too many switches
                            if (context.total_switches >= self.auto_lock_after_switches and
                                not context.lock):
                                await self.lock_language(
                                    call_id=call_id,
                                    language=detection.detected_language,
                                    reason="auto_lock_excessive_switches",
                                    locked_by="system"
                                )
                
        except Exception as e:
            self.logger.error(f"Failed to update conversation context: {e}")
    
    @log_performance("bilingual_lock_language")
    async def lock_language(self, call_id: str, language: LanguageCode,
                          reason: str, locked_by: str,
                          duration: int = 300, auto_release: bool = True) -> bool:
        """
        Lock the language for a conversation.
        
        Args:
            call_id: ID of the call
            language: Language to lock to
            reason: Reason for locking
            locked_by: Who is locking the language
            duration: Lock duration in seconds
            auto_release: Whether to auto-release the lock
            
        Returns:
            True if language was locked successfully
        """
        try:
            with self._lock:
                # Check if already locked
                if call_id in self.language_locks:
                    existing_lock = self.language_locks[call_id]
                    if existing_lock.locked_language == language:
                        # Extend existing lock
                        existing_lock.lock_duration = duration
                        existing_lock.lock_timestamp = datetime.now(timezone.utc)
                        self.logger.info(f"Extended language lock for call {call_id}")
                        return True
                    else:
                        raise ConcurrencyError(
                            "language_already_locked",
                            f"Call {call_id} already has language locked to {existing_lock.locked_language.value}"
                        )
                
                # Create new lock
                language_lock = LanguageLock(
                    call_id=call_id,
                    locked_language=language,
                    lock_timestamp=datetime.now(timezone.utc),
                    lock_duration=duration,
                    lock_reason=reason,
                    locked_by=locked_by,
                    auto_release=auto_release
                )
                
                self.language_locks[call_id] = language_lock
                
                # Update conversation context
                if call_id in self.conversations:
                    self.conversations[call_id].lock = language_lock
                
                # Schedule auto-release if enabled
                if auto_release:
                    asyncio.create_task(self._auto_release_lock(call_id, duration))
                
                self.logger.info(
                    f"Language locked for call {call_id}",
                    LogCategory.LANGUAGE_DETECTION,
                    extra_data={
                        "call_id": call_id,
                        "locked_language": language.value,
                        "reason": reason,
                        "locked_by": locked_by,
                        "duration": duration
                    }
                )
                
                return True
                
        except Exception as e:
            self.logger.error(
                f"Failed to lock language for call {call_id}: {e}",
                LogCategory.LANGUAGE_DETECTION,
                exception=e
            )
            raise
    
    async def _auto_release_lock(self, call_id: str, duration: int):
        """Auto-release a language lock after the specified duration."""
        try:
            await asyncio.sleep(duration)
            await self.unlock_language(call_id, "auto_release")
        except Exception as e:
            self.logger.error(f"Failed to auto-release lock for call {call_id}: {e}")
    
    @log_performance("bilingual_unlock_language")
    async def unlock_language(self, call_id: str, reason: str) -> bool:
        """
        Unlock the language for a conversation.
        
        Args:
            call_id: ID of the call
            reason: Reason for unlocking
            
        Returns:
            True if language was unlocked successfully
        """
        try:
            with self._lock:
                if call_id not in self.language_locks:
                    self.logger.warning(f"No language lock found for call {call_id}")
                    return False
                
                # Remove lock
                del self.language_locks[call_id]
                
                # Update conversation context
                if call_id in self.conversations:
                    self.conversations[call_id].lock = None
                
                self.logger.info(
                    f"Language unlocked for call {call_id}",
                    LogCategory.LANGUAGE_DETECTION,
                    extra_data={
                        "call_id": call_id,
                        "reason": reason
                    }
                )
                
                return True
                
        except Exception as e:
            self.logger.error(
                f"Failed to unlock language for call {call_id}: {e}",
                LogCategory.LANGUAGE_DETECTION,
                exception=e
            )
            return False
    
    def get_current_language(self, call_id: str) -> Optional[LanguageCode]:
        """
        Get the current language for a conversation.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Current language or None
        """
        try:
            with self._lock:
                # Check for active lock first
                if call_id in self.language_locks:
                    lock = self.language_locks[call_id]
                    # Check if lock is still valid
                    if (datetime.now(timezone.utc) - lock.lock_timestamp).total_seconds() < lock.lock_duration:
                        return lock.locked_language
                    else:
                        # Lock expired, remove it
                        del self.language_locks[call_id]
                
                # Check conversation context
                if call_id in self.conversations:
                    context = self.conversations[call_id]
                    if context.detected_language:
                        return context.detected_language
                    return context.primary_language
                
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to get current language for call {call_id}: {e}")
            return None
    
    def get_language_preference(self, call_id: str) -> Optional[LanguageCode]:
        """
        Get the language preference for a conversation.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Language preference or None
        """
        try:
            with self._lock:
                if call_id in self.conversations:
                    context = self.conversations[call_id]
                    return context.user_preference or context.system_preference
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to get language preference for call {call_id}: {e}")
            return None
    
    def set_language_preference(self, call_id: str, language: LanguageCode, 
                              preference_type: str = "user") -> bool:
        """
        Set the language preference for a conversation.
        
        Args:
            call_id: ID of the call
            language: Preferred language
            preference_type: Type of preference (user/system)
            
        Returns:
            True if preference was set successfully
        """
        try:
            with self._lock:
                if call_id not in self.conversations:
                    # Create new conversation context
                    self.conversations[call_id] = ConversationContext(
                        call_id=call_id,
                        primary_language=language,
                        detected_language=None,
                        language_history=[],
                        user_preference=None,
                        system_preference=None,
                        lock=None,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                
                context = self.conversations[call_id]
                
                if preference_type == "user":
                    context.user_preference = language
                elif preference_type == "system":
                    context.system_preference = language
                else:
                    raise ValidationError("preference_type", preference_type, 
                                        "Preference type must be 'user' or 'system'")
                
                context.updated_at = datetime.now(timezone.utc)
                
                self.logger.info(
                    f"Language preference set for call {call_id}",
                    LogCategory.LANGUAGE_DETECTION,
                    extra_data={
                        "call_id": call_id,
                        "language": language.value,
                        "preference_type": preference_type
                    }
                )
                
                return True
                
        except Exception as e:
            self.logger.error(
                f"Failed to set language preference for call {call_id}: {e}",
                LogCategory.LANGUAGE_DETECTION,
                exception=e
            )
            return False
    
    def get_conversation_context(self, call_id: str) -> Optional[ConversationContext]:
        """
        Get the conversation context for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Conversation context or None
        """
        try:
            with self._lock:
                return self.conversations.get(call_id)
        except Exception as e:
            self.logger.error(f"Failed to get conversation context for call {call_id}: {e}")
            return None
    
    def get_detection_history(self, call_id: str, limit: int = 10) -> List[LanguageDetection]:
        """
        Get language detection history for a call.
        
        Args:
            call_id: ID of the call
            limit: Maximum number of detections to return
            
        Returns:
            List of language detections
        """
        try:
            with self._lock:
                history = self.detection_history.get(call_id, [])
                return history[-limit:] if limit > 0 else history
        except Exception as e:
            self.logger.error(f"Failed to get detection history for call {call_id}: {e}")
            return []
    
    def register_detection_callback(self, callback: Callable):
        """Register a callback for language detection events."""
        self.detection_callbacks.append(callback)
    
    def unregister_detection_callback(self, callback: Callable):
        """Unregister a language detection callback."""
        if callback in self.detection_callbacks:
            self.detection_callbacks.remove(callback)
    
    def _update_detection_stats(self, call_id: str, detection: LanguageDetection):
        """Update language detection statistics."""
        if call_id not in self.detection_stats:
            self.detection_stats[call_id] = {
                "start_time": datetime.now(timezone.utc),
                "total_detections": 0,
                "high_confidence_detections": 0,
                "medium_confidence_detections": 0,
                "low_confidence_detections": 0,
                "language_counts": defaultdict(int)
            }
        
        stats = self.detection_stats[call_id]
        stats["total_detections"] += 1
        stats["language_counts"][detection.detected_language.value] += 1
        
        if detection.confidence_level == LanguageConfidence.HIGH:
            stats["high_confidence_detections"] += 1
        elif detection.confidence_level == LanguageConfidence.MEDIUM:
            stats["medium_confidence_detections"] += 1
        else:
            stats["low_confidence_detections"] += 1
    
    def get_detection_statistics(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Get language detection statistics for a call.
        
        Args:
            call_id: ID of the call
            
        Returns:
            Detection statistics or None
        """
        if call_id not in self.detection_stats:
            return None
        
        stats = self.detection_stats[call_id].copy()
        stats["duration_seconds"] = (datetime.now(timezone.utc) - stats["start_time"]).total_seconds()
        
        if stats["total_detections"] > 0:
            stats["high_confidence_rate"] = stats["high_confidence_detections"] / stats["total_detections"]
            stats["medium_confidence_rate"] = stats["medium_confidence_detections"] / stats["total_detections"]
            stats["low_confidence_rate"] = stats["low_confidence_detections"] / stats["total_detections"]
        else:
            stats["high_confidence_rate"] = 0.0
            stats["medium_confidence_rate"] = 0.0
            stats["low_confidence_rate"] = 0.0
        
        return stats
    
    def get_active_locks_count(self) -> int:
        """Get count of active language locks."""
        with self._lock:
            return len(self.language_locks)
    
    def get_active_conversations_count(self) -> int:
        """Get count of active conversations."""
        with self._lock:
            return len(self.conversations)
    
    async def cleanup_expired_data(self):
        """Clean up expired conversations and locks."""
        try:
            current_time = datetime.now(timezone.utc)
            expired_calls = []
            
            with self._lock:
                # Clean up expired locks
                for call_id, lock in list(self.language_locks.items()):
                    if (current_time - lock.lock_timestamp).total_seconds() > lock.lock_duration:
                        del self.language_locks[call_id]
                        self.logger.info(f"Cleaned up expired language lock: {call_id}")
                
                # Clean up old conversations (older than 1 hour)
                for call_id, context in list(self.conversations.items()):
                    if (current_time - context.updated_at).total_seconds() > 3600:
                        expired_calls.append(call_id)
                
                # Clean up expired conversations
                for call_id in expired_calls:
                    del self.conversations[call_id]
                    if call_id in self.detection_history:
                        del self.detection_history[call_id]
                    if call_id in self.detection_stats:
                        del self.detection_stats[call_id]
                    self.logger.info(f"Cleaned up expired conversation: {call_id}")
                
        except Exception as e:
            self.logger.error(f"Failed to cleanup expired bilingual data: {e}")


# Global service instance
_bilingual_manager: Optional[BilingualManager] = None


def get_bilingual_manager() -> BilingualManager:
    """Get the global Bilingual Manager instance."""
    global _bilingual_manager
    if _bilingual_manager is None:
        _bilingual_manager = BilingualManager()
    return _bilingual_manager
