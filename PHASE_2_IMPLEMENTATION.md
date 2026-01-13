# Phase 2 Implementation Plan

## Goal
**Outbound Calling & Campaign Management**: Enable automated reminder calls (24h before appointments) and campaign-based outbound calling with Retell AI integration, rate limiting, and retry logic.

## Phase 2 Scope: Outbound Calling System

### ✅ What's Included

#### 1. Campaign Management
- [ ] **Campaign Model** - Store campaign metadata (name, type, status, google_sheet_id)
- [ ] **CampaignContact Model** - Store campaign contacts with retry logic and additional fields
- [ ] **Google Sheets Integration** - Read campaign data from Google Sheets (not CSV upload)
- [ ] **Campaign Fields** - patient_name, phone, insurance, reasons_for_calling, status (in_progress, responded, not_answered)
- [ ] **Campaign CRUD Endpoints** - Create, list, get, start, pause campaigns
- [ ] **Campaign Status Tracking** - pending → in_progress → completed/failed/paused
- [ ] **Google Sheets Control** - Read control cell to start/stop campaigns
- [ ] **Auto-Complete Logic** - Campaign completes when patient accepts appointment during call

#### 2. Retell Outbound Call API Client
- [ ] **Retell API Service** - `Clinic_app/services/retell_api.py`
- [ ] **Create Outbound Call** - `create_outbound_call(from_number, to_number, override_agent_id, metadata)` using Retell SDK/API
- [ ] **Call Status Tracking** - Track call creation and correlate with webhooks
- [ ] **Error Handling** - Retry logic, rate limit handling (check Retell API rate limits)
- [ ] **API Key Management** - Environment variable for Retell API key
- [ ] **Rate Limit Compliance** - Respect Retell API rate limits (check documentation)

#### 3. Campaign Worker (Background Task)
- [ ] **Campaign Worker** - `Clinic_app/workers/campaign_worker.py`
- [ ] **Google Sheets Sync** - Periodically read from Google Sheets to sync campaign contacts
- [ ] **Process Pending Contacts** - Continuous loop checking for pending campaign contacts
- [ ] **Rate Limiting** - Respect `license.max_concurrency` per clinic AND Retell API rate limits AND Google API rate limits
- [ ] **Retry Logic** - Exponential backoff (1h, 4h, 24h)
- [ ] **Status Updates** - Update campaign_contact status (pending → in_progress → responded/not_answered)
- [ ] **Google Sheets Control** - Read control cell to determine if campaign should run
- [ ] **Auto-Complete Logic** - Campaign completes when patient accepts appointment during call (detected via webhook)

#### 4. Reminder Call System
- [ ] **Reminder Service** - `Clinic_app/services/reminder.py`
- [ ] **Configurable Reminder Timing** - Per-clinic configuration for reminder window (default 24h, configurable)
- [ ] **Find Appointments Ahead** - Query confirmed bookings within configurable window (e.g., 24-25 hours)
- [ ] **Google Calendar Integration** - Check GCal events for reminder status
- [ ] **Patient Phone Lookup** - Decrypt patient phone_token for calling
- [ ] **Reminder Tracking** - Mark GCal event as "reminded" via extendedProperties
- [ ] **Timezone Handling** - Calculate reminder window in provider's timezone
- [ ] **Clinic Configuration** - Add `reminder_hours_before` field to Clinic model (default 24)

#### 5. Reminder Worker (Background Task)
- [ ] **Reminder Worker** - `Clinic_app/workers/reminder_worker.py`
- [ ] **Hourly Scheduler** - Run every hour to check for appointments
- [ ] **License Feature Check** - Only process clinics with "reminders" feature enabled
- [ ] **Concurrency Limits** - Check license.max_concurrency before creating calls
- [ ] **Skip Already Reminded** - Check GCal metadata to avoid duplicate reminders
- [ ] **Worker Control** - Respect start/stop control endpoints (can be paused/started via API)

#### 6. Google Calendar Sync Worker (Background Task)
- [ ] **Calendar Sync Worker** - `Clinic_app/workers/calendar_sync_worker.py`
- [ ] **Configurable Sync Frequency** - Per-clinic configuration for sync interval (default 6 hours, configurable)
- [ ] **Sync Service Function** - `sync_booking_with_google_calendar()` in `Clinic_app/services/booking.py`
- [ ] **Check Event Existence** - Verify `google_event_id` still exists in Google Calendar
- [ ] **Desync Detection** - Detect when Google Calendar event is missing (404 response)
- [ ] **Auto-Cancel on Desync** - Cancel booking when Google Calendar event is deleted externally
- [ ] **Batch Processing** - Process all confirmed bookings with `google_event_id` set
- [ ] **Clinic Configuration** - Add `calendar_sync_interval_hours` field to Clinic model (default 6)
- [ ] **Worker Control** - Respect start/stop control endpoints (can be paused/started via API)
- [ ] **Error Handling** - Graceful handling of API errors, rate limits, and transient failures
- [ ] **Logging** - Log all desync detections and cancellations for audit trail

