<!-- 2e146d24-089f-421c-8610-47b5af8c3577 c1565026-fb19-4ff2-82c3-d400e6d13513 -->
# Azure Cloud Services Integration Plan

## Phase 1: Azure Communication Services (ACS) Telephony Foundation

### 1.1 Configuration Setup

**Files**: `gateway/services/configuration.py`, `env.example`

Extend existing `AzureConfig` class with ACS-specific settings:

```python
class AzureCommunicationConfig(BaseSettings):
    connection_string: SecretStr
    phone_number: str
    callback_url: str
    recording_enabled: bool = False
    max_call_duration_minutes: int = 30
    webhook_secret: SecretStr
    
    class Config:
        env_prefix = "ACS_"
```

Add to `env.example`:

- `ACS_CONNECTION_STRING`
- `ACS_PHONE_NUMBER`
- `ACS_CALLBACK_URL`
- `ACS_WEBHOOK_SECRET`

### 1.2 ACS Service Implementation

**New File**: `gateway/services/azure_communication_service.py`

Create service class with methods:

- `initialize_call(phone_number: str, clinic_id: str)` - Initiate outbound call
- `answer_call(call_id: str)` - Answer inbound call
- `end_call(call_id: str)` - Terminate call
- `start_audio_stream(call_id: str)` - Begin WebSocket audio streaming
- `send_audio_chunk(call_id: str, audio_data: bytes)` - Send TTS audio
- `verify_webhook_signature(request)` - Security validation

### 1.3 WebSocket Audio Streaming Handler

**New File**: `gateway/services/audio_stream_handler.py`

WebSocket manager for real-time audio:

- `AudioStreamConnection` class with connection pooling
- `handle_incoming_audio(websocket, call_id)` - Process STT stream
- `handle_outgoing_audio(websocket, call_id)` - Send TTS stream
- Buffer management for audio chunks
- Connection lifecycle management

### 1.4 ACS API Endpoints

**New File**: `gateway/routes/azure_communication.py`

REST endpoints:

- `POST /acs/calls/initiate` - Start outbound call
- `POST /acs/webhooks/events` - ACS event callbacks
- `POST /acs/webhooks/recording` - Recording events
- `GET /acs/calls/{call_id}/status` - Call status
- WebSocket endpoint at `/ws/audio/{call_id}` for streaming

## Phase 2: Azure Speech Services Integration

### 2.1 Speech Configuration

**Files**: `gateway/services/configuration.py`

Add to `AzureConfig`:

```python
class AzureSpeechConfig(BaseSettings):
    speech_key: SecretStr
    speech_region: str
    stt_language_primary: str = "en-US"
    stt_language_secondary: str = "es-ES"
    tts_voice_en: str = "en-US-JennyNeural"
    tts_voice_es: str = "es-MX-DaliaNeural"
    enable_profanity_filter: bool = True
    
    class Config:
        env_prefix = "AZURE_SPEECH_"
```

### 2.2 Speech-to-Text Service

**New File**: `gateway/services/azure_speech_stt.py`

Implement STT service:

- `SpeechToTextService` class
- `start_continuous_recognition(audio_stream)` - Real-time STT
- `detect_language(audio_chunk)` - EN/ES detection
- `get_partial_result()` - Interim transcription
- `get_final_result()` - Complete transcription
- Language lock mechanism after detection

### 2.3 Text-to-Speech Service

**New File**: `gateway/services/azure_speech_tts.py`

Implement TTS service:

- `TextToSpeechService` class
- `synthesize_speech(text: str, language: str)` - Generate audio
- `synthesize_ssml(ssml: str)` - SSML support for prosody
- `stream_synthesis(text: str)` - Streaming TTS
- Voice selection based on detected language

### 2.4 Bilingual Support Manager

**New File**: `gateway/services/bilingual_manager.py`

Language detection and switching:

- `BilingualManager` class
- `detect_caller_language(audio_samples)` - Initial detection
- `lock_language(call_id: str, language: str)` - Lock after detection
- `get_response_voice(call_id: str)` - Select appropriate TTS voice
- Maintain language state per call in Redis or in-memory cache

## Phase 3: Azure OpenAI Integration

### 3.1 OpenAI Configuration

**Files**: `gateway/services/configuration.py`

Update existing `AzureConfig.openai_*` fields, add:

