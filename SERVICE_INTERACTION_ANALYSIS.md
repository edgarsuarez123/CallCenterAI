# Service Interaction Analysis

## Overview
Analysis of how `azure_communication_service.py`, `audio_stream_handler.py`, `azure_speech_stt.py`, `azure_speech_tts.py`, and `call_orchestrator.py` interact and identify issues.

## Interaction Flow

### 1. Call Lifecycle Flow
```
Incoming Call (Event Grid)
  ↓
azure_communication_service.answer_incoming_call()
  ↓
call_orchestrator.start_call()
  ↓
audio_stream_handler.connect_audio_stream() (via WebSocket route)
  ↓
call_orchestrator._initialize_audio_stream()
  ├─→ Registers STT callback
  └─→ Registers TTS callback
  ↓
azure_speech_stt.start_continuous_recognition()
  ↓
Audio flows: WebSocket → audio_stream_handler → azure_speech_stt
  ↓
STT callback → call_orchestrator._handle_speech_input()
  ↓
call_orchestrator._process_user_input()
  ↓
call_orchestrator._generate_response()
  ↓
azure_speech_tts.synthesize_speech()
  ↓
audio_stream_handler.send_tts_audio() OR azure_communication_service.play_audio_to_call()
```

## Critical Issues Found

### 1. **DUPLICATE CALL STATE MANAGEMENT** ⚠️ CRITICAL

**Problem**: Two separate call state stores that can get out of sync:

- `azure_communication_service.active_calls: Dict[str, CallState]`
  - Tracks: `call_id`, `clinic_id`, `caller_phone`, `acs_call_id`, `status`, `websocket_connected`, `audio_stream_active`
  
- `call_orchestrator.active_calls: Dict[str, CallContext]`
  - Tracks: `call_id`, `caller_phone`, `clinic_id`, `state`, `language`, `conversation_history`, `metadata`

**Impact**: 
- State can become inconsistent between services
- Need to query both stores to get complete call info
- Race conditions when updating state in both places
- `state_sync.py` background job tries to sync them, but this is a band-aid

**Example**:
```python
# In call_orchestrator._synthesize_response():
acs_service = get_azure_communication_service()
async with acs_service._calls_lock:
    call_state = acs_service.active_calls.get(call_context.call_id)  # Querying separate store!
```

### 2. **AUDIO STREAMING RESPONSIBILITY CONFUSION** ⚠️ HIGH

**Problem**: Three different services manage audio streaming with unclear boundaries:

- `azure_communication_service.start_audio_stream()` - Only sets a flag (`audio_stream_active = True`)
- `audio_stream_handler.connect_audio_stream()` - Actually establishes WebSocket connection
- `call_orchestrator._initialize_audio_stream()` - Registers callbacks but doesn't connect

