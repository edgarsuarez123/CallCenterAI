# Edgar J. Suarez Colon
**Target Roles:** AI Engineer | Forward Deployed Engineer
**Project:** CallCenterAI — HEDIS Outreach Automation Platform
**Stack:** Python | FastAPI | Retell AI | Claude API | Azure PostgreSQL | Redis | Google Calendar API | Docker

---

## Project at a Glance

CallCenterAI is a production-grade, multi-tenant SaaS platform that automates HIPAA-compliant patient outreach for primary care clinics. It deploys AI voice agents (Retell AI) to call patients with healthcare care gaps, checks real-time provider availability mid-call, and books appointments — all without human staff involvement. Built solo, from architecture through deployment.

---

## STAR: Building a HIPAA-Compliant AI Voice Scheduling Platform for Healthcare

### Situation

Independent primary care clinics enrolled in value-based care contracts receive monthly HEDIS (Healthcare Effectiveness Data and Information Set) reports identifying patients overdue for preventive services — A1C checks, mammograms, annual wellness visits, colorectal screenings. Closing these gaps requires staff to manually call hundreds of patients, cross-reference provider schedules in NextGen EHR, and book appointments. Most clinics do not have the bandwidth.

The result: fewer than 40% of HEDIS care gaps get closed. For a 500-patient list, that translates directly to tens of thousands of dollars in uncollected pay-for-performance reimbursements per payer contract cycle. No affordable, HIPAA-aligned, automated solution existed purpose-built for independent clinics on NextGen EHR.

### Task

Design and build a multi-tenant SaaS platform, end-to-end and solo, that:

- Automates outbound patient phone calls using a conversational AI voice agent
- Checks real-time provider appointment availability mid-call and books confirmed appointments
- Maintains full HIPAA compliance — zero plaintext PHI in the database, encrypted at rest with authenticated encryption, immutable audit trails for every patient interaction
- Supports multiple clinics on a single deployment with strict tenant isolation
- Operates within the hard real-time constraint imposed by live voice calls: all scheduling responses must return in under 3 seconds

### Action

**1. AI Voice Agent Integration (Retell AI)**

Integrated Retell AI as the voice layer, designing a real-time tool-calling architecture where the AI agent calls FastAPI endpoints mid-conversation to check availability and create bookings. Key engineering decisions:

- Built `POST /retell/schedule` as the primary tool endpoint, handling three distinct intents (book, cancel, reschedule) from a single call in under 3 seconds
- Implemented HMAC-SHA256 webhook signature verification (`hmac.compare_digest` for constant-time comparison) on all Retell webhooks, with environment-aware enforcement — strict in production, permissive in local dev
- Designed provider disambiguation logic: if a patient names a provider matching multiple records, the agent prompts for clarification rather than silently picking one
- Built workload-based provider load balancing — when no provider is specified, a SQL subquery counts upcoming confirmed bookings per active provider and routes to the least-busy one
- Mapped Retell `agent_id` to `clinic_id` via `ClinicIntegration`, supporting one agent per clinic with gap type passed as call metadata

**2. HIPAA-Compliant Data Architecture**

Designed and implemented a zero-knowledge PHI storage model:

- All patient PHI (name, date of birth, phone, email) stored as AES-256-GCM encrypted `BYTEA` in PostgreSQL — never in plaintext. Encryption uses a 12-byte random IV prepended to ciphertext with a 16-byte authentication tag, enabling tamper detection on every read
- SHA-256 hash of normalized `name|DOB` used for O(1) patient dedup lookups — no decryption needed to check for existing records, with decryption-based verification as a collision defense
- Phone numbers masked as `***-***-XXXX` in all application logs
- Immutable `BookingAudit` table records every booking state transition (hold, confirm, cancel, expire) — `ondelete="RESTRICT"` on the booking FK prevents record deletion that would break audit continuity
- PHI encryption key loaded from environment variable, validated for exact 32-byte length, cached at module level — never touches disk or logs

**3. Real-Time Booking State Machine**

Built a tentative-hold booking pattern to handle the race condition of concurrent AI calls competing for the same appointment slot:

- `create_tentative_booking()` creates a 5-minute UUID hold token before the patient commits — prevents double-booking during the AI conversation
- Application-level capacity enforcement counts all overlapping TENTATIVE and CONFIRMED bookings before insertion (supports capacity > 1 per provider)
- Partial unique index on `(provider_id, slot_start, slot_end) WHERE status IN ('tentative', 'confirmed')` at the database level as a backstop
- `call_ended` webhook automatically releases unconfirmed tentative holds from that call
- Background reaper worker (via APScheduler) expires stale holds and frees capacity