```python
openai_max_tokens: int = 500
openai_temperature: float = 0.7
openai_system_prompt_en: str
openai_system_prompt_es: str
enable_conversation_history: bool = True
max_history_messages: int = 10
```

### 3.2 Azure OpenAI Service

**New File**: `gateway/services/azure_openai_service.py`

Create conversational AI service:

- `AzureOpenAIService` class
- `process_intent(transcript: str, context: dict)` - Intent classification
- `generate_response(intent: str, context: dict, language: str)` - Response generation
- `extract_entities(transcript: str)` - Entity extraction
- Conversation history management
- Prompt engineering for healthcare context

### 3.3 Integration with Existing NLP

**Files**: `gateway/services/natural_language_processor.py`

Enhance existing NLP service:

- Add `use_azure_openai: bool` flag
- Create hybrid approach: Azure OpenAI for complex intents, local patterns for simple ones
- Fallback to pattern matching if OpenAI unavailable
- Confidence scoring for routing decisions

## Phase 4: Real-Time Call Processing Pipeline

### 4.1 Call Orchestrator

**New File**: `gateway/services/call_orchestrator.py`

Central coordinator for live calls:

- `CallOrchestrator` class
- `handle_inbound_call(call_event)` - Process incoming call
- `process_audio_chunk(call_id, audio_data)` - STT → OpenAI → TTS pipeline
- `manage_call_state(call_id)` - State machine for call flow
- `handle_emergency(call_id, transcript)` - Emergency detection and routing
- Integration with existing `CallFlowService`

### 4.2 Call Routing Logic

**New File**: `gateway/services/call_router.py`

Implement advanced routing:

- `CallRouter` class
- `route_call(call_id, caller_type, clinic_id)` - Routing decisions
- `check_capacity(clinic_id)` - Load monitoring
- `apply_overload_policy(clinic_id)` - Queue/forward/busy handling
- `transfer_to_human(call_id, reason)` - Human handoff
- Rule-based routing matrix stored in database

### 4.3 Caller Type Detection

**Files**: `gateway/models/models.py`, new migration

Add to `Call` model:

```python
caller_type = Column(String(20))  # patient, physician, pharmacy, insurer
caller_type_confidence = Column(Float)
routing_decision = Column(String(50))
```

New table `caller_routing_rules`:

- `rule_id`, `clinic_id`, `caller_type`, `priority`, `action`, `destination`

### 4.4 Overload Handling

**Files**: `gateway/services/call_router.py`

Implement policies from planner:

- Queue management with 45-second timeout
- Forward to staff numbers when capacity exceeded
- Busy signal as fallback
- Real-time capacity monitoring via existing `ClinicLicense.current_concurrent_calls`

## Phase 5: Reminder System

### 5.1 Reminder Job Definitions

**Files**: `gateway/services/background_jobs.py`

Add to `BackgroundJobManager._register_system_jobs()`:

```python
self.register_job(
    job_id="reminder_scheduler",
    name="Appointment Reminder Scheduler",
    function=self._schedule_reminders,
    schedule_interval=300,  # Every 5 minutes
    priority=JobPriority.HIGH
)

self.register_job(
    job_id="reminder_executor",
    name="Execute Reminder Calls",
    function=self._execute_reminders,
    schedule_interval=60,  # Every minute
    priority=JobPriority.CRITICAL
)
```

### 5.2 Reminder Scheduling Logic

**Files**: `gateway/services/background_jobs.py`

Add methods:

- `_schedule_reminders()` - Query appointments 24 hours ahead, create reminder records
- `_execute_reminders()` - Process pending reminders, initiate ACS calls
- `_handle_reminder_retry()` - Retry logic after 30 minutes if no answer
- Integration with `AzureCommunicationService` for outbound calls

### 5.3 Reminder Data Model

**New Migration**: `gateway/migrations/versions/0004_add_reminder_system.py`

New table `appointment_reminders`:

```sql
reminder_id, appointment_id, phone_token, scheduled_time,
status (pending, calling, completed, failed, retry_scheduled),
retry_count, last_attempt_at, completed_at, call_duration_seconds
```

### 5.4 Reminder TTS Templates

**New File**: `gateway/services/reminder_templates.py`

Bilingual reminder scripts:

- `get_reminder_message(appointment, language)` - Generate reminder text
- SSML templates for natural-sounding reminders
- Confirmation handling (press 1 to confirm, 2 to reschedule)
- Integration with existing appointment service