**Impact**:
- Unclear which service is responsible for what
- `start_audio_stream()` in ACS service is misleading (doesn't actually start anything)
- Connection logic scattered across multiple files

### 3. **DUPLICATE AUDIO PLAYBACK METHODS** ⚠️ MEDIUM

**Problem**: Multiple ways to play audio with overlapping functionality:

1. `azure_communication_service.play_audio_to_call()` - Uses ACS Play API (FileSource/TextSource)
2. `azure_communication_service.play_scripted_text()` - Uses ACS TextSource (fast, no TTS)
3. `audio_stream_handler.send_tts_audio()` - Sends via WebSocket
4. `call_orchestrator._synthesize_response()` - Orchestrates all of the above with fallbacks

**Impact**:
- Complex fallback logic in orchestrator
- Hard to understand which method to use when
- Some methods are redundant (e.g., `play_scripted_text` vs `play_audio_to_call` with TextSource)

### 4. **DUPLICATE ACTIVE CALLS TRACKING** ⚠️ MEDIUM

**Problem**: Three separate stores track active calls:

- `azure_communication_service.active_calls` - ACS call state
- `call_orchestrator.active_calls` - Orchestrator call context
- `audio_stream_handler.active_connections` - WebSocket connections

**Impact**:
- Need to check multiple stores to find a call
- State synchronization issues
- `state_sync.py` tries to keep them in sync, but this is fragile

### 5. **INCONSISTENT CALL ID MAPPING** ⚠️ MEDIUM

**Problem**: Multiple ways to map between `call_id` and `acs_call_id`:

- `azure_communication_service.store_call_id_mapping()` - Stores in `CallState.acs_call_id`
- `azure_communication_service.get_call_id_from_mapping()` - Searches through `active_calls`
- `call_orchestrator` stores `acs_call_id` in `CallContext.metadata['acs_call_id']`

**Impact**:
- Inconsistent lookup patterns
- Performance issues (linear search in `get_call_id_from_mapping`)
- Could use a dedicated mapping dict

### 6. **VOICE CONFIGURATION DUPLICATION** ⚠️ LOW

**Problem**: Voice name mapping exists in two places:

- `azure_communication_service._get_voice_name()` - Maps language to voice name
- `azure_speech_tts.VoiceConfig` - Has voice configuration with name

**Impact**:
- Could get out of sync
- Should be centralized in configuration

## Functionality Evaluation

### ✅ Good Aspects

1. **Clear Separation of Concerns** (mostly):
   - `azure_speech_stt` - Handles STT only
   - `azure_speech_tts` - Handles TTS only
   - `audio_stream_handler` - Handles WebSocket connections
   - `call_orchestrator` - Coordinates everything

2. **Proper Error Handling**:
   - Services have try/except blocks
   - Fallback mechanisms in place
   - Error logging is comprehensive

3. **Thread Safety**:
   - Services use `asyncio.Lock()` appropriately
   - Locks are used around shared state

### ❌ Problematic Aspects

1. **Tight Coupling**:
   - `call_orchestrator` directly accesses `azure_communication_service.active_calls`
   - Services know too much about each other's internals

2. **State Synchronization**:
   - Multiple state stores need to stay in sync
   - Background job (`state_sync.py`) is a workaround, not a solution

3. **Unclear Ownership**:
   - Who owns the call state? ACS service or orchestrator?
   - Who manages audio connections? Audio handler or orchestrator?

## Recommendations

### 1. **Consolidate Call State Management** (HIGH PRIORITY)

**Option A**: Make `call_orchestrator` the single source of truth
- Remove `azure_communication_service.active_calls`
- ACS service only tracks `acs_call_id` mappings
- All call state queries go through orchestrator

**Option B**: Create a dedicated `CallStateManager` service
- Centralized call state store
- All services query/update through this manager
- Prevents state divergence

### 2. **Clarify Audio Streaming Responsibilities** (HIGH PRIORITY)

- `audio_stream_handler` - Owns WebSocket connections
- `azure_communication_service` - Owns ACS call connections
- `call_orchestrator` - Coordinates between them
- Remove misleading `start_audio_stream()` from ACS service

### 3. **Simplify Audio Playback** (MEDIUM PRIORITY)

- Create a unified `AudioPlaybackService`
- Single method: `play_audio(call_id, audio_data, method='auto')`
- Handles fallback logic internally
- Remove duplicate methods

### 4. **Improve Call ID Mapping** (MEDIUM PRIORITY)

- Create dedicated `Dict[str, str]` for `call_id` → `acs_call_id` mapping
- O(1) lookup instead of linear search
- Store in a single place (orchestrator or dedicated service)

### 5. **Centralize Voice Configuration** (LOW PRIORITY)

- Move voice mapping to `configuration.py`
- Single source of truth for voice names
- Both services read from same config

## Architecture Improvement Suggestion

```
┌─────────────────────────────────────┐
│     CallStateManager (NEW)         │
│  - Single source of truth          │
│  - Manages all call state           │
│  - Provides unified API            │
└─────────────────────────────────────┘
           ↑           ↑
           │           │
    ┌──────┴───┐  ┌────┴────┐
    │          │  │         │
┌───▼───┐ ┌───▼──▼──┐ ┌────▼────┐
│  ACS  │ │Orchestr.│ │  Audio   │
│Service│ │         │ │ Handler  │
└───────┘ └─────────┘ └──────────┘
```

This would:
- Eliminate state synchronization issues
- Make ownership clear
- Simplify queries (single source)
- Reduce coupling between services

