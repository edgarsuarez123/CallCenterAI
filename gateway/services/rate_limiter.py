import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass
from services.structured_logging import get_logger

logger = get_logger("rate_limiter")

@dataclass
class SubscriptionTier:
    """Rate limit configuration per subscription tier."""
    name: str
    calls_per_minute: int
    calls_per_hour: int
    burst_capacity: int
    reminder_calls_per_hour: int

# Subscription tiers
SUBSCRIPTION_TIERS = {
    "free": SubscriptionTier("free", calls_per_minute=10, calls_per_hour=100, burst_capacity=20, reminder_calls_per_hour=10),
    "basic": SubscriptionTier("basic", calls_per_minute=50, calls_per_hour=1000, burst_capacity=100, reminder_calls_per_hour=50),
    "pro": SubscriptionTier("pro", calls_per_minute=200, calls_per_hour=5000, burst_capacity=500, reminder_calls_per_hour=200),
    "enterprise": SubscriptionTier("enterprise", calls_per_minute=1000, calls_per_hour=50000, burst_capacity=2000, reminder_calls_per_hour=1000),
}

class TokenBucket:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # Tokens per second
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens. Returns True if successful."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # Add tokens based on time elapsed
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait_for_token(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """Wait until tokens are available or timeout."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if await self.acquire(tokens):
                return True
            
            # Calculate wait time for next token
            async with self._lock:
                if self.tokens < tokens:
                    wait_time = (tokens - self.tokens) / self.rate
                    await asyncio.sleep(min(wait_time, 0.1))
                else:
                    await asyncio.sleep(0.01)
        
        return False

class RateLimiter:
    """Multi-tier rate limiter with subscription support."""
    
    def __init__(self):
        self._clinic_limiters: Dict[str, Dict[str, TokenBucket]] = {}
        self._lock = asyncio.Lock()
    
    def _get_tier(self, clinic_id: str) -> SubscriptionTier:
        """Get subscription tier for clinic. TODO: Query from database."""
        # For now, default to basic tier
        # In production, query from clinic.subscription_tier
        return SUBSCRIPTION_TIERS["basic"]
    
    async def check_acs_call_limit(self, clinic_id: str) -> bool:
        """Check if clinic can make ACS call (answer incoming call)."""
        tier = self._get_tier(clinic_id)
        limiter = await self._get_limiter(clinic_id, "acs_calls", 
                                          rate=tier.calls_per_minute / 60.0,
                                          capacity=tier.burst_capacity)
        return await limiter.acquire()
    
    async def check_reminder_limit(self, clinic_id: str) -> bool:
        """Check if clinic can send reminder call."""
        tier = self._get_tier(clinic_id)
        limiter = await self._get_limiter(clinic_id, "reminders",
                                          rate=tier.reminder_calls_per_hour / 3600.0,
                                          capacity=tier.reminder_calls_per_hour // 10)
        return await limiter.acquire()
    
    async def check_webhook_limit(self, clinic_id: str) -> bool:
        """Check webhook rate limit (DoS protection)."""
        # Webhook limit is more generous - 1000/min burst
        limiter = await self._get_limiter(clinic_id, "webhooks",
                                          rate=100.0,  # 100/second
                                          capacity=1000)
        return await limiter.acquire()
    
    async def _get_limiter(self, clinic_id: str, limiter_type: str, 
                          rate: float, capacity: int) -> TokenBucket:
        """Get or create token bucket for clinic and type."""
        async with self._lock:
            if clinic_id not in self._clinic_limiters:
                self._clinic_limiters[clinic_id] = {}
            
            if limiter_type not in self._clinic_limiters[clinic_id]:
                self._clinic_limiters[clinic_id][limiter_type] = TokenBucket(rate, capacity)
            
            return self._clinic_limiters[clinic_id][limiter_type]

# Global instance
_rate_limiter = RateLimiter()

def get_rate_limiter() -> RateLimiter:
    return _rate_limiter
