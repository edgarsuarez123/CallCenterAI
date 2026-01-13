# PRD — Architecture B (Retell AI + Google Calendar + Thin Backend)

**Version: 3.1 — Updated Implementation Status**  
**Goal:** Create a multi-clinic, HIPAA-eligible AI call center using Retell AI, Google Calendar, and a FastAPI backend.

**Last Updated:** 2025-01-XX  
**Implementation Status:** Phase 1 ~95% Complete (Core booking functionality implemented, background workers pending)

---

## 0. DEFINITIONS

- **Backend**: FastAPI service running in Azure Container Apps
- **DB**: Azure PostgreSQL (asyncpg driver, async SQLAlchemy)
- **Scheduling System**: Google Calendar + AvailabilitySlot model (dual-source)
- **Voice Engine**: Retell AI
- **Clinic**: A logical tenant (UUID-based, licensed)
- **Provider**: A human clinician; each has a unique Google Calendar and timezone
- **Availability Slot**: A time block (can be 15-min, 30-min, or variable) tracked in DB
- **Booking**: An appointment record with tentative/confirmed/canceled states
- **Capacity**: Maximum number of concurrent bookings allowed per slot per provider
- **PHI**: Name, phone, email, appointment date/time (encrypted at rest in Patient model)
- **Hold Token**: UUID token for temporary reservations (tentative bookings)

---

## 1. ARCHITECTURE OVERVIEW

The system consists of:

### Retell AI Agents
- One agent per clinic
- Inbound + outbound call support
- Calls backend via HTTPS tool endpoints
- Webhook callbacks for call lifecycle events

### Backend (FastAPI)
Responsible for:
- Scheduling calls (with tentative hold system)
- Calendar availability computation (dual-source: GCal + AvailabilitySlot)
- Double-booking enforcement (database constraints + application logic)
- Outbound reminder calls
- Outbound campaign calls
- EHR CSV import & GCal sync
- Usage counting (via webhooks)
- PHI storage (encrypted)
- Tenant isolation (clinic_id on all models)
- License enforcement
- Phone routing (DID → clinic mapping)

### Google Calendar
- One Google calendar per provider
- Backend reads and writes appointments
- Backend prevents conflicts (Google does NOT)
- Extended properties used for metadata tracking

### DB (PostgreSQL)
- Stores clinic configuration (with licensing)
- Provider→Calendar mapping (with timezone per provider)
- Patient records (encrypted PHI)
- Booking records (with tentative/confirmed states)
- AvailabilitySlot records (canonical source of truth)
- BookingAudit records (immutable event log)
- Campaign data
- Usage metrics
- EHR sync mapping
- Phone routing (DID → clinic)

---

## 2. CLARITY RULES (FOR AI EXECUTION)

Every requirement below is explicit. No guessing. If uncertain, backend must reject the request with an error.

**Error Response Format:**
```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error message",
    "details": {
      "field": "specific validation issue"
    }
  }
}
```

**HTTP Status Codes:**
- `200`: Success
- `400`: Validation error (client error)
- `401`: Authentication error
- `403`: Authorization error (license/permission)
- `404`: Resource not found
- `409`: Conflict (e.g., double-booking attempt)
- `500`: Internal server error

---

## 3. DATA MODELS (FULL SPECIFICATION)

All models use UUID primary keys (not SERIAL/INT). All timestamps are timezone-aware (TIMESTAMPTZ).