#### 7. Webhook Enhancements
- [ ] **Update call_started Webhook** - Detect outbound_reminder and outbound_campaign call types
- [ ] **Update call_ended Webhook** - Update campaign_contact status based on outcome
- [ ] **Campaign Contact Tracking** - Link CallLog.related_id to campaign_contact_id
- [ ] **Reminder Call Tracking** - Link CallLog.related_id to booking_id for reminders

#### 8. Database Migrations
- [ ] **Campaign Migration** - Create campaign and campaign_contact tables
- [ ] **Clinic Configuration Migration** - Add `calendar_sync_interval_hours` field to Clinic model (default 6)
- [ ] **Indexes** - Add indexes for efficient queries (campaign_status, next_retry_at)
- [ ] **Constraints** - Add check constraints for status values

#### 9. Background Worker Infrastructure
- [ ] **Worker Control Endpoints** - `POST /admin/workers/reminders/start`, `POST /admin/workers/reminders/stop`
- [ ] **Worker Control Endpoints** - `POST /admin/workers/campaigns/start`, `POST /admin/workers/campaigns/stop`
- [ ] **Worker Control Endpoints** - `POST /admin/workers/calendar-sync/start`, `POST /admin/workers/calendar-sync/stop`
- [ ] **Worker Status Endpoints** - `GET /admin/workers/status` - Check if workers are running
- [ ] **Worker Startup** - Start background workers on application startup (or via control endpoints)
- [ ] **Worker Lifecycle** - Graceful shutdown handling
- [ ] **Error Recovery** - Worker restart on exceptions
- [ ] **Logging** - Structured logging for worker activities

#### 10. Testing
- [ ] **Unit Tests** - Campaign service, reminder service, Retell API client, calendar sync service
- [ ] **Integration Tests** - Campaign endpoints, worker functionality, calendar sync worker
- [ ] **End-to-End Tests** - Full reminder flow, full campaign flow, calendar sync desync handling

---

## ❌ What's Deferred to Phase 3

### EHR Integration
- EHR CSV import
- EHR sync mapping
- EHR conflict resolution

### Advanced Features
- Usage tracking endpoints (detailed metrics API)
- Phone routing endpoints (DID → clinic mapping)
- License enforcement (feature flags, concurrency limits)
- AvailabilitySlot sync workers (daily background sync)

### Advanced Security
- Azure Key Vault integration (use env vars for Phase 2)
- Advanced PHI encryption key rotation

---

## Phase 2 Implementation Order

### Week 1: Foundation

1. **Database Models** ✅
   - [ ] Create `Campaign` model (campaign.py)
   - [ ] Create `CampaignContact` model (campaign_contact.py)
   - [ ] Add enums for CampaignStatus and CampaignContactStatus
   - [ ] Create Alembic migration for campaign tables
   - [ ] Run migrations on dev database

2. **Retell API Client** ✅
   - [ ] Create `Clinic_app/services/retell_api.py`
   - [ ] Implement: `create_outbound_call(phone, agent_id, metadata)` 
   - [ ] Implement: Retry logic with exponential backoff
   - [ ] Implement: Error handling (API errors, rate limits)
   - [ ] Add environment variable: `RETELL_API_KEY`
   - [ ] Unit tests for Retell API client

### Week 2: Campaign System

3. **Campaign Service** ✅
   - [ ] Create `Clinic_app/services/campaign.py`
   - [ ] Implement: `sync_campaign_from_sheets(clinic_id, google_sheet_id)` - Read from Google Sheets, sync contacts
   - [ ] Implement: `get_next_pending_contact(clinic_id)` - Get oldest pending contact ready for retry
   - [ ] Implement: `calculate_next_retry(attempt_count)` - Exponential backoff (1h, 4h, 24h)
   - [ ] Implement: `update_contact_status(contact_id, status)` - Update contact status (in_progress, responded, not_answered)
   - [ ] Implement: `mark_campaign_completed(campaign_id)` - Auto-complete when patient accepts appointment
   - [ ] Implement: `check_sheets_control_cell(google_sheet_id)` - Read control cell to start/stop campaign

4. **Campaign Routes** ✅
   - [ ] Create `Clinic_app/Routes/campaign.py`
   - [ ] Implement: `POST /campaigns` - Create campaign with Google Sheet ID
   - [ ] Implement: `POST /campaigns/{campaign_id}/sync` - Sync campaign from Google Sheets
   - [ ] Implement: `GET /campaigns/{clinic_id}` - List all campaigns for clinic
   - [ ] Implement: `GET /campaigns/{campaign_id}` - Get campaign details
   - [ ] Implement: `POST /campaigns/{campaign_id}/start` - Start campaign
   - [ ] Implement: `POST /campaigns/{campaign_id}/pause` - Pause campaign
   - [ ] Add Google Sheets validation (sheet_id, required columns)
   - [ ] Add error handling and logging

