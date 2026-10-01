# HEDIS Campaign Implementation Plan

## Goal
**HEDIS Campaign Automation**: Enable automated outbound HEDIS campaign calls via Retell AI that check real-time NextGen EHR availability and book appointments immediately using AgentQL Chrome Extension. One extension per clinic, all bookings stored in NextGen only, minimal PHI in transit, no PHI stored in database.

## Progress Summary
**Overall: 0% Complete**

- ⚠️ **Database Foundation** - 0/2 tasks (0%)
- ⚠️ **Google Sheets Integration** - 0/4 tasks (0%)
- ⚠️ **Retell Outbound API** - 0/5 tasks (0%)
- ⚠️ **AgentQL Chrome Extension** - 0/6 tasks (0%)
- ⚠️ **WebSocket Infrastructure** - 0/4 tasks (0%)
- ⚠️ **HEDIS Campaign Worker** - 0/5 tasks (0%)
- ⚠️ **Retell Tool Endpoints Updates** - 0/3 tasks (0%)
- ⚠️ **Admin Endpoints** - 0/3 tasks (0%)

---

## HEDIS Campaign Scope: EHR-Only Booking System

### ✅ What's Included

#### 1. Database Foundation (Minimal, No PHI)
- [ ] **Campaign Model** - Store HEDIS campaign metadata (name, status, google_sheet_id, retell_agent_id)
- [ ] **CampaignContact Model** - Store campaign contacts from Google Sheet (name, phone, insurance, reason_for_calling)
- [ ] **CampaignAudit Model** - Minimal audit log (provider_id, slot_datetime, ehr_appointment_id only, NO PHI)
- [ ] **Alembic migrations** - Create campaign tables with proper indexes
- [ ] **Status tracking fields** - `call_made` (boolean), `appointment_booked` (boolean) per contact

#### 2. Google Sheets Integration
- [ ] **Google Sheets Service** - `Clinic_app/services/google_sheets.py`
- [ ] **Read campaign data** - Parse Google Sheet with columns: name, phone, insurance, reason_for_calling
- [ ] **Admin upload endpoint** - `POST /admin/campaigns/upload` - Accept Google Sheet ID
- [ ] **Continuous sync** - Worker periodically syncs Google Sheet to update contacts

#### 3. Retell Outbound Call API Client
- [ ] **Retell API Service** - `Clinic_app/services/retell_api.py`
- [ ] **Create outbound call** - `create_outbound_call(from_number, to_number, override_agent_id, metadata)`
- [ ] **Campaign metadata** - Pass `campaign_contact_id`, `call_type: "hedis_campaign"` in metadata
- [ ] **Error handling** - Retry logic, rate limit handling
- [ ] **API key management** - Environment variable for Retell API key

#### 4. AgentQL Chrome Extension
- [ ] **Extension structure** - Manifest V3, background script, content script
- [ ] **WebSocket client** - Persistent connection to FastAPI backend (one per clinic)
- [ ] **Clinic identification (MVP)** - Extension passes clinic_id via WebSocket query param or config (no OAuth initially)
- [ ] **NextGen availability query** - AgentQL scrapes NextGen calendar for available slots (real-time)
- [ ] **NextGen booking creation** - AgentQL creates appointment in NextGen when patient confirms
- [ ] **Reconnection logic** - Auto-reconnect on disconnect with exponential backoff

#### 5. WebSocket Infrastructure
- [ ] **WebSocket endpoint** - `WS /ws/{clinic_id}` - Persistent connection for Extension
- [ ] **Connection manager** - Track active Extension connections per clinic
- [ ] **Message protocol** - Define message types (availability_request, booking_request, status_update)
- [ ] **Queue system** - Queue booking requests if Extension offline, process when reconnected