### 3.1 Clinic
```sql
clinic (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    network_id UUID,  -- Optional: for multi-clinic networks
    name TEXT NOT NULL,
    tier TEXT NOT NULL,  -- basic/pro/enterprise (from license)
    status TEXT NOT NULL DEFAULT 'active',  -- active/suspended
    license_token TEXT NOT NULL UNIQUE,
    license_expires_at TIMESTAMPTZ,
    business_hours_start TEXT NOT NULL DEFAULT '09:00',  -- HH:MM format
    business_hours_end TEXT NOT NULL DEFAULT '17:00',  -- HH:MM format
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Business Hours:**
- `business_hours_start` and `business_hours_end` define the clinic's operating hours
- Used by availability service to generate candidate appointment slots
- Can be managed via `GET/PUT /admin/clinics/{id}/business-hours` endpoints
- Default: 09:00 - 17:00

**Relationships:**
- One-to-one with `license`
- One-to-many with `provider`, `patient`, `booking`, `availability_slot`, `phone_route`, `booking_audit`

### 3.2 License
```sql
license (
    clinic_id UUID PRIMARY KEY REFERENCES clinic(id) ON DELETE CASCADE,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',  -- active/suspended/expired
    tier TEXT NOT NULL,  -- basic/pro/enterprise
    max_concurrency INT NOT NULL,  -- Max concurrent calls
    features JSONB NOT NULL DEFAULT '{}',  -- {"reminders": true, "hedis": false, "campaigns": true}
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Features JSONB structure:**
```json
{
  "reminders": true,
  "hedis": false,
  "campaigns": true,
  "ehr_sync": true,
  "multi_language": true
}
```

### 3.3 Clinic Integration
```sql
clinic_integration (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    retell_agent_id TEXT NOT NULL,
    retell_did TEXT NOT NULL,  -- E.164 format
    google_service_account_json TEXT NOT NULL,  -- Encrypted JSON
    default_appointment_length_minutes INT NOT NULL DEFAULT 15,
    default_capacity INT NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(clinic_id)  -- One integration per clinic
)
```

### 3.4 Provider → Google Calendar Mapping
```sql
provider (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,  -- Used in AI voice replies, GCal titles
    external_id TEXT,  -- Stable EHR/CSV reference (optional)
    google_calendar_id TEXT NOT NULL,  -- Linked Google Calendar ID
    timezone TEXT NOT NULL,  -- e.g., "America/New_York" (per-provider timezone)
    booking_duration_mins INT NOT NULL DEFAULT 30,  -- Default appointment length
    capacity INT NOT NULL DEFAULT 1,  -- Max concurrent bookings per slot
    active BOOLEAN NOT NULL DEFAULT TRUE,  -- Currently bookable
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Indexes:**
- `idx_provider_clinic_active` on (clinic_id, active)

### 3.5 Patient (PHI Encrypted)
```sql
patient (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    name_token BYTEA NOT NULL,  -- Encrypted patient name (PHI)
    dob_token BYTEA NOT NULL,  -- Encrypted date of birth (PHI)
    phone_token BYTEA NOT NULL,  -- Encrypted phone number (PHI)
    email_token BYTEA,  -- Encrypted email address (PHI, nullable)
    name_dob_hash TEXT NOT NULL,  -- SHA-256 hash of normalized (name|dob) for efficient lookup (NOT PHI)
    language TEXT NOT NULL DEFAULT 'en',  -- en/es for AI voice selection
    insurance_plan TEXT,  -- Insurance plan information (nullable)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Indexes:**
- `idx_clinic_name_dob_hash` on (clinic_id, name_dob_hash)  -- For efficient patient lookup by name+DOB

**Encryption:**
- All PHI fields (`name_token`, `dob_token`, `phone_token`, `email_token`) must be encrypted at rest using AES-256-GCM
- Encryption key stored in Azure Key Vault (Phase 2) or environment variable (Phase 1)
- Decryption only happens in application layer when needed for calls or verification
- `name_dob_hash` is NOT PHI (irreversible hash, safe to index and query)

**Lookup Strategy:**
- Patients are identified by name + DOB within clinic scope (not by phone, as patients may call from different numbers)
- Hash-based lookup provides O(1) performance without decrypting all records
- Hash collisions are detected by decrypting and verifying name+DOB match

### 3.6 AvailabilitySlot (Canonical Source)
```sql
availability_slot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
    slot_start TIMESTAMPTZ NOT NULL,
    slot_end TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,  -- 'csv' or 'gcal' (SlotSource enum)
    status TEXT NOT NULL DEFAULT 'free',  -- 'free', 'booked', 'blocked' (SlotStatus enum)
    last_sync_at TIMESTAMPTZ,  -- Last refresh time from source
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Constraints:**
- `UNIQUE(provider_id, slot_start, slot_end)`  -- Prevents duplicate slots
- `CHECK (slot_end > slot_start)`  -- End must be after start

**Indexes:**
- `idx_clinic_status_start` on (clinic_id, status, slot_start)  -- For efficient "find free slots" queries

**Purpose:**
- Dual-source tracking: slots can come from CSV import OR Google Calendar sync
- Status tracks availability: FREE (bookable), BOOKED (has booking), BLOCKED (intentionally unavailable)
- Backend uses this as canonical source for availability queries

### 3.7 Booking (Appointment Record)
```sql
booking (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    slot_start TIMESTAMPTZ NOT NULL,
    slot_end TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'tentative',  -- 'tentative', 'confirmed', 'canceled' (BookingStatus enum)
    hold_token UUID,  -- Temporary reservation token (only for tentative)
    hold_expires_at TIMESTAMPTZ,  -- Expiration timestamp (only for tentative)
    google_event_id TEXT,  -- Linked GCal event (nullable for graceful degradation)
    source TEXT,  -- Origin: 'call', 'reminder', 'hedis', 'manual', 'ehr_sync'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Constraints:**
- `CHECK (slot_end > slot_start)` - End must be after start

**Indexes:**
- `idx_booking_slot_lookup` on (provider_id, slot_start, slot_end, status) - Non-unique, for slot lookups
- `idx_status_hold_expires` on (status, hold_expires_at) - For reaper efficiency (expiring tentative holds)

**Capacity Enforcement:**
- Application-level enforcement using `SELECT FOR UPDATE` + count check
- Supports `provider.capacity > 1` (multiple concurrent bookings per slot)
- Race conditions prevented via row locking during capacity count
- Booking service function: `_count_slot_bookings()` with FOR UPDATE lock

**State Machine:**
1. **TENTATIVE**: Temporary hold with `hold_token` and `hold_expires_at` (5 minutes)
2. **CONFIRMED**: Finalized booking (hold_token cleared, hold_expires_at cleared, GCal event created)
3. **CANCELED**: Canceled appointment (hold_token cleared, GCal event deleted if exists)

### 3.8 BookingAudit (Immutable Event Log)
```sql
booking_audit (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    booking_id UUID NOT NULL REFERENCES booking(id) ON DELETE RESTRICT,
    action TEXT NOT NULL,  -- 'hold', 'confirm', 'cancel', 'expire' (BookingAction enum)
    actor TEXT NOT NULL,  -- System identifier or user identifier
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Indexes:**
- `idx_booking_audit_booking` on (booking_id)  -- All changes to a booking
- `idx_booking_audit_clinic_timestamp` on (clinic_id, timestamp)  -- Tenant-scoped time queries

**Purpose:**
- Immutable audit trail for HIPAA compliance
- Every status change must create an audit entry
- Used for debugging and compliance reporting

### 3.9 Campaign
```sql
campaign (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    type TEXT,  -- e.g., 'hedis', 'wellness', 'followup'
    status TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'paused')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
)
```

### 3.10 Campaign Contact
```sql
campaign_contact (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id UUID NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    patient_name TEXT NOT NULL,  -- Plain text (not PHI-encrypted, campaign-specific)
    phone_e164 TEXT NOT NULL,  -- E.164 format
    attempt_count INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('pending', 'called', 'unreachable', 'opted_out')),
    last_attempt_at TIMESTAMPTZ,
    next_retry_at TIMESTAMPTZ,  -- For exponential backoff
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Indexes:**
- `idx_campaign_status` on (campaign_id, status)  -- For efficient pending contact queries
- `idx_clinic_next_retry` on (clinic_id, next_retry_at) WHERE status = 'pending'  -- For scheduler

### 3.11 Call Log (PHI-free)
```sql
call_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL,
    call_type TEXT NOT NULL CHECK (call_type IN (
        'inbound', 'outbound_reminder', 'outbound_campaign'
    )),
    related_id UUID,  -- booking_id or campaign_contact_id (nullable)
    tentative_booking_id UUID,  -- For hold cleanup on call_ended (nullable)
    duration_seconds INT,  -- Calculated from webhook events
    outcome TEXT,  -- 'answered', 'no_answer', 'busy', 'failed', 'voicemail'
    retell_call_id TEXT,  -- Retell's call identifier
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
)
```

**Indexes:**
- `idx_clinic_call_type_timestamp` on (clinic_id, call_type, created_at)  -- For usage reporting
- `ix_call_log_retell_call_id` on (retell_call_id)  -- For webhook correlation

**PHI-free requirement:**
- No patient names, phone numbers, or other PHI in this table
- Only IDs and aggregated metrics

**Hold Cleanup:**
- `tentative_booking_id` tracks any tentative booking created during the call
- On `call_ended` webhook, if booking is still TENTATIVE, it is automatically canceled
- This is the PRIMARY cleanup mechanism for abandoned calls

### 3.12 EHR Sync Mapping
```sql
ehr_appointment_sync (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    ehr_id TEXT NOT NULL,  -- External EHR appointment ID
    booking_id UUID REFERENCES booking(id) ON DELETE SET NULL,  -- Linked booking (if exists)
    google_event_id TEXT NOT NULL,  -- Linked GCal event
    last_updated TIMESTAMPTZ DEFAULT now(),
    UNIQUE(clinic_id, ehr_id)  -- One sync record per EHR appointment
)
```

**Indexes:**
- `idx_ehr_clinic_ehr_id` on (clinic_id, ehr_id)  -- For efficient lookup

### 3.13 Phone Route (DID → Clinic Mapping)
```sql
phone_route (
    did_e164 TEXT PRIMARY KEY,  -- E.164 format phone number (e.g., +15551234567)
    clinic_id UUID NOT NULL REFERENCES clinic(id) ON DELETE CASCADE,
    container_url TEXT NOT NULL,  -- Internal container address for gateway reverse-proxy
    active BOOLEAN NOT NULL DEFAULT TRUE,  -- Route status
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

**Indexes:**
- `idx_phone_route_clinic_active` on (clinic_id, active)  -- For efficient routing

**Purpose:**
- Maps inbound phone numbers (DIDs) to clinics
- Supports single global webhook endpoint that routes to correct clinic
- Used by Retell or Azure Communication Services for call routing

---

## 4. BACKEND API (FULL SPECIFICATION)

All endpoints are FastAPI with async/await. All responses use the standard format:

**Success Response:**
```json
{
  "success": true,
  "data": { ... }
}
```

**Error Response:**
```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": { ... }
  }
}
```

### 4.1 Retell Tool Endpoints

#### POST /retell/schedule
**Purpose:** Book/reschedule/cancel appointments (called by Retell AI agent during call).

**Authentication:** Retell signature verification (HMAC-SHA256)

**Request JSON:**
```json
{
  "call_id": "retell_call_123",  // Retell call ID for tracking
  "clinic_id": "550e8400-e29b-41d4-a716-446655440000",
  "patient_name": "John Smith",
  "patient_dob": "1990-05-15",  // YYYY-MM-DD
  "phone": "+17875550000",
  "email": "john@example.com",
  "intent": "book",  // or "reschedule" or "cancel"
  "preferred_date": "2025-11-20",  // ISO date (YYYY-MM-DD)
  "preferred_time_range": ["09:00", "12:00"],  // [start_time, end_time] in HH:MM format
  "language": "en",  // "en" or "es"
  "provider_preference": "Dr. Lopez"  // Optional: provider display_name
}
```

**Response JSON (Success):**
```json
{
  "success": true,
  "message": "Appointment held with Dr. Lopez",
  "booking": {
    "id": "660e8400-e29b-41d4-a716-446655440000",
    "start_time": "2025-11-20T09:15:00-05:00",
    "end_time": "2025-11-20T09:30:00-05:00",
    "provider_name": "Dr. Lopez",
    "status": "tentative",
    "date": "2025-11-20"
  },
  "hold_token": "770e8400-e29b-41d4-a716-446655440000",
  "alternatives": [...]  // Other available slots
}
```

**Response JSON (Multiple Provider Match - Needs Clarification):**
```json
{
  "success": false,
  "message": "Multiple providers match that name. Please specify which one.",
  "needs_clarification": true,
  "provider_options": ["Dr. Maria Lopez", "Dr. Juan Lopez"]
}
```

**Response JSON (Preferred Provider Unavailable - Alternatives Offered):**
```json
{
  "success": false,
  "message": "Dr. Lopez is unavailable on that date. Here are their next available times.",
  "alternatives": [...],
  "alternatives_same_provider": true
}
```

**Response JSON (No Availability with Preferred - Other Provider Offered):**
```json
{
  "success": false,
  "message": "Dr. Lopez has no upcoming availability. Dr. Smith is available.",
  "alternatives": [...],
  "alternative_provider": "Dr. Smith"
}
```

**Provider Selection Logic:**
| Scenario | Behavior |
|----------|----------|
| Patient says "Dr. Lopez" (1 match) | Book with Dr. Lopez |
| Patient says "Lopez" (2+ matches) | Return names for clarification ("Dr. Maria Lopez", "Dr. Juan Lopez") |
| Dr. Lopez unavailable on date | Offer Dr. Lopez's other available dates |
| Dr. Lopez fully booked | Offer other providers |
| No preference | Load balance - pick least-busy provider first |

**Load Balancing (No Provider Preference):**
- Get all active providers sorted by upcoming CONFIRMED booking count (ascending)
- Check availability starting with least-busy provider
- Return first available slot (naturally balances workload across providers)

**Business Logic:**
1. Validate clinic_id exists and is active
2. Find or create patient by name + DOB (within clinic) using hash-based lookup
3. Encrypt all patient PHI (name, DOB, phone, email) and store in encrypted tokens
4. If intent is "book":
   - **Provider Selection:**
     - If `provider_preference` specified:
       - Search providers by name (ILIKE match)
       - If 0 matches: return error
       - If 1 match: use that provider
       - If 2+ matches: return `needs_clarification=true` with `provider_options`
     - If no preference:
       - Get providers sorted by workload (least busy first)
   - **Availability Check:**
     - Generate slots within preferred_time_range (or get next available)
     - For each provider: check availability via Google Calendar + DB bookings
     - If slot available: create tentative booking with 5-minute hold
   - **Fallback Logic (if preferred provider unavailable):**
     - First: offer other dates for same provider (`alternatives_same_provider=true`)
     - Then: offer other providers (`alternative_provider=name`)
   - **Hold Tracking:**
     - Update `CallLog.tentative_booking_id` for cleanup on call_ended
5. If intent is "reschedule":
   - Find existing booking for patient (or by booking_id)
   - Cancel old booking, create new tentative for new slot
6. If intent is "cancel":
   - Find patient's upcoming confirmed booking
   - Update status to 'canceled', delete Google Calendar event

**Validation Rules:**
- `preferred_date` must be in the future
- `preferred_time_range` must be valid time format (HH:MM)
- `phone` must be E.164 format
- `email` must be valid email format (if provided)
- `language` must be "en" or "es"
- Provider must be active and belong to clinic

#### POST /retell/confirm_booking
**Purpose:** Confirm a tentative booking (called after patient confirms during call).

**Request JSON:**
```json
{
  "hold_token": "770e8400-e29b-41d4-a716-446655440000",
  "clinic_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Response JSON:**
```json
{
  "success": true,
  "data": {
    "booking": {
      "id": "660e8400-e29b-41d4-a716-446655440000",
      "status": "confirmed",
      "start_time": "2025-11-20T09:15:00-05:00",
      "end_time": "2025-11-20T09:30:00-05:00",
      "provider_name": "Dr. Lopez",
      "google_event_id": "abc123xyz"  // If GCal sync succeeded
    }
  }
}
```

**Business Logic:**
1. Find booking by hold_token and clinic_id
2. Validate hold_token is not expired
3. Update booking status to 'confirmed'
4. Clear hold_token and hold_expires_at
5. Create Google Calendar event
6. Update AvailabilitySlot status to 'booked'
7. Create BookingAudit entry (action = 'confirm')
8. Return confirmed booking

#### GET /retell/availability
**Purpose:** Get available appointment slots (called by Retell AI to suggest times).

**Query Parameters:**
- `clinic_id` (required): UUID
- `date` (required): ISO date (YYYY-MM-DD)
- `provider_id` (optional): UUID (if specific provider requested)
- `duration_minutes` (optional): Default from provider.booking_duration_mins

**Response JSON:**
```json
{
  "success": true,
  "data": {
    "slots": [
      {
        "start_time": "2025-11-20T09:00:00-05:00",
        "end_time": "2025-11-20T09:15:00-05:00",
        "provider_name": "Dr. Lopez",
        "provider_id": "880e8400-e29b-41d4-a716-446655440000"
      },
      {
        "start_time": "2025-11-20T09:15:00-05:00",
        "end_time": "2025-11-20T09:30:00-05:00",
        "provider_name": "Dr. Lopez",
        "provider_id": "880e8400-e29b-41d4-a716-446655440000"
      }
    ]
  }
}
```

**Business Logic:**
1. Query AvailabilitySlot where:
   - clinic_id matches
   - provider_id matches (if provided)
   - slot_start is on requested date
   - status = 'free'
   - slot_start >= now() (future only)
2. Exclude slots that have tentative/confirmed bookings
3. Return sorted by start_time

### 4.2 Retell Webhook Endpoints

#### POST /retell/webhook/call_started
**Purpose:** Receive call start event from Retell.

**Authentication:** Retell signature verification

**Request JSON (Retell format):**
```json
{
  "event": "call_started",
  "call_id": "retell_call_123",
  "from_number": "+15551234567",
  "to_number": "+15559876543",
  "direction": "inbound",  // or "outbound"
  "timestamp": "2025-11-19T14:00:00Z"
}
```

**Response:** `200 OK` (acknowledge receipt)

**Business Logic:**
1. Route call to clinic via `ClinicIntegration.retell_agent_id` (agent_id → clinic_id)
2. Create call_log entry:
   - clinic_id (from integration lookup)
   - call_type: 'inbound' or 'outbound_reminder' or 'outbound_campaign'
   - retell_call_id: call_id
   - started_at: timestamp
3. Update campaign_contact if outbound_campaign (increment attempt_count)

#### POST /retell/webhook/call_ended
**Purpose:** Receive call end event from Retell. **Primary mechanism for releasing unconfirmed holds.**

**Request JSON:**
```json
{
  "call_id": "retell_call_123",
  "duration_seconds": 180,
  "outcome": "answered",  // or "no_answer", "busy", "failed", "voicemail"
  "timestamp": "2025-11-19T14:03:00Z"
}
```

**Business Logic:**
1. Find call_log by retell_call_id
2. Update call_log:
   - duration_seconds: duration_seconds
   - outcome: outcome
   - ended_at: timestamp
3. **Release unconfirmed holds:**
   - If `call_log.tentative_booking_id` exists:
     - Get booking by ID
     - If booking status is still TENTATIVE → cancel it (release the hold)
     - Clear `call_log.tentative_booking_id`
4. Update campaign_contact if outbound_campaign:
   - If outcome = "answered": status = 'called'
   - If attempt_count >= 3: status = 'unreachable'
   - Update last_attempt_at

**Hold Cleanup Strategy:**
- **Primary**: `call_ended` webhook cancels any unconfirmed tentative booking
- **Backup**: Reaper worker runs every 10-15 minutes for edge cases (webhook failures, network issues)

### 4.3 Campaign CSV Upload

#### POST /campaigns/{clinic_id}/upload
**Purpose:** Upload CSV file with campaign contacts.

**Authentication:** API key or JWT token

**Request:** Multipart form-data with CSV file

**CSV Format:**
```csv
patient_name,phone
John Smith,+17875550000
Jane Doe,+17875550001
```

**Validation:**
- All rows must have patient_name and phone
- Phone must be E.164 format
- If any row fails validation, entire upload is rejected

**Response JSON:**
```json
{
  "success": true,
  "data": {
    "campaign_id": "990e8400-e29b-41d4-a716-446655440000",
    "contacts_created": 150,
    "contacts_failed": 0,
    "errors": []
  }
}
```

**Business Logic:**
1. Validate clinic_id exists and has campaigns feature enabled
2. Parse CSV (validate all rows)
3. Create campaign record (status = 'pending')
4. For each row:
   - Create campaign_contact (status = 'pending')
5. Return campaign_id and summary

### 4.4 Campaign Management

#### POST /campaigns/{campaign_id}/start
**Purpose:** Start a campaign (begin processing pending contacts).

**Response:**
```json
{
  "success": true,
  "data": {
    "campaign_id": "990e8400-e29b-41d4-a716-446655440000",
    "status": "in_progress",
    "pending_contacts": 150
  }
}
```

#### POST /campaigns/{campaign_id}/pause
**Purpose:** Pause a running campaign.

#### GET /campaigns/{clinic_id}
**Purpose:** List all campaigns for a clinic.

### 4.5 EHR CSV Upload

#### POST /ehr/{clinic_id}/import
**Purpose:** Import appointments from EHR system via CSV.

**Request:** Multipart form-data with CSV file

**CSV Format:**
```csv
ehr_id,patient_name,phone,email,date,time,provider_name
ehr_001,John Smith,+17875550000,john@example.com,2025-11-20,09:00,Dr. Lopez
ehr_002,Jane Doe,+17875550001,jane@example.com,2025-11-20,10:00,Dr. Smith
```

**Validation:**
- All required fields must be present
- Date format: YYYY-MM-DD
- Time format: HH:MM (24-hour)
- Provider name must match existing provider.display_name

**Response JSON:**
```json
{
  "success": true,
  "data": {
    "imported": 50,
    "updated": 10,
    "failed": 2,
    "errors": [
      {
        "row": 3,
        "error": "Provider 'Dr. Unknown' not found"
      }
    ]
  }
}
```

**Business Logic:**
1. Validate clinic_id exists and has ehr_sync feature enabled
2. Parse CSV (validate all rows)
3. For each row:
   - Map provider_name → provider_id → google_calendar_id
   - Build datetime = date + time (in provider's timezone)
   - Check ehr_appointment_sync for existing ehr_id
   - If exists:
     - Update Google Calendar event
     - Update booking if exists
   - Else:
     - Create Google Calendar event (with extendedProperties.private.source = "ehr_sync")
     - Create booking (status = 'confirmed', source = 'ehr_sync')
     - Create or update patient record
     - Insert into ehr_appointment_sync
4. Update AvailabilitySlot status to 'booked' for imported slots

### 4.6 Usage Tracking

#### GET /usage/{clinic_id}
**Purpose:** Get usage metrics for a clinic.

**Query Parameters:**
- `start_date` (optional): ISO date
- `end_date` (optional): ISO date
- `group_by` (optional): "day", "week", "month"

**Response JSON:**
```json
{
  "success": true,
  "data": {
    "total_minutes": 1250,
    "total_calls": 85,
    "breakdown": {
      "inbound": {
        "minutes": 800,
        "calls": 50
      },
      "outbound_reminder": {
        "minutes": 300,
        "calls": 25
      },
      "outbound_campaign": {
        "minutes": 150,
        "calls": 10
      }
    },
    "period": {
      "start": "2025-11-01",
      "end": "2025-11-30"
    }
  }
}
```

---

## 5. GOOGLE CALENDAR LOGIC (EXPLICIT)

Google Calendar does NOT enforce availability or capacity. Backend MUST enforce:
- Slot length (aligned to 15-minute blocks or provider.booking_duration_mins)
- No overlap (database constraint + application logic)
- Capacity per provider per slot
- Alternatives generation

### 5.1 Slot Representation

Appointment times must align to configurable blocks:
- Default: 15-minute blocks (00, 15, 30, 45 per hour)
- Per-provider: Can use provider.booking_duration_mins (e.g., 30, 60 minutes)

**Slot Generation Algorithm:**
```python
def generate_slots(date, time_range, duration_minutes=15):
    """
    Generate available slots for a date and time range.
    
    Args:
        date: datetime.date object
        time_range: [start_time_str, end_time_str] in HH:MM format
        duration_minutes: Slot duration (default 15)
    
    Returns:
        List of (start_datetime, end_datetime) tuples in provider's timezone
    """
    slots = []
    start_hour, start_min = map(int, time_range[0].split(':'))
    end_hour, end_min = map(int, time_range[1].split(':'))
    
    current = datetime.combine(date, time(start_hour, start_min))
    end = datetime.combine(date, time(end_hour, end_min))
    
    while current + timedelta(minutes=duration_minutes) <= end:
        slots.append((current, current + timedelta(minutes=duration_minutes)))
        current += timedelta(minutes=duration_minutes)
    
    return slots
```

### 5.2 Fetch Existing Events

Before scheduling, backend must:

1. Call Google Calendar API:
```
GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events
?timeMin=<start_of_window>
&timeMax=<end_of_window>
&singleEvents=true
&orderBy=startTime
```

2. Parse events:
   - ALL events block capacity (regardless of source)
   - Exception: When searching for patient's existing appointment, ignore events where `extendedProperties.private.source != "callcenter_ai"` (to find our own bookings)

3. Count overlapping events:
   - For each slot, count events that overlap with slot_start to slot_end
   - If count >= provider.capacity: slot is unavailable

### 5.3 Double Booking Algorithm (Exact Pseudocode)

```python
async def find_available_slot(
    clinic_id: UUID,
    preferred_date: date,
    preferred_time_range: List[str],
    duration_minutes: int,
    provider_preference: Optional[str] = None
) -> Optional[Tuple[Booking, Provider]]:
    """
    Find first available slot matching criteria.
    
    Returns:
        (Booking, Provider) tuple if found, None otherwise
    """
    # Get active providers for clinic
    if provider_preference:
        providers = await get_providers_by_name(clinic_id, provider_preference)
    else:
        providers = await get_active_providers(clinic_id)
    
    # Generate slots for preferred time range
    slots = generate_slots(preferred_date, preferred_time_range, duration_minutes)
    
    for provider in providers:
        capacity = provider.capacity
        timezone = provider.timezone
        
        for slot_start, slot_end in slots:
            # Convert to provider's timezone
            slot_start_tz = localize_datetime(slot_start, timezone)
            slot_end_tz = localize_datetime(slot_end, timezone)
            
            # Check AvailabilitySlot status
            availability = await get_availability_slot(
                provider_id=provider.id,
                slot_start=slot_start_tz,
                slot_end=slot_end_tz
            )
            if availability and availability.status != SlotStatus.FREE:
                continue  # Slot is booked or blocked
            
            # Fetch Google Calendar events
            gcal_events = await fetch_gcal_events(
                calendar_id=provider.google_calendar_id,
                time_min=slot_start_tz,
                time_max=slot_end_tz
            )
            
            # Count overlapping bookings in DB
            existing_bookings = await get_bookings(
                provider_id=provider.id,
                slot_start=slot_start_tz,
                slot_end=slot_end_tz,
                status_in=[BookingStatus.TENTATIVE, BookingStatus.CONFIRMED]
            )
            
            # Count overlapping GCal events
            overlapping_gcal = count_overlapping_events(gcal_events, slot_start_tz, slot_end_tz)
            
            # Total count = DB bookings + GCal events
            total_count = len(existing_bookings) + overlapping_gcal
            
            if total_count < capacity:
                # Slot is available!
                return (slot_start_tz, slot_end_tz), provider
    
    return None  # No available slots
```

### 5.4 Google Calendar Event Metadata

When creating/updating events, backend must set:

```json
{
  "extendedProperties": {
    "private": {
      "source": "callcenter_ai",
      "booking_id": "660e8400-e29b-41d4-a716-446655440000",
      "clinic_id": "550e8400-e29b-41d4-a716-446655440000",
      "reminded": "false"  // Set to "true" after reminder call
    }
  }
}
```

**Purpose:**
- Identify our own events vs. manual/manual events
- Track reminder status
- Enable efficient lookup for reschedules/cancels
- Store `booking_id` (exists before event creation) for recovery if `google_event_id` is NULL

**Note on Failed Operations:**
- If Google Calendar API fails after retries, booking proceeds with `google_event_id = NULL` (graceful degradation)
- Failed sync operations queue deferred to Phase 2 (background worker to retry failed GCal operations)
- Phase 1: Log failures for manual review; Phase 2: Automatic retry with database queue

**Implementation Note - Retell Endpoint Format:**
The actual implementation of Retell endpoints (`/retell/schedule`, `/retell/confirm_booking`, `/retell/availability`) uses a different request format than specified in Section 4.1. The implementation:
- Extracts `agent_id` from the `call` object in the request body
- Looks up `clinic_id` from `ClinicIntegration` table using `agent_id`
- Extracts parameters from the `args` object (Retell's standard format)
- Supports both POST (Retell format) and GET (RESTful format) for `/retell/availability`

This design is more secure (no clinic_id in request) and aligns with Retell's standard tool calling format. The PRD specification in Section 4.1 shows the logical parameters, but the actual HTTP request format follows Retell's conventions.

### 5.5 Patient Appointment Detection

The availability service detects patient appointments via:

1. **Metadata Check**: Events with `extendedProperties.private.source = "callcenter_ai"` are our bookings
2. **Keyword Detection**: Events with patient-related keywords in the title count toward capacity

**Patient Keywords (English + Spanish):**
```python
PATIENT_KEYWORDS = [
    # English
    "patient", "pt", "appt", "appointment", "visit", "consult",
    "checkup", "check-up", "follow-up", "followup", "new patient",
    # Spanish
    "paciente", "cita", "consulta", "visita", "seguimiento",
    "nuevo paciente", "chequeo",
]
```

**Capacity Logic:**
- **Patient appointments** (detected via metadata or keywords): Count toward `provider.capacity`
- **External events** (staff meetings, personal appointments, etc.): Block the slot entirely
- Example: If `capacity = 2`, a slot with 1 patient appointment can accept 1 more booking. A slot with a "Staff Meeting" event is unavailable.

### 5.6 Availability Service Functions

The availability service (`Clinic_app/services/availability.py`) provides:

| Function | Use Case | Description |
|----------|----------|-------------|
| `is_slot_available()` | Core check | Check if specific slot is available (BLOCKED, GCal, capacity) |
| `get_available_slots()` | "What's available Thursday?" | Get all slots for a date using clinic business hours |
| `get_next_available_slots()` | "I want to book an appointment" | Find next N slots from today |
| `find_slot_at_time()` | "I need a 10am appointment" | Search specific time across multiple days |
| `check_and_offer_alternatives()` | "I want Thursday at 3pm" | Check specific slot, offer alternatives if unavailable |

**Integration Points:**
- Uses `GoogleCalendarService.list_events()` for calendar events
- Queries `Booking` table for TENTATIVE/CONFIRMED bookings
- Queries `AvailabilitySlot` table for BLOCKED status
- Uses `provider.capacity`, `provider.booking_duration_mins`, `provider.timezone`
- Uses `clinic.business_hours_start`, `clinic.business_hours_end` for default time ranges

### 5.7 Booking Service Functions

The booking service (`Clinic_app/services/booking.py`) manages the booking lifecycle:

| Function | Purpose | Description |
|----------|---------|-------------|
| `create_tentative_booking()` | Create hold | Creates TENTATIVE booking with 5-min hold_token |
| `confirm_booking()` | Finalize | Converts TENTATIVE → CONFIRMED, creates GCal event |
| `cancel_booking()` | Cancel | Sets status to CANCELED, deletes GCal event |
| `reschedule_booking()` | Reschedule | Cancels old booking, creates new tentative |
| `expire_booking()` | Reaper | Expires tentative hold (status → CANCELED) |
| `get_booking_by_hold_token()` | Query | Find booking by hold token |
| `get_patient_bookings()` | Query | List patient's bookings |
| `get_expired_tentative_bookings()` | Reaper | Find all expired holds for processing |

**Capacity Enforcement Logic:**
```python
async def _count_slot_bookings(db, provider_id, slot_start, slot_end) -> int:
    """Count bookings with row locking to prevent race conditions."""
    result = await db.execute(
        select(func.count(Booking.id))
        .where(
            and_(
                Booking.provider_id == provider_id,
                Booking.slot_start == slot_start,
                Booking.slot_end == slot_end,
                Booking.status.in_([BookingStatus.TENTATIVE, BookingStatus.CONFIRMED])
            )
        )
        .with_for_update()  # Lock rows during count
    )
    return result.scalar() or 0
```

**Booking Flow:**
1. **Search** → `get_available_slots()` returns options (no holds)
2. **Select** → Patient picks time → `create_tentative_booking()` holds slot
3. **Confirm** → `confirm_booking()` finalizes + creates GCal event
4. **Race handling** → If slot taken, capacity check fails, offer alternatives

---

## 6. REMINDER CALLS (EXPLICIT)

Scheduler runs every hour (background worker).

**Algorithm:**
```python
async def process_reminders():
    """
    Check for appointments 24 hours in the future and send reminder calls.
    """
    now = datetime.now(timezone.utc)
    reminder_window_start = now + timedelta(hours=24)
    reminder_window_end = now + timedelta(hours=25)
    
    # Get all active clinics with reminders feature enabled
    clinics = await get_clinics_with_feature("reminders")
    
    for clinic in clinics:
        # Check license concurrency limits
        if not await check_concurrency_limit(clinic.id):
            continue  # Skip if at limit
        
        for provider in clinic.providers:
            # Fetch Google Calendar events in reminder window
            events = await fetch_gcal_events(
                calendar_id=provider.google_calendar_id,
                time_min=reminder_window_start,
                time_max=reminder_window_end
            )
            
            for event in events:
                # Check if already reminded
                if event.extendedProperties.private.get("reminded") == "true":
                    continue
                
                # Get booking_id from event metadata
                booking_id = event.extendedProperties.private.get("booking_id")
                if not booking_id:
                    continue  # Skip events without booking_id
                
                # Get booking and patient
                booking = await get_booking(booking_id)
                if not booking or booking.status != BookingStatus.CONFIRMED:
                    continue
                
                patient = await get_patient(booking.patient_id)
                
                # Decrypt phone for calling (phone_token is encrypted)
                phone = decrypt_phi(patient.phone_token)
                
                # Create outbound call via Retell
                call = await retell.create_outbound_call(
                    phone=phone,
                    agent_id=clinic.retell_agent_id,
                    metadata={
                        "booking_id": str(booking.id),
                        "call_type": "reminder"
                    }
                )
                
                # Mark event as reminded
                await update_gcal_event(
                    calendar_id=provider.google_calendar_id,
                    event_id=event.id,
                    extended_properties={
                        "private": {
                            **event.extendedProperties.private,
                            "reminded": "true"
                        }
                    }
                )
```

**Edge Cases:**
- Timezone handling: Reminder window calculated in provider's timezone
- Rescheduled appointments: If booking is rescheduled within 24h, reminder is skipped
- Multiple reminders: Only one reminder per appointment (tracked via metadata)

---

## 7. CAMPAIGN CALLS

Background worker checks for pending campaign contacts.

**Algorithm:**
```python
async def process_campaign_calls():
    """
    Process pending campaign contacts with rate limiting and retry logic.
    """
    while True:
        # Get next pending contact (oldest first)
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
            call = await retell.create_outbound_call(
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
            contact.next_retry_at = calculate_next_retry(contact.attempt_count)  # Exponential backoff
            await session.commit()
            
        except Exception as e:
            logger.error(f"Failed to create campaign call: {e}")
            contact.attempt_count += 1
            contact.next_retry_at = calculate_next_retry(contact.attempt_count)
            await session.commit()
```

**Rate Limiting:**
- Max concurrent outbound calls per clinic: `license.max_concurrency`
- Max calls per hour per clinic: Configurable (default: 100)
- Exponential backoff: 1 hour, 4 hours, 24 hours (then mark unreachable)

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

**Status Updates:**
- Handled in webhook handler (`call_ended`):
  - If `outcome = "answered"`: `status = 'called'`
  - If `attempt_count >= 3` and `outcome != "answered"`: `status = 'unreachable'`

---

## 8. EHR SYNC ALGORITHM

**Full Algorithm:**
```python
async def import_ehr_appointments(clinic_id: UUID, csv_file: File):
    """
    Import appointments from EHR CSV and sync to Google Calendar.
    """
    rows = parse_csv(csv_file)
    imported = 0
    updated = 0
    errors = []
    
    for row_num, row in enumerate(rows, start=1):
        try:
            # Map provider_name → provider_id → google_calendar_id
            provider = await get_provider_by_name(clinic_id, row["provider_name"])
            if not provider:
                errors.append({
                    "row": row_num,
                    "error": f"Provider '{row['provider_name']}' not found"
                })
                continue
            
            # Build datetime in provider's timezone
            appointment_datetime = build_datetime(
                date=row["date"],
                time=row["time"],
                timezone=provider.timezone
            )
            
            # Calculate slot_end based on provider.booking_duration_mins
            slot_end = appointment_datetime + timedelta(minutes=provider.booking_duration_mins)
            
            # Check for existing sync record
            sync_record = await get_ehr_sync(clinic_id, row["ehr_id"])
            
            if sync_record:
                # Update existing
                # Update Google Calendar event
                await update_gcal_event(
                    calendar_id=provider.google_calendar_id,
                    event_id=sync_record.google_event_id,
                    start=appointment_datetime,
                    end=slot_end,
                    summary=f"Appointment: {row['patient_name']}",
                    extended_properties={
                        "private": {
                            "source": "ehr_sync",
                            "ehr_id": row["ehr_id"],
                            "booking_id": str(sync_record.booking_id) if sync_record.booking_id else None
                        }
                    }
                )
                
                # Update booking if exists
                if sync_record.booking_id:
                    booking = await get_booking(sync_record.booking_id)
                    if booking:
                        booking.slot_start = appointment_datetime
                        booking.slot_end = slot_end
                        await session.commit()
                
                sync_record.last_updated = datetime.now(timezone.utc)
                await session.commit()
                updated += 1
            else:
                # Create new
                # Find or create patient by name + DOB
                patient = await find_patient(
                    clinic_id=clinic_id,
                    name=row["patient_name"],
                    dob=row["dob"]
                )
                if not patient:
                    patient = await create_patient(
                        clinic_id=clinic_id,
                        name=row["patient_name"],
                        dob=row["dob"],
                        phone=row["phone"],
                        email=row.get("email")
                    )
                
                # Create Google Calendar event
                gcal_event = await create_gcal_event(
                    calendar_id=provider.google_calendar_id,
                    start=appointment_datetime,
                    end=slot_end,
                    summary=f"Appointment: {row['patient_name']}",
                    extended_properties={
                        "private": {
                            "source": "ehr_sync",
                            "ehr_id": row["ehr_id"]
                        }
                    }
                )
                
                # Create booking
                booking = Booking(
                    clinic_id=clinic_id,
                    provider_id=provider.id,
                    patient_id=patient.id,
                    slot_start=appointment_datetime,
                    slot_end=slot_end,
                    status=BookingStatus.CONFIRMED,
                    google_event_id=gcal_event.id,
                    source="ehr_sync"
                )
                session.add(booking)
                await session.flush()
                
                # Create audit entry
                audit = BookingAudit(
                    clinic_id=clinic_id,
                    booking_id=booking.id,
                    action=BookingAction.CONFIRM,
                    actor="ehr_sync"
                )
                session.add(audit)
                
                # Create sync record
                sync_record = EHRAppointmentSync(
                    clinic_id=clinic_id,
                    ehr_id=row["ehr_id"],
                    booking_id=booking.id,
                    google_event_id=gcal_event.id
                )
                session.add(sync_record)
                
                # Update AvailabilitySlot
                await update_or_create_availability_slot(
                    clinic_id=clinic_id,
                    provider_id=provider.id,
                    slot_start=appointment_datetime,
                    slot_end=slot_end,
                    status=SlotStatus.BOOKED,
                    source=SlotSource.GCAL
                )
                
                await session.commit()
                imported += 1
                
        except Exception as e:
            errors.append({
                "row": row_num,
                "error": str(e)
            })
            logger.error(f"Error importing row {row_num}: {e}")
    
    return {
        "imported": imported,
        "updated": updated,
        "failed": len(errors),
        "errors": errors
    }
```

**Conflict Resolution:**
- If EHR CSV has conflicting data (same ehr_id, different times): Update to latest CSV data
- If Google Calendar event was manually deleted: Recreate event on next sync
- If provider name mismatch: Reject row with error (don't guess)

---

## 9. MULTI-LANGUAGE REQUIREMENTS

Backend responsibilities:
- Return times as ISO 8601 strings with timezone (e.g., `"2025-11-20T09:15:00-05:00"`)
- Never generate natural language (e.g., "tomorrow at 9 AM")
- Provide `language` field back to Retell (from patient.language or request parameter)

Retell responsibilities:
- Speech synthesis (TTS) in requested language
- Natural language understanding (NLU) in requested language
- Natural language formatting (e.g., "tomorrow at 9 AM" in Spanish: "mañana a las 9 de la mañana")

**Language Support:**
- `en`: English (default)
- `es`: Spanish

**Language Detection:**
- Patient.language field (stored per patient)
- Request parameter (overrides patient preference for that call)
- Default to "en" if not specified

---

## 10. COMPLIANCE REQUIREMENTS (EXPLICIT)

### 10.1 PHI Protection
- **Patient Model**: `name_token` and `dob_token` encrypted at rest (AES-256)
- **Encryption Key**: Stored in Azure Key Vault (never in DB or code)
- **Decryption**: Only in application layer when needed for calls
- **Call Log**: PHI-free (only IDs and metrics)

### 10.2 Data Retention
- Call recordings: NOT stored (Retell may store, but backend does not)
- Transcripts: NOT stored (Retell may store, but backend does not)
- Logs: Must NOT contain PHI (only IDs, timestamps, error codes)

### 10.3 Access Control
- Google Calendar: Service account under BAA (Business Associate Agreement)
- Database: Encrypted at rest (Azure PostgreSQL)
- Network: TLS 1.2+ required for all traffic

### 10.4 Audit Trail
- BookingAudit: Immutable event log for all booking changes
- Call Log: PHI-free call metrics for usage tracking
- All changes must be logged with actor and timestamp

### 10.5 Authentication
- Retell webhooks: HMAC-SHA256 signature verification
- API endpoints: API key or JWT token (TBD based on deployment)

---

## 11. USAGE TRACKING (EXACT)

Backend records usage via webhook events:

**Call Start Webhook:**
- Create `call_log` entry with `started_at`
- Set `retell_call_id` for correlation

**Call End Webhook:**
- Update `call_log` entry:
  - `duration_seconds` = webhook.duration_seconds
  - `outcome` = webhook.outcome
  - `ended_at` = webhook.timestamp

**Monthly Usage Calculation:**
```sql
SELECT 
    clinic_id,
    call_type,
    SUM(duration_seconds) / 60.0 AS total_minutes,
    COUNT(*) AS total_calls
FROM call_log
WHERE created_at >= '2025-11-01' AND created_at < '2025-12-01'
GROUP BY clinic_id, call_type
```

**Concurrency Tracking:**
- Track active calls per clinic (via call_started/call_ended webhooks)
- Enforce `license.max_concurrency` limit before creating new calls

---

## 12. DEPLOYMENT REQUIREMENTS

### 12.1 Infrastructure
- **Platform**: Azure Container Apps
- **Database**: Azure PostgreSQL (managed, encrypted at rest)
- **Secrets**: Azure Key Vault for:
  - Google service account JSON (encrypted)
  - Retell API key
  - DB credentials
  - Encryption keys (for PHI)

### 12.2 Security
- HTTPS only (TLS 1.2+)
- Retell webhook signature verification (HMAC-SHA256)
- API authentication (API key or JWT)
- Environment variables for all secrets (never hardcoded)

### 12.3 Monitoring
- Health check endpoint: `/health` (returns DB connection status)
- Ping endpoint: `/ping` (fastest response)
- Logging: Structured logs (JSON format, no PHI)

### 12.4 Scalability
- Async/await throughout (FastAPI + asyncpg)
- Database connection pooling (SQLAlchemy)
- Background workers for:
  - Reminder calls (hourly)
  - Campaign calls (continuous)
  - Tentative booking expiration (every 5 minutes)

---

## 13. FULL MVP COMPLETION CHECKLIST

### Backend
- [x] FastAPI app scaffolding ✅ (main.py with router registration)
- [x] DB migrations (Alembic) ✅ (initial_models.py, encrypt_patient_phone_email_add_hash.py)
- [x] Google Calendar client (service account auth) ✅ (google_calendar.py - 910 lines, fully tested)
- [x] Retell webhook handler (call_started, call_ended) ✅ (retell.py - webhook endpoints with signature verification)
- [x] Retell tool endpoints (schedule, confirm_booking, availability) ✅ (retell.py - POST/GET endpoints with agent_id lookup)
- [x] Double-booking engine (with AvailabilitySlot + GCal) ✅ (availability.py - complete with capacity enforcement)
- [x] Tentative booking system (hold tokens, booking service) ✅ (booking.py - complete with 5-min expiration, reaper pending)
- [x] Patient management (find/create with PHI encryption) ✅ (patient.py - hash-based lookup, encrypted PHI)
- [x] Admin endpoints (clinic, integration, license, business hours) ✅ (admin.py - full CRUD operations)
- [x] Provider management (CRUD, time blocking) ✅ (provider.py - complete with GCal validation)
- [x] PHI encryption/decryption ✅ (encryption.py - AES-256-GCM with env var key)
- [x] PHI-free logs (validation) ✅ (structured logging throughout, no PHI in logs)
- [x] Signature validation (Retell webhooks) ✅ (verify_retell_signature with HMAC-SHA256)
- [x] Multi-clinic logic (clinic_id isolation) ✅ (all models have clinic_id, tenant-scoped queries)
- [x] Provider calendar mapping (with timezone support) ✅ (provider model with timezone, GCal ID)
- [x] Validation for every request (Pydantic models) ✅ (admin/provider/retell routes with field validators)
- [x] Error handling (standardized error responses) ✅ (APIResponse format, proper HTTP status codes)
- [x] Health check endpoints ✅ (health.py - /health and /ping)
- [x] Business hours management ✅ (clinic model with business_hours_start/end, admin endpoints)
- [ ] Tentative booking reaper worker (background task to expire holds) - Phase 1 pending
- [ ] EHR CSV importer (with conflict resolution) - Phase 2
- [ ] Campaign engine + workers (with rate limiting) - Phase 2
- [ ] Reminder call engine (hourly scheduler) - Phase 2
- [ ] Usage tracking endpoints (GET /usage/{clinic_id}) - Phase 2
- [ ] License enforcement (feature flags, concurrency limits) - Phase 2
- [ ] Phone routing (DID → clinic mapping endpoints) - Phase 2

### Retell Integration
- [ ] Per-clinic agents (one agent per clinic) - External setup required
- [ ] Per-clinic DID (phone number mapping) - External setup required
- [x] Tools configured (schedule, confirm_booking, availability) ✅ (backend endpoints ready)
- [ ] Outbound call templates (reminder, campaign) - Phase 2
- [ ] English & Spanish prompts (multi-language support) - External Retell configuration
- [x] Webhook configuration (call_started, call_ended) ✅ (backend endpoints ready with signature verification)

### Google Calendar
- [ ] Service account created (with BAA) - External setup required
- [ ] Calendars per provider created (or existing calendars linked) - External setup required
- [ ] Permissions shared (service account has access) - External setup required
- [x] Metadata fields tested (extendedProperties.private) ✅ (google_calendar.py implements metadata handling)
- [x] Event creation/update/delete tested ✅ (28 unit tests in test_google_calendar.py)

### Database
- [x] Core models created ✅ (Clinic, Provider, Patient, Booking, AvailabilitySlot, BookingAudit, CallLog, License, ClinicIntegration, PhoneRoute)
- [x] Indexes created ✅ (all models have proper indexes for performance)
- [x] Constraints created ✅ (foreign keys, check constraints, unique constraints)
- [x] Migrations created ✅ (initial_models.py, encrypt_patient_phone_email_add_hash.py)
- [ ] Campaign models (Campaign, CampaignContact) - Phase 2
- [ ] EHR sync model (EHRAppointmentSync) - Phase 2
- [ ] Encryption key management (Azure Key Vault) - Phase 2, using env var for Phase 1

### Testing
- [x] Unit tests (models, business logic) ✅ (test_google_calendar.py - 28 tests, test_encryption.py, test_patient.py, test_availability.py, test_booking.py)
- [x] Integration tests (API endpoints) ✅ (test_admin.py, test_provider.py, test_retell.py)
- [ ] End-to-end tests (full booking flow) - Pending
- [ ] Load testing (concurrency limits) - Phase 2

### Documentation
- [x] Deployment guide ✅ (DEPLOYMENT_GUIDE.md - 544 lines)
- [x] Phase 1 implementation plan ✅ (PHASE_1_IMPLEMENTATION.md)
- [x] API documentation ✅ (FastAPI auto-docs at /docs)
- [ ] Seed data script - Pending
- [ ] Setup instructions (README) - Pending

---

## 13.1. CURRENT IMPLEMENTATION STATUS (As of Latest Review)

### ✅ Phase 1 - Core Booking System (95% Complete)

**Completed Components:**

1. **Database Foundation** ✅
   - All core models implemented (Clinic, Provider, Patient, Booking, AvailabilitySlot, BookingAudit, CallLog, License, ClinicIntegration, PhoneRoute)
   - Alembic migrations: `3f270d38367a_initial_models.py`, `encrypt_patient_phone_email_add_hash.py`
   - All indexes and constraints in place
   - PHI encryption implemented (AES-256-GCM)

2. **Google Calendar Integration** ✅
   - Complete service implementation (`Clinic_app/services/google_calendar.py` - 910 lines)
   - Service account authentication
   - Event CRUD operations (create, read, update, delete, list)
   - Metadata handling (extendedProperties.private)
   - Retry logic with exponential backoff
   - Graceful degradation on API failures
   - 28 unit tests (all passing)

3. **Admin Endpoints** ✅
   - Clinic CRUD (`POST /admin/clinics`, `GET /admin/clinics/{id}`, `PUT /admin/clinics/{id}`, `GET /admin/clinics`)
   - Clinic setup (`POST /admin/clinics/setup` - creates clinic + integration + license)
   - Integration CRUD (`POST /admin/clinics/{id}/integration`, `GET`, `PUT`)
   - License CRUD (`POST /admin/clinics/{id}/license`, `GET`, `PUT`)
   - Business hours (`GET /admin/clinics/{id}/business-hours`, `PUT`)
   - Provider CRUD (`POST /admin/clinics/{clinic_id}/providers`, `GET /admin/providers/{id}`, `PUT`, `GET /admin/clinics/{id}/providers`)
   - Time blocking (`POST /admin/providers/{id}/block-time`, `POST /admin/providers/{id}/unblock-time`)
   - Google Calendar validation on provider create/update

4. **Retell Integration** ✅
   - Tool endpoints:
     - `POST /retell/schedule` - Book/reschedule/cancel with provider selection, load balancing, alternatives
     - `POST /retell/confirm_booking` - Confirm tentative bookings
     - `GET /retell/availability` - Get available slots (RESTful)
     - `POST /retell/availability` - Get available slots (Retell format)
   - Webhook endpoints:
     - `POST /retell/webhook/call_started` - Track call start, create CallLog, identify clinic by agent_id
     - `POST /retell/webhook/call_ended` - Track call end, release unconfirmed tentative bookings (PRIMARY cleanup)
   - Signature verification (HMAC-SHA256)
   - Agent ID → Clinic ID lookup
   - Provider selection logic (single/multiple match handling)
   - Load balancing (least busy provider first)

5. **Availability Service** ✅
   - `is_slot_available()` - Core availability check
   - `get_available_slots()` - Get slots for a date
   - `get_next_available_slots()` - Find next N slots from today
   - `find_slot_at_time()` - Search specific time across days
   - `check_and_offer_alternatives()` - Check slot, offer alternatives
   - Business hours support (clinic-level configuration)
   - Keyword-based patient appointment detection (English + Spanish)
   - Capacity enforcement (patient appointments count, external events block)
   - Google Calendar integration for conflict checking

6. **Booking Service** ✅
   - `create_tentative_booking()` - Create hold with 5-min expiration
   - `confirm_booking()` - Convert tentative → confirmed, create GCal event
   - `cancel_booking()` - Update status, delete GCal event
   - `reschedule_booking()` - Cancel old, create new tentative
   - `expire_booking()` - Expire tentative holds (for reaper)
   - `get_booking_by_hold_token()` - Query by hold token
   - `get_patient_bookings()` - List patient's bookings
   - `get_expired_tentative_bookings()` - Find expired holds
   - Capacity enforcement with `SELECT FOR UPDATE`
   - BookingAudit trail for all state changes

7. **Patient Service** ✅
   - `find_patient()` - Hash-based lookup by name + DOB
   - `create_patient()` - Create with encrypted PHI
   - PHI encryption (name, DOB, phone, email)
   - Hash-based efficient lookup (O(1) performance)

8. **PHI Encryption** ✅
   - AES-256-GCM encryption
   - `encrypt_phi()` and `decrypt_phi()` functions
   - Environment variable key (Phase 1)
   - Custom exception classes
   - Key validation and caching

9. **Error Handling & Validation** ✅
   - Standardized APIResponse format
   - Pydantic models with field validators
   - Proper HTTP status codes (400/404/409/500)
   - Structured logging (no PHI)
   - Transaction handling with rollback

10. **Health Endpoints** ✅
    - `GET /health` - Database connection check
    - `GET /ping` - Fastest response

11. **Testing** ✅
    - Unit tests: `test_google_calendar.py` (28 tests), `test_encryption.py`, `test_patient.py`, `test_availability.py`, `test_booking.py`
    - Integration tests: `test_admin.py`, `test_provider.py`, `test_retell.py`

12. **Documentation** ✅
    - `DEPLOYMENT_GUIDE.md` (544 lines)
    - `PHASE_1_IMPLEMENTATION.md`
    - FastAPI auto-docs at `/docs`

**Pending Components (Phase 1):**

1. **Tentative Booking Reaper Worker** ⚠️
   - Background task to expire tentative bookings (runs every 10-15 minutes)
   - Note: Primary cleanup happens in `call_ended` webhook; reaper is backup
   - File: `Clinic_app/workers/booking_reaper.py` (not yet created)

2. **Seed Data Script** ⚠️
   - Create test clinic, provider, integration records
   - File: `Clinic_app/scripts/seed_data.py` (not yet created)

**Deferred to Phase 2:**

- Campaign models and endpoints (Campaign, CampaignContact)
- EHR sync models and endpoints (EHRAppointmentSync)
- Reminder call engine (hourly scheduler)
- Campaign call workers (with rate limiting)
- Usage tracking endpoints (`GET /usage/{clinic_id}`)
- License enforcement (feature flags, concurrency limits)
- Phone routing endpoints (DID → clinic mapping)
- Azure Key Vault integration (using env vars for Phase 1)
- AvailabilitySlot sync workers (daily background sync)

### 📊 Implementation Statistics

- **Total Lines of Code:** ~8,000+ lines
- **Services:** 4 (google_calendar, availability, booking, patient)
- **Routes:** 4 (admin, provider, retell, health)
- **Models:** 10 core models
- **Tests:** 8 test files
- **Migrations:** 2 Alembic migrations

### 🔄 Next Steps

1. **Immediate (Complete Phase 1):**
   - Implement tentative booking reaper worker
   - Create seed data script
   - End-to-end testing of full booking flow

2. **Phase 2 (Future):**
   - Campaign system
   - EHR sync
   - Reminder calls
   - Usage tracking
   - License enforcement
   - Phone routing

---

## 14. ADDITIONAL CONSIDERATIONS

### 14.1 Tentative Booking Expiration
Background worker (runs every 5 minutes):
```python
async def expire_tentative_bookings():
    """
    Expire tentative bookings that have passed their hold_expires_at.
    """
    now = datetime.now(timezone.utc)
    expired = await get_tentative_bookings_expired(now)
    
    for booking in expired:
        booking.status = BookingStatus.CANCELED
        audit = BookingAudit(
            clinic_id=booking.clinic_id,
            booking_id=booking.id,
            action=BookingAction.EXPIRE,
            actor="system"
        )
        session.add(audit)
        # Update AvailabilitySlot status to 'free'
        await update_availability_slot_status(
            provider_id=booking.provider_id,
            slot_start=booking.slot_start,
            slot_end=booking.slot_end,
            status=SlotStatus.FREE
        )
    
    await session.commit()
```

### 14.2 AvailabilitySlot Sync
Background worker (runs daily):
- Sync Google Calendar events → AvailabilitySlot (status = 'booked' or 'blocked')
- Sync CSV imports → AvailabilitySlot (status = 'free' or 'blocked')
- Update `last_sync_at` timestamp

### 14.3 Error Recovery
- Retry logic for Google Calendar API failures (exponential backoff)
- Retry logic for Retell API failures (exponential backoff)
- Dead letter queue for failed campaign contacts (after max retries)

---

**END OF PRD**

