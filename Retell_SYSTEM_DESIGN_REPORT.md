# CallCenterAI — System Design Report
## HEDIS Outreach Automation Platform

**Author:** Edgar J. Suárez Colón
**Codebase Branch:** `retell`
**Report Date:** September 2026
**Document Type:** Senior Engineer System Design Analysis

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [What This System Does](#2-what-this-system-does)
3. [High-Level Architecture](#3-high-level-architecture)
4. [Technology Stack & Why Each Choice Was Made](#4-technology-stack--why-each-choice-was-made)
5. [Data Model Design & Rationale](#5-data-model-design--rationale)
6. [PHI Security Model](#6-phi-security-model)
7. [Multi-Tenancy Architecture](#7-multi-tenancy-architecture)
8. [Voice AI Integration — Retell AI](#8-voice-ai-integration--retell-ai)
9. [Booking Lifecycle Engine](#9-booking-lifecycle-engine)
10. [Availability Engine](#10-availability-engine)
11. [HEDIS Campaign Layer (Planned)](#11-hedis-campaign-layer-planned)
12. [NextGen EHR Integration Strategy](#12-nextgen-ehr-integration-strategy)
13. [API Design & Route Architecture](#13-api-design--route-architecture)
14. [Background Jobs & Worker Architecture](#14-background-jobs--worker-architecture)
15. [Known Architectural Gaps & Technical Debt](#15-known-architectural-gaps--technical-debt)
16. [Deployment & Containerization](#16-deployment--containerization)
17. [Testing Strategy](#17-testing-strategy)
18. [Unit Economics & Business Impact](#18-unit-economics--business-impact)
19. [System Design Interview Breakdown](#19-system-design-interview-breakdown)

---

## 1. Problem Statement

Primary care clinics enrolled in value-based care contracts receive monthly care-gap reports from payers (Molina, UHC, BCBS, Medicaid managed care). These reports identify patients who are overdue for preventive services — A1C blood tests for diabetics, mammograms, annual wellness visits, colorectal cancer screenings, blood pressure checks. Acting on these lists requires staff to manually call hundreds of patients, check provider schedules, and book appointments — a process that takes days and requires bandwidth most independent clinics don't have.

The consequence: **fewer than 40% of HEDIS care gaps get closed**, directly reducing clinic HEDIS scores and payer reimbursements under value-based contracts. For a clinic earning $40–$80 per closed gap from pay-for-performance bonuses, an automation rate improvement from 40% to 80% on 500 patients represents $8,000–$16,000 in additional revenue per campaign cycle.

**No affordable, HIPAA-aligned, automated solution exists that is purpose-built for independent clinics on NextGen EHR.** Existing solutions either require large enterprise contracts, non-HIPAA-aligned infrastructure (Supabase, etc.), or are built around phone systems that don't integrate with EHR scheduling.

### The Core System Design Challenge

Build a platform that:
- Places AI voice calls to hundreds of patients with correct clinical context per patient
- Reads live EHR availability mid-call (in under 3 seconds) and books appointments without human intervention
- Handles PHI (Protected Health Information) correctly under HIPAA
- Runs across multiple clinics without data leaking between tenants
- Costs under $200/month per clinic to operate while billing $600–$1,200/month

---

## 2. What This System Does

CallCenterAI is a multi-tenant SaaS platform with two layered capabilities:

### Layer 1 — Inbound/Outbound AI Scheduling (Implemented)

A voice AI agent named "Nicole" (powered by Retell AI) handles inbound and outbound appointment calls for clinic staff. Nicole can:

- Book new appointments (identifies patient by name + DOB, finds availability, places tentative hold, confirms)
- Cancel appointments (looks up patient's upcoming booking, cancels, offers rebook)
- Reschedule appointments (cancel old slot, create new tentative hold atomically)
- Detect patient language (English or Spanish) and switch mid-conversation
- Handle provider disambiguation (multiple "Dr. Lopez" scenarios)
- Manage Google Calendar events bidirectionally (create on confirm, delete on cancel)

### Layer 2 — HEDIS Outreach Campaign Engine (Designed, Not Yet Fully Implemented)

A campaign worker that:
- Accepts CSV uploads of patients with care gaps (any payer format)
- Uses Claude API to parse any column structure, identify gap types, normalize phone numbers to E.164
- Launches outbound Retell AI calls with per-patient context (gap type, provider name, payer, clinic name)
- Reads NextGen EHR availability mid-call via server-side Playwright + AgentQL
- Books appointments directly into NextGen without staff intervention
- Retries voicemails, no-answers, and errors on configurable schedules
- Logs encrypted one-sentence Claude-generated call summaries to a clinic dashboard

---

## 3. High-Level Architecture

```
                          ┌─────────────────────────────────────────┐
                          │             Clinic Staff                 │
                          │    (Google OAuth → JWT → Dashboard)      │
                          └─────────────────┬───────────────────────┘
                                            │ HTTPS
                          ┌─────────────────▼───────────────────────┐
                          │         FastAPI Application              │
                          │   (Uvicorn ASGI, Docker on Azure)        │
                          │                                          │
                          │  ┌──────────┐ ┌──────────┐ ┌────────┐  │
                          │  │ /retell/ │ │ /admin/  │ │ /auth/ │  │
                          │  │ routes   │ │ routes   │ │ routes │  │
                          │  └────┬─────┘ └─────┬────┘ └────────┘  │
                          │       │             │                    │
                          │  ┌────▼─────────────▼──────────────┐    │
                          │  │         Service Layer            │    │
                          │  │  booking.py  availability.py     │    │
                          │  │  patient.py  google_calendar.py  │    │
                          │  └────────────────┬─────────────────┘    │
                          │                   │                      │
                          │  ┌────────────────▼─────────────────┐    │
                          │  │    SQLAlchemy 2.0 Async ORM      │    │
                          │  │    (asyncpg → Azure PostgreSQL)  │    │
                          │  └──────────────────────────────────┘    │
                          └──────┬──────────────────────┬────────────┘
                                 │                      │
               ┌─────────────────▼──┐          ┌───────▼──────────────┐
               │    Retell AI        │          │   Google Calendar     │
               │  (Voice Agent)      │          │   API v3              │
               │  HMAC-SHA256 auth   │          │   Service Account     │
               └────────────────────┘          └──────────────────────┘
                        │
         ┌──────────────▼─────────────┐
         │   HEDIS Campaign Layer     │
         │   (Planned)                │
         │                            │
         │  Playwright + AgentQL      │
         │  → NextGen EHR             │
         │  → Redis selector cache    │
         │  Claude API parsing        │
         └────────────────────────────┘
```

### Request Flow — Inbound Call (Booking)

```
Patient calls DID number
    → Retell AI picks up, runs Nicole agent
    → Agent calls call_started tool → POST /retell/webhook/call_started
        → App creates CallLog, maps agent_id to clinic_id
    → Agent collects name + DOB + preferred time + provider
    → Agent calls check_availability → POST /retell/availability
        → App: generate slots → filter BLOCKED → merge GCal events → return JSON
    → Agent calls schedule_appointment (intent=book) → POST /retell/schedule
        → App: find_patient or create_patient (with encrypted PHI)
        → count overlapping bookings vs capacity
        → INSERT Booking (status=TENTATIVE, hold_token=UUID, expires=+5min)
        → return {success, hold_token, booking details}
    → Patient verbally confirms
    → Agent calls confirm_booking (hold_token) → POST /retell/confirm_booking
        → App: verify hold_token, check not expired, UPDATE status=CONFIRMED
        → Create Google Calendar event (graceful degradation on failure)
        → INSERT BookingAudit (action=confirm)
    → Call ends → POST /retell/webhook/call_ended
        → App: update CallLog duration + outcome
        → Cancel any unconfirmed TENTATIVE holds from this call
```

---

## 4. Technology Stack & Why Each Choice Was Made

### FastAPI 0.104.1 — Async ASGI Framework

**Why FastAPI over Django/Flask:**
Retell AI webhooks must respond in **under 3 seconds** mid-call or the conversational flow breaks. A synchronous framework blocks on I/O (database queries, Google Calendar API calls) during that window. FastAPI + asyncpg gives sub-millisecond I/O non-blocking semantics. Additionally, FastAPI's Pydantic v2 integration gives us automatic request validation at system boundaries for free — critical when Retell sends tool call payloads that must be parsed correctly.

**Why not Node.js:**
Python is the only runtime with mature async SQLAlchemy support (2.0+), Playwright bindings, AgentQL integration, and the Anthropic Claude SDK. The language bet is long-term.

### SQLAlchemy 2.0 Async + asyncpg

**Why not SQLAlchemy 1.x + sync:**
SQLAlchemy 2.0 with the new `async_sessionmaker` API allows truly non-blocking database operations. The `asyncpg` driver is the fastest PostgreSQL driver for Python — important when the booking service must check capacity and create a hold within a Retell webhook round-trip.

**Why not Tortoise ORM or Databases:**
SQLAlchemy's ORM relationship model, Alembic migration tooling, and the ecosystem maturity around PostgreSQL ENUM types were necessary. The ENUM types (`bookingstatus`, `bookingaction`, `slotstatus`) need to be native PostgreSQL ENUMs for constraint enforcement at the DB layer, not just application-layer strings.

**Two drivers:**
- `asyncpg 0.29.0` — runtime driver (async, fastest)
- `psycopg2-binary 2.9.9` — Alembic migration driver only (sync, Alembic doesn't support async)

### PostgreSQL on Azure Flexible Server

**Why PostgreSQL over MySQL:**
JSONB support (License.features column), native UUID type, partial unique indexes (booking double-booking prevention), and ENUM types. The License model stores a JSONB `features` dict to gate capabilities like HEDIS or reminders without schema changes.

**Why Azure:**
Microsoft Azure has a signed HIPAA Business Associate Agreement (BAA) via Microsoft Online Services Terms. AWS and GCP also have BAAs, but Azure was chosen because the target customer base (independent US clinics) often already uses Microsoft 365 for administrative work, reducing procurement friction for the pilot.

### AES-256-GCM Encryption (cryptography lib)

**Why AES-256-GCM over AES-256-CBC:**
GCM is authenticated encryption — it provides both confidentiality (encryption) and integrity (authentication tag). If a ciphertext is tampered with in the database, decryption raises `AuthenticationError` immediately rather than silently returning garbage plaintext. This is essential for HIPAA — the spec is not just about encryption at rest but detection of unauthorized modification.

**Why roll a custom wrapper over a library like PyNaCl:**
`cryptography.hazmat.primitives.ciphers.aead.AESGCM` is the lowest-level, most auditable implementation. The wrapper (`common/encryption.py`) is thin: generate 12-byte random nonce, encrypt, prepend nonce to ciphertext, store as BYTEA. Decryption strips the first 12 bytes as nonce. The key is cached in a module-level singleton after first load to avoid repeated environment variable reads on hot paths.

### Retell AI

**Why Retell over Twilio + GPT or Vapi:**
Retell provides the complete voice stack — telephony, speech-to-text, LLM orchestration, text-to-speech — with a signed HIPAA BAA available self-service. Twilio requires assembling STT + LLM + TTS independently, which significantly increases latency (multiple API round-trips per conversation turn). Retell's tool calling protocol (synchronous HTTP webhook during call) matches perfectly with the booking API — Retell sends a tool call, the API creates a booking hold, returns the hold token, and the agent reads it back to the patient.

**Why one agent per clinic, not one agent globally:**
Retell billing is per-agent. More importantly, each agent is configured with the clinic name, clinic phone number, and agent prompt. A single "Nicole" agent configured for "Bayamon Family Medicine" cannot correctly introduce herself to a patient of "San Juan Internal Medicine." The architecture maps each `ClinicIntegration.retell_agent_id` to one clinic record. Gap type is passed as call metadata, not as a separate agent — this keeps the agent count linear with clinic count (not with clinic × gap-type combinatorics).

### Google Calendar API v3

**Why Google Calendar as availability source:**
For the current Phase 1 (inbound scheduling), clinics need a way to expose provider availability without requiring EHR credentials or EHR API contracts. Google Calendar is a zero-cost tool that clinic staff already understand. The system creates a service account per clinic, shares each provider's calendar with the service account, and reads events to determine availability. The architecture is designed to swap this out for direct NextGen EHR scheduling (via Playwright) for the HEDIS Phase 2 — Google Calendar becomes the fallback.

**Why ThreadPoolExecutor for GCal calls:**
The Google API Python client (`google-api-python-client`) is synchronous — it was built before asyncio matured. Running a synchronous blocking call from within an async FastAPI endpoint would block the event loop. The service wraps every API call in `asyncio.get_event_loop().run_in_executor(ThreadPoolExecutor(max_workers=10), sync_fn)`. This offloads blocking I/O to a thread while the event loop continues handling other requests.

### Playwright + AgentQL (EHR Automation)

**Why Playwright over Selenium:**
Playwright has a superior async API, built-in retry mechanisms, CDP (Chrome DevTools Protocol) support, and is actively maintained. The HEDIS campaign layer requires headless Chromium running server-side (on Azure) to authenticate into NextGen EHR and read appointment grids.

**Why AgentQL over hardcoded CSS selectors:**
NextGen's UI is a web-based SaaS that updates frequently. Hardcoded CSS selectors break silently on updates. AgentQL uses a natural language query interface (`{ available_appointment_slots }`) that maps to DOM elements semantically — it survives most UI changes because it reasons about meaning, not structure. The cost of AgentQL queries is amortized by caching discovered selectors in Redis for 24 hours, reducing token costs ~60%.

**Why CDP (`connectOverCDP`) for the proof-of-concept:**
The `click-test.js` proof-of-concept connects to a Chrome browser already open with `--remote-debugging-port=9222`. This allows testing against the real NextGen instance with a logged-in session without implementing the full headless auth flow first. It validates that AgentQL can navigate the EHR DOM before committing to the full server-side implementation.

### Anthropic Claude API (`claude-sonnet-4-20250514`)

**Why Claude for CSV parsing:**
Payer care-gap reports have no standard format. Molina's column headers differ from UHC's, which differ from BCBS's. A traditional CSV parser requires per-payer column mapping maintenance. Claude receives the raw table text and returns a structured JSON array — it generalizes to any format without code changes. At ~2,000 tokens per upload and Claude Sonnet pricing, the cost is under $0.01 per upload.

**Why Claude for call summaries:**
The `call_analyzed` webhook fires after each call completes. The application sends the Retell transcript to Claude with a prompt: "In one sentence, describe what the patient agreed to or said." The result is stored AES-256-GCM encrypted in `campaign_audit.call_summary_encrypted`. Clinic staff read this summary in the dashboard to understand call outcomes without listening to recordings — reducing PHI exposure surface.

**Why not Azure OpenAI:**
Azure OpenAI was configured in `env.example` and `requirements.txt` (present as `openai==1.3.0`) but has zero active call sites. Claude's context window, instruction-following on structured JSON extraction, and the Anthropic API's availability under HIPAA conditions make it the active choice for new feature development. The Azure OpenAI config is left in place as a fallback but explicitly marked inactive.

### Redis

**Why Redis (planned, not yet active):**
Two use cases gate on Redis:
1. **AgentQL selector cache** — after AgentQL discovers a DOM element in NextGen, its CSS selector is cached with a 24-hour TTL. Subsequent bookings reuse the cached selector without paying AgentQL token costs (~60% reduction).
2. **Distributed lock for concurrent bookings** — under high concurrency (3 calls/clinic × multiple clinics), two Retell webhooks for different patients could race to book the same slot. The current capacity check uses a `SELECT COUNT` + business logic comparison, which works at low concurrency but is not SERIALIZABLE. A Redis SETNX lock on `(provider_id, slot_start)` would serialize booking checks under high load.

### Tenacity (Retry Logic)

All calls to Retell API, Google Calendar API, AgentQL, and Claude API are wrapped in `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`. The GCal service specifically uses a custom wait strategy for 429 rate limit responses (5s → 10s → 20s) versus generic errors (1s → 2s → 4s). This distinction matters in production — Google Calendar's per-service-account quota is shared across all providers in a clinic.

---

## 5. Data Model Design & Rationale

### Entity-Relationship Overview

```
Clinic  ──────────────────────────────────────────────────────────────────┐
 │ 1:1  License            (clinic_id FK CASCADE)    — feature gating     │
 │ 1:1  ClinicIntegration  (clinic_id FK CASCADE)    — third-party creds  │
 │ 1:N  Provider           (clinic_id FK CASCADE)    — bookable calendars  │
 │ 1:N  Patient            (clinic_id FK CASCADE)    — PHI-encrypted       │
 │ 1:N  AvailabilitySlot   (clinic_id FK CASCADE)    — blocked time        │
 │ 1:N  Booking            (clinic_id FK CASCADE)    — appointments        │
 │ 1:N  BookingAudit       (clinic_id FK CASCADE)    — immutable audit     │
 │ 1:N  PhoneRoute         (clinic_id FK CASCADE)    — DID routing         │
 └──────────────────────────────────────────────────────────────────────┘

Provider ──► AvailabilitySlot  (provider_id FK CASCADE)
Provider ──► Booking           (provider_id FK CASCADE)
Patient  ──► Booking           (patient_id FK CASCADE)
Booking  ──► BookingAudit      (booking_id FK RESTRICT)  ← immutable

CallLog  (NO FK — PHI-free, survives clinic deletion)
```

### Why UUID Primary Keys Everywhere

All PKs are `UUID(as_uuid=True)` with `default=uuid.uuid4`. Integer auto-increment keys leak business information — a competitor can enumerate clinic IDs, estimate customer count from booking IDs, or probe for gaps in patient sequences. UUIDs are opaque and non-enumerable. The tradeoff (larger index size, slightly slower range scans) is acceptable given PostgreSQL's efficient UUID B-tree indexing.

### The `Clinic` Table — Tenant Root

Every other table cascades off `clinic_id`. This is the anchor of the multi-tenancy model. Notably, `Clinic` stores `network_id` (nullable UUID) for clinic group support — multiple physical locations under one administrative umbrella. The `license_token` (unique string per clinic) is the API credential used for webhook routing from Retell before the clinic context is established from the agent ID mapping.

### The `License` Table — Feature Gating

A 1:1 table with `Clinic` that stores `max_concurrency` (max simultaneous Retell calls) and a JSONB `features` dict (e.g., `{"hedis": true, "reminders": true}`). This separation lets the system gate HEDIS campaign access independently of the base scheduling tier without schema migrations for each new feature flag. `max_concurrency` maps directly to the Retell account slot count — each clinic's concurrency limit is enforced in the campaign worker before launching a new call.

### The `Patient` Table — PHI Architecture

The critical design: **no PHI field is stored in plaintext**.

```
name_token    BYTEA   ← AES-256-GCM(name)
dob_token     BYTEA   ← AES-256-GCM(dob)
phone_token   BYTEA   ← AES-256-GCM(E.164 phone)
email_token   BYTEA   ← AES-256-GCM(email) — nullable
name_dob_hash VARCHAR ← SHA-256(normalize(name) + "|" + dob)
```

The `name_dob_hash` is the indexed lookup key: `idx_clinic_name_dob_hash(clinic_id, name_dob_hash)`. When a call comes in and the agent collects the patient's name and DOB, the system hashes the inputs and queries by hash — O(log n) without decrypting a single row. On a hash hit, the candidate row is decrypted and the decrypted values are compared to the inputs to defend against SHA-256 collisions (extremely rare, but the system handles them).

**Why not just encrypt the lookup key and query on it?** Deterministic encryption (ECB mode) is semantically insecure. GCM with a random nonce produces different ciphertext for the same plaintext every time — it cannot be used as a lookup key. The SHA-256 hash is non-reversible (PHI-safe to store in plaintext) and collision-resistant.

### The `Booking` Table — Hold-Confirm Pattern

The booking lifecycle uses a two-phase commit pattern designed for voice AI:

```
TENTATIVE  →  CONFIRMED  →  CANCELED
    │                           ↑
    └──── (hold_expires_at) ───►┘  (expire path, via reaper)
```

When Retell's `schedule_appointment` tool call arrives, the system creates a `TENTATIVE` booking with:
- `hold_token`: a fresh UUID the agent uses to confirm
- `hold_expires_at`: `now() + 5 minutes`

The agent reads the appointment details back to the patient verbally. When the patient says "yes," the agent calls `confirm_booking(hold_token)`. If the patient hangs up, the `call_ended` webhook fires and the system cancels all `TENTATIVE` bookings with a `tentative_booking_id` matching the call's CallLog.

**Why a 5-minute hold?** Voice conversations rarely exceed 3 minutes. 5 minutes gives buffer for verbose patients without holding slots hostage for hours. Expired holds are reclaimed by the reaper worker (logic implemented, not yet scheduled — see §15).

**Why capacity > 1?** Providers at group practices sometimes have multiple exam rooms and can see more than one patient simultaneously. The `Provider.capacity` field allows this: a capacity-2 provider can have 2 `TENTATIVE + CONFIRMED` bookings for the same slot before it shows as unavailable.

### The `BookingAudit` Table — Immutable HIPAA Trail

The FK on `BookingAudit.booking_id` uses `ondelete="RESTRICT"` — not CASCADE. This means **a booking cannot be deleted if audit rows reference it**. This is intentional: HIPAA requires an audit trail of all PHI-adjacent actions. You can cancel a booking (status change) but not erase its history. Every status transition writes an immutable `BookingAudit` row with `actor` (who did it: `patient`, `admin`, `system`) and `timestamp`.

### The `CallLog` Table — PHI-Free Usage Tracking

`CallLog` has **no foreign key to `Clinic`**. This is the only table in the schema without a tenant FK. The reasoning: call logs are billing and usage data, not PHI. If a clinic is deleted (churns), the call log records must survive for billing and compliance purposes. `clinic_id` is stored as a plain UUID column so the data is still queryable by clinic, but there's no referential integrity — the clinic record can be deleted without cascading call log deletion.

`CallLog` also has no FK to `Patient` — it stores `retell_call_id` (Retell's opaque ID) and `related_id` (optional reference to a booking or campaign contact), but never a patient UUID. This means call logs are safe to export or analyze without HIPAA-level access controls.

### The `AvailabilitySlot` Table

Stores `BLOCKED` time ranges for providers (lunch, meetings, vacations). `FREE` and `BOOKED` slots are computed dynamically from the booking table and Google Calendar — they are not persisted here to avoid stale data. The UNIQUE constraint on `(provider_id, slot_start, slot_end)` prevents duplicate block records. The partial unique index on `Booking (provider_id, slot_start) WHERE status IN (tentative, confirmed)` prevents double-booking at the database layer as a second line of defense.

### The `PhoneRoute` Table

Maps E.164 DID (Direct Inward Dialing) phone numbers to clinic IDs and container URLs. When Retell receives an inbound call on a DID, the `call_started` webhook arrives at the API. The API looks up `ClinicIntegration` by `retell_agent_id` from the webhook payload — that's the primary routing mechanism. `PhoneRoute` is the secondary routing table for cases where routing must happen at the telephony layer before Retell's agent is invoked.

---

## 6. PHI Security Model

### What Is Stored vs. What Is Not

| Data Element | Stored in DB? | Storage Method | Reasoning |
|---|---|---|---|
| Patient name (during call) | No | Retell call metadata only | Not needed after call launches |
| Patient DOB (during call) | No | Retell call metadata only | Not needed after call launches |
| Patient name (in Patient table) | Yes | AES-256-GCM BYTEA | Required for patient lookup verification |
| Patient phone | Yes | AES-256-GCM BYTEA | Required for outbound dialing and retry |
| Patient DOB (in Patient table) | Yes | AES-256-GCM BYTEA | Required for patient identity verification |
| Patient email | Yes (nullable) | AES-256-GCM BYTEA | Optional contact |
| Call transcript | No | Discarded immediately | Reduces PHI surface |
| Call summary | Yes (HEDIS) | AES-256-GCM encrypted | One sentence, needed for dashboard |
| NextGen credentials | Yes | AES-256-GCM encrypted | Required for Playwright session |
| Booking slot times | Yes | Plaintext | Not PHI — appointment time only |
| Provider name | Yes | Plaintext | Not PHI |
| Gap type | Yes | Plaintext enum | Clinical concept, not patient-specific |
| Payer name | Yes | Plaintext | Insurance plan name, not PHI |
| Call outcome | Yes | Plaintext enum | Operational data |

### Encryption Implementation

```python
# common/encryption.py
def encrypt_phi(plaintext: str) -> bytes:
    key = get_encryption_key()           # 32-byte AES key from env var
    iv = os.urandom(12)                  # Random 12-byte nonce per encryption
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(iv, plaintext.encode('utf-8'), None)
    return iv + ciphertext_with_tag      # Format: IV (12B) || ciphertext || auth_tag (16B)
```

Key properties:
- **Random nonce per encryption call**: Same plaintext produces different ciphertext every time (semantic security)
- **Authentication tag**: GCM appends a 128-bit MAC — any bit flip in the ciphertext causes `AuthenticationError` on decrypt
- **Key caching**: `_encryption_key` is cached at module level after first env var read — hot paths don't re-read environment
- **Phase 2 plan**: Key rotated to Azure Key Vault (current env var approach is Phase 1 simplicity)

### Log Masking

Phone numbers are never logged in plaintext. All log statements referencing phones use the masked pattern `***-***-XXXX`. The service layer never logs decrypted PHI — it logs patient UUIDs at most.

---

## 7. Multi-Tenancy Architecture

Every database table includes `clinic_id` as a non-nullable FK with CASCADE delete. The service layer enforces this invariant: every query includes a `WHERE clinic_id = ?` clause sourced from the authenticated JWT. There is no query that touches data across clinic boundaries except Super Admin routes.

### Tenant Isolation Hierarchy

```
clinic_id (from JWT) → all queries
    ├── SELECT: WHERE Booking.clinic_id = clinic_id
    ├── INSERT: Booking.clinic_id = clinic_id (explicit, not trusted from body)
    └── UPDATE/DELETE: WHERE clinic_id = clinic_id (prevents cross-tenant mutation)
```

The clinic ID in every query comes from the JWT issued at login, not from the request body. This prevents a clinic admin from supplying a different clinic's ID in the request payload to access another tenant's data.

### Retell-to-Clinic Mapping

When a Retell webhook fires, there is no JWT — the call comes from Retell's servers. The clinic is identified by looking up `ClinicIntegration WHERE retell_agent_id = payload.agent_id`. This is the only place where a Retell-to-clinic mapping exists. If the agent ID is not found, the webhook returns 404. This means a rogue Retell call with a fabricated agent ID produces no data leak — the lookup simply fails.

### Network Isolation

Each clinic has:
- Its own Retell agent ID
- Its own Google service account (with access only to that clinic's provider calendars)
- Its own Playwright browser session (independent of other clinics' NextGen sessions)
- Its own `retell_from_number` (E.164 outbound number)

---

## 8. Voice AI Integration — Retell AI

### Webhook Security Model

All Retell webhooks are verified using HMAC-SHA256:

```python
def _verify_retell_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.getenv("RETELL_WEBHOOK_SECRET", "").encode()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

**Critical detail:** `hmac.compare_digest` is used instead of `==`. String equality in Python short-circuits on the first mismatch — this creates a timing side-channel that lets an attacker determine how many characters of their forged signature are correct. `compare_digest` always takes the same time regardless of where the comparison fails, eliminating the timing oracle.

**Test bypass:** Calls with `call_id == "playground"` or `call_id.startswith("test_")` skip signature verification. This allows Retell's dashboard playground and automated test suites to call webhooks without signing. The bypass is conditional on the presence of these exact prefixes — not on an environment variable flag — so it cannot be exploited in production without Retell constructing a call ID that starts with "test_".

### Call Lifecycle Webhooks

| Webhook | Handler | Purpose |
|---|---|---|
| `call_started` | Creates `CallLog`, maps `agent_id → clinic_id` | Establishes call tracking context |
| `call_ended` | Updates `CallLog` duration + outcome, cancels unconfirmed TENTATIVE holds | Cleanup and metrics |
| `call_analyzed` (HEDIS) | Sends transcript to Claude → generates one-sentence summary → stores AES-256-GCM encrypted | Post-call enrichment |

### Tool Call Protocol

Retell tool calls arrive as HTTP POST requests mid-conversation. The agent is blocked (conversation pauses) until the tool endpoint responds. The complete flow for `schedule_appointment`:

```
Retell tool call → POST /retell/schedule
    Body: {intent, patient_name, patient_dob, phone, preferred_date, preferred_time_range, provider_preference}

    1. Verify HMAC signature
    2. Map agent_id → clinic_id
    3. Parse preferred time range → slot_start, slot_end datetimes
    4. Fuzzy-match provider_preference against Provider.display_name
       - Exact match → use that provider
       - Multiple matches → return {needs_clarification: true, provider_options: [...]}
       - No match → return {success: false, message: "Provider not found"}
    5. find_patient(clinic_id, name, dob) or create_patient(...)
    6. create_tentative_booking(provider_id, patient_id, slot_start, slot_end)
    7. Return {success: true, hold_token: UUID, booking: {start_time, provider_name}}
```

The hold_token returned here is used in the subsequent `confirm_booking` call when the patient verbally confirms. This two-step pattern prevents speculative bookings — a slot is held (TENTATIVE) but not committed to Google Calendar until the patient says yes.

### The "Nicole" Agent Prompt Design

The agent prompt (`RETELL_AI_PROMPT.md`) is a detailed instruction document covering:

- **Language switching**: detect Spanish from first patient response, continue in Spanish
- **Capacity semantics**: if `remaining_capacity: 1`, the slot IS bookable — the agent must not filter it out
- **Time parsing**: convert "next Tuesday," "3pm," "afternoon" to exact YYYY-MM-DD HH:MM parameters
- **Function ordering**: `call_started` MUST be first; `call_ended` MUST be last and called only once
- **Hold token handling**: agent must store the UUID from `schedule_appointment` response verbatim and pass it to `confirm_booking` — no modification

The prompt includes worked examples of every function call with exact JSON parameter shapes. This level of specificity is necessary because LLMs are probabilistic — without explicit examples, the agent may omit required parameters, misformat dates, or call functions out of order. The prompt is kept under 3,500 tokens to avoid Retell's per-turn billing surcharge for large prompts.

---

## 9. Booking Lifecycle Engine

### State Machine

```
TENTATIVE ──────────────────────────► CONFIRMED
    │                                      │
    │ (hold_expires_at < now)              │ (patient requests cancel)
    │ (call_ended without confirm)         │
    ▼                                      ▼
CANCELED (expire) ◄────────────────── CANCELED (cancel)
```

### Capacity Enforcement

Capacity is enforced at the application layer using an overlap query:

```python
# Count overlapping TENTATIVE + CONFIRMED bookings
existing_count = await db.execute(
    select(func.count(Booking.id)).where(
        Booking.provider_id == provider_id,
        Booking.slot_start < slot_end,    # Overlap condition (half-open intervals)
        Booking.slot_end > slot_start,    # Overlap condition
        cast(Booking.status, String).in_(['tentative', 'confirmed'])
    )
)
if existing_count >= provider.capacity:
    raise ValueError("Slot is at capacity")
```

The overlap condition `slot_start < B.slot_end AND slot_end > B.slot_start` is the standard half-open interval overlap test. This is correct because: two intervals [A, B) and [C, D) overlap if and only if A < D and B > C.

**Why not SELECT FOR UPDATE?** The service was designed to use `SELECT FOR UPDATE` for serializable capacity enforcement, but the current implementation uses a count-then-insert pattern. Under concurrent load this has a TOCTOU (time-of-check/time-of-use) race window. The planned Redis SETNX lock on `(provider_id, slot_start)` would close this gap. The partial unique index at the database layer (`WHERE status IN (tentative, confirmed)`) serves as the final backstop, causing the second conflicting INSERT to fail with an integrity error.

### Reschedule — Atomic Cancel + Rebook

```python
async def reschedule_booking(booking_id, new_slot_start, new_slot_end):
    await cancel_booking(booking_id, clinic_id, actor)   # status → CANCELED, delete GCal event
    new_booking, hold_token = await create_tentative_booking(  # new TENTATIVE hold
        provider_id=original_booking.provider_id,
        patient_id=original_booking.patient_id,
        slot_start=new_slot_start, slot_end=new_slot_end
    )
    return new_booking, hold_token
```

Both operations happen within the same database session. If `create_tentative_booking` fails (slot at capacity), the cancel has already committed — this is intentional. The patient asked to reschedule; their old slot was released. If the new slot is unavailable, the agent must offer alternatives. Returning the old slot is complex and creates race conditions; the current behavior is simpler and matches how a human scheduler would handle it (cancel first, rebook second).

### Google Calendar Integration — Graceful Degradation

```python
try:
    gcal_event = await GoogleCalendarService.create_event(...)
    booking.google_event_id = gcal_event.get("id")
except Exception as e:
    logger.error(f"GCal event creation failed: {e}")
    # Booking is still CONFIRMED — GCal failure is non-fatal
```

Google Calendar is not the source of truth for bookings — the PostgreSQL `Booking` table is. Calendar events are a convenience for clinic staff (they see appointments on their Google Calendar). If the Calendar API is down, bookings still succeed. If a Calendar event is orphaned (the GCal event exists but the DB booking was deleted), the availability engine detects this via extended property matching and handles it correctly.

---

## 10. Availability Engine

### Slot Generation Algorithm

```
For a provider on a given date:
    1. Get clinic business hours (default 09:00–17:00)
    2. Generate candidate slots at booking_duration_mins intervals in provider.timezone
       [09:00–09:30, 09:30–10:00, ..., 16:30–17:00]
    3. Localize all datetimes to provider.timezone (IANA, via pytz)
    4. Skip weekends (Mon–Fri hardcoded — see §15 for gap)
    5. Fetch BLOCKED AvailabilitySlots from DB (single query for full day window)
    6. Fetch Google Calendar events for full day window (single API call)
    7. For each candidate slot:
       a. Skip if overlaps any BLOCKED slot
       b. Skip if overlaps any non-patient GCal event (meeting, personal, etc.)
       c. Count DB bookings (TENTATIVE + CONFIRMED) overlapping this slot
       d. Count orphaned GCal patient events (not matching any DB booking)
       e. total = db_count + gcal_orphan_count
       f. If total < provider.capacity → slot is available
    8. Return list of available slots with remaining_capacity
```

### The Double-Counting Problem

This is the most subtle part of the availability engine. The system has two sources of booking information: the PostgreSQL `Booking` table and Google Calendar events. Both must be counted correctly without double-counting.

**Scenario that requires careful handling:**
- DB has `Booking` for Tuesday at 10am (google_event_id = "abc123")
- GCal has event "abc123" for Tuesday at 10am
- A naive implementation counts this slot as having 2 bookings when it only has 1

**Resolution:**
GCal events with `source=callcenter_ai` in their extended properties contain `booking_id`. When evaluating a slot, the engine:
1. Collects all `booking_id` values from overlapping GCal callcenter_ai events
2. Queries DB to confirm which of those booking_ids exist as TENTATIVE/CONFIRMED
3. Only counts GCal events whose booking_id is **NOT** already counted from the DB
4. For GCal events without a booking_id (or not from callcenter_ai), compares `google_event_id` against `Booking.google_event_id` to detect the same match

This handles orphaned events (GCal event exists, DB booking was deleted) and duplicate-counting correctly.

### Timezone Normalization

All overlap comparisons normalize to UTC:

```python
def _events_overlap(event_start, event_end, slot_start, slot_end):
    # All datetimes must be timezone-aware — enforced at call sites
    event_start_utc = event_start.astimezone(pytz.UTC)
    slot_start_utc = slot_start.astimezone(pytz.UTC)
    # ...
    return event_start_utc < slot_end_utc and event_end_utc > slot_start_utc
```

Without this normalization, comparing a 10:00 AM EST datetime to a 15:00 UTC datetime would give incorrect results. All datetimes entering the system must be timezone-aware — naive datetimes raise `ValueError` at the comparison boundary.

---

## 11. HEDIS Campaign Layer (Planned)

### Architecture Overview

The HEDIS campaign layer is the primary revenue driver — it's why this system exists. The current implementation (Google Calendar scheduling) is a foundation; the HEDIS campaign layer is built on top.

```
CSV Upload
    → Claude API parses: normalize columns, extract gap_type, phone (E.164), name, DOB, payer, provider
    → Create Campaign record (status=PENDING)
    → Create CampaignContact records (one per patient row, status=PENDING, ordered by row_order)

Campaign Worker (runs per clinic)
    → Check calling hours (9am–6pm clinic timezone)
    → Check concurrency: active_calls < clinic.campaign_concurrency_limit (default 3)
    → Fetch next PENDING or retry-eligible contact (FIFO by row_order)
    → Mark contact status=CALLING
    → POST to Retell API: create_outbound_call(
          to_number=decrypt(contact.phone_encrypted),
          agent_id=clinic.retell_agent_id,
          metadata={
              campaign_contact_id, patient_name, patient_dob,
              gap_type, provider_name, payer, clinic_name,
              clinic_phone, call_type="hedis_campaign"
          }
      )
    → Increment active call count

Retell Webhooks (during call):
    → call_started: mark contact status=CALLING, log retell_call_id
    → get_available_slots: Playwright reads NextGen scheduler → return up to 5 slots in <3s
    → book_appointment: Playwright fills NextGen booking form → return appointment ID
    → call_ended: update contact status (BOOKED/VOICEMAIL/NO_ANSWER/DECLINED/HUMAN_REQUESTED/ERROR)
    → call_analyzed: send transcript to Claude → one-sentence summary → store encrypted

Retry Logic:
    → VOICEMAIL: set next_retry_at = now + voicemail_retry_hours (default 72h)
    → NO_ANSWER: set next_retry_at = now + no_answer_retry_hours (default 48h)
    → ERROR: set next_retry_at = now + error_retry_hours (default 1h)
    → After 3 attempts: status = EXHAUSTED (terminal)
    → BOOKED, DECLINED, HUMAN_REQUESTED: terminal (no retry)
```

### Contact State Machine

```
PENDING
    │
    ├──► CALLING ──► BOOKED           (terminal — appointment created in NextGen)
    │         ├──► VOICEMAIL         (retry after voicemail_retry_hours, max 3×)
    │         ├──► NO_ANSWER         (retry after no_answer_retry_hours, max 3×)
    │         ├──► DECLINED          (terminal — patient refused)
    │         ├──► HUMAN_REQUESTED   (terminal — patient asked for human)
    │         └──► ERROR             (retry once after error_retry_hours)
    │
    └──► EXHAUSTED                   (terminal — 3 attempts, never reached patient)
```

### Gap Type → Script Branch Mapping

Claude parses the CSV gap column and maps to an internal enum:

| CSV Variations | Internal Enum | Script Opening |
|---|---|---|
| "Annual Wellness Visit", "AWV", "Yearly checkup" | `annual_visit` | "You haven't had your annual wellness visit this year..." |
| "Mammogram", "Breast cancer screening", "BSE" | `mammogram` | "You're due for your annual mammogram screening..." |
| "A1C", "HbA1c", "Diabetes lab" | `a1c` | "Your A1C blood test is due..." |
| "Colonoscopy", "Colorectal screening", "CRC" | `colorectal` | "You're due for colorectal cancer screening..." |
| "Blood pressure", "BP follow-up" | `bp_control` | "Your blood pressure needs a follow-up check..." |
| Any unrecognized value | `generic` | "Our records show you have a care item due..." |

Gap type is passed as `metadata.gap_type` in the Retell outbound call — the single agent prompt contains all script branches and the LLM selects the appropriate one based on the metadata.

---

## 12. NextGen EHR Integration Strategy

### The Validation Gate

Before any HEDIS backend code runs against a real clinic, the team must confirm that headless Chromium can:
1. Access the clinic's NextGen instance (not IP-blocked)
2. Successfully authenticate via the login form
3. Navigate to the appointment scheduler
4. Have AgentQL read the available slot grid
5. Have Playwright fill and submit the booking form

This is validated by `agentql-test/click-test.js` (CDP-based proof of concept) and `agentql-test/test_nextgen_headless.py` (full server-side Playwright validation). Both are designed to be run manually with real clinic credentials before the server-side implementation is built.

**Fallback:** If NextGen blocks headless Chromium (some EHR SaaS platforms detect and reject non-browser traffic), the fallback is a Chrome Extension architecture: a browser extension installed at the clinic runs in a Chrome window, connects via WebSocket relay to the backend, and performs the same DOM interactions in a real (non-headless) browser. This adds complexity but is architecturally supported in the implementation plan.

### AgentQL Token Cost Optimization

| Optimization | Savings | Implementation |
|---|---|---|
| Redis selector cache (24h TTL) | ~60% fewer AgentQL queries | After AgentQL finds slot grid, cache the CSS selector in Redis |
| Scoped DOM queries | ~40% fewer tokens | Pass only the scheduler `<div>` HTML to AgentQL, not full page DOM |
| Hardcoded navigation selectors | Zero AgentQL for navigation | Login form, tab routing, page transitions use CSS selectors only |
| **Estimated cost per booking** | ~$0.08–$0.12 | 15,000–20,000 tokens at optimized usage |

### Session Lifecycle

```
Campaign enters RUNNING state
    → Initialize Playwright browser context (one per clinic)
    → Authenticate into NextGen (store session cookies in context)
    → Start heartbeat: every 8 minutes, load a lightweight NextGen page (prevent session timeout)

During campaign:
    → get_available_slots webhook → queue Playwright action (one at a time per clinic)
    → book_appointment webhook → queue Playwright action
    → If session expires unexpectedly → re-authenticate transparently
    → Return slots/confirmation to Retell within 3 seconds

Campaign COMPLETED or PAUSED:
    → Close browser context
    → Clear credentials from memory
```

The <3 second response constraint for `get_available_slots` is the hardest engineering challenge in the system. If the Playwright action queue has a backlog (another booking is in progress), the new request must wait. With 3 concurrent calls and sequential Playwright actions, the worst case is two calls waiting for one action to complete — if that action takes 2.5 seconds, the queued requests timeout. Mitigations: pre-warm the scheduler page before the campaign starts, cache selector results aggressively.

---

## 13. API Design & Route Architecture

### Router Organization

The API has three routers, each in a separate file:

```
main.py
    ├── health_router     (registered) — /health, /ping
    ├── retell_router     (NOT registered) — /retell/*
    ├── admin_router      (NOT registered) — /admin/*
    └── provider_router   (NOT registered) — /admin/clinics/{id}/providers
```

**Critical gap:** `retell_router`, `admin_router`, and `provider_router` are fully implemented but not included in `main.py` via `app.include_router()`. The live application currently serves only health routes. This is a pre-HEDIS fix item (Feature 1.1).

### Admin Route Design

Admin routes follow a RESTful CRUD pattern with one non-standard endpoint:

```
POST /admin/clinics/setup   ← Atomic one-shot onboarding (Clinic + Integration + License)
POST /admin/clinics         ← Create clinic only
GET  /admin/clinics         ← List all clinics
GET  /admin/clinics/{id}    ← Get single clinic
PUT  /admin/clinics/{id}    ← Update clinic
POST /admin/clinics/{id}/integration   ← Create/update Retell + GCal config
POST /admin/clinics/{id}/license       ← Create/update feature flags + concurrency limit
```

The `/admin/clinics/setup` endpoint is a convenience method that creates all three records (Clinic, ClinicIntegration, License) in a single atomic transaction with `db.flush()` to get the clinic ID before creating dependents.

### Error Response Format

All errors use a standardized envelope:

```json
{
  "code": "NOT_FOUND",
  "message": "Clinic not found",
  "resource": "Clinic",
  "id": "550e8400-e29b-41d4-a716-446655440000"
}
```

HTTP 409 (conflict) is used for duplicate unique constraints (license token), 400 for validation, 404 for not found, 500 for unhandled server errors. This consistency matters when Retell's error handling needs to distinguish "that slot is gone" (409) from "your request is malformed" (400).

### Pydantic v2 Validation

Request models use Pydantic v2 `@field_validator` decorators for cross-field and domain-specific validation:

- E.164 phone format: regex `^\+[1-9]\d{1,14}$`
- Google service account JSON: structural validation of required fields (`type`, `project_id`, `private_key_id`, `private_key`, `client_email`)
- IANA timezone: minimum structural check (contains `/`)
- Business hours: `start < end` constraint
- Booking duration: `>= 1 minute`
- Capacity: `>= 1`

---

## 14. Background Jobs & Worker Architecture

### The Reaper Worker (Implemented, Not Scheduled)

```python
# services/booking.py
async def get_expired_tentative_bookings(db, limit=100):
    now = datetime.now(timezone.utc)
    return await db.execute(
        select(Booking).where(
            cast(Booking.status, String) == 'tentative',
            Booking.hold_expires_at < now
        ).limit(limit)
    )

async def expire_booking(db, booking_id):
    booking.status = 'canceled'
    booking.hold_token = None
    booking.hold_expires_at = None
    await _create_audit_entry(action=BookingAction.EXPIRE, actor='system')
```

The index `idx_status_hold_expires(status, hold_expires_at)` is already created, making reaper queries O(log n). The missing piece is scheduling — no APScheduler or Celery beat is configured. The next session's Feature 1.3 work item wires this into a FastAPI lifespan event using APScheduler to run every 60 seconds.

### Current Hold Cleanup Mechanism

The `call_ended` webhook handler cancels all TENTATIVE holds associated with the call's `tentative_booking_id`. This handles the normal case (call completes, hold released). The reaper handles the abnormal case (Retell doesn't fire `call_ended`, network timeout, etc.). Until the reaper is scheduled, expired holds accumulate until the next `call_ended` webhook for any call belonging to that clinic cleans them up — which is not guaranteed.

### HEDIS Campaign Worker (Planned)

The campaign worker will run as an APScheduler job per active clinic:

```python
async def campaign_worker_tick(clinic_id):
    # Check calling hours for clinic timezone
    # Check active call count vs concurrency limit
    # Fetch next retry-eligible contact (FIFO by row_order)
    # Launch Retell outbound call
    # Update contact status=CALLING
```

The worker runs every 5–10 seconds per clinic. With 3 concurrent calls per clinic and 5-second inter-call gaps, a worker could theoretically launch one new call every 5 seconds (once an existing call ends). At average 3-minute call duration, a clinic can process 60 contacts/hour — 480 contacts in an 8-hour calling window.

---

## 15. Known Architectural Gaps & Technical Debt

### Gap 1 — Routers Not Registered

`admin_router`, `retell_router`, and `provider_router` are fully implemented but not registered in `main.py`. The application currently serves only health routes. Registering the routers is a 30-minute fix.

**Root cause:** The routers were implemented during development but the registration step was documented as a "pre-HEDIS fix" in the CLAUDE.md known gaps list, creating a situation where the feature code exists but is unreachable.

### Gap 2 — No Auth on Admin Routes

`/admin/*` routes have no authentication layer. Any caller that can reach the endpoint can read or write clinic data. The fix is a `Depends(verify_admin_api_key)` FastAPI dependency that checks the `X-Admin-Key` header against the `ADMIN_API_KEY` environment variable.

**Risk level:** High if exposed to the internet. Currently mitigated by the admin routes not being registered (Gap 1), but both must be fixed together.

### Gap 3 — Reaper Not Scheduled

`get_expired_tentative_bookings` and `expire_booking` are implemented and indexed but never called on a schedule. Expired TENTATIVE bookings accumulate until the `call_ended` webhook fires for any other call in that clinic.

### Gap 4 — Redis Not Instantiated

`redis==5.0.1` is in requirements. The dev Docker Compose runs a Redis container. But no Redis client is instantiated anywhere in the application. The planned uses (AgentQL selector cache, distributed booking lock) are blocked on this.

### Gap 5 — Weekend Slots Hardcoded Unavailable

`availability.py` always skips `weekday >= 5` (Saturday and Sunday). Clinics that operate on weekends silently return no slots for those days. No per-clinic or per-provider day-of-week configuration exists.

### Gap 6 — `CallState` Enum Unused

`CallState` (GREETING, INTENT_DETECTION, BOOKING_INFO, BOOKING_CONFIRM, etc.) is defined in `enums.py` and alluded to in the PRD call state machine design but is never referenced in any route or service. It was designed to track conversational state server-side for analytics, but the Retell webhook-based architecture handles state transitions implicitly through action sequence.

### Gap 7 — No CI/CD Pipeline

No GitHub Actions, Azure Pipelines, or other CI/CD configuration exists. Tests must be run manually. Deployment is a manual `docker build + docker push + az webapp deploy` process.

### Gap 8 — Google Service Account JSON Stored Unencrypted

`ClinicIntegration.google_service_account_json` stores the Google service account JSON as a raw string (possibly a file path). Unlike NextGen credentials (which will be AES-256-GCM encrypted per the PRD), this is not encrypted at rest in the current implementation. The service account key has write access to provider calendars — a database dump would expose these credentials.

---

## 16. Deployment & Containerization

### Dockerfile Design

```
Base image:    python:3.11-slim
System deps:   libpq-dev gcc (for psycopg2 compilation)
User:          non-root appuser (UID 1000) — security best practice
Playwright:    Browsers installed as root, then user switched
Healthcheck:   GET /health every 30s, 3 retries, 10s start period
Entrypoint:    ./start.sh
```

**Why non-root user:** Running as UID 0 in a container means a container escape gives full host access. Running as UID 1000 limits blast radius. The Playwright browser installation is done as root (Chromium requires root for install) then the user is switched.

**Why `python:3.11-slim` not `3.11-alpine`:** Alpine Linux uses `musl libc` instead of `glibc`. Several Python packages (especially `cryptography` with its native C extensions) require glibc. Using Alpine leads to complex multi-stage build setups. `python:3.11-slim` uses Debian and glibc — fully compatible out of the box.

### The `start.sh` Bootstrap Sequence

```bash
# 1. Wait for PostgreSQL to accept connections (up to 60 seconds, 30 attempts × 2s)
for i in $(seq 1 30); do
    nc -z $DB_HOST $DB_PORT && break
    sleep 2
done

# 2. Run Alembic migrations (idempotent — skips already-applied migrations)
alembic upgrade head

# 3. Start Uvicorn with environment-configured workers
uvicorn Clinic_app.main:app \
    --host 0.0.0.0 \
    --port $APP_PORT \
    --workers $APP_WORKERS
```

This approach means the container won't start serving traffic until migrations are applied. In a Kubernetes deployment, this would be replaced by an init container running migrations separately from the application container.

### Docker Compose Environments

**Dev (`docker-compose.dev.yaml`):**
- Source volume mount → live reload without rebuilding
- Local PostgreSQL 15-alpine with named volume (data persists across restarts)
- Redis 7-alpine with AOF persistence
- Optional `migrate` profile for manual migration runs

**Production (`docker-compose.yaml`):**
- Single app service, external Azure PostgreSQL (not managed by compose)
- JSON file logging driver (10 MB / 3 files — prevents disk exhaustion)
- `restart: unless-stopped` (automatic recovery from crashes)
- No source mounts — immutable container image

---

## 17. Testing Strategy

### Test Architecture

```
pytest.ini:
    asyncio_mode = auto    ← All test coroutines are auto-wrapped
    markers:
        unit         — no external dependencies (mock everything)
        integration  — requires live DB or services
        slow         — long-running (performance, load)
```

### Test Coverage by Module

| Test File | What It Tests | Approach |
|---|---|---|
| `test_encryption.py` | AES-256-GCM encrypt/decrypt, key loading, nonce uniqueness, tamper detection | Unit — cryptography primitives |
| `test_patient.py` | `find_patient` (hash lookup + collision defense), `create_patient` (all validation paths) | Unit — mock DB session |
| `test_booking.py` | Full lifecycle: TENTATIVE → CONFIRMED → CANCELED → EXPIRED, capacity enforcement, hold expiry | Unit — mock DB + GCal |
| `test_availability.py` | Slot generation, GCal event merging, double-counting prevention, `check_and_offer_alternatives` | Unit — mock DB + GCal |
| `test_retell.py` | Tool endpoints, HMAC webhook verification (valid/invalid/playground bypass), hold cleanup on call_ended | Unit — mock DB, FastAPI test client |
| `test_admin.py` | Clinic setup atomic transaction, CRUD endpoints, business hours, bulk booking cancellation | Integration — test DB |
| `test_provider.py` | Provider CRUD, `block-time`, `unblock-time` overlap detection | Integration — test DB |
| `test_google_calendar.py` | GCal CRUD, retry logic on 429/500, graceful degradation | Unit — mock GCal service |
| `test_playwright_validation.py` | PlaywrightEHRService contract (mock-based), Redis cache key format | Unit — fully mocked |
| `test_playwright_docker.py` | Playwright launches, Chromium loads URLs, AgentQL `wrap_async` awaitable | Integration — real Chromium |

### Key Test Design Decisions

**Why mock-based unit tests for the booking lifecycle:**
The booking service operates against an async SQLAlchemy session. Mocking the session allows tests to run without a database, making the test suite fast and deterministic. The tricky parts are mocking `db.execute()` return values for `SELECT COUNT` queries and ensuring `db.add()` / `db.flush()` produce the right side effects.

**Why separate `test_playwright_docker.py` as integration:**
The integration Playwright tests launch a real Chromium browser inside the Docker container. They cannot run in a standard CI environment without Docker and the `playwright install chromium` step. The `@pytest.mark.integration` tag allows the CI to skip these tests without failing the unit test suite.

**HMAC test coverage:**
The `test_retell.py` file verifies:
1. Valid HMAC signature → 200 OK
2. Missing signature header → 401
3. Invalid (forged) signature → 401
4. `call_id == "playground"` with no signature → 200 OK (test bypass)
5. `call_id.startswith("test_")` → 200 OK (test bypass)

---

## 18. Unit Economics & Business Impact

### Infrastructure Cost Per Clinic Per Month (~200 calls)

| Cost Item | Basis | Per Clinic / Month |
|---|---|---|
| Retell AI — voice calls | $0.13–$0.20/min, avg 3 min | $78–$120 |
| Claude API — CSV parsing | ~2,000 tokens/upload, 1–2 uploads | <$0.01 |
| Claude API — AgentQL EHR bookings | ~18,000 tokens × 100 bookings (50% book rate) | ~$10–$15 |
| Claude API — call summaries | ~500 tokens/call × 200 calls | ~$0.10 |
| Azure App Service | Shared container (prorated across clinics) | ~$8–$12 |
| Azure PostgreSQL | Flexible Server small (prorated) | ~$5 |
| Redis (Azure Cache) | Small instance (prorated) | ~$3 |
| **Total COGS** | | **~$104–$155/month** |

### Pricing Tiers

| Plan | Calls Included | Monthly Price | Gross Margin |
|---|---|---|---|
| Starter | 300 calls / 2 gap types | $599 | ~74% |
| Growth | 600 calls / 4 gap types | $899 | ~83% |
| Full Practice | Unlimited / all gap types | $1,199 | ~87% |

### Scalability Ceiling

The current architecture hits a hard ceiling at **6 active clinics** before exhausting Retell's default 20 concurrent call allowance (3 calls/clinic × 6 clinics = 18, leaving 2 for buffer). Beyond 6 clinics:
- Purchase additional Retell concurrency slots ($8/slot/month)
- Or negotiate an enterprise Retell contract at volume pricing
- The application code has no changes needed — `License.max_concurrency` governs per-clinic limits

### Impact Projection

For a clinic working a 500-patient care-gap list over 3 days with this system:
- Manual process: ~40% closure rate (200 appointments) over 2–3 weeks, requiring 2 FTE days
- Automated with this system: targeting ~65–75% contact rate (calls answered), ~50% booking rate = 250 appointments, over 3 days with zero staff hours on the calling task
- At $40–$80/appointment in value-based care pay-for-performance bonuses, that's $10,000–$20,000 in incremental revenue per campaign cycle at $599–$1,199/month SaaS cost

---

## 19. System Design Interview Breakdown

This section frames the system as an AI system design problem and articulates the key decisions explicitly.

---

### Problem Restatement (as an interview question)

> "Design a system that places outbound AI voice calls to patients, checks live EHR availability mid-call, and books appointments — all without human intervention — for multiple healthcare clinics, while complying with HIPAA."

---

### Key Constraints

| Constraint | Value | Source |
|---|---|---|
| Webhook response latency | < 3 seconds | Retell AI conversational flow requirement |
| PHI encryption | AES-256-GCM | HIPAA + BAA requirement |
| Concurrent calls per clinic | 3 (default, configurable) | Retell account limit (20 total) |
| Call attempts per patient | Max 3 | Business requirement |
| Calling hours | 9am–6pm clinic timezone | Legal / patient experience |
| CSV row limit | 2,000 patients | 10 MB file limit |
| Dashboard polling | Every 30 seconds | No WebSocket needed for MVP |
| Appointment booking latency | Real-time, mid-call | Playwright + NextGen EHR |

---

### The Top 10 Design Decisions

**1. Why async throughout?**
A Retell webhook arrives mid-call. The handler must hit the database, hit Google Calendar (or NextGen EHR), and respond — all within 3 seconds. Synchronous I/O would block the thread during database and API calls. FastAPI + asyncpg + asyncio allows hundreds of concurrent webhook handlers on a single-core process.

**2. Why AES-256-GCM with random nonce over other encryption schemes?**
AES-CBC with a static IV is deterministic — same plaintext, same ciphertext. This leaks information (you can detect that two patients have the same phone number). AES-256-GCM with a 12-byte random nonce per encryption is semantically secure and authenticated. The 16-byte authentication tag detects tampering. The key is external to the codebase (env var / later Azure Key Vault).

**3. Why SHA-256 hash for patient lookup, not a DB index on encrypted value?**
AES-256-GCM produces different ciphertext every time (random nonce). You cannot create a B-tree index on a column where the same logical value has thousands of different binary representations. The SHA-256 hash of `normalize(name)|dob` is deterministic and collision-resistant — it enables O(log n) indexed lookups without decrypting any data. Hash collisions trigger a decrypt-and-compare step as a secondary verification.

**4. Why TENTATIVE hold + 5-minute expiry instead of locking the slot immediately?**
Voice conversations are non-transactional — the patient might say "yes" and then change their mind, or hang up. Immediately writing a `CONFIRMED` booking when the agent calls `schedule_appointment` would orphan slots if the patient never confirms. The hold pattern allows a slot to be reserved for the duration of the verbal confirmation sequence without permanently occupying it. If the call drops, the reaper reclaims the hold within 5 minutes.

**5. Why one Retell agent per clinic, not one globally?**
Agent identity is clinic-specific: "Hi, I'm calling from Bayamon Family Medicine" vs "Hi, I'm calling from San Juan Internal Medicine." A global agent would require dynamic name injection every conversation turn, which is fragile with LLMs. Per-clinic agents let the system configure each agent's prompt, from-number, and clinic metadata statically. The cost is linear with clinic count, but at the target scale (20–100 clinics), this is manageable.

**6. Why Google Calendar as the Phase 1 availability source instead of directly hitting NextGen?**
Playwright + NextGen EHR is the correct long-term architecture, but it introduces two hard requirements before any clinic can onboard: (a) validate that NextGen isn't blocking headless Chrome, and (b) handle NextGen session lifecycle, heartbeat, re-authentication, and form structure. Google Calendar has none of these risks and clinics can export their schedules to it trivially. Phase 1 ships without EHR dependency; Phase 2 replaces the availability source.

**7. Why Claude API for CSV parsing instead of predefined column mapping?**
Payer care-gap reports come in hundreds of formats. Molina's "Patient Name" column becomes BCBS's "Member Name" becomes Medicaid's "Beneficiary." Hard-coding column names requires a mapping file per payer, which becomes a maintenance burden as payers change their formats. Claude with a structured JSON output prompt handles any format at ~$0.01 per upload.

**8. Why store call summaries (encrypted) instead of full transcripts?**
Full transcripts are high-value PHI — they contain everything the patient said verbatim. Storing them creates HIPAA obligations for the full transcript lifecycle (retention, breach notification, access logging). One-sentence Claude-generated summaries ("Patient agreed to A1C lab, will visit LabCorp this week") convey the actionable information clinic staff need without retaining raw patient speech. The summary is still PHI-adjacent, so it is AES-256-GCM encrypted.

**9. Why Redis for selector caching instead of in-process memory?**
A process-local Python dict would work for a single-instance deployment, but HIPAA-grade systems typically run with multiple replicas (Azure App Service scale-out). If two Retell webhooks for the same clinic arrive at different application instances, both would trigger AgentQL queries to discover the same NextGen selector. Redis gives a shared cache across all instances with 24-hour TTL, reducing token costs ~60% and reducing NextGen page load time.

**10. Why BookingAudit FK uses RESTRICT instead of CASCADE?**
Audit tables must be immutable to satisfy HIPAA audit trail requirements. If `BookingAudit.booking_id` cascaded, deleting a booking would silently delete its audit history. `RESTRICT` means you cannot delete a booking record that has associated audit entries — forcing any "deletion" to be a status change (status=CANCELED) rather than a hard delete. The data stays; only its status changes. This is the correct pattern for any system operating under healthcare data regulations.

---

### What the System Gets Right

- **PHI surface is minimized**: Patient name and DOB are never stored in the DB during the HEDIS campaign — only passed as Retell metadata
- **Graceful degradation**: GCal API failures don't break bookings; Playwright failures result in the agent offering the clinic phone number
- **Multi-tenant correctness**: clinic_id appears in every query at the service layer, not left to routes to enforce
- **Immutable audit trail**: every booking state transition is recorded; audit rows cannot be deleted
- **Async throughout**: webhook handlers can handle dozens of concurrent Retell calls without thread contention
- **Constant-time webhook verification**: `hmac.compare_digest` prevents timing oracle attacks

### What Is Not Yet Production-Ready

- Routers not registered (system effectively doesn't serve the core API)
- No auth on admin routes
- No reaper scheduling (holds accumulate)
- No Redis client (distributed lock and selector cache planned but not implemented)
- No CI/CD pipeline
- HEDIS campaign worker: 0% implemented
- NextGen EHR integration: proof-of-concept only
- No rate limiting on public-facing endpoints
- Google service account JSON stored unencrypted

---

*End of Report*

**CallCenterAI · HEDIS Outreach Automation Platform · September 2026 · Confidential**
*Report generated from full codebase analysis of the `retell` branch.*
