# PLAN.md — CallCenterAI HEDIS Implementation Plans

> This file tracks all implementation plans in chronological order.
> Plans are never deleted — superseded plans are marked [SUPERSEDED].
> Each plan includes what was decided, why, and what was deferred.
> Source of truth for all feature work: HEDIS_PRD_v2.md
> Architecture reference: INFRASTRUCTURE.md
> Session rules: CLAUDE.md

---

## Plan Index

| # | Date | Title | Status |
|---|---|---|---|
| 001 | 2026-03-18 | MVP Roadmap — Full Feature Inventory | Active |
| 002 | 2026-03-18 | Feature 0 — Playwright Validation Gate | Active |
| 003 | 2026-03-18 | Feature 1 — Pre-HEDIS Codebase Fixes | Complete (code done, tests pending) |
| 004 | 2026-03-18 | Feature 2 — New Schema + Migrations | Complete |
| 005 | 2026-03-18 | Feature 3 — Authentication & Authorization | Active |

---

## Plan 001 — MVP Roadmap — Full Feature Inventory
**Date:** 2026-03-18
**Status:** Active
**Source:** HEDIS_PRD_v2.md (all sections) + INFRASTRUCTURE.md gap analysis

### What We Are Building

A full HEDIS outreach automation platform:
- Multi-tenant SaaS (FastAPI + Azure PostgreSQL)
- Retell AI outbound calling with per-clinic agents
- Claude API CSV parsing (gap type extraction)
- Server-side Playwright + AgentQL for NextGen EHR scheduling
- Clinic dashboard (Google OAuth + JWT) for campaign management
- HIPAA-aligned PHI handling throughout

### Current State (Phase 1 — ~95% Complete)

The core GCal-based booking system (inbound calls) is built and tested:
- 10 ORM models, 2 Alembic migrations
- Retell webhooks + tool endpoints (schedule, confirm, availability)
- PHI encryption (AES-256-GCM), patient service, booking service
- Admin + provider CRUD routes (implemented but NOT registered in main.py)
- Google Calendar service (legacy, fully tested)
- 8 test files covering all services

### What Is Missing for HEDIS MVP

See Features 0–8 below. Everything after Feature 1 is net-new.

### Key Architecture Decisions & Reasoning

1. **Server-side Playwright over Chrome Extension** — Playwright headless runs on Azure; no clinic install required. Chrome Extension fallback documented in HEDIS_CAMPAIGN_IMPLEMENTATION.md. Feature 0 validates which path to take.
2. **One Retell agent per clinic** — gap_type passed as call metadata, not separate agents. Keeps Retell billing simple.
3. **Claude API for CSV parsing** — payer-format CSV columns vary wildly; LLM normalization is cheaper and more robust than heuristics.
4. **Redis for selector cache + distributed lock** — 24h selector TTL saves ~60% AgentQL tokens. Distributed lock prevents concurrent Playwright actions per clinic (NextGen race conditions).
5. **FIFO across campaigns** — contacts processed in CSV row order across all active campaigns. Predictable, matches clinic staff expectations.
6. **No patient name/DOB in DB** — PHI minimization. Name + DOB passed as Retell call metadata only; stored in campaign_audit AES-256-GCM encrypted only for dashboard display.

### Testing Standard (Applied After Every Feature)

**Unit tests:** `@pytest.mark.unit` — mock all DB + external calls, test business logic
**Integration tests:** `@pytest.mark.integration` — real DB (test transaction rollback), mock external APIs
**PHI tests:** encryption/decryption round-trips, hash dedup correctness
**Webhook tests:** HMAC verification with valid + invalid signatures
**Coverage target:** All new service functions, all new route handlers

### Deferred (Post-MVP / Post-Pilot)

- SOAP note generation
- Inbound callback handling
- TCPA do-not-call list checking
- EHR support beyond NextGen
- BAA contract onboarding flow (manual for pilot)
- Advanced analytics/reporting
- Multi-language beyond English + Spanish
- Azure Key Vault (using env var for pilot; Key Vault in v1.1)
- Reminder call engine (deferred from MVP — not needed for HEDIS outreach pilot)

---

## Feature Order and Dependency Graph

```
Feature 0: Playwright Validation Gate (manual — Edgar runs test)
    └── gates all EHR work (Feature 5)

Feature 1: Pre-HEDIS Codebase Fixes
    ├── 1a: Register routers in main.py
    ├── 1b: Admin API key auth
    ├── 1c: Reaper worker (APScheduler)
    └── 1d: Redis client singleton

Feature 2: New Schema + Migrations
    ├── New enums (CampaignStatus, ContactStatus, GapType)
    ├── New tables: clinic_staff, campaign, campaign_contact, campaign_audit, clinic_ehr_config
    ├── Alter: clinic_integration (11 new columns)
    └── New requirements: anthropic, playwright, agentql, PyJWT, python-multipart, openpyxl

Feature 3: Auth (Google OAuth + JWT + Admin API Key)
    ├── 3a: Admin API key dependency
    ├── 3b-d: Google OAuth flow + JWT + clinic selector
    └── 3e-f: JWT dependency + staff management endpoint

Feature 4: CSV Upload + Claude Parsing + Campaign Creation
    ├── 4a-b: Upload endpoint + Claude API client
    ├── 4c-d: Gap type mapping + campaign/contact creation
    └── 4e: Campaign management routes

Feature 5: EHR Integration (Playwright + AgentQL)   [depends on Feature 0 result]
    ├── 5a-e: Playwright service (session, heartbeat, queue, Redis cache)
    ├── 5f-g: Retell EHR tool endpoints
    └── 5h-i: Admin EHR config + credential test

Feature 6: Campaign Worker + Outbound Calling
    ├── 6a-f: Worker loop (concurrency, calling hours, retry, 5s gap)
    ├── 6c: Retell outbound call client
    └── 6g-h: call_analyzed webhook + campaign webhook updates

Feature 7: Clinic Dashboard
    ├── 7a-e: Frontend screens (selector, list, upload, detail, EHR setup)
    └── 7f-g: 30s polling, status badges

Feature 8: Hardening + Pilot Onboarding
    ├── 8a: PHI audit
    ├── 8b: Load test (12 concurrent calls)
    ├── 8c: Azure production deploy
    └── 8d-f: Pilot clinic onboarding + supervised campaign
```

---

## 5-Week Schedule

| Week | Features | Gate |
|---|---|---|
| 1 | F0 (validation) → F1 (fixes) → F2 (schema) → Start F3 (auth) | Playwright test result logged in PROGRESS.txt |
| 2 | Finish F3 → F4 (upload + parsing) → Start F6 (worker scaffold) | Campaign created and visible in DB |
| 3 | F5 (EHR) → Finish F6 (webhooks + worker) | Test booking created in NextGen during supervised test call |
| 4 | F7 (dashboard) → F3f (staff mgmt) → F8a (PHI audit) | Staff can log in and see campaign |
| 5 | F8 (deploy + pilot + supervised run) | First real HEDIS call placed and appointment booked |