#### 6. HEDIS Campaign Worker (Background Task)
- [ ] **Campaign Worker** - `Clinic_app/workers/hedis_campaign_worker.py`
- [ ] **Google Sheet sync** - Periodically read Google Sheet (every 5-10 minutes) for new/updated contacts
- [ ] **Process pending contacts** - Continuous loop checking for pending campaign contacts
- [ ] **Real-time Extension queries** - Uses Extension to query NextGen availability when Retell asks
- [ ] **Queue management** - Move to next contact if no answer, retry later
- [ ] **Create Retell calls** - Call Retell API to create outbound calls for pending contacts
- [ ] **Status updates** - Update campaign_contact status (pending → calling → completed)

#### 7. Retell Tool Endpoints (Update Existing)
- [ ] **Update `/retell/schedule`** - Support HEDIS campaign calls (detect via metadata, query Extension for availability, book immediately)
- [ ] **Update `/retell/availability`** - Real-time NextGen availability via Extension
- [ ] **Update webhooks** - Track campaign calls in `call_started`, update contact status in `call_ended`

#### 8. Admin Endpoints
- [ ] **Campaign upload** - `POST /admin/campaigns/upload` - Upload Google Sheet ID
- [ ] **Campaign status** - `GET /admin/campaigns/{clinic_id}/status` - View progress, metrics
- [ ] **Campaign control** - `POST /admin/campaigns/{clinic_id}/start`, `POST /admin/campaigns/{clinic_id}/pause`

---

## ❌ What's Deferred (Until Core Flow Works)

### OAuth for Extension
- OAuth endpoints and JWT token management for Extension
- Add **after** the full flow works (Retell → FastAPI → Extension → NextGen)
- For MVP: Extension connects with clinic_id in WebSocket URL or config (dev/single-clinic only)

---

## ❌ What's Deferred

### Google Calendar Integration
- No Google Calendar integration for HEDIS campaigns
- All availability and bookings in NextGen EHR only

### Inbound Calls
- No inbound call handling (outbound HEDIS campaigns only)

### Advanced Features
- Campaign analytics dashboard (MVP: basic status tracking)
- Multi-campaign scheduling
- Campaign templates
- Advanced retry strategies

### Advanced Security
- Azure Key Vault integration (use env vars for MVP)
- Advanced PHI encryption key rotation

---

## HEDIS Campaign Implementation Order

### Week 1: Foundation & AgentQL Testing

1. **Test AgentQL Locally (CRITICAL - Do This First)**
   - [ ] Set up minimal Chrome Extension (manifest.json, background.js, content.js)
   - [ ] Load Extension in Chrome (Developer Mode)
   - [ ] Test basic content script injection on NextGen page
   - [ ] Install AgentQL SDK in Extension
   - [ ] Test basic AgentQL query: `page.query_elements("{ some button }")`
   - [ ] Verify AgentQL can find elements on NextGen calendar page
   - [ ] Test NextGen availability query: Extract available time slots
   - [ ] Test NextGen booking flow: Find form, fill fields, submit
   - [ ] Verify appointment creation and extract appointment ID
   - [ ] Test WebSocket connection: Create simple WebSocket server, Extension connects
   - [ ] Test sending/receiving messages via WebSocket
   - [ ] Test reconnection logic
   - **Note**: Validate AgentQL works with NextGen before building full system

2. **Database Models & Migrations**
   - [ ] Create `Campaign` model (campaign.py) - Single HEDIS campaign per clinic
   - [ ] Create `CampaignContact` model (campaign_contact.py)
   - [ ] Create `CampaignAudit` model (campaign_audit.py) - Minimal, no PHI
   - [ ] Add enums: `CampaignStatus`, `CampaignContactStatus`
   - [ ] Create Alembic migration for campaign tables
   - [ ] Add indexes: `idx_campaign_status`, `idx_contact_status`, `idx_contact_next_retry`
   - [ ] Run migrations on dev database

