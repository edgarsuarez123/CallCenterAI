# Phase 1 Implementation Plan

## Goal
**Core Booking Functionality**: Enable inbound calls via Retell AI to successfully book, confirm, and cancel appointments with Google Calendar integration.

## Progress Summary
**Overall: ~90% Complete**

- ✅ **Database Foundation** - 2/3 tasks (67%)
- ✅ **Google Calendar Integration** - 9/9 tasks (100%) - COMPLETE
- ✅ **Retell Integration** - 6/6 tasks (100%) - COMPLETE
- ✅ **Availability Engine** - 5/5 tasks (100%) - COMPLETE
- ✅ **Booking State Machine** - 5/5 tasks (100%) - COMPLETE
- ✅ **Patient Management** - 3/3 tasks (100%) - COMPLETE
- ✅ **Error Handling** - 3/3 tasks (100%) - COMPLETE (admin, provider, retell routes)
- ✅ **Admin Endpoints** - 6/6 tasks (100%) - COMPLETE (includes business hours)
- ✅ **PHI Encryption** - 1/1 tasks (100%) - COMPLETE
- ⚠️ **Infrastructure** - 1/3 tasks (33%)

---

## Phase 1 Scope: MVP Booking System

### ✅ What's Included

#### 1. Database Foundation
- [x] **Models exist** (Clinic, Provider, Patient, Booking, AvailabilitySlot, BookingAudit)
- [x] **Alembic migrations** - Create all tables with proper indexes and constraints
- [ ] **Seed data script** - Create test clinic, provider, and integration records

#### 2. Core Google Calendar Integration
- [x] **Service account authentication** - Google Calendar API client setup
- [x] **Read calendar events** - Fetch existing events for availability checking (`list_events`)
- [x] **Create calendar events** - When booking is confirmed (`create_event`)
- [x] **Update calendar events** - For reschedules (`update_event`)
- [x] **Delete calendar events** - For cancellations (`delete_event`, `delete_multiple_events`)
- [x] **Get calendar event** - Fetch single event (`get_event`)
- [x] **Metadata handling** - Set/get extendedProperties.private for tracking
- [x] **Calendar validation** - Validate calendar access (`validate_calendar_access`)
- [x] **Retry logic** - Exponential backoff, rate limit handling, graceful degradation
- [x] **Unit tests** - 28 tests covering all operations

#### 3. Core Retell Integration ✅ COMPLETE
- [x] **Tool endpoint: `/retell/schedule`** - Book/reschedule/cancel appointments with provider selection
- [x] **Tool endpoint: `/retell/confirm_booking`** - Confirm tentative bookings
- [x] **Tool endpoint: `/retell/availability`** - Get available slots
- [x] **Webhook: `/retell/webhook/call_started`** - Track call start, identify clinic by agent_id
- [x] **Webhook: `/retell/webhook/call_ended`** - Track call end, **release unconfirmed tentative bookings** (primary cleanup mechanism)
- [x] **Signature verification** - HMAC-SHA256 validation for Retell requests
- [x] **Provider selection logic** - Single/multiple match handling, fallback to alternatives
- [x] **Load balancing** - Providers sorted by booking count (least busy first)
- [x] **CallLog.tentative_booking_id** - Track holds for cleanup on call_ended

#### 4. Availability Engine ✅ COMPLETE
- [x] **Slot generation** - Generate candidate slots based on provider.booking_duration_mins
- [x] **AvailabilitySlot querying** - Check FREE/BLOCKED status
- [x] **Google Calendar conflict checking** - Detect patient appointments vs blocking events
- [x] **Double-booking prevention** - Database constraints + application logic
- [x] **Capacity enforcement** - Respect provider.capacity limits (patient appointments only)
- [x] **Multiple search functions** - is_slot_available, get_available_slots, get_next_available_slots, find_slot_at_time, check_and_offer_alternatives
- [x] **Business hours support** - Clinic-level business hours (business_hours_start, business_hours_end)
- [x] **Keyword detection** - Detect patient appointments via keywords in English and Spanish