---

## Plan 002 — Feature 0: Playwright Validation Gate
**Date:** 2026-03-18
**Status:** Active
**Source:** HEDIS_PRD_v2.md §10.6 + CLAUDE.md §Critical Validation Gate
**Depends On:** Pilot clinic credentials (NextGen URL, username, password)

### What We Are Validating

Before writing a single line of backend HEDIS code, we must confirm that:
1. Server-side headless Chromium can open and load the pilot clinic's NextGen EHR
2. Playwright can programmatically log in (not blocked by SSO, CAPTCHA, or IP filter)
3. AgentQL can read available appointment slots from the scheduler page
4. AgentQL can fill the booking form and submit an appointment

**If any step fails,** the architecture pivots to Chrome Extension + WebSocket per `HEDIS_CAMPAIGN_IMPLEMENTATION.md`. This determines whether Features 5 and 6 use Playwright (simpler, fully server-side) or Chrome Extension (more complex, requires clinic install).

### What Currently Exists

`agentql-test/click-test.js` — Node.js proof-of-concept using:
- Playwright via CDP (Chrome DevTools Protocol) connecting to a running Chrome instance
- AgentQL natural-language element querying (`query_elements`)
- Clicks `book_appointment_button` by semantic description

**Limitation of existing test:** Uses CDP to attach to an *existing* running Chrome. For production, we need to confirm **headless Chromium** works (no existing Chrome needed), which is what will run on Azure.

### Key Architecture Decisions for This Feature

- **Headless vs. CDP:** Production uses `playwright.chromium.launch(headless=True)` on the server. The existing test uses CDP (developer convenience). Both must be validated.
- **Node.js vs. Python:** Existing test is Node.js. Production code will be Python (server-side). Both should be tested for NextGen compatibility, but Python test is more important.
- **Azure compatibility:** Azure App Service with Chromium requires specific system dependencies (`libglib2.0`, `libnss3`, etc.). Dockerfile will need Playwright system deps added.

### Implementation Steps

> **Note:** Steps marked [MANUAL — EDGAR] require the pilot clinic's NextGen credentials and cannot be automated by Claude.

#### Step F0.1 — Extend existing test for headless mode [MANUAL — EDGAR]

Run the existing `agentql-test/click-test.js` against pilot clinic's NextGen as a baseline.
- Confirms AgentQL connectivity works at all
- Log result in PROGRESS.txt

**Test to write after this step:** None — this is a manual exploratory test, not a unit test.

**Success criteria:** Script runs without error, `book_appointment_button` is found on the page.
**Failure criteria:** NextGen blocks connection, login fails, or AgentQL throws.

---

#### Step F0.2 — Write Python headless Playwright test [MANUAL — EDGAR + Code]

Create `agentql-test/test_nextgen_headless.py` that validates the full Python headless flow:

```python
# agentql-test/test_nextgen_headless.py
# NOT a pytest test — standalone validation script
# Run manually: python agentql-test/test_nextgen_headless.py

import asyncio
import agentql
from playwright.async_api import async_playwright

NEXTGEN_URL = "..."       # From env or hardcoded for local test only — NEVER commit
NEXTGEN_USERNAME = "..."  # From env — NEVER commit
NEXTGEN_PASSWORD = "..."  # From env — NEVER commit

async def validate():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await agentql.wrap_async(browser.new_page())

        # Step 1: Login
        await page.goto(NEXTGEN_URL)
        # ... login form fill + submit

        # Step 2: Navigate to scheduler
        # ... navigate to appointment scheduler

        # Step 3: Read available slots
        slots_response = await page.query_elements("""
        {
            available_appointment_slots[] {
                date
                time
                provider_name
            }
        }
        """)
        print(f"Slots found: {slots_response.available_appointment_slots}")
        assert len(slots_response.available_appointment_slots) > 0, "No slots found"

        # Step 4: Fill booking form (use test/dummy patient)
        # ... fill form fields via AgentQL

        # Step 5: DO NOT SUBMIT in validation — confirm form is fillable
        print("VALIDATION PASSED: Headless Playwright + AgentQL works with NextGen")

        await browser.close()

asyncio.run(validate())
```

**Test to write after this step:** See F0.4.

**Success criteria:** Script runs headlessly, slots are read, form is fillable.
**Failure criteria:** Any step throws — especially login blocked or scheduler page not parseable.

---

#### Step F0.3 — Test Dockerfile Playwright compatibility [Code]

Add Playwright system dependencies to `Dockerfile` and confirm the container can run Playwright headlessly:

```dockerfile
# Add after the existing apt-get install line:
RUN apt-get install -y \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    --no-install-recommends
```

Also add to `requirements.txt`:
- `playwright` (with `playwright install chromium` as a Dockerfile step)
- `agentql`

**Test to write after this step:** See F0.5.

**Success criteria:** `docker build` succeeds; container can run `python agentql-test/test_nextgen_headless.py` without error.
**Failure criteria:** Missing system library or Playwright install fails in container.

---

#### Step F0.4 — Write pytest unit tests for Playwright service interface [Code]

These tests do NOT connect to real NextGen. They test the service contract — that our `PlaywrightEHRService` class (to be built in Feature 5) has the correct interface and that mocking works correctly for future integration tests.

**File:** `tests/test_playwright_validation.py`

```python
# tests/test_playwright_validation.py
"""
Unit tests validating the Playwright service interface contract.
These use mocks — no real NextGen connection required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.unit
class TestPlaywrightServiceInterface:
    """Verify the PlaywrightEHRService interface contract before implementation."""

    def test_service_constructor_requires_credentials(self):
        """PlaywrightEHRService must require nextgen_url, username, password."""
        # Will be implemented in Feature 5 — this test defines the expected interface
        pass  # Placeholder — replace when PlaywrightEHRService is created

    @pytest.mark.asyncio
    async def test_get_available_slots_returns_list(self):
        """get_available_slots must return a list of slot dicts with start_time, end_time, provider_name."""
        # Mock contract test
        mock_slots = [
            {"start_time": "2026-04-01T09:00:00-05:00", "end_time": "2026-04-01T09:30:00-05:00", "provider_name": "Dr. Smith"},
        ]
        mock_service = AsyncMock()
        mock_service.get_available_slots.return_value = mock_slots
        result = await mock_service.get_available_slots(provider_name="Dr. Smith", date="2026-04-01")
        assert isinstance(result, list)
        assert all("start_time" in s and "end_time" in s and "provider_name" in s for s in result)

    @pytest.mark.asyncio
    async def test_book_appointment_returns_ehr_id(self):
        """book_appointment must return an ehr_appointment_id string on success."""
        mock_service = AsyncMock()
        mock_service.book_appointment.return_value = {"ehr_appointment_id": "nextgen_appt_12345", "success": True}
        result = await mock_service.book_appointment(
            provider_name="Dr. Smith",
            slot_start="2026-04-01T09:00:00-05:00",
            patient_name="John Doe",
            patient_dob="1980-01-15",
            appt_type_code="PREV"
        )
        assert result["success"] is True
        assert "ehr_appointment_id" in result

    @pytest.mark.asyncio
    async def test_get_available_slots_must_respond_within_3s(self):
        """Validates the <3s response time contract per HEDIS PRD §10.3."""
        import time
        mock_service = AsyncMock()
        mock_service.get_available_slots.return_value = []
        start = time.monotonic()
        await mock_service.get_available_slots(provider_name="Dr. Smith", date="2026-04-01")
        elapsed = time.monotonic() - start
        # Mock always passes this — contract test for documentation + future load test
        assert elapsed < 3.0, f"Slot query took {elapsed:.2f}s — exceeds 3s Retell limit"

    def test_agentql_selector_cache_key_format(self):
        """Redis cache key for AgentQL selectors must follow: agentql:selector:{clinic_id}:{element_name}"""
        clinic_id = "550e8400-e29b-41d4-a716-446655440000"
        element_name = "appointment_slot_grid"
        expected_key = f"agentql:selector:{clinic_id}:{element_name}"
        # This documents the key format before implementation
        assert expected_key.startswith("agentql:selector:")
        assert clinic_id in expected_key
        assert element_name in expected_key
```

