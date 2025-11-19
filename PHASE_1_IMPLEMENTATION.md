# Phase 1 Implementation Plan

## Goal
**Core Booking Functionality**: Enable inbound calls via Retell AI to successfully book, confirm, and cancel appointments with Google Calendar integration.

## Progress Summary
**Overall: ~30% Complete**

- ✅ **Database Foundation** - 2/3 tasks (67%)
- ✅ **Google Calendar Integration** - 9/9 tasks (100%) - COMPLETE
- ❌ **Retell Integration** - 0/6 tasks (0%)
- ❌ **Availability Engine** - 0/5 tasks (0%)
- ❌ **Booking State Machine** - 0/5 tasks (0%)
- ❌ **Patient Management** - 0/3 tasks (0%)
- ❌ **Error Handling** - 0/3 tasks (0%)
- ❌ **Admin Endpoints** - 0/5 tasks (0%) - NEW
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

#### 3. Core Retell Integration
- [ ] **Tool endpoint: `/retell/schedule`** - Book/reschedule/cancel appointments
- [ ] **Tool endpoint: `/retell/confirm_booking`** - Confirm tentative bookings
- [ ] **Tool endpoint: `/retell/availability`** - Get available slots
- [ ] **Webhook: `/retell/webhook/call_started`** - Track call start (basic)
- [ ] **Webhook: `/retell/webhook/call_ended`** - Track call end (basic)
- [ ] **Signature verification** - HMAC-SHA256 validation for Retell requests

#### 4. Availability Engine
- [ ] **Slot generation** - Generate 15-minute slots within time ranges
- [ ] **AvailabilitySlot querying** - Check FREE/BLOCKED status
- [ ] **Google Calendar conflict checking** - Count overlapping events
- [ ] **Double-booking prevention** - Database constraints + application logic
- [ ] **Capacity enforcement** - Respect provider.capacity limits

#### 5. Booking State Machine
- [ ] **Tentative booking creation** - With hold_token and hold_expires_at (5 min)
- [ ] **Booking confirmation** - Convert tentative → confirmed
- [ ] **Booking cancellation** - Update status to canceled
- [ ] **Hold expiration reaper** - Background worker to expire tentative holds (every 5 min)
- [ ] **BookingAudit logging** - Record all state changes

#### 6. Patient Management
- [ ] **Find patient by phone** - Within clinic scope
- [ ] **Create patient** - With encrypted name_token (basic encryption for Phase 1)
- [ ] **PHI encryption** - AES-256 encryption for name_token (can use env var key for Phase 1)

#### 7. Basic Error Handling
- [ ] **Standardized error responses** - Success/error format
- [ ] **Input validation** - Pydantic models for all requests
- [ ] **HTTP status codes** - Proper 400/404/409/500 responses

#### 8. Admin Endpoints (NEW - Required for Setup)
- [ ] **Clinic setup endpoint** - `POST /admin/clinics/setup` - Create clinic + integration + license
- [ ] **Provider management** - `POST /admin/clinics/{clinic_id}/providers` - Create provider
- [ ] **Provider management** - `PUT /admin/providers/{provider_id}` - Update provider
- [ ] **Provider management** - `GET /admin/clinics/{clinic_id}/providers` - List providers
- [ ] **Google Calendar validation** - Validate calendar access on provider create/update

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

### ✅ Week 1: Foundation (IN PROGRESS)

1. **Database Setup** ✅ COMPLETE
   - [x] Create Alembic migration for all existing models
   - [x] All models exist: `clinic`, `clinic_integration`, `provider`, `patient`, `booking`, `availability_slot`, `booking_audit`, `call_log`, `license`, `phone_route`
   - [x] Run migrations on dev database
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

3. **Admin Endpoints** (NEW - Required for Setup)
   - [ ] Create `Clinic_app/Routes/admin.py`
   - [ ] Implement: `POST /admin/clinics/setup` - Create clinic + integration + license
   - [ ] Implement: `POST /admin/clinics/{clinic_id}/providers` - Create provider
   - [ ] Implement: `PUT /admin/providers/{provider_id}` - Update provider
   - [ ] Implement: `GET /admin/clinics/{clinic_id}/providers` - List providers
   - [ ] Integrate Google Calendar validation on provider create/update

4. **PHI Encryption Utilities**
   - [ ] Create `Clinic_app/common/encryption.py`
   - [ ] Implement: AES-256 encryption for PHI
   - [ ] Implement: `encrypt_phi()` function
   - [ ] Implement: `decrypt_phi()` function
   - [ ] Use env var key for Phase 1

5. **Basic Patient Service**
   - [ ] Create `Clinic_app/services/patient.py`
   - [ ] Implement: `find_or_create_patient()` - Find by phone, create if not exists
   - [ ] Integrate PHI encryption for name_token and dob_token

### Week 2: Core Booking Logic