#### 5. Booking State Machine ✅ COMPLETE
- [x] **Tentative booking creation** - `create_tentative_booking()` with hold_token and 5-min expiration
- [x] **Booking confirmation** - `confirm_booking()` converts tentative → confirmed, creates GCal event
- [x] **Booking cancellation** - `cancel_booking()` updates status, deletes GCal event
- [x] **Booking rescheduling** - `reschedule_booking()` cancels old, creates new tentative
- [x] **BookingAudit logging** - All state changes logged (HOLD, CONFIRM, CANCEL, EXPIRE)
- [x] **Capacity enforcement** - SELECT FOR UPDATE + count check (supports capacity > 1)
- [x] **Query functions** - `get_booking_by_hold_token()`, `get_patient_bookings()`, `expire_booking()`
- [x] **Database update** - Removed unique constraint, using application-level capacity check

#### 6. Patient Management ✅ COMPLETE
- [x] **Find patient by name + DOB** - Within clinic scope using hash-based lookup
- [x] **Create patient** - With encrypted name_token, dob_token, phone_token, email_token
- [x] **PHI encryption** - AES-256-GCM encryption for all PHI (name, DOB, phone, email)
- [x] **Hash-based lookup** - SHA-256 hash of normalized (name|dob) for efficient O(1) lookup
- [x] **Patient model updated** - phone_e164 → phone_token (BYTEA), email → email_token (BYTEA), added name_dob_hash
- [x] **Database migration** - Encrypt patient phone and email, add hash column

#### 7. Basic Error Handling ✅ COMPLETE
- [x] **Standardized error responses** - Success/error format (implemented in admin.py, provider.py, retell.py)
- [x] **Input validation** - Pydantic models for all requests (implemented in admin.py, provider.py, retell.py)
- [x] **HTTP status codes** - Proper 400/404/409/500 responses (implemented in admin.py, provider.py, retell.py)

#### 8. Admin Endpoints (NEW - Required for Setup) ✅ COMPLETE
- [x] **Clinic setup endpoint** - `POST /admin/clinics/setup` - Create clinic + integration + license
- [x] **Clinic CRUD endpoints** - `POST /admin/clinics`, `GET /admin/clinics/{id}`, `PUT /admin/clinics/{id}`, `GET /admin/clinics`
- [x] **Integration endpoints** - `POST /admin/clinics/{id}/integration`, `GET /admin/clinics/{id}/integration`, `PUT /admin/clinics/{id}/integration`
- [x] **License endpoints** - `POST /admin/clinics/{id}/license`, `GET /admin/clinics/{id}/license`, `PUT /admin/clinics/{id}/license`
- [x] **Business hours endpoints** - `GET /admin/clinics/{id}/business-hours`, `PUT /admin/clinics/{id}/business-hours` - Manage clinic business hours
- [x] **Provider management** - `POST /admin/clinics/{clinic_id}/providers` - Create provider
- [x] **Provider management** - `GET /admin/providers/{provider_id}` - Get provider
- [x] **Provider management** - `PUT /admin/providers/{provider_id}` - Update provider
- [x] **Provider management** - `GET /admin/clinics/{clinic_id}/providers` - List providers
- [x] **Provider time blocking** - `POST /admin/providers/{provider_id}/block-time` - Block time periods
- [x] **Provider time unblocking** - `POST /admin/providers/{provider_id}/unblock-time` - Unblock time periods
- [x] **Google Calendar validation** - Validate calendar access on provider create/update

#### 9. Basic Infrastructure
- [ ] **Environment configuration** - .env file for secrets
- [ ] **Logging setup** - Structured logging (no PHI)
- [x] **Health check** - `/health` endpoint (already exists)

---

## ❌ What's Deferred to Phase 2

### Campaigns
- Campaign CSV upload
- Campaign contact management
- Campaign call workers
- Campaign status tracking

### EHR Integration
- EHR CSV import
- EHR sync mapping
- EHR conflict resolution