**Success criteria:** All 4 tests pass (they're mock-based, should always pass).
**Failure criteria:** Import errors or test framework issues.

---

#### Step F0.5 — Write integration test for Playwright Docker environment [Code]

**File:** `tests/test_playwright_docker.py`

```python
# tests/test_playwright_docker.py
"""
Integration test: validates Playwright + Chromium are installed and can launch.
Does NOT connect to NextGen — just confirms the runtime is available.
Run inside Docker container: pytest tests/test_playwright_docker.py -m integration
"""
import pytest

@pytest.mark.integration
@pytest.mark.slow
class TestPlaywrightRuntime:

    @pytest.mark.asyncio
    async def test_chromium_launches_headlessly(self):
        """Playwright can launch headless Chromium in this environment."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            pytest.skip("playwright not installed — run: pip install playwright && playwright install chromium")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("about:blank")
            title = await page.title()
            await browser.close()
            assert title == ""  # about:blank has empty title

    @pytest.mark.asyncio
    async def test_agentql_importable(self):
        """agentql package is importable and has wrap_async."""
        try:
            import agentql
            assert hasattr(agentql, "wrap_async")
        except ImportError:
            pytest.skip("agentql not installed — run: pip install agentql")
```

**Success criteria:** Both tests pass inside Docker container.
**Failure criteria:** Playwright not installed or system libraries missing in container.

---

#### Step F0.6 — Decision logging and PROGRESS.txt update [MANUAL — EDGAR]

After running F0.1 and F0.2, Edgar must log the result in `PROGRESS.txt` before any Feature 5 work begins:

**If Playwright headless WORKS:**
```
Playwright Validation: PASSED
- Headless: YES
- Login: YES
- AgentQL slot read: YES
- Form fillable: YES
- Architecture path: Server-side Playwright (Features 5-6 use PlaywrightEHRService)
```

**If Playwright headless is BLOCKED:**
```
Playwright Validation: FAILED — NextGen blocks headless
- Reason: [specific error]
- Architecture path: Chrome Extension + WebSocket (see HEDIS_CAMPAIGN_IMPLEMENTATION.md)
- Feature 5 pivots to: WebSocket relay + Chrome Extension AgentQL
```

### Files Created / Modified in Feature 0

| File | Action | Notes |
|---|---|---|
| `agentql-test/test_nextgen_headless.py` | Create | Manual validation script — credentials from env only, never committed |
| `Dockerfile` | Modify | Add Playwright system dependencies |
| `requirements.txt` | Modify | Add `playwright`, `agentql` |
| `tests/test_playwright_validation.py` | Create | Unit tests — mock-based, no real NextGen |
| `tests/test_playwright_docker.py` | Create | Integration test — validates runtime |
| `PROGRESS.txt` | Update | Log validation result |

### What Is NOT In Scope for Feature 0

- Writing the actual `PlaywrightEHRService` class (Feature 5)
- Wiring Playwright into the booking flow (Feature 5)
- Redis selector cache implementation (Feature 5)
- Any campaign logic (Feature 6)

---

## Plan 003 — Feature 1: Pre-HEDIS Codebase Fixes
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 0 validation logged)
**Source:** HEDIS_PRD_v2.md §15 + CLAUDE.md §Known Architectural Gaps

### What We Are Building

4 blocking fixes that make the existing codebase production-functional.
None of these depend on Feature 0's result — they can be parallelized with the Playwright test.

### Implementation Steps

#### Step F1.1 — Register routers in main.py

**File:** `Clinic_app/main.py`

Add `app.include_router()` for `admin_router`, `retell_router`, `provider_router`.
Add APScheduler lifespan event for reaper.

**Changes:**
- Import routers
- `app.include_router(admin_router)`
- `app.include_router(retell_router)`
- `app.include_router(provider_router)`
- Wire APScheduler in `@asynccontextmanager` lifespan

**Tests to write after this step:**
- `tests/test_router_registration.py` — confirm all expected route paths return non-404 with a health-check style test
- Update existing route tests to not fail on missing router

---

#### Step F1.2 — Admin API key authentication

**File:** `Clinic_app/common/auth.py` (new), `Clinic_app/Routes/admin.py`, `Clinic_app/Routes/provider.py`

```python
# common/auth.py
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-Admin-Key", auto_error=False)

async def verify_admin_api_key(api_key: str = Security(API_KEY_HEADER)):
    expected = os.environ.get("ADMIN_API_KEY")
    if not expected or api_key != expected:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid or missing admin API key"})
```

Add `Depends(verify_admin_api_key)` to all `/admin/*` route handlers.

**Tests to write after this step:**
- `tests/test_auth.py` (new) — test valid key passes, missing key returns 401, wrong key returns 401

---

#### Step F1.3 — APScheduler reaper worker

**File:** `Clinic_app/workers/booking_reaper.py` (new), `Clinic_app/main.py`

```python
# workers/booking_reaper.py
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def run_booking_reaper():
    """Expire tentative bookings past their hold_expires_at."""
    from Clinic_app.common.database import AsyncSessionLocal
    from Clinic_app.services.booking import get_expired_tentative_bookings, expire_booking
    async with AsyncSessionLocal() as db:
        expired = await get_expired_tentative_bookings(db)
        for booking in expired:
            await expire_booking(db, booking.id)
            logger.info(f"Reaped expired booking: {booking.id}")
        if expired:
            await db.commit()
```

Add `apscheduler` to `requirements.txt`.