3. **Google Sheets Service**
   - [ ] Create `Clinic_app/services/google_sheets.py`
   - [ ] Implement: `read_campaign_sheet(google_sheet_id)` - Read Google Sheet data
   - [ ] Implement: `parse_campaign_contacts(sheet_data)` - Parse rows into contact objects
   - [ ] Implement: Validation (required columns: name, phone, insurance, reason_for_calling)
   - [ ] Implement: Phone format validation (E.164 format)
   - [ ] Integrate: Google Sheets API with service account authentication
   - [ ] Unit tests for Google Sheets parsing

### Week 2: Extension & WebSocket Infrastructure

4. **Chrome Extension Development**
   - [ ] Create extension structure (manifest.json, background.js, content.js, agentql_integration.js)
   - [ ] Implement: WebSocket client in background.js (persistent connection)
   - [ ] Implement: Clinic ID from config (e.g. extension options page or env) — no OAuth for MVP
   - [ ] Implement: Reconnection logic with exponential backoff
   - [ ] Implement: Heartbeat/ping mechanism (keep connection alive)
   - [ ] Implement: Content script injection for NextGen pages
   - [ ] Implement: Message routing (background ↔ content script)

5. **AgentQL Integration in Extension**
   - [ ] Install AgentQL SDK in extension
   - [ ] Implement: `query_availability(provider_id, date)` - Scrape NextGen calendar using AgentQL
   - [ ] Implement: `book_appointment(patient_data, slot_datetime)` - Create appointment in NextGen using AgentQL
   - [ ] Implement: Error handling (NextGen errors, timeouts, slot taken)
   - [ ] Implement: Status reporting back to FastAPI via WebSocket

6. **WebSocket Infrastructure**
   - [ ] Create `Clinic_app/Routes/websocket.py`
   - [ ] Implement: `WS /ws/{clinic_id}` endpoint (clinic_id in path; no auth for MVP)
   - [ ] Implement: `ConnectionManager` class (track active connections per clinic)
   - [ ] Implement: Message protocol (availability_request, booking_request, status_update)
   - [ ] Implement: Queue system (queue booking requests if Extension offline)
   - [ ] Implement: Error handling (disconnections, timeouts, invalid messages)
   - [ ] Update `main.py` to include websocket router

### Week 3: Retell Integration & Campaign Worker

7. **Retell Outbound API Client**
   - [ ] Create `Clinic_app/services/retell_api.py`
   - [ ] Implement: `create_outbound_call(from_number, to_number, override_agent_id, metadata)`
   - [ ] Implement: Retry logic with exponential backoff
   - [ ] Implement: Error handling (API errors, rate limits)
   - [ ] Add environment variable: `RETELL_API_KEY`, `RETELL_FROM_NUMBER`
   - [ ] Unit tests for Retell API client

8. **HEDIS Campaign Service**
   - [ ] Create `Clinic_app/services/hedis_campaign.py`
   - [ ] Implement: `sync_campaign_from_sheets(campaign_id, google_sheet_id)` - Sync contacts from Google Sheet
   - [ ] Implement: `get_next_pending_contact(clinic_id)` - Get oldest pending contact ready for retry
   - [ ] Implement: `update_contact_status(contact_id, status, call_made, appointment_booked)`
   - [ ] Implement: `mark_campaign_completed(campaign_id)` - When all contacts answered
   - [ ] Implement: `query_nextgen_availability_via_extension(clinic_id, provider_id, date)` - Real-time query
   - [ ] Implement: `book_in_nextgen_via_extension(clinic_id, provider_id, slot_datetime, patient_data)` - Immediate booking

9. **HEDIS Campaign Worker**
    - [ ] Create `Clinic_app/workers/hedis_campaign_worker.py`
    - [ ] Implement: `process_hedis_campaign_calls()` - Main worker loop
    - [ ] Implement: Google Sheet sync (every 5-10 minutes) - Read sheet, update contacts
    - [ ] Implement: Process pending contacts (oldest first, ready for retry)
    - [ ] Implement: Queue management (move to next if no answer, schedule retry)
    - [ ] Implement: Rate limiting (check license.max_concurrency, Retell API limits)
    - [ ] Implement: Create Retell outbound calls for pending contacts
    - [ ] Implement: Status updates based on call outcomes
    - [ ] Implement: Process queued booking requests when Extension reconnects
    - [ ] Add graceful shutdown handling
    - [ ] Add error recovery (restart on exceptions)

