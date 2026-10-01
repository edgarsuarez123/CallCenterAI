# HEDIS Outreach Automation Platform
## Product Requirements Document — v2.0 (Detailed MVP)

**CallCenterAI · March 2026 · CONFIDENTIAL · Built on FastAPI / Azure**

---

| Field | Detail |
|---|---|
| Document Version | 2.0 — Detailed MVP (Final) |
| Author | Edgar J. Suárez Colón |
| Date | March 2026 |
| Codebase | CallCenterAI / Clinic_app (FastAPI 0.104+) |
| Primary EHR | NextGen (web-based SaaS login) |
| Voice Platform | Retell AI (HIPAA BAA, self-service) |
| Hosting | Microsoft Azure (HIPAA BAA via MOSA) |
| LLM | Anthropic Claude API (`claude-sonnet-4-20250514`) |
| Auth | Google OAuth 2.0 (staff) + API Key (admin routes) |
| Compliance Status | MVP pilot — informal HIPAA alignment; BAA with clinic deferred post-pilot |
| Target Market | Mainland US primary care clinics (NextGen EHR) |
| Pilot Clinic | 1 known clinic — pre-existing relationship |

---

## Table of Contents

1. [Purpose & Scope](#1-purpose--scope)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Users & Roles](#4-users--roles)
5. [Authentication & Authorization](#5-authentication--authorization)
6. [Multi-Tenancy & Clinic Isolation](#6-multi-tenancy--clinic-isolation)
7. [Patient List Upload & Parsing](#7-patient-list-upload--parsing)
8. [Campaign Architecture](#8-campaign-architecture)
9. [Retell AI Voice Agent Specification](#9-retell-ai-voice-agent-specification)
10. [NextGen EHR Integration — Playwright + AgentQL](#10-nextgen-ehr-integration--playwright--agentql)
11. [PHI Security Model](#11-phi-security-model)
12. [Database Schema — New & Modified Tables](#12-database-schema--new--modified-tables)
13. [API Endpoints](#13-api-endpoints)
14. [Clinic Dashboard](#14-clinic-dashboard)
15. [Pre-HEDIS Fixes — Existing Codebase](#15-pre-hedis-fixes--existing-codebase)
16. [Implementation Plan — 5 Weeks](#16-implementation-plan--5-weeks)
17. [Unit Economics](#17-unit-economics)
18. [Risks & Mitigations](#18-risks--mitigations)
19. [Open Items — Resolve During Pilot](#19-open-items--resolve-during-pilot)
20. [Appendix — Codebase Reuse Map](#20-appendix--codebase-reuse-map)

---

## 1. Purpose & Scope

This document defines the complete technical and product requirements for the HEDIS Outreach Automation Platform MVP. It supersedes PRD v1.0 and incorporates decisions from a full architecture review session covering authentication, multi-tenancy, campaign logic, EHR integration, voice agent behavior, concurrency, PHI handling, and monitoring.

The system automates outbound HEDIS care-gap campaigns for independent primary care clinics. It reads a patient list uploaded as CSV or Excel, places AI voice calls via Retell AI in English or Spanish (auto-detected), checks real-time NextGen EHR availability mid-call via server-side Playwright, books appointments with the patient's primary care provider, and logs outcomes back to the EHR and the clinic dashboard — with no manual staff involvement after upload.

---

## 2. Problem Statement

Primary care clinics enrolled in value-based care contracts receive monthly care-gap reports from payers (Molina, UHC, BCBS, Medicaid managed care). These lists contain patients who are overdue for preventive services. Acting on them manually requires significant staff bandwidth most clinics do not have. The result: fewer than 40% of care gaps get closed, directly reducing HEDIS scores and payer reimbursements.

No affordable, HIPAA-aligned, automated solution exists that is purpose-built for independent clinics on NextGen EHR. This platform fills that gap.

---

## 3. Goals & Non-Goals

### 3.1 MVP Goals

- Multi-clinic SaaS architecture from day one — isolated data per clinic and per location
- Google OAuth staff authentication with per-clinic access control and clinic selector
- CSV/Excel upload via drag-and-drop dashboard — no Google Workspace dependency
- Claude API parses any payer format, identifies gap types per row, routes to correct call script
- Retell AI outbound calling — one agent per clinic with gap-type-aware instructions
- Auto language detection — agent switches English/Spanish based on patient response
- Server-side Playwright + AgentQL for NextGen availability read and appointment booking
- Primary care provider matching — book with patient's own provider, offer alternatives if unavailable
- Concurrent campaigns per clinic — multiple gap types run simultaneously, shared worker pool
- Real-time dashboard with patient-level call outcomes visible to clinic staff
- Clinic selector screen for staff members belonging to multiple clinic locations
- Flat monthly SaaS pricing — metered by call volume tier

### 3.2 Deferred (Post-MVP)

- SOAP note generation
- Inbound call handling for patient callbacks
- TCPA do-not-call list checking
- EHR support beyond NextGen
- BAA contract flow built into onboarding (handled manually for pilot)
- Advanced analytics and campaign reporting
- Multi-language beyond English and Spanish
- Puerto Rico / ASES Medicaid HEDIS variant support

---

## 4. Users & Roles

| Role | Who | Access |
|---|---|---|
| Super Admin | You (developer) | All clinics, all campaigns, all configuration, debug tools, manual clinic setup |
| Clinic Admin | Office manager / billing staff | Upload CSV, start campaigns, view all patients and outcomes for their clinic(s) |
| Clinic Staff | Front desk, MA | View campaign status and patient outcomes only — no upload or start controls |
| Provider | Physician (optional read) | View their own patients' campaign outcomes if granted access |

> **NOTE:** All clinic roles are scoped per clinic. A staff member with access to Clinic A cannot see Clinic B data even if on the same Google account.

---

## 5. Authentication & Authorization

### 5.1 Google OAuth 2.0 — Staff Login

- All clinic staff authenticate via Google OAuth 2.0
- On first login, Google account is linked to one or more clinic records by Super Admin
- A staff member can belong to multiple clinic locations
- After OAuth callback, if user belongs to more than one clinic, they land on a **Clinic Selector** screen:
  - Clinic Selector shows list of clinics the user belongs to with clinic name and location
  - User clicks a clinic to enter that clinic's dashboard
  - A back button on the dashboard returns to the clinic selector at any time
- If user belongs to exactly one clinic, they skip the selector and go directly to the dashboard
- JWT issued after clinic selection — scoped to selected `clinic_id`, expires in 8 hours
- Role (`admin` vs. `staff`) stored in `clinic_staff` table and embedded in JWT claims

### 5.2 Admin Route Protection

- All `/admin/*` routes require a static API key header: `X-Admin-Key`
- API key stored in environment variable `ADMIN_API_KEY`
- Super Admin uses this key to create clinics, assign staff, configure NextGen credentials, assign Retell agents

### 5.3 NextGen Credential Setup

Two paths for credential entry during clinic onboarding:

1. **Self-service:** Clinic Admin enters their NextGen URL, username, and password in a secure setup screen — stored AES-256-GCM encrypted in `ClinicIntegration` table
2. **Manual:** Super Admin enters credentials directly via admin endpoint — used for testing and initial pilot

- Super Admin can trigger a credential test from the admin panel — Playwright attempts login and returns pass/fail
- Credentials **never** logged, **never** returned in API responses, **never** stored in plaintext

---

## 6. Multi-Tenancy & Clinic Isolation

- Each physical clinic location is a separate `Clinic` record — HIPAA requires this
- All data tables include `clinic_id` FK — no cross-clinic data access is architecturally possible
- Each clinic has its own: NextGen credentials, Retell agent ID, Playwright browser session, campaign worker pool, calling phone number
- Row-level security enforced at service layer — all DB queries include `clinic_id` filter from JWT
- Super Admin is the only role that can query across clinic boundaries

---

## 7. Patient List Upload & Parsing

### 7.1 Upload Interface

- Clinic Admin drags and drops or file-selects a CSV or Excel (`.xlsx`) file on the dashboard
- File size limit: **10 MB** · Row limit: **2,000 patients** per upload
- File is held in memory only — never written to disk, never stored in blob storage
- After parsing, raw file bytes are discarded immediately

### 7.2 Claude API Parsing

- Claude API (`claude-sonnet-4-20250514`) receives the raw table content as text
- Prompt instructs Claude to identify and extract these fields per row regardless of column naming:

| Field | Description |
|---|---|
| `patient_name` | Full name — used as Retell call metadata only, **never stored in DB** |
| `phone` | Any format, normalized to E.164 on extraction |
| `gap_type` | Mapped to internal enum (see Section 7.3) |
| `payer` | Insurance plan name, stored as string |
| `dob` | Date of birth — used as Retell call metadata only, **never stored in DB** |
| `provider_name` | Patient's primary care provider name, used for NextGen provider lookup |

- Claude returns structured JSON array — one object per patient row
- If a row is missing `phone` or `gap_type`, it is flagged as unparseable and skipped — logged for admin review
- Estimated token cost per upload: 1,000–4,000 tokens (~$0.002–$0.01) — negligible
- Upload goes directly to campaign creation — no preview screen shown to clinic

### 7.3 Gap Type Mapping

| CSV Gap Type Variations (examples) | Maps To | Retell Script Used |
|---|---|---|
| Annual Wellness Visit, AWV, Yearly checkup, Preventive visit | `annual_visit` | Annual wellness visit script |
| Mammogram, Breast cancer screening, BSE, Breast exam | `mammogram` | Mammogram outreach script |
| A1C, HbA1c, Diabetes lab, Blood sugar test, Hemoglobin A1C | `a1c` | Diabetes A1C script |
| Colonoscopy, Colorectal screening, CRC, Colon cancer screen | `colorectal` | Colorectal screening script |
| Blood pressure, BP follow-up, Hypertension check | `bp_control` | BP control script |
| Any unrecognized value | — | Row skipped — parse error on upload (see §21) |

---

## 8. Campaign Architecture

### 8.1 Campaign Creation

- One `Campaign` record is created per upload — associated to `clinic_id`
- Campaign name auto-generated: `'{Payer} HEDIS Upload — {date}'`
- A clinic can have multiple active campaigns simultaneously (e.g. mammogram + A1C running at same time)
- All active campaigns share the clinic's worker pool — callers are processed in row order across all campaigns
- Campaign states: `PENDING` → `RUNNING` → `PAUSED` → `COMPLETED` | `FAILED`

### 8.2 Worker Pool & Concurrency

Retell AI accounts on Pay-As-You-Go include **20 concurrent calls**. Additional slots cost **$8/month** each. The system enforces a per-clinic concurrency limit to protect both the Retell account limit and the clinic's NextGen session.

| Parameter | Value | Rationale |
|---|---|---|
| Default concurrent calls per clinic | 3 | Conservative — leaves headroom for Retell account limit across multiple clinics |
| Configurable per clinic | Yes | Set by Super Admin at onboarding — larger clinics may request higher limits |
| Call ordering | Row order from CSV — FIFO across all active campaigns | Predictable, matches clinic expectation |
| Minimum inter-call gap | 5 seconds between launching calls | Avoid hammering Retell API |
| Calling hours | 9:00 am – 6:00 pm clinic local timezone | Configurable per clinic |
| Max attempts per contact | 3 | After 3 no-answers, status set to `EXHAUSTED` |
| Retry wait — no answer | 48 hours (default) | Configurable per clinic via `no_answer_retry_hours` in `ClinicIntegration` |
| Retry wait — voicemail | 72 hours (default) | Configurable per clinic via `voicemail_retry_hours` in `ClinicIntegration` |
| Retry wait — error | 1 hour (default) | Configurable per clinic via `error_retry_hours` in `ClinicIntegration` |

### 8.3 Contact Status State Machine

| Status | Meaning | Next State |
|---|---|---|
| `PENDING` | Loaded from CSV, not yet called | `CALLING` |
| `CALLING` | Retell call currently active | `BOOKED` / `VOICEMAIL` / `DECLINED` / `NO_ANSWER` / `ERROR` |
| `BOOKED` | Appointment confirmed and created in NextGen | Terminal |
| `VOICEMAIL` | Call connected, voicemail left | `PENDING` (retry after configured hours, max 3×) |
| `DECLINED` | Patient explicitly declined appointment | Terminal |
| `NO_ANSWER` | No answer / ring no pickup | `PENDING` (retry after configured hours, max 3×) |
| `EXHAUSTED` | Max attempts reached, never reached patient | Terminal |
| `ERROR` | System error during call or EHR booking | `PENDING` (retry once after configured hours) |
| `HUMAN_REQUESTED` | Patient asked to speak to a human | Terminal — agent ended call gracefully |

---

## 9. Retell AI Voice Agent Specification

### 9.1 Agent Architecture

- One Retell agent per clinic — configured by Super Admin during onboarding
- Agent uses a single multi-intent prompt with `gap_type` passed as call metadata
- Gap type determines which script branch the agent follows — all branches in one prompt
- Agent auto-detects language in first patient response — switches to Spanish if Spanish detected
- Agent identifies itself as calling on behalf of the clinic — does not claim to be a human
- Prompt max length awareness: prompts over 3,500 tokens incur extra Retell billing — keep under

### 9.2 Call Metadata Passed to Retell

| Metadata Field | Value | Used For |
|---|---|---|
| `campaign_contact_id` | UUID from `CampaignContact` table | Webhook correlation — links call back to contact record |
| `patient_name` | From CSV parse — **NOT stored in DB** | Agent addresses patient by name during call |
| `patient_dob` | From CSV parse — **NOT stored in DB** | Agent may confirm identity if needed |
| `gap_type` | Canonical values in §21 / `Clinic_app/data/enums.py` (`GapType`) | Agent selects correct script branch |
| `provider_name` | From CSV parse | Agent tells patient they're scheduling with their provider |
| `payer` | Insurance plan name | Agent may reference payer context in script |
| `clinic_name` | From `Clinic` record | Agent introduces itself as calling from this clinic |
| `clinic_phone` | From `Clinic` record | Agent gives this number if patient requests human |
| `call_type` | `'hedis_campaign'` | Distinguishes HEDIS calls from other call types in webhook handlers |

### 9.3 Gap-Type Script Branches

| Gap Type | Agent Opening | Key Talking Points | CTA |
|---|---|---|---|
| `annual_visit` | Hi, I'm calling from [clinic] on behalf of [provider]... | You haven't had your annual wellness visit this year. It's a short visit covered by your insurance. | Would you like to schedule your annual visit? |
| `mammogram` | Hi, I'm calling from [clinic] regarding your preventive care... | You're due for your annual mammogram screening. Early detection saves lives and it's fully covered. | Can I help you schedule your mammogram? |
| `a1c` | Hi, I'm calling from [clinic] about your diabetes care... | Your A1C blood test is due — it's a quick lab visit, usually 15 minutes, no fasting required. | Would you like to come in for your A1C check? |
| `colorectal` | Hi, I'm calling from [clinic] about your cancer screening... | You're due for colorectal cancer screening. We have multiple options including a simple stool test. | Can I help schedule your screening? |
| `bp_control` | Hi, I'm calling from [clinic] about your blood pressure follow-up... | Your last visit noted your blood pressure needs a follow-up check. It's a quick 20-minute visit. | Would you like to come in for a blood pressure check? |

*Legacy rows above (`annual_visit`, `mammogram`, etc.) are illustrative; the implemented taxonomy is **§21** — there is no `generic` gap type.*

### 9.4 Call Outcome Handling

| Patient Response | Agent Action | System Action |
|---|---|---|
| Yes, I want an appointment | Trigger `get_available_slots` webhook, offer dates | Playwright reads NextGen — returns slots in <3 seconds |
| Picks a slot | Confirm slot, trigger `book_appointment` webhook | Playwright books in NextGen — returns appointment ID |
| No available time works | Offer to call back, give clinic phone number | Status: `DECLINED` — logged with reason |
| I want to speak to a human | "Of course, please call us at [clinic_phone]. Have a great day." | Status: `HUMAN_REQUESTED` — terminal |
| Not interested | "No problem, have a great day." | Status: `DECLINED` — terminal |
| Wrong number | "I'm sorry to have bothered you." | Status: `ERROR` — flagged for manual review |
| No answer / voicemail | Agent leaves scripted voicemail | Status: `VOICEMAIL` — retry after configured hours |
| Speaks Spanish | Agent switches to Spanish mid-call | All subsequent turns in Spanish |

### 9.5 Retell Concurrency Reality Check

> **NOTE:** Pay-as-you-go Retell accounts include **20 concurrent calls**. At 3 concurrent calls per clinic, this platform supports up to **6 active clinics** before hitting the account limit. Additional concurrent slots cost **$8/month** each. At scale, upgrade to higher concurrency tier or enterprise agreement. Budget $8/month per extra slot needed beyond 20.

---

## 10. NextGen EHR Integration — Playwright + AgentQL

### 10.1 Architecture Decision

- Server-side Playwright runs on Azure — nothing installed at clinic
- Playwright connects to NextGen via standard web browser (Chromium headless)
- AgentQL used for dynamic UI elements (slot grids, form fields) — natural language selectors
- Hardcoded Playwright selectors used for stable navigation (login form, known tab structure)
- One persistent authenticated browser context per clinic — maintained for campaign duration

### 10.2 Session Lifecycle

| Event | Action |
|---|---|
| Campaign enters `RUNNING` state | Playwright initializes browser context for clinic, logs into NextGen using encrypted credentials |
| Every 8 minutes | Heartbeat: Playwright loads a lightweight NextGen page to prevent session timeout |
| Session expires unexpectedly | Auto re-authentication using stored credentials — transparent to ongoing calls |
| Concurrent booking requests | Queue — one Playwright action at a time per clinic to avoid NextGen race conditions |
| Campaign `COMPLETED` / `PAUSED` | Browser context closed, session terminated, credentials cleared from memory |
| NextGen unreachable | Agent tells patient to call office directly — status set to `ERROR`, retried after configured hours |

### 10.3 `get_available_slots` Webhook Flow

- Retell fires `POST /retell/tools/get_available_slots` mid-call when patient agrees to schedule
- Payload includes: `campaign_contact_id`, `provider_name`, `gap_type`, `clinic_id` (from call metadata)
- Backend queues Playwright action for that clinic's browser session
- Playwright navigates to NextGen scheduler, selects provider, reads available slots via AgentQL
- **Response must be returned to Retell in under 3 seconds** or call loses conversational flow
- Returns: list of up to 5 available slots formatted as human-readable strings (e.g. `"Tuesday March 24th at 10am"`)
- If provider has no availability in 14 days: agent offers next available provider at same clinic
- If no providers available: agent gives clinic phone number, status set to `CALLBACK_NEEDED`

### 10.4 `book_appointment` Webhook Flow

- Retell fires `POST /retell/tools/book_appointment` when patient selects a slot
- Payload includes: `campaign_contact_id`, `chosen_slot`, `provider_name`, `patient_name`, `patient_dob`, `gap_type`
- Playwright clicks the selected slot in NextGen scheduler
- Playwright fills appointment form: patient name, DOB, appointment type (configured per clinic per gap type), provider
- Playwright submits form — waits for confirmation screen
- Extracts NextGen appointment ID from confirmation — stored in `CampaignAudit`
- Returns confirmation to Retell — agent reads appointment time back to patient

### 10.5 Appointment Type Configuration

- NextGen appointment type codes vary by clinic — configured per clinic per gap type by Super Admin at onboarding
- Stored in a new `ClinicEhrConfig` table: `clinic_id`, `gap_type`, `nextgen_appt_type_code`
- Super Admin enters these during clinic setup — retrieved from clinic's NextGen admin or front desk
- Default fallback: `"Preventive Care Visit"` if no specific code configured

> **Known Unknown:** Pilot clinic will confirm their appointment type codes during onboarding.

### 10.6 Playwright Validation Gate

> **NOTE:** Before any backend development begins — run `agentql-test/click-test.js` against the pilot clinic's NextGen instance. Confirm: headless Chrome is not blocked, login works, AgentQL can read scheduler slots, booking form can be filled and submitted. **If NextGen blocks headless browsers, revert to Chrome Extension architecture.** This test gates all of Week 1.

### 10.7 Token Cost Control for AgentQL

| Optimization | Implementation | Savings |
|---|---|---|
| Cache element selectors | After AgentQL finds a slot grid element, store selector string in Redis. Reuse for 24 hours before re-querying. | ~60% token reduction on repeated bookings |
| AgentQL scope limiting | Pass only the scheduler `div` HTML to AgentQL, not full page DOM | ~40% fewer tokens per query |
| Hardcode stable navigation | Login, tab clicks, page routing use CSS selectors — no AgentQL | Zero tokens for navigation |
| Estimated cost per booking | 15,000–20,000 tokens per EHR booking at optimized usage | ~$0.08–$0.12 per booking |

---

## 11. PHI Security Model

### 11.1 What Is and Is Not Stored

| Data Element | Stored in DB? | How | Rationale |
|---|---|---|---|
| Patient full name | **NO** | Passed as Retell call metadata only | Name is PHI — not needed after call launches |
| Patient DOB | **NO** | Passed as Retell call metadata only | DOB is PHI — not needed after call launches |
| Patient phone | **YES** — encrypted | AES-256-GCM via `encryption.py` | Required for dialing and retry logic |
| Phone hash | **YES** — plaintext | SHA-256 of E.164 number | Deduplication without decrypting |
| Gap type | **YES** — plaintext | Internal enum value only | Not a clinical detail — safe to store |
| Payer name | **YES** — plaintext | Insurance plan name | Not PHI |
| Provider name | **NO** | Passed as Retell metadata and Playwright action param | Not needed persistently |
| Call outcome | **YES** — plaintext | Enum: `BOOKED`/`VOICEMAIL`/etc. | Required for dashboard and retry logic |
| Call summary | **YES** — encrypted | AES-256-GCM in `campaign_audit` | One-sentence Claude-generated summary for clinic dashboard display |
| Patient name (audit) | **YES** — encrypted | AES-256-GCM in `campaign_audit` | Required for dashboard patient table display |
| Appointment ID | **YES** — plaintext | NextGen-generated ID | Audit trail — not PHI |
| Call transcript | **NO (MVP)** | Discarded after summary extracted | Reduces PHI surface — deferred to v1.1 |
| NextGen credentials | **YES** — encrypted | AES-256-GCM in `ClinicIntegration` | Required for Playwright login |
| Call duration | **YES** — plaintext | Integer seconds | Non-PHI, useful for billing |

### 11.2 Encryption

- AES-256-GCM used for all PHI at rest — reuse existing `common/encryption.py`
- `PHI_ENCRYPTION_KEY` in environment variable — never in code or logs
- All logs mask phone numbers: `***-***-XXXX` pattern enforced in logging middleware
- TLS 1.2+ on all external connections — Azure PostgreSQL SSL required (already configured)

### 11.3 HIPAA Posture for Pilot

- **Azure HIPAA BAA:** Covered via Microsoft Online Services Terms — already in effect
- **Retell HIPAA BAA:** Self-service signing — must be completed before pilot goes live
- **Clinic BAA:** Deferred for pilot — one clinic, known relationship, informal agreement
- **Post-pilot:** BAA template created by attorney, signed before onboarding any paying clinic

> **NOTE:** Do not onboard a second clinic without a signed BAA. The pilot exception applies only to the one known clinic.

---

## 12. Database Schema — New & Modified Tables

### 12.1 New Table: `clinic_staff`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK → `clinic` | CASCADE delete |
| `google_sub` | VARCHAR(255) | Google OAuth subject identifier — unique per Google account |
| `email` | VARCHAR(255) | Google account email — display only |
| `role` | ENUM | `clinic_admin` / `clinic_staff` / `provider` |
| `is_active` | BOOLEAN | Default `true` — deactivate without deleting |
| `created_at` | TIMESTAMPTZ | |
| `last_login_at` | TIMESTAMPTZ | Nullable |

### 12.2 New Table: `campaign`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK → `clinic` | CASCADE delete |
| `name` | VARCHAR(255) | Auto-generated: `'{Payer} HEDIS Upload — {date}'` |
| `status` | ENUM | `PENDING` / `RUNNING` / `PAUSED` / `COMPLETED` / `FAILED` |
| `total_contacts` | INTEGER | Count from CSV parse |
| `called_count` | INTEGER | Running count — incremented on `call_started` webhook |
| `booked_count` | INTEGER | Running count — incremented on `BOOKED` outcome |
| `created_at` | TIMESTAMPTZ | |
| `started_at` | TIMESTAMPTZ | Nullable |
| `completed_at` | TIMESTAMPTZ | Nullable |

### 12.3 New Table: `campaign_contact`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `campaign_id` | UUID FK → `campaign` | CASCADE delete |
| `phone_encrypted` | TEXT | AES-256-GCM encrypted phone in E.164 |
| `phone_hash` | VARCHAR(64) | SHA-256 for deduplication |
| `gap_type` | VARCHAR(50) | Internal enum value |
| `payer` | VARCHAR(255) | Insurance plan name |
| `status` | ENUM | See state machine in Section 8.3 |
| `attempt_count` | SMALLINT | Default 0, max 3 |
| `next_retry_at` | TIMESTAMPTZ | Nullable — set on `VOICEMAIL` or `NO_ANSWER` |
| `row_order` | INTEGER | Original CSV row number — determines call order |
| `created_at` | TIMESTAMPTZ | |

### 12.4 New Table: `campaign_audit`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `campaign_contact_id` | UUID FK → `campaign_contact` | |
| `retell_call_id` | VARCHAR(255) | Retell's unique call identifier |
| `outcome` | ENUM | `BOOKED` / `VOICEMAIL` / `DECLINED` / `NO_ANSWER` / `EXHAUSTED` / `ERROR` / `HUMAN_REQUESTED` |
| `ehr_appointment_id` | VARCHAR(255) | Nullable — NextGen appointment ID if booked |
| `appointment_datetime` | TIMESTAMPTZ | Nullable — booked appointment time |
| `provider_booked` | VARCHAR(255) | Nullable — provider name at time of booking |
| `duration_seconds` | INTEGER | Call duration |
| `language_detected` | VARCHAR(10) | `'en'` or `'es'` |
| `patient_name_encrypted` | TEXT | Nullable — AES-256-GCM encrypted patient name for dashboard display only |
| `call_summary_encrypted` | TEXT | Nullable — AES-256-GCM encrypted one-sentence Claude-generated summary of patient response |
| `created_at` | TIMESTAMPTZ | |

### 12.5 New Table: `clinic_ehr_config`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK → `clinic` | UNIQUE per `clinic_id` + `gap_type` |
| `gap_type` | VARCHAR(50) | Internal enum value |
| `nextgen_appt_type_code` | VARCHAR(255) | As configured in NextGen for this clinic |
| `nextgen_appt_duration_mins` | INTEGER | Default 30 — varies by gap type and clinic |
| `updated_at` | TIMESTAMPTZ | |

### 12.6 Modified Table: `clinic_integration` — New Columns

| New Column | Type | Notes |
|---|---|---|
| `nextgen_url` | VARCHAR(500) | Base URL of clinic's NextGen instance |
| `nextgen_username_encrypted` | TEXT | AES-256-GCM |
| `nextgen_password_encrypted` | TEXT | AES-256-GCM |
| `retell_agent_id` | VARCHAR(255) | Retell agent configured for this clinic |
| `retell_from_number` | VARCHAR(20) | E.164 outbound number for this clinic |
| `campaign_concurrency_limit` | SMALLINT | Default 3, configurable per clinic |
| `calling_hours_start` | TIME | Default `09:00` |
| `calling_hours_end` | TIME | Default `18:00` |
| `clinic_timezone` | VARCHAR(50) | IANA timezone string, e.g. `'America/New_York'` |
| `voicemail_retry_hours` | SMALLINT | Hours before retrying a voicemail contact — default 72 |
| `no_answer_retry_hours` | SMALLINT | Hours before retrying a no-answer contact — default 48 |
| `error_retry_hours` | SMALLINT | Hours before retrying an error contact — default 1 |

---

## 13. API Endpoints

### 13.1 Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/auth/google` | Public | Redirect to Google OAuth consent screen |
| GET | `/auth/google/callback` | Public | OAuth callback — issue JWT or redirect to clinic selector |
| GET | `/auth/me` | JWT | Return current user info and clinic list |
| POST | `/auth/select-clinic` | JWT | Set active `clinic_id` in new scoped JWT |
| POST | `/auth/logout` | JWT | Invalidate session |

### 13.2 Campaign

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/campaigns/upload` | Clinic JWT (admin) | Accept CSV/Excel, parse via Claude API, create campaign + contacts, return `campaign_id` |
| GET | `/campaigns` | Clinic JWT | List all campaigns for active clinic — status, counts, created date |
| GET | `/campaigns/{id}` | Clinic JWT | Full campaign detail — counts, contact list with outcomes and summaries |
| POST | `/campaigns/{id}/pause` | Clinic JWT (admin) | Pause running campaign — in-flight calls complete |
| POST | `/campaigns/{id}/resume` | Clinic JWT (admin) | Resume paused campaign |
| GET | `/campaigns/{id}/export` | Clinic JWT | CSV export — `phone_hash`, `gap_type`, outcome, `appointment_datetime`, `language_detected` — no PHI |

### 13.3 Retell Tool Webhooks

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/retell/tools/get_available_slots` | HMAC-SHA256 | Mid-call: Playwright reads NextGen availability — must respond in <3s |
| POST | `/retell/tools/book_appointment` | HMAC-SHA256 | Mid-call: Playwright books appointment in NextGen |
| POST | `/retell/webhook/call_started` | HMAC-SHA256 | Mark contact `CALLING`, log `retell_call_id` |
| POST | `/retell/webhook/call_ended` | HMAC-SHA256 | Update contact status, write `CampaignAudit` record |
| POST | `/retell/webhook/call_analyzed` | HMAC-SHA256 | Extract `language_detected` and duration. Send transcript to Claude API to generate one-sentence call summary. Store summary encrypted in `campaign_audit.call_summary_encrypted`. Discard raw transcript. |

### 13.4 Admin (Super Admin only — API Key)

| Method | Path | Description |
|---|---|---|
| POST | `/admin/clinics` | Create new clinic + `ClinicIntegration` record |
| POST | `/admin/clinics/{id}/staff` | Add staff member (link Google account to clinic with role) |
| PUT | `/admin/clinics/{id}/ehr-config` | Set NextGen credentials, Retell agent ID, concurrency limit, calling hours, retry wait hours |
| POST | `/admin/clinics/{id}/ehr-test` | Trigger Playwright credential test — returns pass/fail + error detail |
| PUT | `/admin/clinics/{id}/appt-types` | Set `gap_type` → `nextgen_appt_type_code` mapping |
| GET | `/admin/clinics` | List all clinics with status |
| GET | `/admin/campaigns` | All campaigns across all clinics |

---

## 14. Clinic Dashboard

### 14.1 Screens

| Screen | Who Sees It | Contents |
|---|---|---|
| Clinic Selector | Staff in 2+ clinics | List of clinics user belongs to — click to enter |
| Campaign List | All clinic staff | All campaigns: name, status, progress bar, created date |
| Upload Screen | Clinic Admin only | Drag-and-drop CSV/Excel, upload button, status indicator |
| Campaign Detail | All clinic staff | Patient-level table: name, gap type, status, appointment time, provider, language, call summary, attempt count |
| EHR Setup | Clinic Admin only | NextGen URL, username, password fields + Test Connection button |

### 14.2 Campaign Detail — Patient Table

- Shows: patient name, gap type, status (color-coded badge), appointment date/time, provider, language, attempts, last called, and call summary
- **Call Summary column** shows the Claude-generated one-sentence summary of what the patient said (e.g. `"Patient agreed to A1C lab, will visit LabCorp this week"`)
- Clinic admin uses call summary to know when to send lab orders or follow up on special requests
- Status color codes: **green** = `BOOKED`, **yellow** = `PENDING`/`VOICEMAIL`, **red** = `DECLINED`/`EXHAUSTED`, **gray** = `CALLING`
- Table sortable by status and last called date
- Dashboard polls `GET /campaigns/{id}` every **30 seconds** — no WebSocket needed for MVP

> **NOTE:** Patient name and call summary are both stored AES-256-GCM encrypted in `campaign_audit`. Name is passed as Retell call metadata and stored on `call_analyzed`. Summary is generated by Claude API from the Retell transcript — one sentence describing what the patient agreed to or said. Both decrypted and shown only to authenticated clinic staff.

### 14.3 Technology

- Desktop only — no mobile optimization required for MVP
- Simple HTML + vanilla JS served from FastAPI, or minimal React — decision deferred to implementation
- No separate frontend build pipeline required — keep it simple for pilot
- The dashboard is a standard web page accessed via browser at your domain (e.g. `app.yourclinicai.com`) — nothing to install at the clinic

---

## 15. Pre-HEDIS Fixes — Existing Codebase

> **NOTE:** All four items below are blocking issues. Must be resolved in Week 1 before HEDIS work begins.

| Gap | File | Fix | Est. Time |
|---|---|---|---|
| Routers not registered in `main.py` | `main.py` | Add `app.include_router()` for `admin_router`, `retell_router`, `provider_router` | 30 min |
| Reaper worker not scheduled | `main.py` + `services/booking.py` | Add APScheduler lifespan event — call `expire_booking()` every 60 seconds | 1 hour |
| No auth on admin routes | `routes/admin.py` | Add `Depends(verify_admin_api_key)` to all `/admin/*` routes | 1 hour |
| Redis client not instantiated | `common/` or `main.py` | Instantiate Redis client — needed for AgentQL selector cache and distributed lock | 2 hours |

---

## 16. Implementation Plan — 5 Weeks

### Week 1 — Validation & Foundation

- **Day 1:** Run Playwright + AgentQL against pilot clinic's NextGen — validate headless access, login, scheduler read, booking. This is the **only hard blocker** for the entire project.
- **Day 2:** Apply all four pre-HEDIS fixes from Section 15
- **Day 3–4:** Alembic migrations for all new tables (Section 12). Redis client instantiation.
- **Day 5:** Google OAuth flow — `/auth/google`, `/auth/google/callback`, JWT issuance, clinic selector

### Week 2 — Upload, Parsing & Campaign Core

- CSV/Excel upload endpoint — Claude API parsing, E.164 normalization, `CampaignContact` creation
- Campaign service: create, start, pause, resume, status aggregation
- Campaign worker: FIFO queue across campaigns, calling hours enforcement, concurrency limit, configurable retry scheduling
- Retell API client: `create_outbound_call` with full metadata payload

### Week 3 — EHR Integration & Webhooks

- Playwright service: session initialization, heartbeat, re-authentication, action queue
- AgentQL integration: `get_available_slots` with selector caching in Redis
- AgentQL integration: `book_appointment` with NextGen appointment type lookup from `ClinicEhrConfig`
- Retell tool endpoints: `get_available_slots`, `book_appointment`
- Retell webhook handlers: `call_started`, `call_ended`, `call_analyzed` (includes Claude API call summary generation)
- Patient name encryption in `campaign_audit` for dashboard display

### Week 4 — Dashboard, Admin & Security

- Admin endpoints: clinic creation, staff assignment, EHR config, credential test, appointment type mapping
- Clinic dashboard: campaign list, upload screen, campaign detail patient table with summary column, 30-second polling
- EHR setup screen: credential entry + test connection flow
- PHI audit: verify no PHI in logs, no plaintext names in DB, encryption verified end-to-end
- Load test: 3 concurrent calls per clinic, 4 clinics simultaneously (12 concurrent Retell calls total)

### Week 5 — Pilot Onboarding & Hardening

- Deploy to Azure production with all environment variables configured
- Onboard pilot clinic: enter NextGen credentials, test connection, map appointment types, assign Retell agent, configure retry hours
- Add pilot clinic staff Google accounts
- Run first supervised campaign — monitor Playwright session stability, Retell webhook timing, booking accuracy, call summary quality
- Fix any session management or timing issues discovered under real NextGen usage
- Document known NextGen UI quirks for AgentQL selector maintenance

---

## 17. Unit Economics

### Infrastructure Cost Per Clinic / Month (~200 calls)

| Cost Item | Basis | Per Clinic / Month |
|---|---|---|
| Retell AI — voice calls | $0.13–$0.20/min all-in, 3 min avg | $78–$120 |
| Retell — extra concurrency slots | $8/slot/month if >20 slots total needed | $0 (shared across clinics under 20 limit) |
| Claude API — CSV parsing | ~2,000 tokens per upload, 1–2 uploads/month | <$0.01 |
| Claude API — AgentQL EHR | ~18,000 tokens/booking, ~50% book rate = 100 bookings | ~$10–$15 |
| Claude API — call summaries | ~500 tokens/call × 200 calls | ~$0.10 |
| Azure App Service | Always-on container (shared across clinics) | ~$8–$12 per clinic share |
| Azure PostgreSQL | Flexible Server small (shared across clinics) | ~$5 per clinic share |
| Redis (Azure Cache) | Small instance for selector cache | ~$3 per clinic share |
| **Total per clinic** | | **~$104–$155 / month** |

### Pricing Tiers

| Plan | Calls Included | Monthly Price | Gross Margin |
|---|---|---|---|
| Starter | Up to 300 calls / 2 gap types | $599 | ~74% |
| Growth | Up to 600 calls / 4 gap types | $899 | ~83% |
| Full Practice | Unlimited calls / all gap types | $1,199 | ~87% |

---

## 18. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| NextGen blocks headless Playwright | Medium | Critical | Test Week 1 Day 1 — fallback is Chrome Extension architecture (already documented in `HEDIS_CAMPAIGN_IMPLEMENTATION.md`) |
| Playwright response >3s during call | Medium | High | Pre-warm session before campaign starts. Cache selectors. Return partial slot list fast if full query is slow. |
| NextGen UI update breaks AgentQL selectors | Medium | Medium | AgentQL semantic queries survive most UI changes. Monitor weekly. Keep selector cache TTL at 24 hours to force re-discovery. |
| Retell account hits 20 concurrent call limit | Low (early) | Medium | 3 calls/clinic limit means 6 clinics max before hitting 20. Buy extra slots ($8/slot) as clinic count grows. |
| Patient calls back on voicemail number | Medium | Low | Inbound handling deferred. Retell inbound on that number can play a "please call the clinic at X" message as a stopgap. |
| Claude API misidentifies gap type from CSV | Low | Medium | Unrecognized labels produce a per-row parse error on upload (row skipped). Log parse results. Fix CSV or mapping and re-upload before starting. |
| NextGen appt type codes wrong at pilot clinic | High (first run) | Medium | Test booking with a dummy patient during onboarding before live campaign. |
| Staff sees PHI on dashboard without secure login | Low | High | Google OAuth required before any dashboard access. HTTPS enforced on all routes. JWT scoped to clinic. |
| Call summary quality poor from Claude | Low | Low | Summary prompt is simple and well-constrained. Review first 20 summaries manually during pilot and adjust prompt if needed. |

---

## 19. Open Items — Resolve During Pilot

| Item | Owner | When |
|---|---|---|
| Confirm pilot clinic's NextGen appointment type codes per gap type | Edgar + clinic contact | Week 5 onboarding |
| Confirm NextGen URL and whether login uses SSO or direct credentials | Edgar + clinic contact | Week 1 Day 1 |
| Decide if agent discloses it is AI (CMS HIPAA outreach disclosure guidance) | Edgar (legal review) | Before live calls |
| Retell agent ID for pilot clinic — build and configure in Retell dashboard | Edgar | Week 3 |
| Configure retry hours per gap type preference for pilot clinic | Edgar + clinic contact | Week 5 onboarding |
| BAA template — engage healthcare attorney for post-pilot paid customers | Edgar | Post-pilot |
| Determine if pilot clinic has 1 or multiple providers — affects scheduler complexity | Edgar + clinic contact | Week 5 onboarding |
| Confirm Spanish-speaking patient volume at pilot clinic — informs QA testing priority | Edgar + clinic contact | Week 5 onboarding |

---

## 20. Appendix — Codebase Reuse Map

| Existing Component | File | Reused As-Is |
|---|---|---|
| AES-256-GCM encryption | `common/encryption.py` | Phone, credentials, patient name in audit, call summary — no changes |
| Async SQLAlchemy + session factory | `common/database.py` | All new tables — no changes |
| Retell HMAC-SHA256 webhook verification | `routes/retell.py` | Extended with new tool + webhook handlers |
| Clinic / ClinicIntegration models | `data/models/` | Extended with new columns per Section 12.6 |
| Tenacity retry decorator | `requirements.txt` | Retell API calls, Playwright retry on session fail |
| Docker + Azure deployment config | `Dockerfile`, `docker-compose.yaml` | No changes needed |
| httpx async HTTP client | `requirements.txt` | Retell API client (`create_outbound_call`) |
| Google API client libraries | `requirements.txt` | Google OAuth flow (not Calendar — different API scope) |
| pytest async test suite patterns | `tests/` | All new tests follow same async patterns |
| Azure OpenAI config | `env.example`, `main.py` | Left in place but unused — Claude API used instead for HEDIS |

---

## 21. HEDIS Gap Type Taxonomy (Finalized 2026-03-23)

### Appointment-Based (Playwright books in NextGen)

| Enum value | Description | Notes |
|---|---|---|
| `preventive_visit` | Annual preventive / wellness visit | Insurance year rule applies (§22) |
| `hospital_flu` | Hospital follow-up within 7 days of discharge | **Always highest priority** (`priority_order = 0`) |

### Order-Based (call summary only — clinic admin sends order manually)

| Enum value | Description |
|---|---|
| `colorectal` | Colorectal cancer screening / stool test |
| `eye_exam` | Eye exam / retinal exam |
| `breast_cancer` | Breast cancer screening / mammogram |
| `kidney` | Kidney function lab |
| `afr_cmp` | Albumin/creatinine ratio + urinalysis |

### Excluded (filtered at CSV parse — never enters campaign queue)

| Enum value | Action |
|---|---|
| `medication_review` | Removed at CSV parse — never dialed |

### Unrecognized gap labels

Rows whose gap type cannot be mapped to a canonical enum value are **not** imported; they appear as parse errors on upload (same as invalid phone numbers).

**There is NO `a1c` gap type.** What appeared as A1C in earlier notes was the preventive visit timing rule.

### CSV Alias Normalization

Claude's CSV parser must map all known clinic CSV variations to canonical enum values:

| CSV input(s) | Canonical value |
|---|---|
| Preventive visit, Annual wellness, AWV, Yearly checkup | `preventive_visit` |
| Hospital follow-up, Hospital flu, Hosp flu, Post-hospital, Discharge follow-up | `hospital_flu` |
| Colorectal, CRC, Colonoscopy, Stool test, FIT | `colorectal` |
| Eye exam, Eye, Vision, Ophthalmology, Retinal exam | `eye_exam` |
| Breast cancer, Breast cancer screening, Mammogram, BSE | `breast_cancer` |
| Kidney, Kidney function, CKD, Renal | `kidney` |
| AFR/CMP, Albumin creatinine, Alb/Cr ratio, urine albumin, bw/uA | `afr_cmp` |
| Medication review, Med review, Medication management | `medication_review` → EXCLUDE |
| Anything else | Parse error — row skipped (no dial) |

---

## 22. Scheduling Rules (Finalized 2026-03-23)

### 22.1 Double Booking Rules

Only 1 appointment per hour slot maximum. Cannot double book restricted type pairs in the same hour. Only follow-up appointments can share a slot with restricted types. HEDIS patients are never new patients — "new patient" only matters when Playwright reads what is already in a NextGen slot.

**Default combination flags (all configurable per clinic in `clinic_scheduling_rules`):**

| Pair | Default |
|---|---|
| preventive + follow-up | ALLOWED |
| preventive + hospital_flu | BLOCKED |
| preventive + new_patient | BLOCKED |
| hospital_flu + follow-up | ALLOWED |
| hospital_flu + new_patient | BLOCKED |
| new_patient + follow-up | ALLOWED |

Playwright reads existing appointment types in each candidate slot via AgentQL and checks the clinic's flags before accepting the slot.

### 22.2 Hospital Flu — Scheduling

**7-day deadline:** `release_date` comes from CSV. `deadline = release_date + 7 days`. Campaign worker checks `deadline < today` before dialing; if expired → `status = EXPIRED` (terminal, never dial).

**Two scheduling modes** (determined by payer in `clinic_insurance_rules`):

| Mode | Slot type | Constraint |
|---|---|---|
| `telehealth_4_5pm` | Telehealth only | Within `hospital_flu_telehealth_start`–`hospital_flu_telehealth_end` (clinic timezone). Only on telehealth-enabled days. |
| `next_to_followup` | In-person only | Must share hour slot with existing follow-up appointment already in NextGen. Only on in-person-enabled days. |

If payer not in `clinic_insurance_rules` → default to `next_to_followup` + flag contact for review.

Time window and enabled days are configurable per clinic (stored in `clinic_scheduling_rules`).

### 22.3 Preventive Visit — Insurance Year Rules

**Two rules** (determined by payer in `clinic_insurance_rules`):

| Rule | Logic |
|---|---|
| `different_year` | Appointment must be in a different calendar year than last preventive visit |
| `one_year_one_day` | Appointment must be 366+ days after last visit date |

Last visit date is NOT in the CSV — Playwright reads it from the NextGen patient record via AgentQL. Cached in Redis: key `clinic_id:phone_hash:last_visit`, TTL 24 hours.

If payer not in `clinic_insurance_rules` → default to `different_year` + flag for review.

If patient not yet eligible → agent communicates earliest eligible date → `status = NOT_YET_ELIGIBLE` (terminal, no retry).

---

## 23. New Database Tables (2026-03-23)

### 23.1 `clinic_insurance_rules`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK → clinic | |
| `payer_name` | VARCHAR(255) | Matches payer string from CSV |
| `preventive_rule` | ENUM | `different_year` / `one_year_one_day` |
| `hospital_flu_rule` | ENUM | `telehealth_4_5pm` / `next_to_followup` |
| `active` | BOOLEAN | default true |
| `updated_at` | TIMESTAMPTZ | |

### 23.2 `clinic_scheduling_rules`

One row per clinic (UNIQUE on `clinic_id`).

| Column | Type | Default |
|---|---|---|
| `id` | UUID PK | |
| `clinic_id` | UUID FK → clinic UNIQUE | |
| `allow_preventive_with_followup` | BOOLEAN | true |
| `allow_preventive_with_hospital_flu` | BOOLEAN | false |
| `allow_preventive_with_new_patient` | BOOLEAN | false |
| `allow_hospital_flu_with_followup` | BOOLEAN | true |
| `allow_hospital_flu_with_new_patient` | BOOLEAN | false |
| `allow_new_patient_with_followup` | BOOLEAN | true |
| `hospital_flu_telehealth_start` | TIME | 16:00 |
| `hospital_flu_telehealth_end` | TIME | 17:00 |
| `hospital_flu_telehealth_mon` – `_sun` | BOOLEAN × 7 | fri=true, rest=false |
| `hospital_flu_inperson_mon` – `_sun` | BOOLEAN × 7 | mon–fri=true, sat/sun=false |
| `updated_at` | TIMESTAMPTZ | |
| `updated_by` | UUID FK → clinic_staff.id NULLABLE | null = Super Admin action |

### 23.3 New Columns on `campaign_contact`

| Column | Type | Notes |
|---|---|---|
| `release_date` | DATE NULLABLE | Hospital flu only — from CSV |
| `priority_order` | INTEGER | `hospital_flu` = 0; all others = CSV row order |

---

## 24. New Contact Statuses (2026-03-23)

| Status | Category | Description |
|---|---|---|
| `NOT_YET_ELIGIBLE` | Terminal | Preventive patient not yet eligible per insurance year rule — agent told patient earliest eligible date |
| `EXPIRED` | Terminal | Hospital flu 7-day deadline passed before call — worker never dials |
| `ORDER_AGREED` | Terminal | Order-based gap — patient verbally agreed — clinic admin sends order |
| `ORDER_DECLINED` | Terminal | Order-based gap — patient declined |

---

## 25. New API Endpoints (2026-03-23)

| Method | Path | Auth | Description |
|---|---|---|---|
| `PUT` | `/clinics/scheduling-rules` | Clinic Admin JWT | Update own clinic's scheduling rules |
| `PUT` | `/clinics/insurance-rules` | Clinic Admin JWT | Update own clinic's insurance payer rules |
| `PUT` | `/admin/clinics/{id}/scheduling-rules` | X-Admin-Key | Super Admin update any clinic's scheduling rules |
| `PUT` | `/admin/clinics/{id}/insurance-rules` | X-Admin-Key | Super Admin update any clinic's insurance rules |

---

## 26. Dashboard Additions (2026-03-23, extends §14)

### New Status Colors

| Color | Status |
|---|---|
| Orange | `ORDER_AGREED` — "Send Order" indicator shown next to row |
| Purple | `NOT_YET_ELIGIBLE` |
| Red | Also covers `EXPIRED` (added to existing red group) |

### New Urgent Badge

`URGENT` badge on `hospital_flu` contacts with ≤ 2 days before the 7-day deadline. Shows days-remaining counter next to patient name.

### New Column: Summary

One-sentence Claude-generated description of what the patient said. Examples:
- "Patient agreed to colorectal screening, doctor to send order."
- "Patient booked preventive visit March 26 at 2pm with Dr. Rivera."
- "Patient declined — said already completed mammogram elsewhere."

### New Settings Screen

Accessible from dashboard sidebar. Clinic Admin editable; Clinic Staff read-only.

**Section 1: Double Booking Rules** — 6 toggles (one per combination pair)
**Section 2: Hospital Follow-Up Telehealth** — 7 day checkboxes + start/end time pickers (clinic timezone)
**Section 3: Hospital Follow-Up In-Person** — 7 day checkboxes

Save → `PUT /clinics/scheduling-rules`. Shows "Last updated [date] by [staff name]" or "by System" when Super Admin changed it.

---

## 27. Super Admin Onboarding Screen (Post-Pilot)

**When:** After first clinic is onboarded manually during pilot. **Why deferred:** Learn real requirements before building.

**URL:** `/admin/onboard` — plain HTML served by FastAPI, protected by `X-Admin-Key`, never linked from clinic dashboard.

**Steps (single transaction on submit):**
1. Clinic creation — name, location, timezone, phone
2. Staff entry — email + role (`clinic_admin` / `clinic_staff` / `provider`), multiple rows
3. EHR config — NextGen URL + credentials, Retell agent ID, from number (E.164), concurrency limit, calling hours, timezone, retry hours
4. Test Connection — inline `POST /admin/clinics/{id}/ehr-test`; must pass before proceeding
5. Appointment type codes — one row per appointment-based gap (`preventive_visit`, `hospital_flu`); NextGen appointment type string
6. Scheduling rules — 6 combination toggles + telehealth window + 14 day checkboxes
7. Insurance rules — one row per payer; `preventive_rule` + `hospital_flu_rule` dropdowns
8. Submit all — single DB transaction
9. Success screen — `clinic_id` + staff login instructions to send to clinic

**Payment model:** Invoice only — no Stripe. QuickBooks / Wave / PDF. ACH, check, or payment link. Only automate billing when clinic count exceeds ~20.

---

## 28. Open Question — `updated_by` for Super Admin Actions

When Super Admin modifies scheduling rules via `X-Admin-Key` (no Google OAuth, no `clinic_staff.id`):

- **Option A:** Store `null` → dashboard shows "Last updated [date] by System"
- **Option B:** Create a Super Admin record in `clinic_staff` → link to it

**Not decided as of 2026-03-23.** Must resolve before writing the Alembic migration for `clinic_scheduling_rules.updated_by`.

---

*— End of Document —*

**HEDIS Outreach Automation Platform · PRD v2.0 · March 2026 · CONFIDENTIAL**