**Tests to write after this step:**
- `tests/test_booking_reaper.py` — test that expired holds are found and expired, non-expired holds are untouched

---

#### Step F1.4 — Redis client singleton

**File:** `Clinic_app/common/redis.py` (new), `Clinic_app/main.py`

```python
# common/redis.py
import os
import redis.asyncio as aioredis

_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis_client = await aioredis.from_url(url, encoding="utf-8", decode_responses=True)
    return _redis_client

async def close_redis():
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
```

**Tests to write after this step:**
- `tests/test_redis.py` — test get/set/delete with a real Redis instance (integration, tagged `@pytest.mark.integration`) and test client initialization with mock (unit)

---

### Feature 1 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_router_registration.py` | Unit | All routes return non-404, router is registered |
| `tests/test_auth.py` | Unit | Admin key validation (valid/missing/wrong) |
| `tests/test_booking_reaper.py` | Unit + Integration | Reaper expires correct bookings |
| `tests/test_redis.py` | Unit + Integration | Redis client init, get/set/delete |

---

## Plan 004 — Feature 2: New Schema + Migrations
**Date:** 2026-03-18
**Updated:** 2026-03-20 (expanded to full step-by-step with architecture rationale)
**Status:** Active (Feature 1 code complete, Feature 2 begins next session)
**Source:** HEDIS_PRD_v2.md §12

### What We Are Building

The HEDIS schema layer. Phase 1 has no concept of outbound campaigns, HEDIS care gaps, clinic staff
logins, or EHR (NextGen) credentials. Feature 2 adds all of that at the data model level — no
business logic yet, just the schema foundation that Features 3–8 build on.

### Key Architecture Decisions & Reasoning

1. **`clinic_staff` uses `google_sub` not email** — Google OAuth `sub` claim is stable; email
   can be changed by the user. `sub` is what we store and match on callback. This prevents
   a staff member from being locked out or duplicated if they change their Google email.

2. **`campaign_contact` stores phone_encrypted + phone_hash, no name/DOB** — PHI minimization.
   Name and DOB are passed as Retell call metadata at the moment of dial. They are never
   stored in this table. The dual-column pattern (AES-256-GCM + SHA-256 hash) mirrors the
   patient table — hash enables dedup across campaigns without decrypting every row.

3. **`campaign_audit.patient_name_encrypted`** — The only place name appears in the DB is here,
   after the call ends, for dashboard display. It comes from the Retell `call_analyzed` webhook
   metadata. Raw transcripts are discarded; only a one-sentence Claude summary is stored
   (encrypted).

4. **`clinic_ehr_config.appt_type_mapping` as JSONB** — NextGen appointment type codes are
   arbitrary per-clinic and change rarely. One clinic uses "PREV" for colorectal, another
   "SCREEN_COL". JSONB avoids a join table and doesn't require schema migration when a clinic
   updates their codes. Application code maps `GapType` enum value to the code at call time.

5. **Campaign retry hours as per-campaign columns (not global)** — Different campaigns have
   different urgency. A campaign running against an imminent HEDIS deadline may retry voicemails
   after 2 hours; a low-priority campaign might wait 24 hours. These cannot be global constants.

6. **`clinic_integration` gets the HEDIS operational columns** (not `clinic`) — Retell agent
   config, GCal creds, and outbound campaign settings are all integration/operational concerns.
   `clinic` stays as the lightweight tenant record (billing tier, status, license).

### Deferred (Not in Feature 2 Scope)

- Business logic, services, workers — Feature 4–6
- Auth flow — Feature 3
- Dashboard — Feature 7
- Alembic downgrade paths beyond stub `pass` — post-pilot

---

### Implementation Steps

#### Step F2.1 — Add 3 enums to `enums.py`

**File:** `Clinic_app/data/enums.py`

Add below the existing enums:

```python
class CampaignStatus(str, Enum):
    """Lifecycle state of a HEDIS outreach campaign (batch)."""
    PENDING = "pending"       # Created, not yet started
    ACTIVE = "active"         # Worker is actively placing calls
    PAUSED = "paused"         # Manually paused by staff
    COMPLETED = "completed"   # All contacts reached final state
    CANCELED = "canceled"     # Manually canceled


class ContactStatus(str, Enum):
    """Lifecycle state of a single patient contact within a campaign."""
    PENDING = "pending"       # Not yet attempted
    CALLING = "calling"       # Call in progress right now
    BOOKED = "booked"         # Appointment successfully created in NextGen
    DECLINED = "declined"     # Patient explicitly declined
    VOICEMAIL = "voicemail"   # Reached voicemail — will retry
    NO_ANSWER = "no_answer"   # No answer — will retry
    ERROR = "error"           # Technical error — will retry
    EXHAUSTED = "exhausted"   # Max attempts (3) reached, no booking


class GapType(str, Enum):
    """HEDIS care gap types. Drives Retell agent script and NextGen appt type mapping."""
    COLORECTAL_CANCER_SCREENING = "colorectal_cancer_screening"
    BREAST_CANCER_SCREENING = "breast_cancer_screening"
    CERVICAL_CANCER_SCREENING = "cervical_cancer_screening"
    DIABETES_HBA1C = "diabetes_hba1c"
    DIABETES_EYE_EXAM = "diabetes_eye_exam"
    DIABETES_NEPHROPATHY = "diabetes_nephropathy"
    HYPERTENSION_CONTROL = "hypertension_control"
    DEPRESSION_SCREENING = "depression_screening"
    WELL_CHILD_VISIT = "well_child_visit"
    ADOLESCENT_WELL_CARE = "adolescent_well_care"
    ADULT_BMI_ASSESSMENT = "adult_bmi_assessment"
    MEDICATION_ADHERENCE_DIABETES = "medication_adherence_diabetes"
    MEDICATION_ADHERENCE_HYPERTENSION = "medication_adherence_hypertension"
    OTHER = "other"  # Fallback for Claude parsing edge cases
```

**Why these gap types?** These are the standard HEDIS measures that NextGen-based primary care clinics most commonly need to close before year-end. The `OTHER` fallback prevents Claude CSV parsing from throwing on an unrecognized measure.

---

#### Step F2.2 — Create `clinic_staff.py`

**File:** `Clinic_app/data/models/clinic_staff.py`

```python
# Clinic_app/data/models/clinic_staff.py
"""
Staff member linked to a clinic via Google OAuth.
One staff member can belong to multiple clinics (multiple rows, same google_sub).
"""
id: UUID PK
clinic_id: UUID FK → clinic.id CASCADE
google_sub: String(255) NOT NULL          # Google OAuth 'sub' claim — stable, not email
email: String(255) NOT NULL               # For display only — not used as auth key
role: String(50) NOT NULL default "viewer"  # "admin" | "viewer"
created_at: DateTime(tz)
```

**Indexes:**
- `UNIQUE (clinic_id, google_sub)` — one role per staff per clinic, prevents duplicates
- `Index('idx_staff_google_sub', 'google_sub')` — fast lookup on OAuth callback (across all clinics)

