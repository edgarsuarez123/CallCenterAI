# CallCenterAI — Infrastructure & Architecture Reference

> **Generated:** March 18, 2026  
> **Codebase:** `C:\Users\Edgar\Projects\CallCenterAI`  
> **Status:** Active development — see [Known Gaps](#12-known-architectural-gaps) for incomplete areas.

---

## Table of Contents

1. [Repository Layout](#1-repository-layout)
2. [Technology Stack](#2-technology-stack)
3. [Environment & Configuration](#3-environment--configuration)
4. [Database Schema](#4-database-schema)
5. [API Surface](#5-api-surface)
6. [Service Layer](#6-service-layer)
7. [PHI Security Model](#7-phi-security-model)
8. [External Service Integrations](#8-external-service-integrations)
9. [Background Jobs & Workers](#9-background-jobs--workers)
10. [Containerization & Deployment](#10-containerization--deployment)
11. [Testing](#11-testing)
12. [Known Architectural Gaps](#12-known-architectural-gaps)

---

## 1. Repository Layout

```
CallCenterAI/
├── Clinic_app/                  # Core FastAPI application
│   ├── main.py                  # App factory, router registration, CORS
│   ├── alembic.ini              # Alembic configuration
│   ├── common/
│   │   ├── database.py          # Async SQLAlchemy engine + session factory
│   │   └── encryption.py        # AES-256-GCM PHI encrypt/decrypt
│   ├── data/
│   │   ├── enums.py             # All domain enumerations
│   │   └── models/              # SQLAlchemy ORM models (10 tables)
│   │       ├── __init__.py
│   │       ├── clinic.py
│   │       ├── license.py
│   │       ├── clinic_integration.py
│   │       ├── provider.py
│   │       ├── patient.py
│   │       ├── availability_slot.py
│   │       ├── booking.py
│   │       ├── booking_audit.py
│   │       ├── phone_route.py
│   │       └── call_log.py
│   ├── Routes/
│   │   ├── health.py            # GET /health, GET /ping
│   │   ├── retell.py            # Retell AI tool endpoints + webhooks
│   │   ├── admin.py             # Admin CRUD (clinics, licenses, bookings)
│   │   └── provider.py          # Provider CRUD + time blocking
│   ├── services/
│   │   ├── patient.py           # Patient lookup + PHI-safe creation
│   │   ├── booking.py           # Full booking lifecycle
│   │   ├── availability.py      # Slot generation + GCal merge
│   │   └── google_calendar.py   # Google Calendar API v3 wrapper
│   └── alembic/
│       ├── env.py               # Alembic env (sync psycopg2 for migrations)
│       ├── script.py.mako       # Migration file template
│       └── versions/
│           ├── 3f270d38367a_initial_models.py
│           └── encrypt_patient_phone_email_add_hash.py
├── tests/                       # pytest async test suite
│   ├── test_encryption.py
│   ├── test_patient.py
│   ├── test_booking.py
│   ├── test_availability.py
│   ├── test_retell.py
│   ├── test_admin.py
│   ├── test_provider.py
│   ├── test_google_calendar.py
│   └── README.md
├── agentql-test/                # Experimental NextGen EHR automation
│   └── click-test.js            # Playwright + AgentQL CDP proof-of-concept
├── Dockerfile                   # Production container (Python 3.11-slim)
├── docker-compose.yaml          # Production compose (app only, external DB)
├── docker-compose.dev.yaml      # Dev compose (app + postgres + redis)
├── start.sh                     # Entrypoint: wait-for-PG → migrate → serve
├── requirements.txt             # Python dependencies
├── pytest.ini                   # pytest config (asyncio_mode=auto)
├── env.example                  # Environment variable template
└── PRD.md                       # Product Requirements Document v3.2
```

---

## 2. Technology Stack

### Backend

| Component | Library / Version | Role |
|---|---|---|
| API Framework | FastAPI 0.104.1 | Async REST API |
| ASGI Server | Uvicorn 0.24.0 (standard) | HTTP server |
| ORM | SQLAlchemy 2.0.23 (async) | Database abstraction |
| Async PG Driver | asyncpg 0.29.0 | Runtime DB driver |
| Sync PG Driver | psycopg2-binary 2.9.9 | Alembic migrations only |
| Schema Migrations | Alembic 1.12.1 | Database versioning |
| Data Validation | Pydantic 2.5.0 / pydantic-settings 2.1.0 | Request/response models |
| Encryption | cryptography 41.0.7 | AES-256-GCM PHI at rest |
| HTTP Client (async) | httpx 0.25.2 | External API calls |
| HTTP Client (sync) | requests 2.31.0 | Utility requests |
| Retry Logic | tenacity 8.2.3 | Resilient external calls |
| Timezone | pytz 2024.1 / python-dateutil 2.8.2 | IANA timezone handling |
| Env Loading | python-dotenv 1.0.0 | `.env` file support |
| System Monitoring | psutil 5.9.6 | Health check metrics |

### Infrastructure

| Component | Technology | Role |
|---|---|---|
| Database | PostgreSQL (Azure Flexible Server) | Primary data store |
| Cache / Broker | Redis 7 (Alpine) | Configured, not yet used |
| Container Runtime | Docker / Docker Compose | Local dev + production |
| Cloud Platform | Azure | PostgreSQL + OpenAI hosting |

### External Services

| Service | Library | Role |
|---|---|---|
| Retell AI | Webhook + HMAC-SHA256 | Voice conversation engine |
| Google Calendar API v3 | google-api-python-client 2.108.0 | Appointment event management |
| Google Auth | google-auth 2.23.4 + oauthlib + httplib2 | Service account auth |
| Azure OpenAI | openai 1.3.0 | Configured, not yet active |
| NextGen EHR | Playwright (Node.js) + AgentQL | Planned EHR automation |

### Testing & Tooling

| Tool | Version | Role |
|---|---|---|
| pytest | 7.4.3 | Test runner |
| pytest-asyncio | 0.21.1 | Async test support |
| black | 23.11.0 | Code formatter |
| flake8 | 6.1.0 | Linter |

---

## 3. Environment & Configuration

All runtime configuration flows through environment variables. See `env.example` for the full template.

```
# Application
APP_ENVIRONMENT=development|production
APP_PORT=8000
APP_WORKERS=4

# PostgreSQL
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=

# PHI Encryption (AES-256 key, base64-encoded 32 bytes)
PHI_ENCRYPTION_KEY=

# Retell AI
RETELL_WEBHOOK_SECRET=

# Azure OpenAI (not yet active)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=
AZURE_OPENAI_DEPLOYMENT_NAME=

# Redis (not yet active)
REDIS_URL=redis://localhost:6379

# CORS (optional)
# ALLOWED_ORIGINS=
```

**SSL:** The async database engine always connects with `ssl=True` (asyncpg) and the Alembic sync URL appends `?sslmode=require`, targeting Azure PostgreSQL Flexible Server.

---

## 4. Database Schema

### 4.1 Native PostgreSQL Enumerations

| Enum | Values |
|---|---|
| `bookingstatus` | `tentative`, `confirmed`, `canceled` |
| `slotstatus` | `free`, `booked`, `blocked` |
| `slotsource` | `csv`, `gcal` |
| `bookingaction` | `hold`, `confirm`, `cancel`, `expire` |

> `CallState` (greeting / intent_detection / booking_info / …) is defined in `enums.py` but not yet referenced by any route or service.

### 4.2 Entity-Relationship Overview

```
Clinic  ──────────────────────────────────────────────────────────┐
 │ 1:1  License           (clinic_id FK, CASCADE)                 │
 │ 1:1  ClinicIntegration (clinic_id FK, CASCADE, UNIQUE)         │
 │ 1:N  Provider          (clinic_id FK, CASCADE)                 │
 │ 1:N  Patient           (clinic_id FK, CASCADE)                 │
 │ 1:N  AvailabilitySlot  (clinic_id FK, CASCADE)                 │
 │ 1:N  Booking           (clinic_id FK, CASCADE)                 │
 │ 1:N  BookingAudit      (clinic_id FK, CASCADE)                 │
 │ 1:N  PhoneRoute        (clinic_id FK, CASCADE)                 │
 └──────────────────────────────────────────────────────────────┘

Provider ──► AvailabilitySlot  (provider_id FK, CASCADE)
Provider ──► Booking           (provider_id FK, CASCADE)
Patient  ──► Booking           (patient_id  FK, CASCADE)
Booking  ──► BookingAudit      (booking_id  FK, RESTRICT — immutable audit)

CallLog  (NO FK to Clinic — survives clinic deletion, PHI-free)
```

### 4.3 Model Reference

#### `Clinic` — Multi-tenant root

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR | |
| `tier` | VARCHAR | `basic` / `pro` / `enterprise` |
| `status` | VARCHAR | `active` / `suspended` |
| `license_token` | VARCHAR UNIQUE | Clinic auth token |
| `network_id` | UUID nullable | Clinic group support |
| `business_hours_start` | TIME | Default slot generation window |
| `business_hours_end` | TIME | |
| `created_at` / `updated_at` | TIMESTAMP | |

#### `License` — Feature gating (1:1 Clinic)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `max_concurrency` | INT | Max simultaneous calls |
| `tier` | VARCHAR | |
| `status` | VARCHAR | `active` / `expired` / `suspended` |
| `features` | JSONB | e.g. `{"reminders": true, "hedis": false}` |
| `expires_at` | TIMESTAMP nullable | |

#### `ClinicIntegration` — Third-party credentials (1:1 Clinic)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK UNIQUE | CASCADE |
| `retell_agent_id` | VARCHAR | Maps Retell agent → clinic |
| `retell_did` | VARCHAR | E.164 inbound DID |
| `google_service_account_json` | TEXT | File path or raw JSON string |
| `default_appointment_length_minutes` | INT | |
| `default_capacity` | INT | |

#### `Provider` — Bookable calendar resource

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `display_name` | VARCHAR | |
| `google_calendar_id` | VARCHAR | GCal calendar identifier |
| `timezone` | VARCHAR | IANA timezone string |
| `booking_duration_mins` | INT | Slot length in minutes |
| `capacity` | INT | Concurrent bookings per slot |
| `active` | BOOLEAN | |
| `external_id` | VARCHAR nullable | EHR system ID |

**Index:** `idx_provider_clinic_active (clinic_id, active)`

#### `Patient` — PHI-encrypted contact (all tokens are BYTEA)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `name_token` | BYTEA | AES-256-GCM encrypted name |
| `dob_token` | BYTEA | AES-256-GCM encrypted date of birth |
| `phone_token` | BYTEA | AES-256-GCM encrypted E.164 phone |
| `email_token` | BYTEA nullable | AES-256-GCM encrypted email |
| `name_dob_hash` | VARCHAR | SHA-256 of `normalize(name)\|dob` |
| `language` | VARCHAR | `en` / `es` |
| `insurance_plan` | VARCHAR nullable | |

**Index:** `idx_clinic_name_dob_hash (clinic_id, name_dob_hash)` — all patient lookups go through this hash.

#### `AvailabilitySlot` — Physical slot record

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `provider_id` | UUID FK | CASCADE |
| `slot_start` / `slot_end` | TIMESTAMP WITH TZ | |
| `source` | `slotsource` ENUM | `csv` or `gcal` |
| `status` | `slotstatus` ENUM | `free` / `booked` / `blocked` |
| `last_sync_at` | TIMESTAMP nullable | |

**Constraint:** UNIQUE `(provider_id, slot_start, slot_end)`  
**Index:** `idx_clinic_status_start (clinic_id, status, slot_start)`

#### `Booking` — Appointment record

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `provider_id` | UUID FK | CASCADE |
| `patient_id` | UUID FK | CASCADE |
| `slot_start` / `slot_end` | TIMESTAMP WITH TZ | |
| `status` | `bookingstatus` ENUM | `tentative` / `confirmed` / `canceled` |
| `hold_token` | UUID | Unique claim token (used to confirm) |
| `hold_expires_at` | TIMESTAMP | 5-minute expiry window |
| `google_event_id` | VARCHAR nullable | GCal event ID (set on confirm) |
| `source` | `slotsource` ENUM | |

**Indexes:**  
- `idx_booking_slot_lookup (provider_id, slot_start, slot_end, status)`  
- `idx_status_hold_expires (status, hold_expires_at)` — reaper efficiency  
- `idx_booking_unique_slot` — partial UNIQUE on `(provider_id, slot_start)` WHERE `status IN (tentative, confirmed)` — double-booking prevention

#### `BookingAudit` — Immutable HIPAA event log

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK | CASCADE |
| `booking_id` | UUID FK | **RESTRICT** — audit rows block booking deletion |
| `action` | `bookingaction` ENUM | `hold` / `confirm` / `cancel` / `expire` |
| `actor` | VARCHAR | `retell_ai` / `admin` / `system` |
| `timestamp` | TIMESTAMP | |
| `metadata` | JSONB nullable | Extra context |

#### `PhoneRoute` — Inbound call routing

| Column | Type | Notes |
|---|---|---|
| `did_e164` | VARCHAR PK | E.164 phone number (DID) |
| `clinic_id` | UUID FK | CASCADE |
| `container_url` | VARCHAR | Target service URL |
| `active` | BOOLEAN | |

#### `CallLog` — Usage tracking (no clinic FK)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID (no FK) | Survives clinic deletion |
| `retell_call_id` | VARCHAR UNIQUE | Retell's call identifier |
| `call_type` | VARCHAR | `inbound` / `outbound_reminder` / `outbound_campaign` |
| `tentative_booking_id` | UUID nullable | Associated hold (no FK) |
| `duration_seconds` | INT nullable | |
| `outcome` | VARCHAR nullable | |
| `started_at` / `ended_at` | TIMESTAMP | |

### 4.4 Migration Chain

```
3f270d38367a  initial_models
    └── a1b2c3d4e5f6  encrypt_patient_phone_email_add_hash
                       (adds phone_token, email_token, name_dob_hash;
                        drops plaintext phone_e164 and email columns)
```

---

## 5. API Surface

> **Important:** `admin_router`, `retell_router`, and `provider_router` are fully implemented in their respective files but are **not registered** in `main.py`. The running application currently only serves health routes. See [Known Gaps §12.1](#121-router-registration).

### 5.1 Health (`/`)

| Method | Path | Description |
|---|---|---|
| GET | `/` | Root — returns API name + version info |
| GET | `/health` | DB liveness ping + status object |
| GET | `/ping` | Simple `{"status": "ok"}` liveness |

Auto-generated docs at `/docs` (Swagger UI) and `/redoc`.

### 5.2 Retell AI (`/retell/`) — implemented, not registered

| Method | Path | Description |
|---|---|---|
| POST | `/retell/schedule` | Main booking tool: book / cancel / reschedule via Retell tool call |
| POST | `/retell/confirm_booking` | Confirm a tentative hold by `hold_token` |
| GET | `/retell/availability` | REST-style slot availability query |
| POST | `/retell/availability` | Retell tool call format availability query |
| POST | `/retell/webhook/call_started` | Inbound webhook: creates `CallLog`, identifies clinic by `agent_id` |
| POST | `/retell/webhook/call_ended` | Inbound webhook: updates `CallLog`, releases unconfirmed holds |

**Security:** All webhook endpoints verify HMAC-SHA256 signature using `RETELL_WEBHOOK_SECRET` with `hmac.compare_digest` (constant-time). Playground/test calls (`call_id == "playground"` or prefix `"test_"`) bypass verification.

### 5.3 Admin (`/admin/`) — implemented, not registered

| Method | Path | Description |
|---|---|---|
| POST | `/admin/clinics/setup` | Atomic one-shot onboarding: Clinic + Integration + License |
| POST | `/admin/clinics` | Create clinic only |
| GET | `/admin/clinics` | List all clinics |
| GET | `/admin/clinics/{clinic_id}` | Get single clinic |
| PUT | `/admin/clinics/{clinic_id}` | Update clinic fields |
| POST | `/admin/clinics/{clinic_id}/integration` | Create/replace integration config |
| GET | `/admin/clinics/{clinic_id}/integration` | Get integration |
| PUT | `/admin/clinics/{clinic_id}/integration` | Update integration |
| POST | `/admin/clinics/{clinic_id}/license` | Create/replace license |
| GET | `/admin/clinics/{clinic_id}/license` | Get license |
| PUT | `/admin/clinics/{clinic_id}/license` | Update license |
| GET | `/admin/clinics/{clinic_id}/business-hours` | Get business hours |
| PUT | `/admin/clinics/{clinic_id}/business-hours` | Update business hours |
| GET | `/admin/clinics/{clinic_id}/bookings` | List bookings (provider / patient / status / date filters; paginated) |
| DELETE | `/admin/clinics/{clinic_id}/bookings/{booking_id}` | Cancel single booking |
| DELETE | `/admin/clinics/{clinic_id}/bookings` | Bulk cancel (up to 100) |

**Security gap:** No authentication layer exists on admin routes. See [§12.6](#126-no-authentication-on-admin-routes).

### 5.4 Provider (`/admin/`) — implemented, not registered

| Method | Path | Description |
|---|---|---|
| POST | `/admin/clinics/{clinic_id}/providers` | Create provider (validates GCal access on creation) |
| GET | `/admin/clinics/{clinic_id}/providers` | List providers (`active_only` filter) |
| GET | `/admin/providers/{provider_id}` | Get provider |
| PUT | `/admin/providers/{provider_id}` | Update provider |
| POST | `/admin/providers/{provider_id}/block-time` | Block a time range (creates `AvailabilitySlot` with `status=blocked`) |
| POST | `/admin/providers/{provider_id}/unblock-time` | Remove blocked slot |

---

## 6. Service Layer

### 6.1 `booking.py` — Booking Lifecycle

```
create_tentative_booking()
  ├── count overlapping TENTATIVE + CONFIRMED bookings vs provider.capacity
  ├── raise ConflictError if at or over capacity
  ├── INSERT Booking (status=tentative, hold_expires_at = now + 5 min)
  └── INSERT BookingAudit (action=hold)

confirm_booking(hold_token)
  ├── SELECT booking WHERE hold_token = ?
  ├── raise NotFoundError / ExpiredError / AlreadyConfirmedError
  ├── UPDATE Booking status=confirmed
  ├── create_google_calendar_event() — graceful degradation on failure
  ├── UPDATE Booking.google_event_id
  └── INSERT BookingAudit (action=confirm)

cancel_booking(booking_id)
  ├── UPDATE Booking status=canceled
  ├── delete_google_calendar_event() — graceful degradation
  └── INSERT BookingAudit (action=cancel)

reschedule_booking(booking_id, new_slot)
  ├── cancel_booking(old)    ─┐ atomic within one DB transaction
  └── create_tentative_booking(new) ─┘

expire_booking(booking_id)
  ├── UPDATE Booking status=canceled (special expire path)
  └── INSERT BookingAudit (action=expire)

get_expired_tentative_bookings()
  └── SELECT WHERE status=tentative AND hold_expires_at < now()
      (ready for reaper worker — not yet scheduled)
```

**Capacity enforcement:** `_count_slot_bookings` counts overlapping `(TENTATIVE | CONFIRMED)` bookings for the same provider. The partial unique index on `availability_slots` prevents duplicate BLOCKED records; the booking-level partial unique index prevents the same slot being double-confirmed.

### 6.2 `availability.py` — Slot Generation & Merging

```
get_available_slots(clinic_id, provider_id, date)
  ├── generate candidate slots from business_hours at booking_duration_mins intervals
  ├── localize to provider.timezone (IANA)
  ├── skip weekends (Mon–Fri hardcoded)
  ├── fetch BLOCKED AvailabilitySlots from DB
  ├── fetch Google Calendar events for date window (single batched API call)
  │   ├── filter "patient appointment" keywords (English + Spanish)
  │   ├── match events with source=callcenter_ai to DB bookings by extended property booking_id
  │   └── orphaned GCal events (not in DB) count toward capacity
  └── return slots where booked_count < provider.capacity

get_next_available_slots(clinic_id, provider_id, n=5, max_days=14)
  └── iterates get_available_slots day-by-day up to max_days

find_slot_at_time(preferred_time, ...)
  └── searches ±2 days from preferred time

check_and_offer_alternatives(...)
  └── if requested slot full → call get_next_available_slots → return suggestions
```

### 6.3 `patient.py` — PHI-Safe Patient Management

```
find_patient(clinic_id, name, dob)
  ├── hash = SHA-256(normalize(name) + "|" + dob)
  ├── SELECT WHERE clinic_id = ? AND name_dob_hash = hash
  ├── decrypt name_token + dob_token for each candidate (collision defense)
  └── return patient where decrypted values match

create_patient(clinic_id, name, dob, phone, email?, language, insurance?)
  ├── validate phone → E.164
  ├── validate dob → YYYY-MM-DD
  ├── validate email regex (if provided)
  ├── validate language in {en, es}
  ├── encrypt name, dob, phone, email → AES-256-GCM BYTEA tokens
  ├── compute name_dob_hash
  └── INSERT Patient
```

### 6.4 `google_calendar.py` — Calendar API Wrapper

```
GoogleCalendarService(service_account_json, calendar_id)
  ├── _build_service()       — credentials from JSON file or raw string
  ├── _execute_in_thread()   — run sync API calls in ThreadPoolExecutor(10)
  │
  ├── list_events(start, end, ...)
  ├── create_event(summary, start, end, metadata)
  │   └── extended_properties: source=callcenter_ai, booking_id, clinic_id
  ├── update_event(event_id, ...)
  ├── delete_event(event_id)
  ├── delete_multiple_events(event_ids)  — parallel deletion
  ├── get_event(event_id)
  └── validate_calendar_access()        — used at provider creation time

Retry policy (tenacity):
  ├── 3 attempts
  ├── Default: exponential backoff 1s → 2s → 4s
  └── Rate limit (429 / quota): 5s → 10s → 20s
```

---

## 7. PHI Security Model

All Protected Health Information is encrypted **before** it reaches the database.

### Encryption Spec

| Property | Value |
|---|---|
| Algorithm | AES-256-GCM (authenticated encryption) |
| Key source | `PHI_ENCRYPTION_KEY` env var (base64-encoded 32 bytes) |
| Key caching | Module-level singleton (`_encryption_key` cached after first load) |
| IV/nonce | 12-byte random nonce prepended to each ciphertext |
| Storage format | `nonce (12B) \|\| ciphertext` stored as PostgreSQL `BYTEA` |
| Library | `cryptography.hazmat.primitives.ciphers.aead.AESGCM` |

### PHI Columns (all `BYTEA`)

| Model | Encrypted Columns |
|---|---|
| `Patient` | `name_token`, `dob_token`, `phone_token`, `email_token` |

### Lookup Strategy

Patient identity lookups use a **SHA-256 hash** of `normalize(name)|dob` stored in `name_dob_hash`. This allows indexed DB queries without decrypting all rows. On hash collision, each candidate row is decrypted and verified in application code.

### What Is NOT Encrypted

- `booking.slot_start/end`, `provider.display_name`, `clinic.name` — not classified as PHI under the current model
- `CallLog` — intentionally PHI-free; stores no patient identifiers

---

## 8. External Service Integrations

### 8.1 Retell AI

| Aspect | Detail |
|---|---|
| Role | Voice AI engine — runs conversations and makes tool calls back to this API |
| Clinic routing | `ClinicIntegration.retell_agent_id` maps each Retell agent to a clinic |
| Tool protocol | HTTP POST with JSON body; response is JSON structured tool result |
| Webhook auth | HMAC-SHA256 of raw body using `RETELL_WEBHOOK_SECRET`; `hmac.compare_digest` |
| Test bypass | `call_id == "playground"` or `call_id.startswith("test_")` skip signature check |
| Hold cleanup | `call_ended` webhook cancels all unconfirmed tentative holds for that call |

### 8.2 Google Calendar API v3

| Aspect | Detail |
|---|---|
| Role | Per-provider appointment event store; source of truth for external blocking |
| Auth | Service account JSON per clinic (`ClinicIntegration.google_service_account_json`) |
| Credential format | File path string or raw JSON string (auto-detected) |
| Concurrency | `ThreadPoolExecutor(max_workers=10)` bridges sync API to async app |
| Event metadata | Extended properties: `source=callcenter_ai`, `booking_id`, `clinic_id`, `reminded` |
| Blocking detection | Events without `source=callcenter_ai` extended property AND matching appointment keywords are treated as external blocks |
| Graceful degradation | All GCal operations wrapped; booking creation / cancellation succeeds even if Calendar API is unavailable |

### 8.3 Azure OpenAI

| Aspect | Detail |
|---|---|
| Status | **Configured but not active** |
| Config vars | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT_NAME` |
| Library | `openai==1.3.0` |
| Current usage | No call sites exist in application code |

### 8.4 Redis

| Aspect | Detail |
|---|---|
| Status | **Configured but not active** |
| Config | `REDIS_URL` env var; `redis:7-alpine` service in dev compose with AOF persistence |
| Library | `redis==5.0.1` |
| Current usage | No Redis client instantiated in application code |

### 8.5 NextGen EHR (Planned)

| Aspect | Detail |
|---|---|
| Status | **Proof-of-concept only** — `agentql-test/click-test.js` |
| Mechanism | Playwright connects via Chrome DevTools Protocol (CDP); AgentQL queries page elements by natural language |
| PRD direction | Architecture v3.2 declares a full pivot to EHR-native scheduling (replacing GCal) |
| Implementation | 0% complete |

---

## 9. Background Jobs & Workers

### 9.1 Tentative Booking Reaper

| Aspect | Detail |
|---|---|
| Status | **Logic implemented, not scheduled** |
| Functions | `get_expired_tentative_bookings()`, `expire_booking()` in `services/booking.py` |
| Trigger | Should run periodically (e.g., every minute) to expire `TENTATIVE` bookings past `hold_expires_at` |
| Current fallback | `call_ended` webhook handles cleanup for calls that complete normally |
| Index | `idx_status_hold_expires (status, hold_expires_at)` already exists |
| Missing piece | No APScheduler / Celery / asyncio background task wiring exists |

### 9.2 HEDIS Campaign Worker (Planned)

Per `HEDIS_CAMPAIGN_IMPLEMENTATION.md`:

| Component | Status |
|---|---|
| Google Sheets sync (contact list polling) | Not implemented |
| Outbound call dispatcher (Retell API) | Not implemented |
| WebSocket connection manager (Chrome Extension relay) | Not implemented |
| AgentQL-based NextGen EHR scraping | Not implemented |

### 9.3 Call Hold Release (Active — via Webhook)

The `POST /retell/webhook/call_ended` handler performs an in-request cleanup of all unconfirmed tentative bookings associated with the ended call. This is the only active hold-expiry mechanism.

---

## 10. Containerization & Deployment

### 10.1 Dockerfile

```
Base:       python:3.11-slim
System:     libpq-dev, gcc (for psycopg2 build)
User:       non-root appuser (UID 1000)
Workdir:    /app
Expose:     8000
Healthcheck: GET http://localhost:8000/health  every 30s, 3 retries, 10s start
Entrypoint: ./start.sh
```

### 10.2 `start.sh` — Container Entrypoint

```bash
1. Poll DB_HOST:DB_PORT every 2s until reachable (up to 30 attempts)
2. alembic upgrade head
3. uvicorn Clinic_app.main:app \
     --host 0.0.0.0 \
     --port $APP_PORT \
     --workers $APP_WORKERS
```

### 10.3 Docker Compose Configurations

#### Production (`docker-compose.yaml`)
- Single `app` service
- External PostgreSQL (Azure) — not managed by compose
- `restart: unless-stopped`
- JSON-file log driver (10 MB / 3 files)
- `APP_ENVIRONMENT=production`

#### Development (`docker-compose.dev.yaml`)
- `app` service with source volume mount → live reload
- `postgres:15-alpine` with named volume (`callcenter_pgdata`)
- `redis:7-alpine` with AOF persistence (`callcenter_redis_data`)
- Optional `migrate` profile for manual migration runs
- Internal bridge network `callcenter-network`

### 10.4 CI/CD

**None exists.** No GitHub Actions, Azure Pipelines, or other CI/CD configuration is present in the repository.

---

## 11. Testing

### Configuration (`pytest.ini`)

```ini
asyncio_mode = auto
testpaths = tests
markers:
  unit        — no external dependencies
  integration — requires DB / external services
  slow        — long-running tests
```

### Test Coverage by Module

| Test File | What It Covers |
|---|---|
| `test_encryption.py` | AES-256-GCM encrypt/decrypt, key loading, nonce uniqueness |
| `test_patient.py` | `find_patient` (hash lookup + collision defense), `create_patient` (validation + encryption) |
| `test_booking.py` | Tentative → confirm → cancel → expire lifecycle; capacity enforcement; hold expiry |
| `test_availability.py` | Slot generation; GCal merge; double-counting prevention; `check_and_offer_alternatives` |
| `test_retell.py` | Tool call endpoints; webhook signature verification; hold release on `call_ended` |
| `test_admin.py` | Clinic setup; CRUD; business hours; booking management |
| `test_provider.py` | Provider CRUD; `block-time` / `unblock-time` |
| `test_google_calendar.py` | `GoogleCalendarService` CRUD; retry logic; graceful degradation |

---

## 12. Known Architectural Gaps

### 12.1 Router Registration

`admin_router`, `retell_router`, and `provider_router` are fully implemented in `Clinic_app/Routes/` but are **not included** in `main.py`. The live application serves only `/`, `/health`, and `/ping`.

**Fix:** Add `app.include_router(...)` calls in `main.py` for all three routers.

### 12.2 Reaper Worker Not Scheduled

`get_expired_tentative_bookings()` + `expire_booking()` exist and are index-backed, but nothing calls them on a schedule. Expired holds accumulate until the `call_ended` webhook fires.

**Fix:** Wire a background task using `asyncio`, APScheduler, or a lightweight Celery beat schedule to call the reaper every 60 seconds.

### 12.3 Redis Not Used

`redis==5.0.1` is in requirements and the service runs in dev, but no Redis client is instantiated anywhere. Likely planned for distributed locking (double-booking prevention under load) or rate limiting.

### 12.4 Azure OpenAI Not Used

`openai==1.3.0` and four Azure env vars are configured but have zero call sites. Presumably planned for NLU fallback, summarization, or HEDIS campaign scripting.

### 12.5 Architecture Pivot (PRD v3.2 vs Current Code)

The PRD declares a pivot to **EHR-native scheduling** via NextGen EHR + AgentQL Chrome Extension + WebSocket relay. The current implementation is 100% Google Calendar-based. The `agentql-test/click-test.js` is a proof-of-concept only. HEDIS campaign implementation is 0% complete.

### 12.6 No Authentication on Admin Routes

The `/admin/` endpoints have no authentication layer — no API key header, no JWT, no OAuth. Any network-reachable caller can create, read, or delete clinic data.

**Fix:** Add an API key dependency (at minimum) or Azure AD / OAuth2 token validation before any admin route is exposed to a non-local network.

### 12.7 `CallState` Enum Unused

`CallState` (values: `greeting`, `intent_detection`, `booking_info`, `confirmation`, `completed`, `error`) is defined in `data/enums.py` and alluded to in the PRD's call state machine design, but is never referenced in route or service code.

### 12.8 Hardcoded Mon–Fri Business Days

`availability.py` skips weekends unconditionally. There is no per-clinic or per-provider day-of-week configuration. Clinics that operate on weekends will silently return no slots for Saturday/Sunday.

---

*Document reflects codebase state as of March 18, 2026. Re-run the codebase exploration to keep this current after major changes.*