### Advanced Features
- Reminder calls (24h before)
- Usage tracking (detailed metrics)
- Phone routing (DID → clinic mapping) - Can hardcode for Phase 1
- License enforcement (feature flags) - Can skip for Phase 1
- AvailabilitySlot sync workers - Manual sync for Phase 1

### Advanced Security
- Azure Key Vault integration (use env vars for Phase 1)
- Advanced PHI encryption key rotation
- JWT authentication (can use API key for Phase 1)

### Google Calendar Sync Queue
- Failed GCal operations queue (if API fails after retries, allow booking and sync later)
- Background worker to retry failed operations
- Database table for tracking failed syncs
- Automatic retry with exponential backoff
- Manual retry endpoint for admin

---

## Phase 1 Implementation Order

### ✅ Week 1: Foundation (COMPLETE - Admin endpoints, PHI encryption, and patient service all done)

1. **Database Setup** ✅ COMPLETE
   - [x] Create Alembic migration for all existing models
   - [x] All models exist: `clinic`, `clinic_integration`, `provider`, `patient`, `booking`, `availability_slot`, `booking_audit`, `call_log`, `license`, `phone_route`
   - [x] Run migrations on dev database
   - [x] Migration for encrypting patient phone/email: `encrypt_patient_phone_email_add_hash.py` (adds phone_token, email_token, name_dob_hash)
   - [ ] Create seed script for test data

2. **Google Calendar Client** ✅ COMPLETE
   - [x] Create `Clinic_app/services/google_calendar.py`
   - [x] Implement: `get_credentials`, `get_calendar_service` (authentication)
   - [x] Implement: `list_events` (read calendar events)
   - [x] Implement: `create_event` (create calendar events)
   - [x] Implement: `update_event` (update calendar events)
   - [x] Implement: `delete_event`, `delete_multiple_events` (delete calendar events)
   - [x] Implement: `get_event` (get single event)
   - [x] Implement: `validate_calendar_access` (calendar validation)
   - [x] Implement: `build_extended_properties`, `parse_extended_properties` (metadata handling)
   - [x] Implement: `count_overlapping_events` (conflict checking)
   - [x] Implement: Retry logic with exponential backoff
   - [x] Implement: Graceful degradation
   - [x] Unit tests: 28 tests, all passing

3. **Admin Endpoints** ✅ COMPLETE
   - [x] Create `Clinic_app/Routes/admin.py`
   - [x] Implement: `POST /admin/clinics/setup` - Create clinic + integration + license
   - [x] Implement: `POST /admin/clinics` - Create clinic only
   - [x] Implement: `GET /admin/clinics/{clinic_id}` - Get clinic
   - [x] Implement: `PUT /admin/clinics/{clinic_id}` - Update clinic
   - [x] Implement: `GET /admin/clinics` - List clinics
   - [x] Implement: `POST /admin/clinics/{clinic_id}/integration` - Create/update integration
   - [x] Implement: `GET /admin/clinics/{clinic_id}/integration` - Get integration
   - [x] Implement: `PUT /admin/clinics/{clinic_id}/integration` - Update integration
   - [x] Implement: `POST /admin/clinics/{clinic_id}/license` - Create/update license
   - [x] Implement: `GET /admin/clinics/{clinic_id}/license` - Get license
   - [x] Implement: `PUT /admin/clinics/{clinic_id}/license` - Update license
   - [x] Create `Clinic_app/Routes/provider.py`
   - [x] Implement: `POST /admin/clinics/{clinic_id}/providers` - Create provider
   - [x] Implement: `GET /admin/providers/{provider_id}` - Get provider
   - [x] Implement: `PUT /admin/providers/{provider_id}` - Update provider
   - [x] Implement: `GET /admin/clinics/{clinic_id}/providers` - List providers
   - [x] Implement: `POST /admin/providers/{provider_id}/block-time` - Block time periods
   - [x] Implement: `POST /admin/providers/{provider_id}/unblock-time` - Unblock time periods
   - [x] Integrate Google Calendar validation on provider create/update
   - [x] All routes include validation, error handling, and logging
   - [x] Standardized APIResponse format across all endpoints
   - [x] Comprehensive Pydantic models with field validators
   - [x] Error helper functions (raise_not_found, raise_validation_error, raise_conflict_error)
   - [x] Transaction handling with proper rollback on errors
   - [x] Structured logging (info/warning/error levels, no PHI)