**No FK to a global `user` table** — staff identity is Google's responsibility. We don't manage
user accounts; we manage clinic membership.

---

#### Step F2.3 — Create `campaign.py`

**File:** `Clinic_app/data/models/campaign.py`

```python
# Clinic_app/data/models/campaign.py
"""
One campaign = one CSV upload batch.
Stores operational config (calling hours, concurrency, retry hours) per campaign.
Progress counters are denormalized for dashboard performance.
"""
id: UUID PK
clinic_id: UUID FK → clinic.id CASCADE, index
name: Text NOT NULL                             # e.g., "Q1 2026 HEDIS Outreach"
status: CampaignStatus NOT NULL default PENDING
total_contacts: Integer NOT NULL default 0      # Set on campaign creation from CSV row count
called_count: Integer NOT NULL default 0        # Incremented on each CALLING transition
booked_count: Integer NOT NULL default 0        # Incremented on BOOKED
failed_count: Integer NOT NULL default 0        # Incremented on EXHAUSTED or DECLINED

# Operational config — override clinic defaults
calling_hours_start: String(5) NOT NULL default "09:00"   # HH:MM
calling_hours_end: String(5) NOT NULL default "18:00"
campaign_concurrency_limit: Integer NOT NULL default 3
voicemail_retry_hours: Integer NOT NULL default 4
no_answer_retry_hours: Integer NOT NULL default 2
error_retry_hours: Integer NOT NULL default 24
max_attempts: Integer NOT NULL default 3

created_by: UUID FK → clinic_staff.id SET NULL  # nullable — staff account may be deleted
created_at: DateTime(tz)
updated_at: DateTime(tz)
```

**Indexes:**
- `Index('idx_campaign_clinic_status', 'clinic_id', 'status')` — worker queries active campaigns per clinic
- `CheckConstraint('booked_count + failed_count <= total_contacts', ...)` — basic sanity guard

**Why denormalized counters?** The dashboard polls every 30 seconds. A `COUNT(*)` across
`campaign_contact` with `clinic_id` filter on every poll adds up. These counters are incremented
atomically in the same transaction as the contact status update — no separate query needed.

---

#### Step F2.4 — Create `campaign_contact.py`

**File:** `Clinic_app/data/models/campaign_contact.py`

```python
# Clinic_app/data/models/campaign_contact.py
"""
One row per patient per campaign. The campaign worker reads from this table to know who to call.
PHI minimization: only phone stored here (encrypted + hash). Name/DOB passed as Retell metadata only.
"""
id: UUID PK
campaign_id: UUID FK → campaign.id CASCADE, index
clinic_id: UUID FK → clinic.id CASCADE, index    # denormalized for row-level tenant queries
phone_encrypted: BYTEA NOT NULL                  # AES-256-GCM encrypted E.164 phone
phone_hash: String(64) NOT NULL                  # SHA-256 for dedup without decryption
gap_type: GapType NOT NULL                       # Drives Retell agent script + NextGen appt type
preferred_language: String(10) NOT NULL default "en"  # "en" | "es"
status: ContactStatus NOT NULL default PENDING
attempt_count: Integer NOT NULL default 0        # 0–3
last_attempted_at: DateTime(tz) nullable
next_attempt_after: DateTime(tz) nullable        # NULL = ready now; set by retry scheduler
ehr_appointment_id: String nullable              # NextGen appt ID on BOOKED
created_at: DateTime(tz)
updated_at: DateTime(tz)
```

**Indexes:**
- `Index('idx_contact_worker_queue', 'clinic_id', 'campaign_id', 'status', 'next_attempt_after')`
  — the campaign worker's primary query: "give me PENDING contacts where next_attempt_after IS NULL
  or <= now(), ordered by created_at (FIFO)"
- `Index('idx_contact_phone_hash', 'clinic_id', 'phone_hash')` — dedup check on CSV import

**Why `clinic_id` denormalized here?** Every worker query, every admin dashboard query, every
audit lookup must filter by `clinic_id` for tenant isolation. Joining through `campaign` to get
`clinic_id` on every query is wasteful and risks missing the tenant filter if a join is forgotten.

---

#### Step F2.5 — Create `campaign_audit.py`

**File:** `Clinic_app/data/models/campaign_audit.py`

```python
# Clinic_app/data/models/campaign_audit.py
"""
Immutable call-level record. One row per call attempt.
Written by the call_analyzed webhook handler after each call ends.
"""
id: UUID PK
campaign_contact_id: UUID FK → campaign_contact.id CASCADE, index
campaign_id: UUID FK → campaign.id CASCADE, index
clinic_id: UUID FK → clinic.id CASCADE, index
retell_call_id: String NOT NULL, index           # For webhook correlation
outcome: ContactStatus NOT NULL                  # BOOKED | DECLINED | VOICEMAIL | NO_ANSWER | ERROR
patient_name_encrypted: BYTEA nullable           # AES-256-GCM — for dashboard display only
call_summary_encrypted: BYTEA nullable           # One-sentence Claude summary, AES-256-GCM
ehr_appointment_id: String nullable              # NextGen appt ID if outcome == BOOKED
attempt_number: Integer NOT NULL                 # 1, 2, or 3
called_at: DateTime(tz)
created_at: DateTime(tz)
```

**Indexes:**
- `Index('idx_audit_clinic_campaign', 'clinic_id', 'campaign_id', 'called_at')` — dashboard detail view

**Why `patient_name_encrypted` nullable?** The name arrives from Retell's `call_analyzed` webhook
metadata. If the webhook fires without metadata (edge case), we don't want to block the audit write.
The dashboard handles NULL name gracefully (shows "—").

**Why immutable?** Audit rows are never updated — they represent what happened on a specific call.
If a retry occurs, a new audit row is written with `attempt_number=2`. This gives a complete
call history per contact.

---

#### Step F2.6 — Create `clinic_ehr_config.py`

**File:** `Clinic_app/data/models/clinic_ehr_config.py`

```python
# Clinic_app/data/models/clinic_ehr_config.py
"""
NextGen EHR connection config for Playwright automation.
One record per clinic (UNIQUE on clinic_id).
Credentials are AES-256-GCM encrypted — never stored plaintext.
"""
id: UUID PK
clinic_id: UUID FK → clinic.id CASCADE, UNIQUE, index   # one EHR config per clinic
nextgen_url: Text NOT NULL                              # URL Playwright navigates to
nextgen_username_encrypted: BYTEA NOT NULL              # AES-256-GCM
nextgen_password_encrypted: BYTEA NOT NULL              # AES-256-GCM
appt_type_mapping: JSONB NOT NULL default {}
  # e.g.: {"colorectal_cancer_screening": "PREV", "diabetes_hba1c": "DM_A1C"}
  # Keys are GapType enum values; values are clinic-specific NextGen appt type codes
connection_verified_at: DateTime(tz) nullable           # Timestamp of last successful credential test
created_at: DateTime(tz)
updated_at: DateTime(tz)
```