## Phase 6: Testing Infrastructure

### 6.1 Mock Services for Local Testing

**New Files**:

- `gateway/tests/mocks/mock_acs_service.py`
- `gateway/tests/mocks/mock_speech_service.py`
- `gateway/tests/mocks/mock_openai_service.py`

Mock implementations simulating Azure services:

- Pre-recorded audio responses
- Simulated transcriptions
- Mock intent recognition
- Controllable latency and error injection

### 6.2 Integration Tests

**New File**: `gateway/tests/test_azure_integration.py`

Comprehensive tests:

- End-to-end call flow simulation
- WebSocket streaming tests
- Bilingual conversation tests
- Error handling and fallback scenarios
- Performance benchmarks (700ms latency target)

### 6.3 Azure Sandbox Configuration

**Files**: `.env.sandbox`, `gateway/AZURE_SANDBOX_SETUP.md`

Documentation and configuration for Azure dev environment:

- Sandbox resource setup instructions
- Test phone numbers
- WebSocket connection testing
- Cost monitoring for sandbox usage

## Phase 7: Monitoring and Observability

### 7.1 Call Metrics Collection

**Files**: `gateway/services/structured_logging.py`

Add logging categories:

- `LogCategory.AZURE_SPEECH` - STT/TTS events
- `LogCategory.AZURE_OPENAI` - LLM interactions
- `LogCategory.CALL_ROUTING` - Routing decisions
- Performance metrics: audio latency, transcription accuracy, response time

### 7.2 Dashboard Integration

**Files**: `gateway/routes/background_jobs.py`

Extend health endpoint with call metrics:

- Active calls count
- Average call duration
- Reminder success rate
- Routing decision distribution
- Azure service health status

## Implementation Order

1. **Week 1-2**: Phase 1 (ACS Foundation + WebSocket streaming)
2. **Week 3**: Phase 2 (Speech Services STT/TTS)
3. **Week 4**: Phase 3 (Azure OpenAI Integration)
4. **Week 5**: Phase 4 (Call Orchestration + Routing)
5. **Week 6**: Phase 5 (Reminder System)
6. **Week 7**: Phase 6 (Testing Infrastructure)
7. **Week 8**: Phase 7 (Monitoring + Documentation)

## Key Integration Points

- All Azure services use existing `configuration.py` Pydantic models
- Reminder system integrates into `BackgroundJobManager`
- Call routing uses existing `Clinic`, `ClinicLicense` models
- Structured logging with PHI masking applies to all new components
- Custom exceptions for Azure-specific errors already defined in `services/exceptions.py`
- Transaction management for concurrent call handling via existing `TransactionManager`

## Success Criteria

- Inbound calls answered via ACS within 2 seconds
- STT transcription latency < 500ms
- End-to-end response latency < 700ms average
- Language detection accuracy > 95%
- Reminder delivery rate > 90%
- Zero PHI exposure in logs
- Graceful degradation on Azure service failures

### To-dos

- [ ] Extend Pydantic configuration with ACS settings and update env.example
- [ ] Implement Azure Communication Service with call management and webhook handling
- [ ] Create WebSocket audio stream handler for real-time bidirectional audio
- [ ] Build ACS API endpoints and WebSocket endpoint for audio streaming
- [ ] Add Azure Speech configuration with bilingual voice settings
- [ ] Implement Speech-to-Text service with continuous recognition and language detection
- [ ] Implement Text-to-Speech service with streaming synthesis
- [ ] Create bilingual support manager for language detection and locking
- [ ] Update Azure OpenAI configuration with conversation settings
- [ ] Implement Azure OpenAI service for intent classification and response generation
- [ ] Integrate Azure OpenAI with existing NLP service as hybrid approach
- [ ] Build call orchestrator to coordinate STT, OpenAI, and TTS pipeline
- [ ] Implement call routing logic with capacity checking and overload policies
- [ ] Add caller type detection with database migration for routing rules
- [ ] Add reminder scheduler and executor jobs to background job manager
- [ ] Create database migration for appointment_reminders table
- [ ] Build bilingual reminder TTS templates with SSML
- [ ] Create mock Azure services for local testing without Azure resources
- [ ] Write comprehensive integration tests for end-to-end call flows
- [ ] Document Azure sandbox environment setup and configuration
- [ ] Add call-specific logging categories and performance metrics
- [ ] Extend health endpoints with call metrics and Azure service status