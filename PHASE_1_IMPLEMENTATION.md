# Phase 1 Implementation Plan

## Goal
**Core Booking Functionality**: Enable inbound calls via Retell AI to successfully book, confirm, and cancel appointments with Google Calendar integration.

---

## Phase 1 Scope: MVP Booking System

### ✅ What's Included

#### 1. Database Foundation
- [x] **Models exist** (Clinic, Provider, Patient, Booking, AvailabilitySlot, BookingAudit)
- [ ] **Alembic migrations** - Create all tables with proper indexes and constraints
- [ ] **Seed data script** - Create test clinic, provider, and integration records

#### 2. Core Google Calendar Integration
- [ ] **Service account authentication** - Google Calendar API client setup
- [ ] **Read calendar events** - Fetch existing events for availability checking
- [ ] **Create calendar events** - When booking is confirmed
- [ ] **Update calendar events** - For reschedules
- [ ] **Delete calendar events** - For cancellations
- [ ] **Metadata handling** - Set/get extendedProperties.private for tracking

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

#### 8. Basic Infrastructure
- [ ] **Environment configuration** - .env file for secrets
- [ ] **Logging setup** - Structured logging (no PHI)
- [ ] **Health check** - `/health` endpoint (already exists)

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

---

## Phase 1 Implementation Order

### Week 1: Foundation
1. **Database Setup**
   - Create Alembic migration for all existing models
   - Add missing models: `clinic_integration`, `campaign`, `campaign_contact`, `call_log`, `ehr_appointment_sync`
   - Run migrations on dev database
   - Create seed script for test data

2. **Google Calendar Client**
   - Set up Google service account
   - Create `Clinic_app/services/google_calendar.py`
   - Implement: authenticate, list_events, create_event, update_event, delete_event
   - Test with real calendar

3. **Basic Patient Service**
   - Create `Clinic_app/services/patient.py`
   - Implement: find_or_create_patient
   - Basic encryption for name_token (AES-256 with env var key)

### Week 2: Core Booking Logic
4. **Availability Service**
   - Create `Clinic_app/services/availability.py`
   - Implement: generate_slots, check_availability, find_available_slot
   - Integrate AvailabilitySlot + Google Calendar checking

5. **Booking Service**
   - Create `Clinic_app/services/booking.py`
   - Implement: create_tentative_booking, confirm_booking, cancel_booking
   - Implement: BookingAudit logging
   - Integrate with Google Calendar

6. **Tentative Booking Reaper**
   - Create background worker (can use asyncio task or Celery)
   - Expire tentative bookings every 5 minutes
   - Update AvailabilitySlot status

### Week 3: Retell Integration
7. **Retell Tool Endpoints**
   - Create `Clinic_app/Routes/retell.py`
   - Implement: POST `/retell/schedule`
   - Implement: POST `/retell/confirm_booking`
   - Implement: GET `/retell/availability`
   - Add signature verification middleware

8. **Retell Webhooks**
   - Implement: POST `/retell/webhook/call_started`
   - Implement: POST `/retell/webhook/call_ended`
   - Create basic call_log entries

9. **Error Handling & Validation**
   - Create Pydantic request/response models
   - Standardize error responses
   - Add input validation

### Week 4: Testing & Polish
10. **Integration Testing**
    - Test full booking flow: call → tentative → confirm → GCal event
    - Test cancellation flow
    - Test reschedule flow
    - Test double-booking prevention

11. **Error Scenarios**
    - Test expired hold tokens
    - Test no available slots
    - Test invalid clinic_id/provider_id
    - Test Google Calendar API failures

12. **Documentation**
    - API documentation (FastAPI auto-docs)
    - Setup instructions
    - Environment variables guide

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
│   ├── google_calendar.py (NEW)
│   ├── patient.py (NEW)
│   ├── availability.py (NEW)
│   ├── booking.py (NEW)
│   └── retell.py (NEW - Retell API client)
├── Routes/
│   ├── health.py ✅ (exists)
│   └── retell.py (NEW - Retell endpoints)
├── workers/
│   └── booking_reaper.py (NEW - Expire tentative bookings)
├── main.py ✅ (exists)
└── alembic/ (NEW - Database migrations)
    ├── versions/
    └── alembic.ini
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

**Estimated Timeline**: 4 weeks for Phase 1 MVP