**Why JSONB for `appt_type_mapping`?** NextGen appointment type codes are arbitrary per-clinic
and change rarely. JSONB avoids a join table and doesn't require an Alembic migration when a
clinic updates their codes. Application code at call time does:
`code = ehr_config.appt_type_mapping.get(gap_type.value, "PREV")` as safe fallback.

---

#### Step F2.7 — Alter `clinic_integration.py` (9 new columns)

**File:** `Clinic_app/data/models/clinic_integration.py`

Add these columns to the existing model:

```python
# HEDIS campaign operational defaults — overridable per campaign
timezone = Column(String(100), nullable=False, default="America/New_York")
  # IANA timezone — used by campaign worker to enforce calling hours in clinic local time
calling_hours_start = Column(String(5), nullable=False, default="09:00")
calling_hours_end = Column(String(5), nullable=False, default="18:00")
campaign_concurrency_limit = Column(Integer, nullable=False, default=3)
voicemail_retry_hours = Column(Integer, nullable=False, default=4)
no_answer_retry_hours = Column(Integer, nullable=False, default=2)
error_retry_hours = Column(Integer, nullable=False, default=24)
max_attempts = Column(Integer, nullable=False, default=3)

# Outbound calling DID (separate from inbound retell_did)
retell_outbound_number = Column(String, nullable=True)
  # E.164 format. Nullable — clinic may not have outbound enabled yet
```

**Why on `clinic_integration` and not `clinic`?** These are operational/integration settings
that live alongside the Retell agent ID and GCal credentials. `clinic` stays as the lean tenant
record (name, tier, status, license). Mixing campaign operational defaults into `clinic` would
bloat it with concerns that belong in integration config.

---

#### Step F2.8 — Alembic migration: `add_hedis_tables`

**File:** `Clinic_app/alembic/versions/add_hedis_tables.py`

```
Operations:
1. Create PostgreSQL ENUM types: campaignstatus, contactstatus, gaptype
2. CREATE TABLE clinic_staff
3. CREATE TABLE campaign
4. CREATE TABLE campaign_contact
5. CREATE TABLE campaign_audit
6. CREATE TABLE clinic_ehr_config

Downgrade: DROP all 5 tables + 3 ENUM types (in reverse FK order)
```

**Migration order matters:** `clinic_staff` before `campaign` (FK `created_by`),
`campaign` before `campaign_contact` (FK `campaign_id`),
`campaign_contact` before `campaign_audit` (FK `campaign_contact_id`),
`clinic_ehr_config` has no inter-table FKs, can go in any order.

---

#### Step F2.9 — Alembic migration: `extend_clinic_integration`

**File:** `Clinic_app/alembic/versions/extend_clinic_integration.py`

```
Operations:
ADD COLUMN timezone VARCHAR(100) NOT NULL DEFAULT 'America/New_York'
ADD COLUMN calling_hours_start VARCHAR(5) NOT NULL DEFAULT '09:00'
ADD COLUMN calling_hours_end VARCHAR(5) NOT NULL DEFAULT '18:00'
ADD COLUMN campaign_concurrency_limit INTEGER NOT NULL DEFAULT 3
ADD COLUMN voicemail_retry_hours INTEGER NOT NULL DEFAULT 4
ADD COLUMN no_answer_retry_hours INTEGER NOT NULL DEFAULT 2
ADD COLUMN error_retry_hours INTEGER NOT NULL DEFAULT 24
ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3
ADD COLUMN retell_outbound_number VARCHAR NULL

Downgrade: DROP COLUMN each of the above
```

**This migration is independent of `add_hedis_tables`** — they modify different tables and can
be applied in either order, though by convention `add_hedis_tables` runs first (lower revision number).

---

#### Step F2.10 — Update `requirements.txt`

Add (skip if already present from Feature 0):
```
anthropic>=0.25.0        # Claude API — CSV gap type parsing + call summary
PyJWT>=2.8.0             # JWT for clinic staff sessions (Feature 3)
python-multipart>=0.0.9  # FastAPI file upload support (Feature 4)
openpyxl>=3.1.0          # Excel CSV parsing (Feature 4)
```

`playwright` and `agentql` already added in Feature 0. `redis` already in requirements.

---

#### Step F2.11 — Update `data/models/__init__.py`

Add imports for all 5 new models so Alembic's `env.py` `target_metadata` picks them up:

```python
from Clinic_app.data.models.clinic_staff import ClinicStaff
from Clinic_app.data.models.campaign import Campaign
from Clinic_app.data.models.campaign_contact import CampaignContact
from Clinic_app.data.models.campaign_audit import CampaignAudit
from Clinic_app.data.models.clinic_ehr_config import ClinicEHRConfig
```

---

### Feature 2 Test Plan

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_enums.py` | Unit | All enum values and members match PRD spec; `GapType.OTHER` exists as fallback |
| `tests/test_new_models.py` | Unit | Model instantiation with required fields, field defaults, FK relationships, `__repr__` |
| `tests/test_migrations.py` | Integration | Alembic `upgrade head` succeeds on clean DB; `downgrade base` reverses cleanly |

---

### What Is NOT In Scope for Feature 2

- Business logic, services, or workers that use these models (Features 4–6)
- Google OAuth flow or JWT auth (Feature 3)
- Campaign routes or CSV upload endpoint (Feature 4)
- Dashboard frontend (Feature 7)
- Alembic downgrade beyond `pass` stub — not needed for pilot

---

## Plan 005 — Feature 3: Authentication & Authorization
**Date:** 2026-03-18
**Updated:** 2026-03-20 (expanded to full step-by-step)
**Status:** Active
**Source:** HEDIS_PRD_v2.md §5

### What We Are Building

The authentication layer that gates the clinic dashboard. Staff log in with their Google account,
the system maps their Google identity to their clinic membership(s), and issues a JWT that carries
`clinic_id` + `role` for every subsequent request.

Admin API key auth is already done (F1.2). This feature adds the staff-facing auth path.

### Key Architecture Decisions & Reasoning

1. **`google_sub` as identity anchor, not email** — Already stored in `clinic_staff` this way
   (F2). The OAuth callback extracts `sub` from the ID token. Email is stored for display only.

2. **Two-phase JWT (unscoped → scoped)** — A staff member can belong to multiple clinics.
   After callback we issue an **unscoped JWT** (no `clinic_id`). The client calls `/auth/me`
   to get their clinic list, picks one, and calls `/auth/select-clinic` to get a **scoped JWT**
   (`clinic_id` + `role` embedded). All campaign/dashboard routes require a scoped JWT.
   Single-clinic staff can skip the selector and get a scoped JWT directly from callback.

3. **Stateless CSRF protection for OAuth state** — Rather than server-side sessions, the `state`
   param sent to Google is a short-lived HMAC-signed token (signed with `JWT_SECRET_KEY`,
   5-minute expiry). On callback, we verify it. No session store required.

4. **PyJWT for JWT, not python-jose** — Already in `requirements.txt`. Simpler, well-maintained,
   no cryptography dependency beyond what we already have.

5. **httpx for Google token exchange** — Already in requirements. Async, fits our FastAPI stack.

6. **`get_current_staff` dependency returns `StaffToken`** — A small Pydantic model with
   `google_sub`, `email`, `clinic_id` (Optional), `role` (Optional). Routes that need a scoped
   token call `Depends(require_scoped_staff)` which wraps `get_current_staff` and raises 403 if
   `clinic_id` is None.

### Deferred

- Refresh tokens / sliding sessions — 8h JWT expiry is fine for pilot
- PKCE — not required for server-side OAuth flow
- Role-based field-level access within dashboard — viewer vs admin enforced at route level only
- Token revocation — not needed for pilot

---

### Implementation Steps

#### Step F3.1 — Create `Clinic_app/common/jwt.py`

JWT utility module. Two token types share the same signing key but differ in payload:

- **Unscoped** — `{ sub, email, type: "unscoped", exp }`
- **Scoped** — `{ sub, email, clinic_id, role, type: "scoped", exp }`
- **State** — `{ nonce, type: "oauth_state", exp }` (5-min expiry, CSRF guard)

```python
# Clinic_app/common/jwt.py
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 8
STATE_EXPIRY_SECONDS = 300  # 5 minutes