4. **PHI Encryption Utilities** ✅ COMPLETE
   - [x] Create `Clinic_app/common/encryption.py`
   - [x] Implement: AES-256-GCM encryption for PHI
   - [x] Implement: `encrypt_phi()` function
   - [x] Implement: `decrypt_phi()` function
   - [x] Use env var key for Phase 1
   - [x] Custom exception classes (EncryptionError, EncryptionKeyError, DecryptionError, AuthenticationError)
   - [x] Key validation and caching
   - [x] Structured logging (no PHI in logs)

5. **Basic Patient Service** ✅ COMPLETE
   - [x] Create `Clinic_app/services/patient.py`
   - [x] Implement: `find_patient()` - Find by name + DOB hash within clinic scope
   - [x] Implement: `create_patient()` - Create new patient with encrypted PHI
   - [x] Compute `name_dob_hash` from normalized (name|dob) for efficient lookup
   - [x] Query by `clinic_id` and `name_dob_hash` (O(1) lookup)
   - [x] Decrypt `name_token` and `dob_token` to verify match (defense against hash collisions)
   - [x] Encrypt all PHI (name, DOB, phone, email) using `encrypt_phi()` from encryption.py
   - [x] Input validation (clinic_id, name, DOB format, phone E.164, email format, language)
   - [x] Structured logging (no PHI in logs)
   - [x] Error handling (ValueError, EncryptionError, DecryptionError)

### Week 2: Core Booking Logic

6. **Availability Service** ✅ COMPLETE
   - [x] Create `Clinic_app/services/availability.py`
   - [x] Implement: `_generate_candidate_slots()` - Generate slots based on provider.booking_duration_mins
   - [x] Implement: `is_slot_available()` - Core availability check (BLOCKED, GCal events, DB bookings, capacity)
   - [x] Implement: `get_available_slots()` - Get all available slots for a date with single GCal API call
   - [x] Implement: `get_next_available_slots()` - Find next N available slots from today
   - [x] Implement: `find_slot_at_time()` - Search specific time across multiple days
   - [x] Implement: `check_and_offer_alternatives()` - Check specific slot, offer alternatives if unavailable
   - [x] Implement: `_is_patient_appointment()` - Detect patient appointments via keywords (English + Spanish)
   - [x] Implement: `_get_clinic_business_hours()` - Get clinic business hours with fallback defaults
   - [x] Integrate: Google Calendar conflict checking via GoogleCalendarService.list_events()
   - [x] Implement: Capacity enforcement (patient appointments count toward capacity, external events block)
   - [x] Implement: Double-booking prevention logic

7. **Booking Service** ✅ COMPLETE
   - [x] Create `Clinic_app/services/booking.py`
   - [x] Implement: `create_tentative_booking()` - Create booking with hold_token and 5-min expiration
   - [x] Implement: `confirm_booking()` - Convert tentative → confirmed, create Google Calendar event
   - [x] Implement: `cancel_booking()` - Update status to canceled, delete Google Calendar event
   - [x] Implement: `reschedule_booking()` - Cancel old, create new tentative booking
   - [x] Implement: `BookingAudit` logging - `_create_audit_entry()` for all state changes
   - [x] Implement: `_count_slot_bookings()` - SELECT FOR UPDATE for capacity enforcement
   - [x] Implement: Query functions - `get_booking_by_hold_token()`, `get_patient_bookings()`, `get_booking_by_id()`
   - [x] Implement: `expire_booking()` and `get_expired_tentative_bookings()` for reaper
   - [x] Integrate: Google Calendar event creation/deletion with graceful degradation
   - [x] Update: Removed unique constraint from Booking model, using application-level capacity check
   - [x] Update: Migration updated to use non-unique `idx_booking_slot_lookup` index