10. **Retell Tool Endpoints (Updates)**
    - [ ] Update `/retell/schedule` endpoint in `Clinic_app/Routes/retell.py`:
      - Detect campaign calls via metadata (`call_type: "hedis_campaign"`)
      - Query NextGen availability via Extension (WebSocket) when Retell asks
      - Attempt immediate booking in NextGen via Extension when patient confirms
      - Handle NextGen rejections (offer alternative slots immediately)
    - [ ] Update `/retell/availability` endpoint:
      - For campaign calls, query NextGen via Extension (real-time)
      - Return available slots to Retell
    - [ ] Update webhooks in `Clinic_app/Routes/retell.py`:
      - `call_started`: Track campaign calls, link `CallLog.related_id` to `campaign_contact_id`
      - `call_ended`: Update `campaign_contact.status` based on outcome, set `call_made = True`

### Week 4: Admin Endpoints & Testing

11. **Admin Endpoints**
    - [ ] Create `Clinic_app/Routes/hedis_campaign.py`
    - [ ] Implement: `POST /admin/campaigns/upload` - Upload Google Sheet ID
    - [ ] Implement: `GET /admin/campaigns/{clinic_id}/status` - Get campaign progress, metrics
    - [ ] Implement: `POST /admin/campaigns/{clinic_id}/start` - Start campaign
    - [ ] Implement: `POST /admin/campaigns/{clinic_id}/pause` - Pause campaign
    - [ ] Add validation, error handling, and logging
    - [ ] Standardized APIResponse format

12. **Integration Testing**
    - [ ] Test full HEDIS campaign flow: upload → worker sync → Retell call → Extension query → booking
    - [ ] Test Extension offline scenario (queue booking requests)
    - [ ] Test Extension reconnection (process queued requests)
    - [ ] Test NextGen booking rejection (offer alternatives)
    - [ ] Test Google Sheet sync (new contacts, updated contacts)

13. **Error Scenarios Testing**
    - [ ] Test Extension offline during booking request
    - [ ] Test NextGen availability query timeout
    - [ ] Test NextGen booking failure (slot taken)
    - [ ] Test Retell API rate limits
    - [ ] Test WebSocket disconnection/reconnection

14. **Documentation**
    - [ ] Extension installation guide (per clinic) — include how to set clinic_id for MVP
    - [ ] Google Sheet format requirements
    - [ ] API documentation (FastAPI auto-docs at `/docs`)
    - [ ] Campaign worker configuration

### After MVP Works: OAuth for Extension (Optional / Production)

15. **OAuth Authentication** — Add only after full flow is working
   - [ ] Create `Clinic_app/Routes/auth.py`
   - [ ] Implement: `POST /auth/extension/login` - OAuth login endpoint
   - [ ] Implement: `GET /auth/extension/callback` - OAuth callback
   - [ ] Implement: JWT token issuance (include clinic_id in token)
   - [ ] Implement: Token validation on WebSocket connection
   - [ ] Update Extension to use OAuth instead of config clinic_id

---

## HEDIS Campaign Success Criteria

### Functional Requirements
- ✅ Google Sheet upload creates campaign and contacts
- ✅ Campaign worker continuously syncs Google Sheet (every 5-10 minutes)
- ✅ Campaign worker processes pending contacts with rate limiting
- ✅ Retell API creates outbound calls for HEDIS campaigns
- ✅ Extension queries NextGen availability in real-time when Retell asks
- ✅ Extension books appointments in NextGen immediately when patient confirms
- ✅ Campaign contacts track `call_made` and `appointment_booked` status
- ✅ Queue system handles offline Extension gracefully (queue requests, process on reconnect)
- ✅ Campaign completes when all contacts are answered
- ✅ NextGen booking failures handled gracefully (offer alternatives immediately)