5. **Campaign Worker** ✅
   - [ ] Create `Clinic_app/workers/campaign_worker.py`
   - [ ] Implement: `process_campaign_calls()` - Main worker loop
   - [ ] Implement: Periodic Google Sheets sync (every 5-10 minutes)
   - [ ] Implement: Check Google Sheets control cell before processing
   - [ ] Implement: Rate limiting (check license.max_concurrency, Retell API limits, Google API limits)
   - [ ] Implement: Retry backoff checking
   - [ ] Implement: Call Retell API to create outbound calls
   - [ ] Implement: Update campaign_contact on call creation (status = "in_progress")
   - [ ] Implement: Auto-complete campaign when patient accepts appointment (via webhook)
   - [ ] Add graceful shutdown handling
   - [ ] Add error recovery (restart on exceptions)

### Week 3: Reminder System

6. **Reminder Service** ✅
   - [ ] Create `Clinic_app/services/reminder.py`
   - [ ] Implement: `get_appointments_for_reminder(clinic_id)` - Find appointments within configurable window
   - [ ] Implement: `get_reminder_window(clinic_id)` - Get clinic's reminder_hours_before setting (default 24)
   - [ ] Implement: `check_already_reminded(event)` - Check GCal metadata
   - [ ] Implement: `mark_event_as_reminded(provider_id, event_id)` - Update GCal metadata
   - [ ] Implement: `get_patient_phone(patient_id)` - Decrypt phone_token
   - [ ] Integrate: Google Calendar service for event metadata
   - [ ] Handle: Timezone conversion (provider timezone)