8. **Tentative Booking Reaper** (Backup safety net)
   - [ ] Create `Clinic_app/workers/booking_reaper.py`
   - [ ] Implement: Background worker (asyncio task)
   - [ ] Implement: Call `get_expired_tentative_bookings()` and `expire_booking()` every 10-15 minutes
   - [ ] Integrate: Start worker on application startup
   - **Note**: Primary cleanup happens in `call_ended` webhook. Reaper is backup for edge cases (webhook failures, network issues).

### Week 3: Retell Integration ✅ COMPLETE

9. **Retell Tool Endpoints** ✅ COMPLETE
   - [x] Create `Clinic_app/Routes/retell.py`
   - [x] Implement: `POST /retell/schedule` - Book/reschedule/cancel appointments
     - [x] Call `find_patient()` then `create_patient()` if not found
     - [x] Call `AvailabilityService.get_available_slots()` or `get_next_available_slots()`
     - [x] Call `BookingService.create_tentative_booking()` or `cancel_booking()`
     - [x] Provider selection: Single match → book, Multiple matches → clarify
     - [x] Load balancing: Providers sorted by booking count (least busy first)
     - [x] Fallback: If preferred provider unavailable → offer other dates → offer other providers
   - [x] Implement: `POST /retell/confirm_booking` - Confirm tentative bookings
     - [x] Call `BookingService.confirm_booking()` (creates Google Calendar event)
   - [x] Implement: `GET /retell/availability` - Get available slots
     - [x] Call `AvailabilityService.get_available_slots()` or `get_next_available_slots()`
   - [x] Add signature verification middleware (HMAC-SHA256)
   - [x] Pydantic models: `ScheduleRequest`, `ScheduleResponse`, `ConfirmRequest`, `ConfirmResponse`, `AvailabilityRequest`, `AvailabilityResponse`

10. **Retell Webhooks** ✅ COMPLETE
   - [x] Implement: `POST /retell/webhook/call_started` - Track call start
     - [x] Lookup clinic by `agent_id` from `ClinicIntegration`
     - [x] Create `CallLog` entry with `retell_call_id`
   - [x] Implement: `POST /retell/webhook/call_ended` - Track call end
     - [x] Update `CallLog` with duration and outcome
     - [x] **Release unconfirmed holds**: Find any TENTATIVE bookings for this call and cancel them
     - [x] This is the PRIMARY cleanup mechanism (reaper is backup)
   - [x] Add `tentative_booking_id` field to `CallLog` to track which booking to cleanup
   - [x] Pydantic models: `CallStartedWebhook`, `CallEndedWebhook`

11. **Error Handling & Validation** ✅ COMPLETE
   - [x] Create Pydantic request/response models for all endpoints (admin.py, provider.py, retell.py)
   - [x] Standardize error responses (success/error format) (admin.py, provider.py, retell.py)
   - [x] Add input validation (date ranges, phone format, timezone, etc.) (admin.py, provider.py, retell.py)
   - [x] Implement proper HTTP status codes (400/404/409/500) (admin.py, provider.py, retell.py)
   - [x] Applied same patterns to Retell endpoints

### Week 4: Testing & Polish

12. **Integration Testing**
    - [ ] Test full booking flow: call → tentative → confirm → GCal event
    - [ ] Test cancellation flow
    - [ ] Test reschedule flow
    - [ ] Test double-booking prevention
    - [ ] Test patient auto-creation during booking

13. **Error Scenarios Testing**
    - [ ] Test expired hold tokens
    - [ ] Test no available slots
    - [ ] Test invalid clinic_id/provider_id
    - [ ] Test Google Calendar API failures (graceful degradation)
    - [ ] Test capacity limits

14. **Seed Data Script**
    - [ ] Create `Clinic_app/scripts/seed_data.py`
    - [ ] Create test clinic with integration
    - [ ] Create test providers with Google Calendar IDs
    - [ ] Create test patients (optional)