### Technical Requirements
- ✅ All database migrations run successfully
- ✅ Retell API client handles errors gracefully
- ✅ WebSocket connections are stable and reconnect on failure
- ✅ Extension identifies clinic (config for MVP; OAuth when added for production)
- ✅ No PHI stored in database (only in transit)
- ✅ Minimal audit logs (provider_id, slot_datetime, ehr_appointment_id only)
- ✅ Background worker runs continuously without crashing
- ✅ Logs contain no PHI

### Testing Requirements
- ✅ Unit tests for all services (campaign, retell_api, google_sheets)
- ✅ Integration tests for API endpoints
- ✅ End-to-end test: Full HEDIS campaign flow (upload → start → calls → booking)
- ✅ Extension functionality tests (WebSocket, AgentQL)

---

## HEDIS Campaign File Structure

```
Clinic_app/
├── data/
│   ├── models/
│   │   ├── campaign.py ✅ (NEW - Campaign model, single HEDIS campaign per clinic)
│   │   ├── campaign_contact.py ✅ (NEW - CampaignContact model)
│   │   └── campaign_audit.py ✅ (NEW - CampaignAudit model, minimal, no PHI)
│   └── enums.py ✅ (UPDATE - Add CampaignStatus, CampaignContactStatus)
├── services/
│   ├── retell_api.py ✅ (NEW - Retell API client for outbound calls)
│   ├── google_sheets.py ✅ (NEW - Google Sheets API client)
│   └── hedis_campaign.py ✅ (NEW - Campaign service)
├── Routes/
│   ├── websocket.py ✅ (NEW - WebSocket endpoint for Extension)
│   ├── auth.py (OPTIONAL - OAuth for Extension; add after MVP works)
│   ├── hedis_campaign.py ✅ (NEW - Campaign admin endpoints)
│   └── retell.py ✅ (UPDATE - Support HEDIS campaign calls)
├── workers/
│   └── hedis_campaign_worker.py ✅ (NEW - Background worker for campaigns)
├── chrome_extension/ ✅ (NEW - AgentQL Chrome Extension)
│   ├── manifest.json
│   ├── background.js
│   ├── content.js
│   └── agentql_integration.js
├── alembic/
│   └── versions/
│       └── create_hedis_campaign_tables.py ✅ (NEW - Migration)
├── main.py ✅ (UPDATE - Include websocket router, start campaign worker)
└── tests/
    ├── test_hedis_campaign.py ✅ (NEW - Campaign service and endpoint tests)
    ├── test_retell_api.py ✅ (NEW - Retell API client tests)
    ├── test_google_sheets.py ✅ (NEW - Google Sheets service tests)
    └── test_websocket.py ✅ (NEW - WebSocket functionality tests)
```

---

## HEDIS Campaign Dependencies

### Python Packages (add to requirements.txt)
```
# Retell API
httpx==0.25.2 ✅ (already have)

# Google Sheets API
google-api-python-client==2.108.0 ✅ (already have for Calendar)
google-auth==2.23.4 ✅ (already have)

# WebSocket (FastAPI includes via Starlette)
# No additional package needed

# OAuth/JWT (add when implementing OAuth for Extension, after MVP works)
# python-jose[cryptography]==3.3.0
# python-multipart==0.0.6
```

### External Services
- Retell AI account with API key
- Retell agent configured for HEDIS campaigns (outbound calls)
- Retell phone number for outbound calls (from_number)
- Google Sheets API (enable in Google Cloud project)
- Google Workspace account or service account for Sheets access
- NextGen EHR access (via browser, Extension will automate)

### Environment Variables
```bash
# Retell API
RETELL_API_KEY=... (Retell API key for creating outbound calls)
RETELL_FROM_NUMBER=... (Retell phone number, E.164 format)

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=... (for Sheets API access, already have)

# WebSocket
WEBSOCKET_HEARTBEAT_INTERVAL=30 (seconds)

# OAuth/JWT (only when adding OAuth for Extension, after MVP works)
# OAUTH_CLIENT_ID=...
# OAUTH_CLIENT_SECRET=...
# OAUTH_REDIRECT_URI=...
# JWT_SECRET_KEY=...
# JWT_ALGORITHM=HS256
```