6. **Availability Service**
   - [ ] Create `Clinic_app/services/availability.py`
   - [ ] Implement: `generate_slots()` - Generate 15-minute slots within time ranges
   - [ ] Implement: `check_availability()` - Check AvailabilitySlot status (FREE/BLOCKED)
   - [ ] Implement: `find_available_slot()` - Find first available slot for provider
   - [ ] Integrate: Google Calendar conflict checking using `count_overlapping_events()`
   - [ ] Implement: Capacity enforcement (respect provider.capacity limits)
   - [ ] Implement: Double-booking prevention logic

7. **Booking Service**
   - [ ] Create `Clinic_app/services/booking.py`
   - [ ] Implement: `create_tentative_booking()` - Create booking with hold_token and hold_expires_at (5 min)
   - [ ] Implement: `confirm_booking()` - Convert tentative → confirmed, create Google Calendar event
   - [ ] Implement: `cancel_booking()` - Update status to canceled, delete Google Calendar event
   - [ ] Implement: `reschedule_booking()` - Cancel old, create new tentative booking
   - [ ] Implement: `BookingAudit` logging - Record all state changes
   - [ ] Integrate: Google Calendar event creation/update/delete

8. **Tentative Booking Reaper**
   - [ ] Create `Clinic_app/workers/booking_reaper.py`
   - [ ] Implement: Background worker (asyncio task)
   - [ ] Implement: Expire tentative bookings every 5 minutes
   - [ ] Implement: Update AvailabilitySlot status back to FREE
   - [ ] Integrate: Start worker on application startup

### Week 3: Retell Integration

9. **Retell Tool Endpoints**
   - [ ] Create `Clinic_app/Routes/retell.py`
   - [ ] Implement: `POST /retell/schedule` - Book/reschedule/cancel appointments
     - [ ] Call `PatientService.find_or_create_patient()`
     - [ ] Call `AvailabilityService.find_available_slot()`
     - [ ] Call `BookingService.create_tentative_booking()` or `cancel_booking()`
   - [ ] Implement: `POST /retell/confirm_booking` - Confirm tentative bookings
     - [ ] Call `BookingService.confirm_booking()` (creates Google Calendar event)
   - [ ] Implement: `GET /retell/availability` - Get available slots
     - [ ] Call `AvailabilityService.generate_slots()` and `check_availability()`
   - [ ] Add signature verification middleware (HMAC-SHA256)

10. **Retell Webhooks**
   - [ ] Implement: `POST /retell/webhook/call_started` - Track call start
   - [ ] Implement: `POST /retell/webhook/call_ended` - Track call end
   - [ ] Create basic `CallLog` entries for usage tracking

11. **Error Handling & Validation**
   - [ ] Create Pydantic request/response models for all endpoints
   - [ ] Standardize error responses (success/error format)
   - [ ] Add input validation (date ranges, phone format, etc.)
   - [ ] Implement proper HTTP status codes (400/404/409/500)

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
│   └── encryption.py (NEW - PHI encryption utilities)
├── data/
│   ├── enums.py ✅ (exists)
│   └── models/ ✅ (exists, may need clinic_integration model)
├── services/
│   ├── google_calendar.py ✅ (COMPLETE - 910 lines, fully tested)
│   ├── patient.py (NEW)
│   ├── availability.py (NEW)
│   ├── booking.py (NEW)
│   └── retell.py (NEW - Retell API client)
├── Routes/
│   ├── health.py ✅ (exists)
│   ├── admin.py (NEW - Admin endpoints for clinics/providers)
│   └── retell.py (NEW - Retell endpoints)
├── scripts/
│   └── seed_data.py (NEW - Seed script for test data)
├── workers/
│   └── booking_reaper.py (NEW - Expire tentative bookings)
├── main.py ✅ (exists)
├── alembic/ ✅ (COMPLETE - migrations exist)
│   ├── versions/
│   │   └── 3f270d38367a_initial_models.py ✅ (exists)
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
1. **Admin Endpoints** - Create `Clinic_app/Routes/admin.py`
   - Required to create clinics and providers before testing
   - Priority: HIGH (blocks other development)

2. **PHI Encryption** - Create `Clinic_app/common/encryption.py`
   - Required for patient creation
   - Priority: HIGH (blocks patient service)

3. **Patient Service** - Create `Clinic_app/services/patient.py`
   - Required for booking flow
   - Priority: HIGH (blocks booking service)

### Next (Week 2)
4. **Availability Service** - Create `Clinic_app/services/availability.py`
5. **Booking Service** - Create `Clinic_app/services/booking.py`
6. **Tentative Booking Reaper** - Create `Clinic_app/workers/booking_reaper.py`

### Then (Week 3)
7. **Retell Endpoints** - Create `Clinic_app/Routes/retell.py`
8. **Retell Webhooks** - Add to retell.py
9. **Error Handling** - Pydantic models and validation

### Finally (Week 4)
10. **Testing** - Integration and error scenario tests
11. **Seed Script** - Create test data
12. **Documentation** - Setup guides and API docs

---

**Estimated Timeline**: 4 weeks for Phase 1 MVP