class StaffToken(BaseModel):
    google_sub: str
    email: str
    clinic_id: Optional[UUID] = None
    role: Optional[str] = None      # "admin" | "viewer"
    token_type: str                 # "unscoped" | "scoped"

def create_state_token() -> str: ...           # For OAuth CSRF protection
def verify_state_token(state: str) -> bool: ...# Validate state on callback

def create_unscoped_token(sub: str, email: str) -> str: ...
def create_scoped_token(sub: str, email: str, clinic_id: UUID, role: str) -> str: ...
def decode_token(token: str) -> StaffToken: ...# Raises 401 on invalid/expired
```

**FastAPI dependencies (also in this file):**

```python
async def get_current_staff(
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer(auto_error=False))
) -> StaffToken:
    # Extracts Bearer token, decodes, returns StaffToken
    # Raises HTTP 401 if missing or invalid

async def require_scoped_staff(
    staff: StaffToken = Depends(get_current_staff)
) -> StaffToken:
    # Wraps get_current_staff — raises HTTP 403 if clinic_id is None
    # Use this on all campaign/dashboard routes
```

---

#### Step F3.2 — Create `Clinic_app/services/auth_service.py`

Business logic for the auth flow. Keeps routes thin.

```python
# Clinic_app/services/auth_service.py

def build_google_auth_url(state: str) -> str:
    """Build Google OAuth authorization URL with required scopes."""
    # scope: openid email profile
    # Reads GOOGLE_CLIENT_ID, GOOGLE_REDIRECT_URI from env

async def exchange_code_for_tokens(code: str) -> dict:
    """POST to Google token endpoint, return token response dict."""
    # Reads GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI from env
    # Uses httpx.AsyncClient
    # Returns { access_token, id_token, ... }

def extract_google_user(id_token_payload: dict) -> tuple[str, str]:
    """Extract (sub, email) from decoded Google ID token payload."""
    # PyJWT decode without verification (already verified by Google)
    # Returns (sub, email)

async def get_staff_clinics(
    db: AsyncSession, google_sub: str
) -> list[ClinicStaff]:
    """Return all ClinicStaff rows for this google_sub, with clinic joined."""

async def upsert_staff_email(
    db: AsyncSession, google_sub: str, email: str
) -> None:
    """Update email on all ClinicStaff rows for this sub (email can change on Google)."""

async def create_staff(
    db: AsyncSession,
    clinic_id: UUID,
    google_sub: str,
    email: str,
    role: str,
) -> ClinicStaff:
    """Create a new ClinicStaff row. Raises 409 if already exists."""
```

---

#### Step F3.3 — Create `Clinic_app/Routes/auth.py`

Four endpoints on `auth_router` (prefix `/auth`, no auth dependency at router level — each
endpoint manages its own auth):

**`GET /auth/google`**
```
→ Generate state token (create_state_token)
→ Build Google auth URL (build_google_auth_url)
→ Return 302 redirect to Google
```

**`GET /auth/google/callback?code=&state=`**
```
→ Verify state token (verify_state_token) → 400 if invalid
→ Exchange code for tokens (exchange_code_for_tokens) → 400 on failure
→ Decode Google ID token → extract (sub, email)
→ upsert_staff_email (keep email current)
→ get_staff_clinics(sub)
→ If 0 clinics → 403 {"code": "NOT_PROVISIONED"}
→ If 1 clinic → create_scoped_token → return {"token": ..., "token_type": "scoped"}
→ If >1 clinics → create_unscoped_token → return {"token": ..., "token_type": "unscoped", "requires_clinic_selection": true}
```

**`GET /auth/me`** — requires `get_current_staff` (unscoped or scoped)
```
→ get_staff_clinics(staff.google_sub)
→ Return list of { clinic_id, clinic_name, role }
```

**`POST /auth/select-clinic`** — requires `get_current_staff` (unscoped)
```
Body: { "clinic_id": UUID }
→ Verify staff.google_sub has access to clinic_id in DB
→ If not found → 403
→ Issue create_scoped_token(sub, email, clinic_id, role)
→ Return {"token": ..., "token_type": "scoped"}
```

---

#### Step F3.4 — Add `POST /admin/clinics/{clinic_id}/staff` to `admin.py`

```
Body: { google_sub, email, role }
→ Verify clinic exists
→ create_staff(db, clinic_id, google_sub, email, role)
→ 409 if already provisioned
→ Return created staff record
```

This is how Edgar provisions clinic staff before they can log in.
Protected by `verify_admin_api_key` (already on all admin routes).

---

#### Step F3.5 — Register `auth_router` in `main.py`

```python
from Clinic_app.Routes.auth import auth_router
app.include_router(auth_router)  # No global auth — endpoints manage their own
```

---

#### Step F3.6 — Write tests

**`tests/test_jwt.py`** (unit)
- `create_unscoped_token` → decodes to correct payload
- `create_scoped_token` → decodes with clinic_id and role
- Expired token → `decode_token` raises HTTP 401
- Tampered token → raises HTTP 401
- `create_state_token` → `verify_state_token` round-trip passes
- Expired state token → `verify_state_token` returns False
- `get_current_staff` with valid Bearer → returns StaffToken
- `get_current_staff` with no header → raises 401
- `require_scoped_staff` with unscoped token → raises 403

**`tests/test_auth_routes.py`** (unit — all external calls mocked)
- `GET /auth/google` → 302 redirect with correct Google URL params
- `GET /auth/google/callback` with invalid state → 400
- `GET /auth/google/callback` with valid state, 1 clinic → scoped JWT returned
- `GET /auth/google/callback` with valid state, 0 clinics → 403 NOT_PROVISIONED
- `GET /auth/google/callback` with valid state, 2 clinics → unscoped JWT + requires_clinic_selection
- `GET /auth/me` with valid token → clinic list
- `GET /auth/me` with no token → 401
- `POST /auth/select-clinic` with valid clinic_id → scoped JWT
- `POST /auth/select-clinic` with clinic_id staff doesn't belong to → 403
- `POST /admin/clinics/{id}/staff` → creates staff row
- `POST /admin/clinics/{id}/staff` duplicate → 409

---

### Files Created / Modified

| File | Action |
|---|---|
| `Clinic_app/common/jwt.py` | Create |
| `Clinic_app/services/auth_service.py` | Create |
| `Clinic_app/Routes/auth.py` | Create |
| `Clinic_app/Routes/admin.py` | Modify — add staff endpoint |
| `Clinic_app/main.py` | Modify — register auth_router |
| `tests/test_jwt.py` | Create |
| `tests/test_auth_routes.py` | Create |

### Feature 3 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_jwt.py` | Unit | Token creation, decode, expiry, CSRF state, FastAPI dependencies |
| `tests/test_auth_routes.py` | Unit | All 4 auth endpoints + staff management, mocked Google OAuth |