15. **Documentation**
    - [ ] API documentation (FastAPI auto-docs at `/docs`)
    - [ ] Setup instructions (README)
    - [ ] Environment variables guide
    - [ ] Admin endpoint usage guide

---

## Phase 1 Success Criteria

### Functional Requirements
- ✅ Inbound call can check availability
- ✅ Inbound call can create tentative booking
- ✅ Inbound call can confirm booking
- ✅ Confirmed booking creates Google Calendar event
- ✅ Inbound call can cancel existing booking
- ✅ Double-booking is prevented (DB constraint + app logic)
- ✅ Tentative bookings expire after 5 minutes
- ✅ AvailabilitySlot status is updated correctly

### Technical Requirements
- ✅ All database migrations run successfully
- ✅ Google Calendar integration works (read/write)
- ✅ Retell tool endpoints respond correctly
- ✅ Retell webhooks are received and processed
- ✅ Error handling returns proper status codes
- ✅ Logs contain no PHI
- ✅ Health check endpoint works

### Testing Requirements
- ✅ Unit tests for core services (availability, booking)
- ✅ Integration tests for API endpoints
- ✅ End-to-end test: full booking flow
- ✅ Manual testing with real Retell agent

---

## Phase 1 File Structure

```
Clinic_app/
├── common/
│   ├── database.py ✅ (exists)
│   └── encryption.py ✅ (COMPLETE - PHI encryption utilities)
├── data/
│   ├── enums.py ✅ (exists)
│   └── models/ ✅ (exists, may need clinic_integration model)
├── services/
│   ├── google_calendar.py ✅ (COMPLETE - 910 lines, fully tested)
│   ├── patient.py ✅ (COMPLETE - Patient service with find_patient and create_patient)
│   ├── availability.py ✅ (COMPLETE - Availability engine with multiple search functions)
│   ├── booking.py ✅ (COMPLETE - Booking state machine with capacity enforcement)
│   └── retell.py (NEW - Retell API client)
├── Routes/
│   ├── health.py ✅ (exists)
│   ├── admin.py ✅ (COMPLETE - Clinic, integration, license endpoints)
│   ├── provider.py ✅ (COMPLETE - Provider CRUD + time blocking)
│   └── retell.py ✅ (COMPLETE - Retell tool endpoints + webhooks)
├── scripts/
│   └── seed_data.py (NEW - Seed script for test data)
├── workers/
│   └── booking_reaper.py (NEW - Expire tentative bookings)
├── main.py ✅ (exists)
├── alembic/ ✅ (COMPLETE - migrations exist)
│   ├── versions/
│   │   ├── 3f270d38367a_initial_models.py ✅ (exists)
│   │   └── encrypt_patient_phone_email_add_hash.py ✅ (exists - encrypts phone/email, adds hash)
│   ├── env.py ✅ (exists)
│   └── alembic.ini ✅ (exists)
└── tests/
    ├── test_google_calendar.py ✅ (COMPLETE - 28 tests, all passing)
    └── README.md ✅ (exists)
```

---

## Phase 1 Dependencies

### Python Packages (add to requirements.txt)
```
# Google Calendar
google-auth==2.23.4 ✅ (exists)
google-auth-oauthlib==1.1.0 ✅ (exists)
google-api-python-client==2.108.0 ✅ (exists)

# Encryption
cryptography==41.0.7 ✅ (exists)

# Background tasks (choose one)
# Option 1: Simple asyncio background task
# Option 2: Celery (if needed later)
celery==5.3.4 (optional)

# Retell API client
httpx==0.25.2 ✅ (exists)
```

### External Services
- Google Cloud Project with service account
- Google Calendar API enabled
- Retell AI account with agent configured
- Azure PostgreSQL database (or local Postgres for dev)

### Environment Variables
```bash
# Database
DB_HOST=...
DB_PORT=5432
DB_NAME=...
DB_USER=...
DB_PASSWORD=...

# Google Calendar
GOOGLE_SERVICE_ACCOUNT_JSON=... (path to JSON file or JSON string)

# Retell
RETELL_API_KEY=...
RETELL_WEBHOOK_SECRET=... (for signature verification)

# Encryption (Phase 1: simple env var, Phase 2: Key Vault)
PHI_ENCRYPTION_KEY=... (32-byte key for AES-256)
```

