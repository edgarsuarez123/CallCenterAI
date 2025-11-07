"""
Response Cache Service

This module provides a comprehensive caching system for AI responses to optimize
token usage and improve response latency. It supports both template-based responses
and AI-generated response caching with tiered TTL strategies.

Key Features:
- Redis-backed persistent caching
- Template-based variable substitution
- Tiered TTL strategies (greetings: 24h, questions: 1h, specific: 5min)
- Cache statistics and monitoring
- Graceful fallback when Redis unavailable
- Thread-safe operations
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError

from .configuration import get_settings
from .structured_logging import logger, LogCategory


class CacheTier(Enum):
    """Cache TTL tiers for different response types."""
    GREETING = 86400      # 24 hours
    QUESTION = 3600       # 1 hour
    SPECIFIC = 300        # 5 minutes
    AI_GENERATED = 300    # 5 minutes


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    response: str
    template: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None
    created_at: datetime = None
    ttl: int = 300
    source: str = "template"  # "template" or "ai_generated"
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now(AST)


@dataclass
class CacheStatistics:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    errors: int = 0
    total_requests: int = 0
    cache_size: int = 0
    last_reset: datetime = None
    
    def __post_init__(self):
        if self.last_reset is None:
            self.last_reset = datetime.now(AST)
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests
    
    @property
    def miss_rate(self) -> float:
        """Calculate cache miss rate."""
        return 1.0 - self.hit_rate


class ResponseCacheService:
    """
    Service for caching AI responses with Redis backend.
    
    Provides intelligent caching of both template-based responses and
    AI-generated responses to optimize token usage and improve performance.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = logger
        self.redis_client: Optional[redis.Redis] = None
        self._connection_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()  # Lock for statistics updates
        self._cache_lock = asyncio.Lock()  # Lock for local cache access
        self._stats = CacheStatistics()
        self._local_cache: Dict[str, CacheEntry] = {}  # Fallback cache
        self._is_connected = False
        
        # Cache configuration
        self.redis_config = self.settings.redis_cache
        self.key_prefix = self.redis_config.key_prefix
        self.default_ttl = self.redis_config.default_ttl
        
        # TTL mapping for different response types
        self.cache_ttl_mapping = {
            "greeting": CacheTier.GREETING.value,
            "goodbye": CacheTier.GREETING.value,
            "name_request": CacheTier.QUESTION.value,
            "provider_selection": CacheTier.QUESTION.value,
            "date_selection": CacheTier.QUESTION.value,
            "time_selection": CacheTier.QUESTION.value,
            "confirmation": CacheTier.QUESTION.value,
            "ai_generated": CacheTier.AI_GENERATED.value,
            "specific": CacheTier.SPECIFIC.value
        }
        
        self.logger.info(
            "Response cache service initialized",
            LogCategory.CACHE,
            extra_data={
                "redis_host": self.redis_config.host,
                "redis_port": self.redis_config.port,
                "key_prefix": self.key_prefix,
                "default_ttl": self.default_ttl
            }
        )
    
    async def initialize(self) -> bool:
        """
        Initialize Redis connection.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            async with self._connection_lock:
                if self.redis_client is None:
                    # Create Redis connection pool
                    connection_kwargs = {
                        "host": self.redis_config.host,
                        "port": self.redis_config.port,
                        "db": self.redis_config.db,
                        "max_connections": self.redis_config.max_connections,
                        "socket_timeout": self.redis_config.socket_timeout,
                        "socket_connect_timeout": self.redis_config.socket_connect_timeout,
                        "retry_on_timeout": self.redis_config.retry_on_timeout,
                        "health_check_interval": self.redis_config.health_check_interval,
                        "decode_responses": True
                    }
                    
                    # Add password if provided
                    if self.redis_config.password:
                        connection_kwargs["password"] = self.redis_config.password.get_secret_value()
                    
                    self.redis_client = redis.Redis(**connection_kwargs)
                    
                    # Test connection
                    await self.redis_client.ping()
                    self._is_connected = True
                    
                    self.logger.info(
                        "Redis connection established",
                        LogCategory.CACHE,
                        extra_data={
                            "host": self.redis_config.host,
                            "port": self.redis_config.port,
                            "db": self.redis_config.db
                        }
                    )
                    
                    return True
                    
        except (RedisError, ConnectionError, TimeoutError) as e:
            self.logger.warning(
                f"Redis connection failed, using local cache fallback: {e}",
                LogCategory.CACHE,
                extra_data={"error": str(e)}
            )
            self._is_connected = False
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error initializing Redis: {e}",
                LogCategory.CACHE,
                extra_data={"error": str(e)}
            )
            self._is_connected = False
            return False
    
    async def get_cached_response(
        self, 
        intent: str, 
        language: str, 
        variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Get cached response for given intent and language.
        
        Args:
            intent: Intent type (e.g., "greeting", "name_request")
            language: Language code (e.g., "en", "es")
            variables: Template variables for substitution
            
        Returns:
            Optional[str]: Cached response if found, None otherwise
        """
        try:
            # Update statistics with lock
            async with self._stats_lock:
                self._stats.total_requests += 1
            
            # Generate cache key
            cache_key = self._generate_cache_key(intent, language, variables)
            
            # Try Redis first if connected
            if not self._is_connected:
                await self.initialize()
            
            if self._is_connected and self.redis_client:
                try:
                    cached_data = await self.redis_client.get(cache_key)
                    if cached_data:
                        try:
                            entry_data = json.loads(cached_data)
                            entry = CacheEntry(**entry_data)
                        except (json.JSONDecodeError, TypeError, KeyError) as e:
                            self.logger.warning(f"Failed to parse cached data: {e}", LogCategory.CACHE)
                            cached_data = None
                        
                        if cached_data and entry:
                            # Issue 160: Re-validate entry after retrieval to handle cache invalidation race conditions
                            # Check if entry is still valid after retrieving from Redis
                            if self._is_entry_valid(entry):
                                async with self._stats_lock:
                                    self._stats.hits += 1
                                self.logger.debug(
                                    f"Cache hit for {intent}:{language}",
                                    LogCategory.CACHE,
                                    extra_data={"cache_key": cache_key}
                                )
                                # Issue 160: Return entry only if still valid after retrieval
                                return entry.response
                            else:
                                # Entry expired between check and return - remove it
                                await self.redis_client.delete(cache_key)
                        else:
                            # Remove expired entry
                            await self.redis_client.delete(cache_key)
                            
                except (RedisError, ConnectionError, TimeoutError) as e:
                    self.logger.warning(
                        f"Redis error during get, falling back to local cache: {e}",
                        LogCategory.CACHE
                    )
                    self._is_connected = False
            
            # Fallback to local cache (with lock)
            async with self._cache_lock:
                if cache_key in self._local_cache:
                    entry = self._local_cache[cache_key]
                    if entry and self._is_entry_valid(entry):
                        async with self._stats_lock:
                            self._stats.hits += 1
                        self.logger.debug(
                            f"Local cache hit for {intent}:{language}",
                            LogCategory.CACHE
                        )
                        return entry.response
                    else:
                        # Remove expired entry
                        del self._local_cache[cache_key]
            
            async with self._stats_lock:
                self._stats.misses += 1
            return None
            
        except Exception as e:
            async with self._stats_lock:
                self._stats.errors += 1
            self.logger.error(
                f"Error getting cached response: {e}",
                LogCategory.CACHE,
                extra_data={"intent": intent, "language": language, "error": str(e)}
            )
            return None
    
    async def cache_response(
        self,
        intent: str,
        language: str,
        response: str,
        template: Optional[str] = None,
        variables: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
        source: str = "template"
    ) -> bool:
        """
        Cache a response for given intent and language.
        
        Args:
            intent: Intent type
            language: Language code
            response: Response text to cache
            template: Template string (if applicable)
            variables: Template variables
            ttl: Time to live in seconds (uses default if None)
            source: Source of response ("template" or "ai_generated")
            
        Returns:
            bool: True if cached successfully, False otherwise
        """
        try:
            # Determine TTL
            if ttl is None:
                ttl = self.cache_ttl_mapping.get(intent, self.default_ttl)
            
            # Create cache entry
            entry = CacheEntry(
                response=response,
                template=template,
                variables=variables,
                ttl=ttl,
                source=source
            )
            
            # Generate cache key
            cache_key = self._generate_cache_key(intent, language, variables)
            
            # Try Redis first if connected
            if self._is_connected and self.redis_client:
                try:
                    entry_data = json.dumps(asdict(entry), default=str)
                    await self.redis_client.setex(cache_key, ttl, entry_data)
                    
                    self.logger.debug(
                        f"Cached response in Redis for {intent}:{language}",
                        LogCategory.CACHE,
                        extra_data={
                            "cache_key": cache_key,
                            "ttl": ttl,
                            "source": source
                        }
                    )
                    return True
                    
                except (RedisError, ConnectionError, TimeoutError) as e:
                    self.logger.warning(
                        f"Redis error during cache, using local cache: {e}",
                        LogCategory.CACHE
                    )
                    self._is_connected = False
            
            # Fallback to local cache (with lock)
            async with self._cache_lock:
                self._local_cache[cache_key] = entry
            
            # Issue 176: Verify cache write succeeded
            async with self._cache_lock:
                if cache_key not in self._local_cache:
                    self.logger.error(f"Failed to write to local cache for {intent}:{language}")
                    return False
            
            # Clean up old local cache entries
            await self._cleanup_local_cache()
            
            self.logger.debug(
                f"Cached response locally for {intent}:{language}",
                LogCategory.CACHE,
                extra_data={"ttl": ttl, "source": source}
            )
            return True
            
        except Exception as e:
            async with self._stats_lock:
                self._stats.errors += 1
            self.logger.error(
                f"Error caching response: {e}",
                LogCategory.CACHE,
                extra_data={"intent": intent, "language": language, "error": str(e)}
            )
            return False
    
    def _generate_cache_key(
        self, 
        intent: str, 
        language: str, 
        variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate cache key for intent, language, and variables.
        
        Args:
            intent: Intent type
            language: Language code
            variables: Template variables
            
        Returns:
            str: Cache key
        """
        # Create base key
        base_key = f"{intent}:{language}"
        
        # Add variable hash if variables provided
        if variables:
            # Sort variables for consistent hashing
            sorted_vars = sorted(variables.items())
            # Use full SHA256 hash to prevent collisions
            var_hash = hashlib.sha256(json.dumps(sorted_vars, sort_keys=True).encode()).hexdigest()[:16]
            base_key = f"{base_key}:{var_hash}"
        
        return f"{self.key_prefix}response:{base_key}"
    
    def _is_entry_valid(self, entry: CacheEntry) -> bool:
        """
        Check if cache entry is still valid.
        
        Args:
            entry: Cache entry to validate
            
        Returns:
            bool: True if entry is valid, False otherwise
        """
        if entry.created_at is None:
            return False
        
        elapsed = (datetime.now(AST) - entry.created_at).total_seconds()
        return elapsed < entry.ttl
    
    async def _cleanup_local_cache(self):
        """Clean up expired entries from local cache."""
        # Issue 191: Use a flag to prevent concurrent cleanup
        # Check if cleanup is already in progress
        if hasattr(self, '_cleanup_in_progress') and self._cleanup_in_progress:
            return  # Cleanup already in progress, skip
        
        try:
            # Issue 191: Set cleanup flag to prevent concurrent cleanup
            self._cleanup_in_progress = True
            
            current_time = datetime.now(AST)
            expired_keys = []
            
            # Get expired keys with lock
            async with self._cache_lock:
                for key, entry in list(self._local_cache.items()):  # Create copy to avoid modification during iteration
                    if entry and not self._is_entry_valid(entry):
                        expired_keys.append(key)
            
            # Remove expired keys with lock
            if expired_keys:
                async with self._cache_lock:
                    # Issue 191: Re-check keys are still expired (might have been updated by another thread)
                    for key in expired_keys:
                        if key in self._local_cache:
                            entry = self._local_cache[key]
                            # Re-validate entry is still expired
                            if entry and not self._is_entry_valid(entry):
                                del self._local_cache[key]
                                async with self._stats_lock:
                                    self._stats.evictions += 1
            
            if expired_keys:
                self.logger.debug(
                    f"Cleaned up {len(expired_keys)} expired local cache entries",
                    LogCategory.CACHE
                )
        finally:
            # Issue 191: Always clear cleanup flag, even if exception occurs
            self._cleanup_in_progress = False
                
        except Exception as e:
            self.logger.error(
                f"Error cleaning up local cache: {e}",
                LogCategory.CACHE
            )
            # Issue 191: Ensure cleanup flag is cleared on error
            self._cleanup_in_progress = False
    
    async def get_cache_statistics(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.
        
        Returns:
            Dict[str, Any]: Cache statistics
        """
        try:
            # Get Redis info if connected
            redis_info = {}
            if self._is_connected and self.redis_client:
                try:
                    info = await self.redis_client.info("memory")
                    if info:
                        redis_info = {
                            "redis_used_memory": info.get("used_memory_human", "unknown"),
                            "redis_connected_clients": info.get("connected_clients", 0),
                            "redis_evicted_keys": info.get("evicted_keys", 0)
                        }
                except Exception as e:
                    self.logger.warning(f"Could not get Redis info: {e}")
            
            # Calculate cache size (with lock)
            async with self._cache_lock:
                cache_size = len(self._local_cache)
            
            if self._is_connected and self.redis_client:
                try:
                    # Count keys with our prefix
                    pattern = f"{self.key_prefix}response:*"
                    keys = await self.redis_client.keys(pattern)
                    if keys:
                        cache_size = len(keys)
                except Exception:
                    pass
            
            async with self._stats_lock:
                self._stats.cache_size = cache_size
            
            return {
                "statistics": asdict(self._stats),
                "connection_status": {
                    "redis_connected": self._is_connected,
                    "local_cache_size": cache_size
                },
                "redis_info": redis_info,
                "ttl_mapping": self.cache_ttl_mapping
            }
            
        except Exception as e:
            self.logger.error(
                f"Error getting cache statistics: {e}",
                LogCategory.CACHE
            )
            return {"error": str(e)}
    
    async def clear_cache(self, pattern: Optional[str] = None) -> bool:
        """
        Clear cache entries.
        
        Args:
            pattern: Optional pattern to match keys (default: all response keys)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if pattern is None:
                pattern = f"{self.key_prefix}response:*"
            
            cleared_count = 0
            
            # Clear Redis cache
            if self._is_connected and self.redis_client:
                try:
                    keys = await self.redis_client.keys(pattern)
                    if keys and len(keys) > 0:
                        cleared_count += await self.redis_client.delete(*keys)
                except Exception as e:
                    self.logger.warning(f"Error clearing Redis cache: {e}")
            
            # Clear local cache (with lock)
            async with self._cache_lock:
                if pattern == f"{self.key_prefix}response:*" or pattern is None:
                    cleared_count += len(self._local_cache)
                    self._local_cache.clear()
                else:
                    # Clear matching local cache entries
                    keys_to_remove = [k for k in self._local_cache.keys() if pattern.replace("*", "") in k]
                    for key in keys_to_remove:
                        if key in self._local_cache:
                            del self._local_cache[key]
                    cleared_count += len(keys_to_remove)
            
            self.logger.info(
                f"Cleared {cleared_count} cache entries",
                LogCategory.CACHE,
                extra_data={"pattern": pattern, "cleared_count": cleared_count}
            )
            
            return True
            
        except Exception as e:
            self.logger.error(
                f"Error clearing cache: {e}",
                LogCategory.CACHE
            )
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on cache service.
        
        Returns:
            Dict[str, Any]: Health check results
        """
        try:
            health_status = {
                "status": "healthy",
                "redis_connected": False,
                "local_cache_available": True,
                "timestamp": datetime.now(AST).isoformat()
            }
            
            # Test Redis connection
            if self.redis_client:
                try:
                    await self.redis_client.ping()
                    health_status["redis_connected"] = True
                except Exception as e:
                    health_status["redis_connected"] = False
                    health_status["redis_error"] = str(e)
            
            # Test local cache (with lock)
            try:
                async with self._cache_lock:
                    test_key = f"{self.key_prefix}health_check"
                    test_entry = CacheEntry(response="test", ttl=1)
                    self._local_cache[test_key] = test_entry
                    if test_key in self._local_cache:
                        del self._local_cache[test_key]
            except Exception as e:
                health_status["local_cache_available"] = False
                health_status["local_cache_error"] = str(e)
                health_status["status"] = "unhealthy"
            
            if not health_status["redis_connected"] and not health_status["local_cache_available"]:
                health_status["status"] = "unhealthy"
            
            return health_status
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.now(AST).isoformat()
            }
    
    async def close(self):
        """Close Redis connection."""
        try:
            if self.redis_client:
                await self.redis_client.close()
                self._is_connected = False
                self.logger.info("Redis connection closed", LogCategory.CACHE)
        except Exception as e:
            self.logger.error(f"Error closing Redis connection: {e}", LogCategory.CACHE)


# Global instance
_response_cache_service: Optional[ResponseCacheService] = None


def get_response_cache_service() -> ResponseCacheService:
    """
    Get global response cache service instance.
    
    Returns:
        ResponseCacheService: Global cache service instance
    """
    global _response_cache_service
    if _response_cache_service is None:
        _response_cache_service = ResponseCacheService()
    return _response_cache_service