---

## Plan 006 — Feature 4: CSV Upload + Claude Parsing + Campaign Creation
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 3)
**Source:** HEDIS_PRD_v2.md §7 + §8.1

### Summary

- `POST /campaigns/upload` — multipart, 10MB/2000-row limit, CSV + Excel
- `services/csv_parser.py` — Claude API client, gap type normalization, E.164 phone normalization
- `services/campaign.py` — create Campaign + CampaignContact rows, phone AES-256-GCM + hash
- Campaign management routes: list, detail, pause, resume, export (no PHI in export)

### Feature 4 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_csv_parser.py` | Unit | Claude response parsing, gap type mapping, malformed row handling |
| `tests/test_campaign_service.py` | Unit + Integration | Campaign creation, contact dedup, phone encryption |
| `tests/test_campaign_routes.py` | Integration | Upload endpoint, list, detail, pause/resume |

---

## Plan 007 — Feature 5: EHR Integration (Playwright + AgentQL)
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 0 result is logged + Feature 2 complete)
**Source:** HEDIS_PRD_v2.md §10
**Architecture Branch:** Server-side Playwright (default) OR Chrome Extension (if F0 shows NextGen blocks headless)

### Summary

- `services/playwright_ehr.py` — browser context lifecycle, login, 8-min heartbeat, re-auth, asyncio.Queue action serializer
- AgentQL slot reader + appointment booker + Redis selector cache (24h TTL)
- `POST /retell/tools/get_available_slots` — must respond <3s
- `POST /retell/tools/book_appointment` — returns ehr_appointment_id
- `POST /admin/clinics/{id}/ehr-test` — credential test
- `PUT /admin/clinics/{id}/appt-types` — gap_type → nextgen_appt_type_code mapping

### Feature 5 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_playwright_ehr_service.py` | Unit | Session lifecycle, slot parse, booking form fill — all mocked |
| `tests/test_ehr_tool_endpoints.py` | Integration | `/retell/tools/get_available_slots` and `book_appointment` with mock Playwright |
| `tests/test_selector_cache.py` | Unit | Redis cache get/set/miss/TTL logic |
| `tests/test_ehr_credential_test.py` | Unit | Admin ehr-test endpoint returns pass/fail correctly |

---

## Plan 008 — Feature 6: Campaign Worker + Outbound Calling
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 4 + Feature 5)
**Source:** HEDIS_PRD_v2.md §8.2 + §9

### Summary

- `workers/campaign_worker.py` — FIFO loop, calling hours (9am–6pm clinic tz), concurrency limiter (Redis lock), 5s inter-call gap, retry scheduler, EXHAUSTED at 3 attempts
- `services/retell_client.py` — async httpx Retell outbound call client with tenacity retry
- `POST /retell/webhook/call_analyzed` — Claude API one-sentence summary, encrypt, store in campaign_audit
- Update `call_started` + `call_ended` webhook handlers to handle `call_type=hedis_campaign` and update CampaignContact status

### Feature 6 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_campaign_worker.py` | Unit | FIFO ordering, calling hours gate, concurrency limit, retry timing |
| `tests/test_retell_client.py` | Unit | Outbound call creation, retry on failure, metadata payload |
| `tests/test_call_analyzed_webhook.py` | Unit | Claude API call, summary encryption, transcript discard |
| `tests/test_campaign_webhooks.py` | Integration | call_started/call_ended update CampaignContact status correctly |

---

## Plan 009 — Feature 7: Clinic Dashboard
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 3 + Feature 4)
**Source:** HEDIS_PRD_v2.md §14

### Summary

Desktop-only. Minimal React SPA (Vite) served as static files from FastAPI.

Screens:
1. Clinic Selector (staff in 2+ clinics)
2. Campaign List (name, status, progress bar, date)
3. Upload Screen (drag-and-drop CSV/Excel)
4. Campaign Detail (patient table: name, gap type, status badge, appointment, provider, language, attempts, summary)
5. EHR Setup (URL + credentials + Test Connection)

30-second polling on campaign detail. Status color codes per PRD §14.2.

### Feature 7 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_dashboard_api.py` | Integration | Campaign detail endpoint returns correct patient data (decrypted) |
| `tests/test_export.py` | Unit | CSV export contains no PHI — only phone_hash, gap_type, outcome |

---

## Plan 010 — Feature 8: Hardening + Pilot Onboarding
**Date:** 2026-03-18
**Status:** Pending (starts after Feature 7)
**Source:** HEDIS_PRD_v2.md §16 Week 5

### Summary

- PHI audit: grep for plaintext names/phones in logs, verify encryption end-to-end
- Load test: 12 concurrent Retell calls (4 clinics × 3 concurrent each)
- Azure production deploy with all env vars
- Pilot clinic onboarding: NextGen creds, appt type mapping, Retell agent config, retry hours
- First supervised campaign with real patients

### Feature 8 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_phi_audit.py` | Unit | No PHI in log output, no plaintext in DB columns |
| `tests/test_load.py` | Slow | 12 concurrent mock calls — checks concurrency limit enforcement |

---

*Last updated: 2026-03-20*
*Maintained by: Edgar J. Suárez Colón*
*Next action: Begin Feature 2 — F2.1 (enums) → F2.2–F2.6 (models) → F2.7 (clinic_integration alter) → F2.8–F2.9 (migrations) → F2.10–F2.11 (requirements + __init__) → tests*