---

## Phase 1 Risks & Mitigations

### Risk 1: Google Calendar API Rate Limits
- **Mitigation**: Implement exponential backoff, cache calendar events

### Risk 2: Retell Webhook Reliability
- **Mitigation**: Idempotent webhook handlers, retry logic

### Risk 3: Tentative Booking Race Conditions
- **Mitigation**: Database unique constraint + transaction isolation

### Risk 4: PHI Encryption Key Management
- **Mitigation**: Phase 1 uses env var (acceptable for MVP), Phase 2 moves to Key Vault

---

## Phase 1 Deliverables

1. **Working API** - All Retell endpoints functional
2. **Database** - All migrations applied, test data seeded
3. **Google Calendar Integration** - Can read/write events
4. **Basic Documentation** - Setup guide, API docs
5. **Test Suite** - Unit + integration tests
6. **Deployment Guide** - How to deploy to Azure Container Apps

---

## Next Steps After Phase 1

Once Phase 1 is complete and tested:
- **Phase 2**: Add campaigns, EHR sync, reminder calls
- **Phase 2**: Enhanced usage tracking, phone routing
- **Phase 2**: Azure Key Vault integration, advanced security

---

## Next Steps (Priority Order)

### Immediate (Week 1 - Continue)
1. **Admin Endpoints** ✅ COMPLETE
   - [x] Created `Clinic_app/Routes/admin.py` with clinic, integration, license endpoints
   - [x] Created `Clinic_app/Routes/provider.py` with provider CRUD + time blocking
   - [x] All routes include validation, error handling, logging, and Google Calendar validation

2. **PHI Encryption** - Create `Clinic_app/common/encryption.py`
   - Required for patient creation
   - Priority: HIGH (blocks patient service)

3. **Patient Service** ✅ COMPLETE
   - [x] Created `Clinic_app/services/patient.py` with find_patient() and create_patient()
   - [x] Hash-based lookup using name+DOB
   - [x] All PHI encrypted (name, DOB, phone, email)
   - [x] Input validation and error handling

### Next (Week 2)
4. **Availability Service** ✅ COMPLETE
   - [x] Created `Clinic_app/services/availability.py` with all search functions
   - [x] Integrates with Google Calendar, Booking model, AvailabilitySlot
   - [x] Supports clinic business hours
   - [x] Detects patient appointments via keywords (English + Spanish)
5. **Booking Service** ✅ COMPLETE
   - [x] Created `Clinic_app/services/booking.py` with full booking lifecycle
   - [x] Capacity enforcement via SELECT FOR UPDATE (supports capacity > 1)
   - [x] Google Calendar integration (create on confirm, delete on cancel)
   - [x] BookingAudit trail for HIPAA compliance
   - [x] Updated migration to remove unique constraint
6. **Tentative Booking Reaper** - Create `Clinic_app/workers/booking_reaper.py`

### Then (Week 3) ✅ COMPLETE
7. **Retell Endpoints** ✅ COMPLETE - Created `Clinic_app/Routes/retell.py`
   - `POST /retell/schedule` - Book/reschedule/cancel with provider selection & load balancing
   - `POST /retell/confirm_booking` - Confirm tentative bookings
   - `GET /retell/availability` - Get available slots
8. **Retell Webhooks** ✅ COMPLETE - Added to retell.py
   - `POST /retell/webhook/call_started` - Track call start, identify clinic
   - `POST /retell/webhook/call_ended` - Track call end, release unconfirmed holds
9. **Error Handling** ✅ COMPLETE - Pydantic models and validation in all routes

### Finally (Week 4)
10. **Testing** - Integration and error scenario tests
11. **Seed Script** - Create test data
12. **Documentation** - Setup guides and API docs

---

**Estimated Timeline**: 4 weeks for Phase 1 MVP