**4. Dual-Source Availability Engine**

Availability checks reconcile two independent data sources — the internal booking database and Google Calendar — with deduplication to prevent double-counting:

- Single Google Calendar API call per day covers all events; local filtering applies blocked slots and capacity limits
- Bilingual keyword detection (English + Spanish) identifies patient appointment events in GCal vs. external blocking events, determining whether an event counts toward provider capacity
- Deduplication uses `booking_id` stored in GCal event `extendedProperties.private` and cross-referenced against internal `google_event_id` — eliminates phantom capacity collisions
- Forward search across 14 days finds next available slots when patients have no date preference
- All datetime comparisons normalize to UTC; timezone-aware per clinic (IANA format)

**5. Async Backend on Azure**

- FastAPI with async SQLAlchemy 2.0 + `asyncpg` driver on Azure PostgreSQL Flexible Server (SSL required, HIPAA BAA in effect)
- Google Calendar API v3 wrapped in `ThreadPoolExecutor` for async compatibility; retry engine with exponential backoff distinguishes rate limits (enhanced 5/10/20s backoff) from transient errors (1/2/4s) from permanent failures (403 — always raise)
- Graceful degradation: if Google Calendar is unavailable, booking proceeds against internal DB only
- Redis for distributed locking and AgentQL selector cache (24-hour TTL)
- Multi-tenant row isolation enforced at application layer — every query includes `clinic_id` filter; no cross-tenant access possible
- 2 Alembic migrations covering 10 ORM models; second migration retroactively encrypted plaintext phone/email columns and added SHA-256 hash index
- Dockerized with Playwright Chromium bundled in image; `start.sh` waits for Postgres, runs Alembic, starts uvicorn with configurable workers
- 200+ pytest async test cases across 10 test files: unit tests for encryption, PHI hashing, booking state machine, availability engine, HMAC verification; integration tests for Google Calendar retry logic

### Result

- Platform capable of processing ~480 patient contacts per 8-hour calling window per clinic (3 concurrent calls, 5-second inter-call gap)
- Targeting 50%+ appointment booking rate versus the industry baseline of under 40% for manual outreach
- Projected $10,000–$20,000 in incremental payer reimbursements per campaign cycle for a 500-patient care-gap list
- Infrastructure cost of ~$104–$155/month per clinic; SaaS pricing from $599–$1,199/month yields 74–87% gross margin
- ~13,500 lines of production code across 25 source files and 11 test files, built solo

---

## Technical Skills Demonstrated

**AI & LLM Integration**
- Retell AI real-time voice agent tool calling (sub-3s latency constraint)
- Anthropic Claude API (`claude-sonnet-4-20250514`) for call transcript summarization
- Natural-language to structured intent parsing within live voice conversations

**Backend Engineering**
- Python async/await — FastAPI 0.104.1, SQLAlchemy 2.0 (async), asyncpg
- Real-time webhook handling with HMAC-SHA256 signature verification
- Booking state machine design (tentative hold, confirmation, expiration, audit)
- Dual-source data reconciliation (GCal + internal DB dedup)
- Provider load balancing via SQL subquery aggregation
- Retry logic with exponential backoff and per-error-code routing

**Security & Compliance**
- AES-256-GCM authenticated encryption for PHI at rest (IV + ciphertext + auth tag)
- SHA-256 hash-based lookup with decryption-based collision defense
- Constant-time HMAC comparison (`hmac.compare_digest`)
- Multi-tenant row-level isolation
- HIPAA-compliant architecture on Microsoft Azure (BAA in effect)
- Immutable audit trail design

**Data & Infrastructure**
- PostgreSQL (Azure Flexible Server) — partial unique indexes, ENUM types, JSONB feature flags
- Alembic schema migrations (online + offline mode)
- Redis (distributed lock, selector cache with TTL)
- Google Calendar API v3 — service account auth, extended properties, async wrapping
- Docker + docker-compose (dev + production), health checks, non-root container user
- pytest-asyncio test suite — unit, integration, and slow test markers

**Systems Design**
- Multi-tenant SaaS architecture from scratch
- Campaign orchestration design (FIFO, concurrency limits, retry policies, calling hour enforcement)
- Graceful degradation patterns (bookings proceed if GCal unavailable)
- ThreadPoolExecutor bridging of sync APIs into async context