7. **Reminder Worker** ✅
   - [ ] Create `Clinic_app/workers/reminder_worker.py`
   - [ ] Implement: `process_reminders()` - Main worker loop (runs hourly)
   - [ ] Implement: Check worker control status (can be paused via API)
   - [ ] Implement: Get clinics with "reminders" feature enabled
   - [ ] Implement: Check license concurrency limits
   - [ ] Implement: Call reminder service to find appointments (using clinic's reminder_hours_before)
   - [ ] Implement: Create outbound calls via Retell API
   - [ ] Implement: Mark GCal events as reminded
   - [ ] Add hourly scheduling (asyncio.sleep(3600))
   - [ ] Add error recovery

8. **Calendar Sync Service & Worker** ✅
   - [ ] Add sync functions to `Clinic_app/services/booking.py`:
     - `sync_booking_with_google_calendar(booking, provider, clinic_id, db)` - Check if event exists, cancel booking if missing
     - `sync_all_bookings_with_google_calendar(clinic_id, provider_id, db)` - Batch sync for provider
   - [ ] Create `Clinic_app/workers/calendar_sync_worker.py`
   - [ ] Implement: `process_calendar_sync()` - Main worker loop (runs at configurable interval)
   - [ ] Implement: Check worker control status (can be paused via API)
   - [ ] Implement: Get all clinics with confirmed bookings that have `google_event_id` set
   - [ ] Implement: Use clinic's `calendar_sync_interval_hours` for sync frequency (default 6 hours)
   - [ ] Implement: For each booking, check if Google Calendar event exists
   - [ ] Implement: Cancel booking if event is missing (404 from Google Calendar API)
   - [ ] Implement: Log all desync detections and cancellations
   - [ ] Implement: Handle rate limits and API errors gracefully
   - [ ] Add configurable interval scheduling (based on clinic setting)
   - [ ] Add error recovery

9. **Webhook Enhancements** ✅
   - [ ] Update `call_started` webhook in retell.py:
     - Detect call_type from metadata (reminder vs campaign)
     - Set CallLog.call_type correctly (outbound_reminder, outbound_campaign)
     - Link CallLog.related_id to booking_id (reminder) or campaign_contact_id (campaign)
   - [ ] Update `call_ended` webhook in retell.py:
     - Update campaign_contact.status based on outcome:
       - "answered" → status = 'called'
       - attempt_count >= 3 and not "answered" → status = 'unreachable'
     - Update campaign_contact.last_attempt_at and attempt_count

### Week 4: Integration & Testing

10. **Worker Infrastructure** ✅
   - [ ] Create `Clinic_app/workers/__init__.py` - Worker management module
   - [ ] Implement: Worker state management (running/stopped status)
   - [ ] Implement: `start_background_workers()` - Start campaign, reminder, and calendar sync workers
   - [ ] Implement: `stop_background_workers()` - Stop workers gracefully
   - [ ] Update `main.py` to optionally start workers on startup (or via control endpoints)
   - [ ] Implement: Graceful shutdown (catch SIGTERM, stop workers)
   - [ ] Add worker health monitoring (optional)
   - [ ] Create worker control routes in admin.py or new workers.py route file

11. **Testing** ✅
    - [ ] Unit tests: Campaign service (CSV parsing, retry logic)
    - [ ] Unit tests: Reminder service (appointment finding, timezone handling)
    - [ ] Unit tests: Retell API client (call creation, error handling)
    - [ ] Unit tests: Calendar sync service (event existence check, desync handling)
    - [ ] Integration tests: Campaign endpoints (upload, start, pause)
    - [ ] Integration tests: Campaign worker (process contacts)
    - [ ] Integration tests: Reminder worker (process reminders)
    - [ ] Integration tests: Calendar sync worker (detect and handle desyncs)
    - [ ] End-to-end test: Full campaign flow (upload → start → calls → completion)
    - [ ] End-to-end test: Full reminder flow (booking → 24h wait → reminder call)
    - [ ] End-to-end test: Calendar sync flow (delete GCal event → sync detects → booking canceled)

12. **Documentation** ✅
    - [ ] Update API documentation (FastAPI auto-docs)
    - [ ] Add campaign usage examples
    - [ ] Add reminder system documentation
    - [ ] Update deployment guide with worker configuration

---

## Phase 2 Success Criteria

### Functional Requirements
- ✅ Google Sheets sync creates/updates campaign and contacts
- ✅ Campaign worker processes pending contacts with rate limiting
- ✅ Campaign worker reads Google Sheets control cell to start/stop
- ✅ Retell API creates outbound calls for campaigns and reminders
- ✅ Campaign contacts update status based on call outcomes (in_progress, responded, not_answered)
- ✅ Campaign auto-completes when patient accepts appointment during call
- ✅ Reminder worker finds appointments within configurable window (per clinic)
- ✅ Reminder calls are created via Retell API
- ✅ GCal events are marked as "reminded" to prevent duplicates
- ✅ Retry logic works (exponential backoff: 1h, 4h, 24h)
- ✅ Rate limiting respects license.max_concurrency, Retell API limits, Google API limits
- ✅ Worker control endpoints allow start/stop of workers
- ✅ Calendar sync worker detects when Google Calendar events are deleted externally
- ✅ Calendar sync worker cancels bookings when Google Calendar event is missing (404)
- ✅ Calendar sync frequency is configurable per clinic (default 6 hours)
- ✅ Calendar sync handles API errors gracefully without false cancellations

### Technical Requirements
- ✅ All database migrations run successfully
- ✅ Retell API client handles errors gracefully
- ✅ Background workers run continuously without crashing
- ✅ Workers handle graceful shutdown
- ✅ Webhooks correctly track outbound calls
- ✅ Logs contain no PHI
- ✅ Error handling returns proper status codes

### Testing Requirements
- ✅ Unit tests for all services (campaign, reminder, retell_api, calendar sync)
- ✅ Integration tests for API endpoints
- ✅ End-to-end test: full campaign flow
- ✅ End-to-end test: full reminder flow
- ✅ End-to-end test: calendar sync detects and handles desyncs
- ✅ Worker functionality tests

---

## Phase 2 File Structure

```
Clinic_app/
├── data/
│   ├── models/
│   │   ├── campaign.py ✅ (NEW - Campaign model)
│   │   └── campaign_contact.py ✅ (NEW - CampaignContact model)
│   └── enums.py ✅ (UPDATE - Add CampaignStatus, CampaignContactStatus)
├── services/
│   ├── retell_api.py ✅ (NEW - Retell API client for outbound calls)
│   ├── google_sheets.py ✅ (NEW - Google Sheets API client for reading campaign data)
│   ├── campaign.py ✅ (NEW - Campaign service with Google Sheets sync, contact management)
│   ├── reminder.py ✅ (NEW - Reminder service for finding appointments)
│   └── booking.py ✅ (UPDATE - Add calendar sync functions)
├── Routes/
│   ├── campaign.py ✅ (NEW - Campaign endpoints: sync, CRUD, start, pause)
│   └── workers.py ✅ (NEW - Worker control endpoints: start/stop reminders and campaigns)
├── workers/
│   ├── campaign_worker.py ✅ (NEW - Background worker for processing campaign calls)
│   ├── reminder_worker.py ✅ (NEW - Background worker for reminder calls)
│   └── calendar_sync_worker.py ✅ (NEW - Background worker for Google Calendar sync)
├── alembic/
│   └── versions/
│       └── create_campaign_tables.py ✅ (NEW - Migration for campaign models)
├── main.py ✅ (UPDATE - Start background workers on startup)
└── tests/
    ├── test_campaign.py ✅ (NEW - Campaign service and endpoint tests)
    ├── test_reminder.py ✅ (NEW - Reminder service tests)
    ├── test_retell_api.py ✅ (NEW - Retell API client tests)
    ├── test_calendar_sync.py ✅ (NEW - Calendar sync service and worker tests)
    └── test_workers.py ✅ (NEW - Worker functionality tests)
```

---

## Phase 2 Dependencies

### Python Packages (add to requirements.txt)
```
# Already have:
httpx==0.25.2 ✅ (for Retell API calls)
asyncio ✅ (built-in, for background workers)

# NEW - Google Sheets API
google-api-python-client==2.108.0 ✅ (already have for Calendar, also works for Sheets)
google-auth==2.23.4 ✅ (already have)
google-auth-httplib2==0.1.1 ✅ (already have)
```

### External Services
- Retell AI account with API key
- Retell agent configured for outbound calls
- Retell phone number for outbound calls (from_number)
- Google Calendar API (already configured)
- Google Sheets API (enable in Google Cloud project)
- Google Sheets with campaign data (one sheet per clinic/campaign)

### Environment Variables
```bash
# Retell API (NEW)
RETELL_API_KEY=... (Retell API key for creating outbound calls)
RETELL_FROM_NUMBER=... (Retell phone number for outbound calls, E.164 format)

# Already have:
RETELL_WEBHOOK_SECRET=... (for webhook signature verification)
GOOGLE_SERVICE_ACCOUNT_JSON=... (for GCal and Sheets API access)

# Optional - Rate Limits (if needed)
RETELL_MAX_CALLS_PER_HOUR=100 (default, check Retell docs)
GOOGLE_SHEETS_MAX_REQUESTS_PER_MINUTE=60 (default, check Google docs)
```

---

## Phase 2 Implementation Details

### 1. Campaign Model Structure

**Campaign Table:**
- `id` (UUID, PK)
- `clinic_id` (UUID, FK to clinic)
- `name` (TEXT) - Campaign name
- `type` (TEXT, nullable) - 'hedis', 'wellness', 'followup', etc.
- `status` (TEXT) - 'pending', 'in_progress', 'completed', 'failed', 'paused'
- `google_sheet_id` (TEXT) - Google Sheets ID for reading campaign data
- `control_cell` (TEXT, nullable) - Cell reference for start/stop control (e.g., "A1")
- `created_at` (TIMESTAMPTZ)
- `started_at` (TIMESTAMPTZ, nullable)
- `completed_at` (TIMESTAMPTZ, nullable)

**CampaignContact Table:**
- `id` (UUID, PK)
- `campaign_id` (UUID, FK to campaign)
- `clinic_id` (UUID, FK to clinic) - Denormalized for efficient queries
- `patient_name` (TEXT) - Plain text (not PHI-encrypted, campaign-specific)
- `phone_e164` (TEXT) - E.164 format phone number
- `insurance` (TEXT, nullable) - Insurance information
- `reasons_for_calling` (TEXT, nullable) - Reason for the campaign call
- `status` (TEXT) - 'pending', 'in_progress', 'responded', 'not_answered', 'opted_out'
- `attempt_count` (INT, default=0)
- `last_attempt_at` (TIMESTAMPTZ, nullable)
- `next_retry_at` (TIMESTAMPTZ, nullable) - For exponential backoff
- `created_at` (TIMESTAMPTZ)

**Indexes:**
- `idx_campaign_status` on (campaign_id, status) - For efficient pending contact queries
- `idx_clinic_next_retry` on (clinic_id, next_retry_at) WHERE status = 'pending' - For scheduler

### 2. Retell API Client

**Function: `create_outbound_call(from_number, to_number, override_agent_id, metadata)`**

```python
async def create_outbound_call(
    from_number: str,  # E.164 format - Retell phone number
    to_number: str,  # E.164 format - Patient phone number
    override_agent_id: Optional[str] = None,  # Optional agent override
    metadata: Optional[Dict[str, str]] = None  # {"call_type": "reminder", "booking_id": "..."}
) -> Dict[str, Any]:
    """
    Create an outbound call via Retell API.
    
    Uses Retell SDK or direct API call:
    - POST https://api.retellai.com/create-phone-call
    - Headers: Authorization: Bearer {RETELL_API_KEY}
    - Body: {
        "from_number": from_number,
        "to_number": to_number,
        "override_agent_id": override_agent_id,  # Optional
        "metadata": metadata  # Optional
    }
    
    Returns:
        {
            "call_id": "retell_call_123",
            "status": "initiated"
        }
    """
```

**Retell API Details:**
- **Endpoint**: `POST https://api.retellai.com/create-phone-call`
- **Authentication**: Bearer token with `RETELL_API_KEY`
- **Required**: `from_number` (Retell phone number), `to_number` (patient phone)
- **Optional**: `override_agent_id` (if different from number's default agent), `metadata`
- **Rate Limits**: Check Retell API documentation for current rate limits
- **Error Handling**: 
  - Retry on 429 (rate limit) with exponential backoff
  - Retry on 5xx errors (up to 3 attempts)
  - Return structured errors

### 3. Google Sheets Integration

**Google Sheets Service:**
- Create `Clinic_app/services/google_sheets.py`
- Use Google Sheets API v4 with service account authentication
- Read data from specified Google Sheet ID
- Parse rows into campaign contacts

**Google Sheets Format:**
Required columns:
- `patient_name` (TEXT)
- `phone` (TEXT, E.164 format)
- `insurance` (TEXT, optional)
- `reasons_for_calling` (TEXT, optional)
- `status` (TEXT) - Values: "in_progress", "responded", "not_answered" (optional, defaults to "pending")

**Example Sheet:**
```
| patient_name | phone           | insurance      | reasons_for_calling | status        |
|--------------|-----------------|----------------|---------------------|---------------|
| John Smith   | +17875550000    | Blue Cross     | Annual checkup      | in_progress   |
| Jane Doe     | +17875550001    | Aetna          | Follow-up           | responded     |
```

**Control Cell:**
- Read from specified cell (e.g., "A1" or "CONTROL!A1")
- Values: "START" or "STOP" (case-insensitive)
- If "STOP", campaign worker pauses processing
- If "START" or empty, campaign worker processes contacts

**Processing:**
1. Authenticate with Google Sheets API using service account
2. Read sheet data (validate required columns exist)
3. Parse rows (validate phone E.164 format)
4. Sync with database:
   - Create new contacts for rows not in DB
   - Update existing contacts if status changed in sheet
   - Skip rows with invalid data (log errors)
5. Return sync summary (created, updated, errors)

### 4. Campaign Worker Algorithm

```python
async def process_campaign_calls():
    """
    Continuous loop processing pending campaign contacts.
    """
    while True:
        # Get next pending contact (oldest first, ready for retry)
        contact = await get_next_pending_campaign_contact()
        
        if not contact:
            await asyncio.sleep(60)  # Wait 1 minute if no pending contacts
            continue
        
        # Check clinic concurrency limits
        clinic = await get_clinic(contact.clinic_id)
        if not await check_concurrency_limit(clinic.id):
            await asyncio.sleep(30)  # Wait if at limit
            continue
        
        # Check retry backoff
        if contact.next_retry_at and contact.next_retry_at > datetime.now(timezone.utc):
            continue  # Skip if not ready for retry
        
        # Create outbound call via Retell
        try:
            call = await retell_api.create_outbound_call(
                phone=contact.phone_e164,
                agent_id=clinic.retell_agent_id,
                metadata={
                    "campaign_contact_id": str(contact.id),
                    "call_type": "campaign"
                }
            )
            
            # Update contact
            contact.attempt_count += 1
            contact.last_attempt_at = datetime.now(timezone.utc)
            contact.next_retry_at = calculate_next_retry(contact.attempt_count)
            await session.commit()
            
        except Exception as e:
            logger.error(f"Failed to create campaign call: {e}")
            contact.attempt_count += 1
            contact.next_retry_at = calculate_next_retry(contact.attempt_count)
            await session.commit()
```

**Retry Logic:**
```python
def calculate_next_retry(attempt_count: int) -> datetime:
    """
    Calculate next retry time with exponential backoff.
    """
    backoff_hours = [1, 4, 24]  # Hours to wait before retry
    if attempt_count <= len(backoff_hours):
        hours = backoff_hours[attempt_count - 1]
    else:
        hours = 24  # Default to 24 hours after 3 attempts
    
    return datetime.now(timezone.utc) + timedelta(hours=hours)
```

### 5. Reminder Worker Algorithm

```python
async def process_reminders():
    """
    Check for appointments within configurable window and send reminder calls.
    Runs every hour.
    """
    while True:
        try:
            # Check if worker is enabled (can be stopped via control endpoint)
            if not reminder_worker_enabled:
                await asyncio.sleep(3600)
                continue
            
            now = datetime.now(timezone.utc)
            
            # Get clinics with reminders feature enabled
            clinics = await get_clinics_with_feature("reminders")
            
            for clinic in clinics:
                # Get clinic's reminder window (default 24 hours)
                reminder_hours = clinic.reminder_hours_before or 24
                reminder_window_start = now + timedelta(hours=reminder_hours)
                reminder_window_end = now + timedelta(hours=reminder_hours + 1)
            
                # Check license concurrency limits
                if not await check_concurrency_limit(clinic.id):
                    continue  # Skip if at limit
                
                for provider in clinic.providers:
                    # Fetch Google Calendar events in reminder window
                    events = await google_calendar.list_events(
                        calendar_id=provider.google_calendar_id,
                        time_min=reminder_window_start,
                        time_max=reminder_window_end
                    )
                    
                    for event in events:
                        # Check if already reminded
                        metadata = google_calendar.parse_extended_properties(event)
                        if metadata and metadata.get("reminded") == "true":
                            continue
                        
                        # Get booking_id from event metadata
                        booking_id = metadata.get("booking_id") if metadata else None
                        if not booking_id:
                            continue  # Skip events without booking_id
                        
                        # Get booking and patient
                        booking = await get_booking_by_id(booking_id)
                        if not booking or booking.status != BookingStatus.CONFIRMED:
                            continue
                        
                        patient = await get_patient(booking.patient_id)
                        
                        # Decrypt phone for calling
                        phone = decrypt_phi(patient.phone_token)
                        
                        # Create outbound call via Retell
                        call = await retell_api.create_outbound_call(
                            phone=phone,
                            agent_id=clinic.retell_agent_id,
                            metadata={
                                "booking_id": str(booking.id),
                                "call_type": "reminder"
                            }
                        )
                        
                        # Mark event as reminded
                        await google_calendar.update_event(
                            calendar_id=provider.google_calendar_id,
                            event_id=event["id"],
                            extended_properties={
                                "private": {
                                    **metadata,
                                    "reminded": "true"
                                }
                            }
                        )
            
            # Wait 1 hour before next run
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"Error in reminder worker: {e}", exc_info=True)
            await asyncio.sleep(300)  # Wait 5 minutes on error before retry
```

### 6. Webhook Updates

**call_started Webhook:**
- Extract `metadata` from Retell webhook
- Check `metadata.call_type`:
  - If "reminder" → `CallLog.call_type = "outbound_reminder"`, `related_id = booking_id`
  - If "campaign" → `CallLog.call_type = "outbound_campaign"`, `related_id = campaign_contact_id`

**call_ended Webhook:**
- Find `CallLog` by `retell_call_id`
- If `call_type == "outbound_campaign"`:
  - Find `CampaignContact` by `related_id`
  - If `outcome == "answered"`: 
    - Check if patient accepted appointment during call (via Retell metadata or booking creation)
    - If appointment accepted: `status = "responded"`, mark campaign as completed if all contacts processed
    - Else: `status = "in_progress"` (call answered but no appointment)
  - If `outcome != "answered"`:
    - If `attempt_count >= 3`: `status = "not_answered"`
    - Else: Keep `status = "pending"` for retry
  - Update `last_attempt_at` and `attempt_count`
- If `call_type == "outbound_reminder"`:
  - Reminder call completed (already marked as reminded in GCal)

### 7. License Feature Check

**Function: `get_clinics_with_feature(feature_name)`**

```python
async def get_clinics_with_feature(db: AsyncSession, feature_name: str) -> List[Clinic]:
    """
    Get all active clinics that have a specific feature enabled in their license.
    """
    # Query: Clinic JOIN License WHERE license.features->>feature_name = 'true'
    # AND clinic.status = 'active' AND license.status = 'active'
```

**License Features JSONB:**
```json
{
  "reminders": true,
  "campaigns": true,
  "hedis": false,
  "ehr_sync": true
}
```

### 8. Concurrency Limit Check

**Function: `check_concurrency_limit(clinic_id)`**

```python
async def check_concurrency_limit(db: AsyncSession, clinic_id: UUID) -> bool:
    """
    Check if clinic is below max_concurrency limit.
    Also checks Retell API rate limits and Google API rate limits.
    
    Returns:
        True if can create new call, False if at limit
    """
    # Get license.max_concurrency
    # Count active CallLog entries (started_at is not null, ended_at is null)
    # Check Retell API rate limits (if configured)
    # Check Google API rate limits (if configured)
    # Return count < max_concurrency AND within API limits
```

### 9. Clinic Reminder Configuration

**Add to Clinic Model:**
- `reminder_hours_before` (INT, nullable, default=24) - Hours before appointment to send reminder
- Admin endpoint: `PUT /admin/clinics/{clinic_id}/reminder-settings` - Update reminder timing

### 10. Google Calendar Sync Implementation

**Add to Clinic Model:**
- `calendar_sync_interval_hours` (INT, nullable, default=6) - Hours between calendar sync runs
- Admin endpoint: `PUT /admin/clinics/{clinic_id}/calendar-sync-settings` - Update sync interval

**Sync Service Functions (in `Clinic_app/services/booking.py`):**

```python
async def sync_booking_with_google_calendar(
    db: AsyncSession,
    booking: Booking,
    provider: Provider,
    clinic_id: UUID
) -> bool:
    """
    Check if Google Calendar event exists for booking.
    If event is missing (404), cancel the booking.
    
    Returns:
        True if sync successful, False if booking was canceled due to missing event
    """
    if not booking.google_event_id or not provider.google_calendar_id:
        return True  # No sync needed
    
    try:
        # Check if event exists
        event = await GoogleCalendarService.get_event(
            calendar_id=provider.google_calendar_id,
            event_id=booking.google_event_id,
            clinic_id=clinic_id,
            db=db
        )
        
        if event is None:
            # Event missing - cancel booking
            logger.warning(
                f"Google Calendar event missing for booking {booking.id}, canceling booking"
            )
            await cancel_booking(
                db=db,
                booking_id=booking.id,
                clinic_id=clinic_id,
                actor="system"  # System-initiated cancellation
            )
            return False
        
        return True  # Event exists, sync successful
        
    except Exception as e:
        # Log error but don't cancel on transient API errors
        logger.error(f"Error syncing booking {booking.id} with Google Calendar: {e}")
        return True  # Assume sync successful to avoid false cancellations


async def sync_all_bookings_with_google_calendar(
    db: AsyncSession,
    clinic_id: UUID,
    provider_id: Optional[UUID] = None
) -> Dict[str, int]:
    """
    Sync all confirmed bookings with google_event_id for a clinic/provider.
    
    Returns:
        Dict with sync statistics: {"synced": count, "canceled": count, "errors": count}
    """
    # Query confirmed bookings with google_event_id
    query = select(Booking).where(
        and_(
            Booking.clinic_id == clinic_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.google_event_id.isnot(None)
        )
    )
    
    if provider_id:
        query = query.where(Booking.provider_id == provider_id)
    
    result = await db.execute(query)
    bookings = result.scalars().all()
    
    stats = {"synced": 0, "canceled": 0, "errors": 0}
    
    for booking in bookings:
        provider = await db.get(Provider, booking.provider_id)
        if not provider:
            stats["errors"] += 1
            continue
        
        try:
            sync_result = await sync_booking_with_google_calendar(
                db=db,
                booking=booking,
                provider=provider,
                clinic_id=clinic_id
            )
            
            if sync_result:
                stats["synced"] += 1
            else:
                stats["canceled"] += 1
                
        except Exception as e:
            logger.error(f"Error syncing booking {booking.id}: {e}")
            stats["errors"] += 1
    
    return stats
```

**Calendar Sync Worker Algorithm:**

```python
async def process_calendar_sync():
    """
    Continuous loop syncing bookings with Google Calendar.
    Runs at configurable interval per clinic.
    """
    while True:
        try:
            # Check if worker is enabled
            if not calendar_sync_worker_enabled:
                await asyncio.sleep(3600)  # Check every hour
                continue
            
            # Get all active clinics
            clinics = await get_all_active_clinics()
            
            for clinic in clinics:
                # Get clinic's sync interval (default 6 hours)
                sync_interval = clinic.calendar_sync_interval_hours or 6
                
                # Check if it's time to sync this clinic
                # (Track last sync time per clinic)
                if not should_sync_clinic(clinic.id, sync_interval):
                    continue
                
                # Sync all bookings for this clinic
                stats = await sync_all_bookings_with_google_calendar(
                    db=db,
                    clinic_id=clinic.id
                )
                
                logger.info(
                    f"Calendar sync completed for clinic {clinic.id}: "
                    f"synced={stats['synced']}, canceled={stats['canceled']}, errors={stats['errors']}"
                )
                
                # Update last sync time
                update_last_sync_time(clinic.id)
            
            # Sleep for minimum interval (1 hour) before next check
            await asyncio.sleep(3600)
            
        except Exception as e:
            logger.error(f"Error in calendar sync worker: {e}", exc_info=True)
            await asyncio.sleep(300)  # Wait 5 minutes on error before retry
```

**Key Features:**
- Per-clinic configurable sync frequency (default 6 hours)
- Only syncs confirmed bookings with `google_event_id` set
- Cancels booking if Google Calendar event is missing (404)
- Handles API errors gracefully (doesn't cancel on transient errors)
- Logs all sync operations and cancellations for audit trail
- Respects worker control endpoints (can be paused/started)

### 11. Worker Control Endpoints

**Endpoints:**
- `POST /admin/workers/reminders/start` - Start reminder worker
- `POST /admin/workers/reminders/stop` - Stop reminder worker
- `POST /admin/workers/campaigns/start` - Start campaign worker
- `POST /admin/workers/campaigns/stop` - Stop campaign worker
- `POST /admin/workers/calendar-sync/start` - Start calendar sync worker
- `POST /admin/workers/calendar-sync/stop` - Stop calendar sync worker
- `GET /admin/workers/status` - Get worker status (running/stopped)

**Worker State Management:**
- Store worker state in memory (or database for persistence)
- Workers check state before processing
- Graceful shutdown on stop command

---

## Phase 2 Risks & Mitigations

### Risk 1: Retell API Rate Limits
- **Mitigation**: Implement exponential backoff, respect concurrency limits, queue calls

### Risk 2: Background Worker Crashes
- **Mitigation**: Error recovery with try/except, restart workers on exceptions, structured logging

### Risk 3: Duplicate Reminder Calls
- **Mitigation**: Check GCal metadata "reminded" flag before creating calls

### Risk 4: Campaign Contact Retry Loops
- **Mitigation**: Max attempt_count limit (mark as unreachable after 3 attempts), exponential backoff

### Risk 5: Timezone Handling in Reminders
- **Mitigation**: Calculate reminder window in provider's timezone, use pytz for conversions

---

## Phase 2 Deliverables

1. **Working Campaign System** - CSV upload, worker processing, status tracking
2. **Working Reminder System** - Hourly worker, 24h ahead detection, GCal integration
3. **Retell API Integration** - Outbound call creation, error handling
4. **Background Workers** - Campaign and reminder workers running continuously
5. **Webhook Enhancements** - Proper tracking of outbound calls
6. **Test Suite** - Unit + integration tests for all new functionality
7. **Documentation** - API docs, worker configuration, usage examples

---

## Next Steps After Phase 2

Once Phase 2 is complete and tested:
- **Phase 3**: EHR sync, usage tracking endpoints, phone routing
- **Phase 3**: Advanced license enforcement, feature flags
- **Phase 3**: Azure Key Vault integration

---

**Estimated Timeline**: 4 weeks for Phase 2 MVP

