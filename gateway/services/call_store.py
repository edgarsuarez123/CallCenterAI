"""
LRU cache for call contexts with size limit.
In production, this should be replaced with Redis or database storage.
"""

from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import asyncio
from models.call_flow_models import CallFlowContext
from services.structured_logging import get_logger

# Atlantic Standard Time (UTC-4)
AST = timezone(timedelta(hours=-4))

logger = get_logger("call_store")

MAX_STORED_CALLS = 1000  # Configurable limit

class CallStoreLRU:
    """LRU cache for call contexts with size limit."""
    
    def __init__(self, max_size: int = MAX_STORED_CALLS):
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[CallFlowContext, datetime]] = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def store_call(self, call_sid: str, context: CallFlowContext) -> None:
        async with self._lock:
            # Remove if exists (to update position)
            if call_sid in self._store:
                del self._store[call_sid]
            
            # Remove oldest if at capacity
            if len(self._store) >= self.max_size:
                oldest_sid = next(iter(self._store))
                del self._store[oldest_sid]
                logger.warning(f"Call store at capacity, removed oldest call: {oldest_sid}")
            
            self._store[call_sid] = (context, datetime.now(AST))
            self._store.move_to_end(call_sid)  # Mark as most recent
    
    async def get_call(self, call_sid: str) -> Optional[CallFlowContext]:
        async with self._lock:
            if call_sid in self._store:
                context, _ = self._store[call_sid]
                self._store.move_to_end(call_sid)  # Update access time
                return context
            return None
    
    async def remove_call(self, call_sid: str) -> bool:
        async with self._lock:
            if call_sid in self._store:
                del self._store[call_sid]
                return True
            return False
    
    async def list_calls(self) -> Dict[str, CallFlowContext]:
        async with self._lock:
            return {sid: context for sid, (context, _) in self._store.items()}
    
    async def clear_all_calls(self) -> None:
        async with self._lock:
            self._store.clear()

# Global instance
_call_store = CallStoreLRU()

async def store_call(call_sid: str, context: CallFlowContext) -> None:
    await _call_store.store_call(call_sid, context)

async def get_call(call_sid: str) -> Optional[CallFlowContext]:
    return await _call_store.get_call(call_sid)

async def remove_call(call_sid: str) -> bool:
    return await _call_store.remove_call(call_sid)

async def list_calls() -> Dict[str, CallFlowContext]:
    return await _call_store.list_calls()

async def clear_all_calls() -> None:
    await _call_store.clear_all_calls()