---

## HEDIS Campaign Risks & Mitigations

### Risk 1: AgentQL Not Working with NextGen
- **Mitigation**: Test AgentQL locally first (Week 1) before building full system
- **Fallback**: Manual testing, adjust AgentQL selectors as needed

### Risk 2: Extension Offline During Critical Booking
- **Mitigation**: Queue booking requests, process when Extension reconnects
- **Fallback**: Mark contact for retry, move to next contact

### Risk 3: NextGen UI Changes Break AgentQL
- **Mitigation**: Use semantic selectors (natural language), not brittle CSS selectors
- **Fallback**: Update AgentQL queries when NextGen updates

### Risk 4: Multiple Clinics Using Same Extension
- **Mitigation (MVP)**: Each clinic configures Extension with their clinic_id (dev/single-clinic)
- **Mitigation (Production)**: Add OAuth so Extension is linked to clinic via login

### Risk 5: Retell API Rate Limits
- **Mitigation**: Implement exponential backoff, respect concurrency limits, queue calls

### Risk 6: Google Sheet Sync Failures
- **Mitigation**: Retry logic, graceful error handling, log sync failures

---

## HEDIS Campaign Deliverables

1. **Working HEDIS Campaign System** - Google Sheet upload, worker processing, status tracking
2. **AgentQL Chrome Extension** - Real-time NextGen availability and booking (one per clinic)
3. **WebSocket Infrastructure** - Stable Extension ↔ FastAPI communication
4. **HEDIS Campaign Worker** - Continuous Google Sheet sync and contact processing
5. **Test Suite** - Unit + integration + end-to-end tests
6. **Documentation** - Extension installation guide (per clinic), setup instructions, API docs

---

## Next Steps After HEDIS Campaign

Once HEDIS Campaign is complete and tested:
- **OAuth for Extension** — Add when ready for production / multi-clinic (Extension login, JWT, clinic association)
- **Future**: Advanced campaign analytics
- **Future**: Multi-campaign support
- **Future**: Campaign templates
- **Future**: Advanced retry strategies

---

## Next Steps (Priority Order)

### Immediate (Week 1 - Critical)
1. **Test AgentQL Locally** - Set up minimal Extension, test NextGen interaction
   - Validate AgentQL works with NextGen before building full system
   - Test availability query, booking flow, WebSocket connection
   - Priority: CRITICAL (blocks all other work)

2. **Database Models** - Create Campaign, CampaignContact, CampaignAudit models
   - Required for all campaign functionality
   - Priority: HIGH

3. **Google Sheets Service** - Read and parse Google Sheet data
   - Required for campaign data ingestion
   - Priority: HIGH

### Next (Week 2)
4. **Chrome Extension** - Build Extension with AgentQL integration (clinic_id from config for MVP)
5. **WebSocket Infrastructure** - Create WebSocket endpoint and connection manager

### Then (Week 3)
6. **Retell Outbound API** - Create outbound call client
7. **Update Retell Endpoints** - Add campaign support to existing endpoints
8. **HEDIS Campaign Worker** - Build worker with Google Sheet sync and Extension queries

### Finally (Week 4)
9. **Admin Endpoints** - Create campaign upload and status endpoints
10. **Integration Testing** - Test full flow: upload → worker → Retell → Extension → NextGen
11. **Documentation** - Extension installation guide, API docs

### After Everything Works
12. **OAuth for Extension** - Add OAuth/JWT so Extension authenticates per clinic (production)

---

**Estimated Timeline**: 4 weeks for HEDIS Campaign MVP

**Critical Note**: Test AgentQL locally first (Week 1) before building full system. This validates NextGen integration works and prevents wasted development time.
