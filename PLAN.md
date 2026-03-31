# PLAN.md — CallCenterAI HEDIS Implementation Plans

> This file tracks all implementation plans in chronological order.
> Plans are never deleted — superseded plans are marked [SUPERSEDED].
> Each plan includes what was decided, why, and what was deferred.
> Source of truth for all feature work: HEDIS_PRD_v2.md
> Architecture reference: INFRASTRUCTURE.md
> HIPAA Security Rule compliance audit: HIPAA_COMPLIANCE_AUDIT.md
> Session rules: CLAUDE.md

---

## Plan Index

| # | Date | Title | Status |
|---|---|---|---|
| 001 | 2026-03-18 | MVP Roadmap — Full Feature Inventory | Active (reference) |
| 002 | 2026-03-18 | Feature 0 — Playwright Validation Gate | ✅ Complete (NextGen validated 2026-03-20) |
| 003 | 2026-03-18 | Feature 1 — Pre-HEDIS Codebase Fixes | ✅ Complete |
| 004 | 2026-03-18 | Feature 2 — New Schema + Migrations | ✅ Complete |
| 005 | 2026-03-18 | Feature 3 — Authentication & Authorization | ✅ Complete |
| 006 | 2026-03-20 | Feature 4 — CSV Upload + Parsing + Campaign Creation + Clinic Settings | ✅ Complete |
| 007 | 2026-03-18 | Feature 5 — EHR Integration (Playwright + AgentQL) | ✅ Complete |
| 008 | 2026-03-18 | Feature 6 — Campaign Worker + Outbound Calling | ✅ Complete |
| 011 | 2026-03-22 | Retell agent playbook + E2E voice gate + post-call staff notes | ✅ Partially complete — superseded by Plan 014 (Sprint B + C absorbed) |
| 013 | 2026-03-23 | Business Logic Decisions — Gap Types, Scheduling Rules, Schema Additions | ✅ Partially complete — critical subset done in Plan 014 Sprint A; complex rules deferred post-MVP |
| 015 | 2026-03-23 | HIPAA Security Rule Compliance Audit | ✅ Critical/high/medium findings addressed — active reference |
| 016 | 2026-03-23 | Basic application logging (structured + PHI-safe) | ✅ Complete (2026-03-25) |
| 017 | 2026-03-25 | Choosable summarizer + CSV direct mapping + audit endpoint | ✅ Complete (2026-03-26) |
| 014 | 2026-03-23 | **MVP Sprint — Test Call by March 27** | **🔴 ACTIVE — E2E gate remaining** |
| 012 | 2026-03-23 | API security hardening + HTTP rate limits + Claude rate limits | Pending — after MVP test call; before Plan 009 |
| 018 | 2026-03-26 | AgentQL → Browser-Use + Azure OpenAI (HIPAA-safe EHR automation) | ✅ Complete (2026-03-27) |
| 019 | 2026-03-27 | EHR automation architecture — MVP path vs post-MVP (selectors, slot cache, multi-EHR) | Active (reference) |
| 020 | 2026-03-30 | Unified Retell webhook — single URL + `event` dispatch | Complete (2026-03-30) |
| 009 | 2026-03-18 | Feature 7 — Clinic Dashboard | Pending — after MVP test call + Plan 012 |
| 010 | 2026-03-18 | Feature 8 — Hardening + Pilot Onboarding | Pending — last, after dashboard |

### Implementation order (current — revised 2026-03-23 for MVP sprint)

**THIS WEEK (MVP goal: Edgar can upload a fake HEDIS CSV and watch the system make a real call):**

1. **Plan 014 Sprint A** — Fix GapType enum mismatch + add missing ContactStatus values + hospital_flu columns. This is blocking a test call.
2. **Plan 014 Sprint B** — Create `docs/retell_agent_playbook.md` + audit retell.py/worker metadata alignment. Lets Edgar configure the Retell agent in the dashboard.
3. **Plan 020** — **Complete.** `POST /retell/webhook` + `_handle_call_*`; playbook + `docs/local_test_guide.md` updated. Register `{APP_BASE_URL}/retell/webhook` in Retell.
4. **Plan 014 Sprint C** — Use hardcoded scheduling defaults (no new DB tables), simplified staff notes extractor, E2E gate (upload CSV → call fires → correct script → slot/booking path → DB updated).
5. **Plan 016** — Basic logging: app-wide log configuration, structured/consistent levels, PHI-safe masking (phone numbers, etc. per CLAUDE.md), correlation where useful for worker + Retell webhooks + tool calls. Supports Sprint C “watch worker log” and production troubleshooting.

**AFTER MVP TEST CALL CONFIRMED:**

6. **Plan 012** — API security hardening before any real clinic uses the system. Includes **M2 (CORS + rate limiting + security headers)** from the HIPAA audit — three sub-tasks:
   - **CORS:** Add `CORSMiddleware` with explicit allowed origins list (required before any web dashboard is built)
   - **Rate limiting:** Add `slowapi` throttle on auth endpoints and Retell webhooks (prevents DB exhaustion)
   - **Security headers:** One middleware pass setting `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` on all responses
7. **Plan 018** — Replace AgentQL with Browser-Use (open-source) + Azure OpenAI. Required before pilot with real patients — resolves HIPAA audit finding T-01 (AgentQL has no BAA). See full plan below.
8. **Plan 009 (Feature 7)** — React dashboard once the core call path is trusted.
9. **Plan 013 complex rules** — `clinic_insurance_rules`, `clinic_scheduling_rules` tables, double-booking enforcement, insurance year eligibility, hospital_flu telehealth mode. Build these against a working system.
10. **Plan 010 (Feature 8)** — Production deploy, PHI audit, pilot onboarding, load tests. Includes Azure OpenAI private endpoints + Zero Data Retention approval (prerequisite for Plan 018 in production).
11. **Plan 015** — HIPAA Security Rule compliance audit (`HIPAA_COMPLIANCE_AUDIT.md`, 2026-03-23). Use it as the running checklist for critical/high findings; remediation overlaps **Plan 012** (e.g. webhook integrity, rate limits, OpenAPI exposure) and **Plan 010** (production hardening, operational PHI controls).

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

### Current State (HEDIS MVP — through Feature 4)

The Phase 1 GCal-based booking system (inbound calls) remains built and tested. On top of that, the following HEDIS milestones are **implemented in code** (see Plan Index):

- **Feature 0:** NextGen headless Playwright + AgentQL validated (pilot clinic).
- **Feature 1:** Routers registered in `main.py`; admin API key auth; booking reaper (APScheduler); Redis singleton.
- **Feature 2:** HEDIS schema (campaigns, contacts, audit, clinic_staff, clinic_ehr_config, clinic_integration extensions); multiple Alembic migrations (including `measurement_year`).
- **Feature 3:** Google OAuth + JWT (`/auth/*`), scoped clinic selection, staff provisioning via admin routes.
- **Feature 4:** CSV/XLSX upload + Claude parsing, campaign + contact creation with dedup, clinic settings GET/PATCH, campaign management + PHI-safe export (see Plan 006).

**Inventory (approximate):** 5 Alembic version files under `Clinic_app/alembic/versions/`; 19+ pytest modules under `tests/`. Routers in `main.py` include health, admin, provider, retell, auth, clinic, and campaign.

**Next for HEDIS MVP:** Feature 5 (NextGen EHR tools + Playwright service), then Feature 6 (campaign worker + outbound Retell + campaign webhooks). Legacy Retell availability still uses Google Calendar until EHR tools ship.

### What Is Missing for HEDIS MVP

See Features 5–8 below (EHR automation, outbound worker, dashboard UI, hardening/pilot).

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
**Status:** Complete (pilot NextGen validated 2026-03-20 — see `PROGRESS.txt`)
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
**Status:** Complete
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
**Status:** Complete
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
**Status:** Complete
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

## Plan 006 — Feature 4: CSV Upload + Claude Parsing + Campaign Creation + Clinic Settings
**Date:** 2026-03-18
**Updated:** 2026-03-21 (marked complete — implementation reconciled with repository)
**Status:** Complete
**Source:** HEDIS_PRD_v2.md §7 + §8.1

**Implementation (repository):** `Clinic_app/Routes/campaigns.py`, `Clinic_app/Routes/clinic.py`, `Clinic_app/services/csv_parser.py`, `Clinic_app/services/campaign_service.py`, `Clinic_app/services/clinic_service.py`, Alembic `d4e5f6a7b8c9_add_measurement_year_to_campaign.py`; tests `test_csv_parser.py`, `test_campaign_service.py`, `test_campaign_routes.py`, `test_clinic_settings.py`, `test_measurement_year_dedup.py`.

### What We Are Building

The campaign creation pipeline. A clinic admin uploads a CSV of patients with HEDIS care gaps.
The system parses it (Claude API for gap type normalization), creates a Campaign record, and creates
one CampaignContact row per patient. Also adds the clinic settings API so admins can configure
calling hours, max attempts, and retry hours from the dashboard rather than requiring a superadmin.

### Key Architecture Decisions & Reasoning

1. **`measurement_year` on `Campaign` — cross-year HEDIS dedup**
   HEDIS is a yearly program. Insurance carriers send gap lists annually. If the same patient
   appears in a 2025 gap list AND a 2026 gap list, both are legitimate — they represent different
   measurement year obligations. However, if a patient appears in TWO 2025 gap lists (e.g., one
   from Medicare, one from Medicaid — dual eligibles), we must not call them twice for the same
   gap in the same year.

   **Dedup rule at CSV ingestion:**
   - Check: `clinic_id + phone_hash + gap_type + measurement_year`
   - If an active contact (not EXHAUSTED/DECLINED) already exists for all four → skip row,
     log as `already_active`, do not create duplicate
   - If a BOOKED contact already exists for all four → skip row, log as `already_booked`
   - If measurement_year differs → always create new contact (new year = new obligation)

2. **Claude API for CSV column normalization — not regex**
   Payer-submitted HEDIS CSVs have wildly inconsistent column names. One uses "Member Phone",
   another "contact_number", another "cell". One uses "Colorectal Cancer Screening", another
   "COL". Claude maps these to our internal schema reliably; regex would require per-payer
   maintenance. Claude is called once per upload (batch prompt for all rows), not once per row.

3. **E.164 phone normalization before encryption**
   All phones are normalized to E.164 (`+1XXXXXXXXXX`) before encryption and hashing.
   The SHA-256 hash is computed over the E.164 form — this ensures a phone stored as
   "787-555-1234" and "+17875551234" produce the same hash and dedup correctly.

4. **Clinic settings API — scoped JWT, admin role only for writes**
   Calling hours, max attempts, and retry hours are on `clinic_integration` (added in F2.7).
   Currently only the superadmin API key can touch this table. Clinic admins need to configure
   these from the dashboard without contacting Edgar. `PATCH /clinic/settings` requires
   `role=admin` in the scoped JWT. `GET /clinic/settings` is readable by any staff.

5. **Campaign defaults inherit from clinic settings at creation time**
   When a CSV is uploaded, the new Campaign row is initialized with the clinic's current
   `calling_hours_start`, `calling_hours_end`, `max_attempts`, etc. The campaign can then
   be further customized per-campaign after creation. This avoids the campaign worker having
   to join through `clinic_integration` on every tick.

6. **10MB / 2000-row limits on upload**
   Per PRD §7. Claude API prompt size is a constraint — 2000 rows fits safely in a single
   Anthropic API call for header/column normalization. Rows over the limit are rejected with
   a 422 explaining the limit, not silently truncated.

### Deferred (Not in Feature 4 Scope)

- Campaign worker / outbound calling (Feature 6)
- Retell webhook handlers (Feature 5/6)
- Dashboard frontend (Feature 7)
- Excel (.xlsx) upload — CSV only for pilot; openpyxl conversion deferred to v1.1
- Per-row retry customization (campaign-level only for now)

---

### Implementation Steps

#### Step F4.1 — Alembic migration: add `measurement_year` to `campaign`

**File:** `Clinic_app/alembic/versions/d4e5f6a7b8c9_add_measurement_year_to_campaign.py`

```python
# Revision chain: c3d4e5f6a7b8 → d4e5f6a7b8c9
def upgrade():
    op.add_column('campaign',
        sa.Column('measurement_year', sa.Integer(), nullable=False,
                  server_default=str(datetime.utcnow().year))
    )
    # Composite index for the cross-campaign dedup query
    op.create_index(
        'idx_contact_dedup',
        'campaign_contact',
        ['clinic_id', 'phone_hash', 'gap_type', 'measurement_year']
        # measurement_year joined through campaign — actual index in campaign table
    )
    # measurement_year index on campaign itself for worker queries
    op.create_index('idx_campaign_year', 'campaign', ['clinic_id', 'measurement_year'])

def downgrade():
    op.drop_index('idx_campaign_year')
    op.drop_index('idx_contact_dedup')
    op.drop_column('campaign', 'measurement_year')
```

Also add `measurement_year: int` column to `Clinic_app/data/models/campaign.py`.

**Tests to write after this step:**
- `tests/test_measurement_year_dedup.py` — unit test the dedup query logic (mocked DB)

---

#### Step F4.2 — Clinic settings API

**Files:** `Clinic_app/Routes/clinic.py` (new), `Clinic_app/services/clinic_service.py` (new or extend)

**`GET /clinic/settings`** — requires `require_scoped_staff` (any role)
```
→ Load ClinicIntegration row for staff.clinic_id
→ Return: {
    timezone, calling_hours_start, calling_hours_end,
    campaign_concurrency_limit, max_attempts,
    voicemail_retry_hours, no_answer_retry_hours, error_retry_hours
  }
```

**`PATCH /clinic/settings`** — requires `require_scoped_staff` with `role == "admin"`
```
Body (all fields optional):
{
  "calling_hours_start": "09:00",   # HH:MM, validated: 00:00–23:59
  "calling_hours_end": "17:00",
  "campaign_concurrency_limit": 3,  # 1–10
  "max_attempts": 3,                # 1–5
  "voicemail_retry_hours": 4,       # 1–72
  "no_answer_retry_hours": 2,
  "error_retry_hours": 24,
  "timezone": "America/Chicago"     # Must be valid IANA tz
}
→ Validate: calling_hours_start < calling_hours_end
→ Validate: all ints within bounds
→ Validate: timezone is valid IANA string (use zoneinfo.available_timezones())
→ Update ClinicIntegration row for staff.clinic_id
→ Return updated settings
```

**Why `role == "admin"` check in route, not via dependency?**
We want all scoped staff to be able to call `GET /clinic/settings`. A separate dependency
that checks role would block viewers from the GET. So `require_scoped_staff` handles the
auth, and the PATCH handler explicitly checks `staff.role == "admin"` → 403 if not.

**Register `clinic_router` in `main.py`:**
```python
from Clinic_app.Routes.clinic import clinic_router
app.include_router(clinic_router)
```

---

#### Step F4.3 — Claude CSV parser service

**File:** `Clinic_app/services/csv_parser.py`

```python
# services/csv_parser.py
"""
Claude API CSV normalization.
Handles inconsistent payer HEDIS CSV column formats.
One API call per upload (batch prompt, not per-row).
"""

SYSTEM_PROMPT = """
You are a HEDIS data normalization assistant. You will receive the first 3 rows
of a CSV (header + 2 data rows) and return a JSON column mapping that maps each
input column header to one of the following normalized field names:

  phone         → patient phone number (required)
  gap_type      → HEDIS care gap measure (required)
  language      → preferred language (optional, default "en")
  patient_name  → patient name for call greeting (optional, passed to Retell only)
  patient_dob   → date of birth (optional, passed to Retell only)
  ignore        → column should be ignored

For gap_type values, also map the raw value to one of these standard codes:
  colorectal_cancer_screening | breast_cancer_screening | cervical_cancer_screening |
  diabetes_hba1c | diabetes_eye_exam | diabetes_nephropathy | hypertension_control |
  depression_screening | well_child_visit | adolescent_well_care | adult_bmi_assessment |
  medication_adherence_diabetes | medication_adherence_hypertension | other

Return ONLY valid JSON. No explanation.
"""

async def parse_csv_columns(header_row: list[str], sample_rows: list[list[str]]) -> ColumnMapping:
    """Call Claude API with the first 2 data rows to normalize column names."""
    # Returns ColumnMapping(phone_col, gap_type_col, language_col, name_col, dob_col)

def normalize_phone(raw: str) -> str:
    """Normalize phone to E.164 (+1XXXXXXXXXX). Raises ValueError if unparseable."""
    # Strip non-digits, add +1 if 10 digits, validate 11 digits starting with 1

def map_gap_type(raw: str, mapping: dict) -> GapType:
    """Apply Claude-provided gap_type mapping. Falls back to GapType.OTHER."""

async def parse_csv_file(
    file_bytes: bytes,
    encoding: str = "utf-8",
) -> list[ParsedRow]:
    """
    Full parse pipeline:
    1. Detect delimiter (comma vs pipe vs tab)
    2. Extract header + first 2 rows → Claude column normalization
    3. Apply mapping to all rows
    4. Normalize phones to E.164
    5. Map gap types
    6. Return list of ParsedRow(phone_e164, gap_type, language, name, dob, raw_row_num)
    7. Collect errors per row (don't abort entire upload on bad rows)
    """
```

**Key behavior:**
- Rows with unparseable phones are collected in `parse_errors` and returned to the caller —
  upload is not aborted. The caller decides whether to proceed or reject.
- Rows with unrecognized gap types are mapped to `GapType.OTHER` — not rejected.
- Claude is called ONCE with just the header + 2 rows. The actual column mapping is then
  applied locally in Python to all remaining rows (no per-row Claude calls).

---

#### Step F4.4 — Campaign service

**File:** `Clinic_app/services/campaign_service.py`

```python
# services/campaign_service.py

async def create_campaign(
    db: AsyncSession,
    clinic_id: UUID,
    staff_id: UUID,
    name: str,
    measurement_year: int,
    parsed_rows: list[ParsedRow],
    clinic_integration: ClinicIntegration,
) -> CampaignCreateResult:
    """
    Create one Campaign row + N CampaignContact rows.
    Applies cross-campaign dedup before inserting.
    Returns CampaignCreateResult with campaign_id, inserted_count, skipped_count, error_rows.
    """
    # 1. Create Campaign row (inherit defaults from clinic_integration)
    # 2. For each ParsedRow:
    #    a. Normalize + hash phone (SHA-256 of E.164)
    #    b. Dedup check: SELECT id FROM campaign_contact
    #                    JOIN campaign USING (campaign_id)
    #                    WHERE clinic_id = :clinic_id
    #                      AND phone_hash = :hash
    #                      AND gap_type = :gap_type
    #                      AND measurement_year = :year
    #                      AND status NOT IN ('exhausted', 'declined')
    #       → If found: skip, add to skipped_contacts list
    #    c. Encrypt phone (AES-256-GCM via common/encryption.py)
    #    d. INSERT CampaignContact
    # 3. UPDATE Campaign.total_contacts = inserted_count
    # 4. COMMIT
    # 5. Return CampaignCreateResult

async def get_campaign(db: AsyncSession, clinic_id: UUID, campaign_id: UUID) -> Campaign:
    """Fetch campaign by ID, enforcing clinic_id tenant filter. Raises 404 if not found."""

async def list_campaigns(
    db: AsyncSession, clinic_id: UUID, status: Optional[CampaignStatus] = None
) -> list[Campaign]:
    """List campaigns for clinic, optionally filtered by status. Ordered by created_at DESC."""

async def pause_campaign(db: AsyncSession, clinic_id: UUID, campaign_id: UUID) -> Campaign:
    """Set status=PAUSED. Raises 409 if not ACTIVE."""

async def resume_campaign(db: AsyncSession, clinic_id: UUID, campaign_id: UUID) -> Campaign:
    """Set status=ACTIVE. Raises 409 if not PAUSED."""

async def cancel_campaign(db: AsyncSession, clinic_id: UUID, campaign_id: UUID) -> Campaign:
    """Set status=CANCELED. Terminal — cannot be resumed."""

async def get_campaign_contacts(
    db: AsyncSession, clinic_id: UUID, campaign_id: UUID,
    limit: int = 100, offset: int = 0
) -> list[CampaignContact]:
    """Paginated contact list for campaign detail view."""
```

---

#### Step F4.5 — Campaign upload endpoint

**File:** `Clinic_app/Routes/campaigns.py` (new)

```python
campaign_router = APIRouter(prefix="/campaigns", tags=["campaigns"])

POST /campaigns/upload
  - Requires: require_scoped_staff + role=admin
  - Body: multipart/form-data
      file: UploadFile (CSV, max 10MB)
      name: str           (campaign name)
      measurement_year: int (default: current year)
  - Validation:
      → file.content_type must be text/csv or text/plain
      → File size ≤ 10MB (read into memory, check len)
      → Row count ≤ 2000 (checked after parse)
  - Pipeline:
      → parse_csv_file(file_bytes) → list[ParsedRow] + parse_errors
      → If len(parsed_rows) > 2000 → 422
      → If len(parsed_rows) == 0 → 422 "No valid rows found"
      → create_campaign(db, clinic_id, staff_id, name, measurement_year, rows, clinic_integration)
  - Response 201:
      {
        campaign_id, name, measurement_year,
        total_contacts, skipped_contacts, parse_errors,
        status: "pending"
      }
```

---

#### Step F4.6 — Campaign management routes

**File:** `Clinic_app/Routes/campaigns.py` (continued)

```python
GET    /campaigns                  → list_campaigns (any scoped staff)
GET    /campaigns/{id}             → get_campaign + contact count breakdown (any scoped staff)
GET    /campaigns/{id}/contacts    → paginated contact list, status filter (any scoped staff)
POST   /campaigns/{id}/pause       → pause_campaign (admin only)
POST   /campaigns/{id}/resume      → resume_campaign (admin only)
POST   /campaigns/{id}/cancel      → cancel_campaign (admin only, confirm required)
GET    /campaigns/{id}/export      → CSV export: phone_hash, gap_type, status, attempt_count
                                     NO patient name, NO decrypted phone (PHI-safe export)
```

Register `campaign_router` in `main.py`.

---

#### Step F4.7 — Tests

**`tests/test_csv_parser.py`** (unit — Claude mocked)
- Column normalization: "Member Phone" → `phone`, "COL" → `colorectal_cancer_screening`
- E.164 normalization: "787-555-1234" → "+17875551234"
- E.164 normalization: "(787) 555-1234" → "+17875551234"
- Unparseable phone → row collected in parse_errors, not raised
- Unrecognized gap type → maps to `GapType.OTHER`
- Zero valid rows → empty list returned
- Claude API failure → tenacity retry, raises after max retries

**`tests/test_campaign_service.py`** (unit + integration)
- `create_campaign` creates Campaign row + correct contact count
- Dedup: same phone + gap_type + measurement_year → skipped (not duplicated)
- Different measurement_year → NOT skipped (new year = new obligation)
- Different gap_type, same phone → NOT skipped (different gap)
- BOOKED contact → skipped on re-upload (status in exhausted/declined/booked)
- Phone is stored encrypted (not plaintext)
- Phone hash is SHA-256 of E.164 form
- `pause_campaign` raises 409 if already PAUSED
- `list_campaigns` filters by clinic_id (no cross-tenant leakage)

**`tests/test_campaign_routes.py`** (unit — DB mocked)
- Upload: valid CSV → 201 with campaign_id
- Upload: file > 10MB → 422
- Upload: > 2000 rows → 422
- Upload: 0 valid rows → 422
- Upload: non-admin staff → 403
- GET /campaigns → returns list for correct clinic only
- POST /campaigns/{id}/pause → 200 if ACTIVE, 409 if already PAUSED
- GET /campaigns/{id}/export → no PHI in response

**`tests/test_clinic_settings.py`** (unit)
- GET /clinic/settings → returns current values
- PATCH /clinic/settings as admin → updates and returns new values
- PATCH /clinic/settings as viewer → 403
- PATCH with calling_hours_start > calling_hours_end → 422
- PATCH with invalid timezone → 422
- PATCH with concurrency_limit > 10 → 422

---

### Files Created / Modified

| File | Action |
|---|---|
| `Clinic_app/alembic/versions/d4e5f6a7b8c9_add_measurement_year.py` | Create |
| `Clinic_app/data/models/campaign.py` | Modify — add `measurement_year` column |
| `Clinic_app/Routes/clinic.py` | Create |
| `Clinic_app/services/clinic_service.py` | Create (or extend existing) |
| `Clinic_app/services/csv_parser.py` | Create |
| `Clinic_app/services/campaign_service.py` | Create |
| `Clinic_app/Routes/campaigns.py` | Create |
| `Clinic_app/main.py` | Modify — register clinic_router, campaign_router |
| `tests/test_csv_parser.py` | Create |
| `tests/test_campaign_service.py` | Create |
| `tests/test_campaign_routes.py` | Create |
| `tests/test_clinic_settings.py` | Create |

### Feature 4 Test Summary

| Test File | Type | What It Tests |
|---|---|---|
| `tests/test_csv_parser.py` | Unit | Claude response parsing, column mapping, E.164 normalization, malformed rows |
| `tests/test_campaign_service.py` | Unit + Integration | Campaign creation, cross-year dedup logic, phone encryption, tenant isolation |
| `tests/test_campaign_routes.py` | Unit | Upload endpoint, file limits, campaign CRUD, PHI-safe export |
| `tests/test_clinic_settings.py` | Unit | Settings GET/PATCH, role enforcement, validation (hours, tz, bounds) |
| `tests/test_measurement_year_dedup.py` | Unit | Dedup: same year skipped, new year passes, same phone/diff gap passes |

---

## Plan 007 — Feature 5: EHR Integration (Playwright + AgentQL)
**Date:** 2026-03-18
**Updated:** 2026-03-21
**Status:** Complete — `playwright_ehr`, Redis selector cache, Retell EHR tool endpoints, admin EHR config + credential test (see Feature 5 test summary below)
**Source:** HEDIS_PRD_v2.md §10
**Architecture Branch:** Server-side Playwright (confirmed for pilot — Feature 0 PASS 2026-03-20). Chrome Extension fallback documented in `HEDIS_CAMPAIGN_IMPLEMENTATION.md` if headless is blocked elsewhere.

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
**Status:** Complete — campaign worker, Retell outbound client, campaign webhooks, `POST /campaigns/{id}/start`, `call_analyzed` summary path (see Feature 6 test summary below)
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
**Status:** Pending — **do not start UI until Plan 011 E2E gate and Plan 012 security/rate-limit work are done** (voice path verified; API ready for browser clients)
**Source:** HEDIS_PRD_v2.md §14

### Ordering

- **Penultimate** product milestone: ship after **Plan 011** and **Plan 012**. **Feature 8 (Plan 010)** is the **last** milestone (broader hardening + pilot onboarding) and follows the dashboard.

### Summary

Desktop-only. Minimal React SPA (Vite) served as static files from FastAPI. Campaign detail must surface **decrypted staff notes / structured extraction** produced in Plan 011 (not only the one-sentence summary), within existing role and PHI rules.

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
**Status:** Pending — **last** milestone; starts after Feature 7 dashboard ships
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

## Plan 011 — Retell agent playbook + E2E voice gate + post-call staff notes
**Date:** 2026-03-22  
**Updated:** 2026-03-22  
**Status:** **Active — next to implement.** Finish documentation, agent alignment, richer post-call persistence, and a **full end-to-end test gate** before any dashboard UI work (Plan 009).  
**Source:** Clinic workflow requirement (labs / follow-up visibility) + operational need to configure one Retell agent per clinic with correct tools and webhooks

### Goals (in order)

1. **Single source of truth** for how each clinic’s Retell agent is wired: gap types, dynamic metadata, webhook URLs, custom tool URLs, and what the server expects for summaries — so onboarding is repeatable and debuggable.
2. **Staff-usable post-call artifact** beyond a one-sentence summary (Claude extraction; see below).
3. **E2E validation** (automated + staged real/simulated call where appropriate) proving outbound → voice → tools → booking path → webhooks → DB **before** building the React dashboard.

### Retell agent setup structure (playbook contents)

Maintain the **Retell agent playbook** at [`docs/retell_agent_playbook.md`](docs/retell_agent_playbook.md) (update when routes or metadata change). For each environment (`APP_BASE_URL`), it lists:

| Area | What to configure | FastAPI routes (prefix `/retell`) |
|---|---|---|
| **Agent** | One agent per clinic; store Retell `agent_id` in DB; prompt references `gap_type` and clinic-specific scripts. | — |
| **Outbound metadata** | `create-phone-call` must send fields the worker already supplies (e.g. `clinic_id`, `campaign_contact_id`, `gap_type`, patient context for the voice layer). Playbook documents **exact keys** and allowed `gap_type` values (mirror `data/enums.py` / CSV). | — |
| **Custom tools (EHR)** | Retell custom functions pointing at this API with clinic auth as today. | `POST /retell/tools/get_available_slots`, `POST /retell/tools/book_appointment` |
| **Call lifecycle webhooks** | HMAC with `RETELL_WEBHOOK_SECRET`. | `POST /retell/webhook/call_started`, `POST /retell/webhook/call_ended`, `POST /retell/webhook/call_analyzed` |
| **Legacy / other** | Older demo routes may exist; playbook should state **HEDIS campaign agent must use the tool + webhook paths above**, not legacy scheduling paths unless explicitly migrated. | `POST /retell/schedule`, `POST /retell/confirm_booking`, `GET|POST /retell/availability` — confirm non-HEDIS or deprecated per code review |

Playbook sections to include: **environment variables checklist** (`RETELL_API_KEY`, `RETELL_FROM_NUMBER`, `RETELL_WEBHOOK_SECRET`, `APP_BASE_URL`), **Retell dashboard copy-paste URLs**, **prompt snippet** instructing the model when to call slots vs book vs hand off, and **timeout note** (e.g. slot lookup must stay under 3 seconds per architecture rules).

### Problem (staff notes)

Some HEDIS gaps are **informational** (e.g. bloodwork or mammogram reminders). Staff need **what the patient agreed to** (labs, location, timing) to operationalize orders. The current **one-sentence** encrypted summary in `campaign_audit` may be insufficient.

### Decision (two complementary inputs, one extraction step)

**Do not rely on Retell’s summary alone** unless product verifies it always contains the fields staff need.

1. **Input to Claude** (best available, in order): Retell **post-call summary** from `call_analyzed` when useful; and/or **transcript** / `transcript_with_tool_calls` when the summary is thin.
2. **Claude output:** **Option A** — short bounded staff-facing narrative; **Option B** — validated JSON (e.g. `patient_agreed_to_labs`, `lab_or_location_mentioned`, `follow_up_action_for_staff`, `free_text_note`). Encrypt at rest; **do not** store full transcript by default unless policy explicitly allows.
3. **NextGen appointment type strings:** Mapping values must be the **exact strings** the NextGen control expects (display label vs `value` — match `playwright_ehr`).

### E2E gate (blocking before Plan 009)

**Definition of done for Plan 011** includes all of:

- [ ] Playbook reviewed against actual `Routes/retell.py` and `retell_client` / worker metadata.
- [ ] pytest: webhook + tool handlers + staff-notes extraction paths (summary-only, transcript-only, both).
- [ ] **Staged E2E:** from campaign start through at least one contact — outbound call connects (or Retell test mode per their docs), agent invokes **get_available_slots** and **book_appointment** as designed, `call_started` / `call_ended` / `call_analyzed` update DB correctly, encrypted staff artifact present where implemented.
- [ ] Sign-off recorded in `PROGRESS.txt` (date + what was exercised).

Only after this gate: proceed to **Plan 012** (API security + rate limits), then begin Feature 7 dashboard UI (Plan 009).

### Implementation steps

- [ ] Add **Retell agent playbook** doc with the table above + gap-type list + env checklist.
- [ ] Extend `call_summarizer` or add `call_staff_notes_extractor.py` (Claude, JSON or bounded text; minimal PHI echo in stored blob).
- [ ] Alembic: encrypted column(s) on `campaign_audit` (or sibling) for staff notes / structured extraction.
- [ ] Update `webhook_call_analyzed` to feed extractor; persist encrypted result alongside or instead of expanding only the one-liner (product choice).
- [ ] **Optional for gate:** minimal authenticated **read** API or admin-only JSON endpoint to inspect one campaign row for QA — **not** a substitute for tests; dashboard UI remains Plan 009.
- [ ] E2E checklist execution + `PROGRESS.txt` entry.

### Deferred

- Full transcript retention at rest (explicit compliance decision).
- Automatic lab orders in NextGen.
- Feature 7 UI and polish — **Plan 009**, after Plan 011 gate **and Plan 012**.

### Relationship to other plans

- **Plan 012:** Hardens the API and adds rate limits **before** staff use the dashboard in production-like environments.
- **Plan 009:** Consumes persisted staff notes; first **user-facing** surface for them.
- **Plan 010:** Broader production hardening, pilot onboarding, audits, load tests **after** dashboard.
- **Plan 008:** `call_analyzed` is the integration hook; this plan extends persistence and operationalizes Retell configuration.

---

## Plan 012 — API security hardening + HTTP rate limits + Claude rate limits
**Date:** 2026-03-23  
**Status:** Pending — implement **after Plan 011 E2E gate**, **before Plan 009** (clinic dashboard / SPA)  
**Source:** Gap analysis vs current `main.py`, `Routes/auth.py`, `Routes/campaigns.py`, `Routes/retell.py`, `call_summarizer` / any Anthropic usage

### Why (before dashboard)

The browser UI will increase **attack surface** (CORS, credential handling, traffic patterns). Today: **no global HTTP rate limiting**, **OpenAPI docs publicly exposed**, **no CORS middleware** configured for a separate SPA origin, **500 handler may return raw exception strings**, and **Claude calls** are only indirectly bounded (retries, not quota-style limits). Plan 012 closes these **before** clinics use the dashboard against a shared API.

### Scope — API / edge

- [ ] **OpenAPI / docs:** Disable or restrict `/docs` and `/redoc` in **production** (`APP_ENVIRONMENT`); keep available in dev or behind admin auth if desired.
- [ ] **CORS:** Configure allowed origins via env (e.g. comma-separated or JSON list) for the future Vite SPA; reject unexpected browser origins in production.
- [ ] **Error responses:** Production 500 responses must **not** echo internal exception text to clients; log server-side only.
- [ ] **HTTP rate limiting:** Add application-level limits (e.g. `slowapi` or equivalent) on high-risk routes, at minimum:
  - **`/auth/*`** — OAuth start, callback, token refresh patterns, `/me`, `/select-clinic` (per-IP and/or per-identity where feasible).
  - **Campaign file upload / mutating admin-style staff routes** — e.g. CSV/Excel upload, campaign start, exports if abuse-prone.
  - **Optional:** stricter limits on **`/retell/webhook/call_analyzed`** or other externally triggered paths if needed beyond Retell’s own controls (coordinate with HMAC auth).
- [ ] **Storage backend for limits:** Prefer **Redis** (`REDIS_URL`) when available so limits are consistent across multiple app workers; document in-memory fallback for single-process dev.

### Scope — Claude / Anthropic

- [ ] **Rate limit** all server paths that call Anthropic (`call_summarizer`, CSV gap-type parsing if applicable, future staff-notes extractor): e.g. **global** requests-per-minute and/or **per-`clinic_id`** (when resolvable) to cap cost and reduce burst abuse.
- [ ] **Behavior on limit exceeded:** Return a safe, non-leaking response for HTTP-triggered paths; for webhooks, define policy (queue vs drop vs generic summary) — document choice.
- [ ] **Tests:** Unit/integration tests for limiter wiring and “over limit” behavior on at least one auth and one Claude path.

### Explicitly out of scope (remain in Plan 010 unless pulled forward)

- Full **PHI log audit** automation, **12-call load test**, **Azure BAA** operational checklist — keep in **Plan 010** unless a blocker for pilot.

### Open decisions (answer before implementation)

1. **CORS:** Single global allowlist env var vs per-tenant origins in DB for white-label / multi-domain clinics?
2. **Claude limits:** Global-only vs **per-`clinic_id`** buckets (fairness across tenants)?
3. **Admin routes (`X-Admin-Key`):** Same rate-limit tier as staff auth, stricter, or IP allowlist in Azure only?

---

*Last updated: 2026-03-23*
*Maintained by: Edgar J. Suárez Colón*
*Next action: Plan 011 (E2E gate) → Plan 012 (security + rate limits) → Plan 009 (dashboard) → Plan 010 (onboarding).*

---

## Plan 013 — Business Logic Decisions: Gap Types, Scheduling Rules, Schema Additions
**Date:** 2026-03-23
**Status:** Active — decisions finalized; schema migrations + code changes required before Plan 009 dashboard can be built
**Source:** Handwritten notes + Edgar decisions made 2026-03-23

### What Was Decided

A comprehensive set of business logic decisions was finalized covering: HEDIS gap type taxonomy, CSV alias normalization, double-booking rules, hospital flu scheduling modes, preventive visit insurance year rules, two new DB tables, new columns on `campaign_contact`, new API endpoints, new contact statuses, dashboard additions, and the Super Admin onboarding screen. All decisions recorded below as authoritative source of truth.

---

### 1. HEDIS Gap Type Taxonomy (Finalized)

#### Appointment-Based (Playwright books in NextGen)
| Enum value | Description | Notes |
|---|---|---|
| `preventive_visit` | Annual preventive / wellness visit | Insurance year rule applies |
| `hospital_flu` | Hospital follow-up within 7 days of discharge | **Priority queue** — always called first (`priority_order = 0`) |

#### Order-Based (call summary only — clinic admin sends order manually)
| Enum value | Description |
|---|---|
| `colorectal` | Colorectal cancer screening / stool test |
| `eye_exam` | Eye exam / retinal exam |
| `breast_cancer` | Breast cancer screening / mammogram |
| `kidney` | Kidney function lab |
| `afr_cmp` | Albumin/creatinine ratio + urinalysis |

#### Excluded (filtered at CSV parse — never enters campaign queue)
| Enum value | Action |
|---|---|
| `medication_review` | Filtered out — never called |

#### Unrecognized gap labels

Rows that cannot be mapped to a canonical `GapType` produce a **parse error** on CSV upload (row skipped), not a fallback enum.

**There is NO `a1c` gap type.** What appeared as A1C in notes was the preventive visit timing rule.

#### CSV Alias Normalization (Claude must recognize all variants)

| CSV value(s) | Normalized to |
|---|---|
| Preventive visit, Annual wellness, AWV, Yearly checkup | `preventive_visit` |
| Hospital follow-up, Hospital flu, Hosp flu, Post-hospital, Discharge follow-up | `hospital_flu` |
| Colorectal, CRC, Colonoscopy, Stool test, FIT | `colorectal` |
| Eye exam, Eye, Vision, Ophthalmology, Retinal exam | `eye_exam` |
| Breast cancer, Breast cancer screening, Mammogram, BSE | `breast_cancer` |
| Kidney, Kidney function, CKD, Renal | `kidney` |
| AFR/CMP, Albumin creatinine, Alb/Cr ratio, urine albumin, bw/uA | `afr_cmp` |
| Medication review, Med review, Medication management | `medication_review` (EXCLUDED) |
| Anything else | Parse error — row skipped |

---

### 2. Double Booking Rules

- Only 1 appointment per hour slot max.
- Cannot double book restricted type pairs in the same hour.
- Only follow-up appointments can share a slot with restricted types.
- HEDIS patients are never new patients — "new patient" matters only when Playwright reads existing slots.

#### Default Combination Flags (all configurable per clinic)

| Pair | Default |
|---|---|
| `preventive` + `follow-up` | ALLOWED (true) |
| `preventive` + `hospital_flu` | BLOCKED (false) |
| `preventive` + `new_patient` | BLOCKED (false) |
| `hospital_flu` + `follow-up` | ALLOWED (true) |
| `hospital_flu` + `new_patient` | BLOCKED (false) |
| `new_patient` + `follow-up` | ALLOWED (true) |

Stored as 6 boolean flags in `clinic_scheduling_rules`. Clinic Admin can modify anytime. `updated_by` tracks who last changed rules.

---

### 3. Hospital Flu — Scheduling Rules

**7-day deadline:** `release_date` comes from CSV. `deadline = release_date + 7 days`. Worker checks before dialing — if `deadline < today` → `status = EXPIRED` → never call.

**Two scheduling modes** (determined by insurance plan in `clinic_insurance_rules`):

| Mode | Slots | Constraint |
|---|---|---|
| `telehealth_4_5pm` | Telehealth only | Within `hospital_flu_telehealth_start`–`hospital_flu_telehealth_end` (clinic timezone). Only on configured days. |
| `next_to_followup` | In-person only | Must be in same hour as existing follow-up already in NextGen. Only on configured in-person days. |

If payer not configured → default to `next_to_followup` + flag for review.

Days and time window are fully configurable per clinic (stored in `clinic_scheduling_rules`).

---

### 4. Preventive Visit — Insurance Year Rules

**Two rules** (determined by insurance plan in `clinic_insurance_rules`):

| Rule | Logic |
|---|---|
| `different_year` | Appointment just needs to be in a different calendar year from last preventive visit |
| `one_year_one_day` | Appointment must be 366+ days from last visit date |

**Last visit date** is NOT in the CSV — Playwright looks it up in NextGen via AgentQL. Cached in Redis: `clinic_id:phone_hash:last_visit`, 24-hour TTL.

If payer not configured → default to `different_year` + flag for review.

If not yet eligible → agent tells patient earliest eligible date → `status = NOT_YET_ELIGIBLE` (terminal, no retry).

---

### 5. New Database Tables

#### `clinic_insurance_rules`
```
id                  UUID PK
clinic_id           UUID FK → clinic
payer_name          VARCHAR(255)
preventive_rule     ENUM(different_year, one_year_one_day)
hospital_flu_rule   ENUM(telehealth_4_5pm, next_to_followup)
active              BOOLEAN default true
updated_at          TIMESTAMPTZ
```

#### `clinic_scheduling_rules`
```
id                                   UUID PK
clinic_id                            UUID FK → clinic  UNIQUE

-- Double booking combination flags
allow_preventive_with_followup       BOOLEAN default true
allow_preventive_with_hospital_flu   BOOLEAN default false
allow_preventive_with_new_patient    BOOLEAN default false
allow_hospital_flu_with_followup     BOOLEAN default true
allow_hospital_flu_with_new_patient  BOOLEAN default false
allow_new_patient_with_followup      BOOLEAN default true

-- Hospital flu telehealth time window (clinic timezone)
hospital_flu_telehealth_start        TIME default 16:00
hospital_flu_telehealth_end          TIME default 17:00

-- Hospital flu telehealth days (7 booleans)
hospital_flu_telehealth_mon          BOOLEAN default false
hospital_flu_telehealth_tue          BOOLEAN default false
hospital_flu_telehealth_wed          BOOLEAN default false
hospital_flu_telehealth_thu          BOOLEAN default false
hospital_flu_telehealth_fri          BOOLEAN default true
hospital_flu_telehealth_sat          BOOLEAN default false
hospital_flu_telehealth_sun          BOOLEAN default false

-- Hospital flu in-person days (7 booleans)
hospital_flu_inperson_mon            BOOLEAN default true
hospital_flu_inperson_tue            BOOLEAN default true
hospital_flu_inperson_wed            BOOLEAN default true
hospital_flu_inperson_thu            BOOLEAN default true
hospital_flu_inperson_fri            BOOLEAN default true
hospital_flu_inperson_sat            BOOLEAN default false
hospital_flu_inperson_sun            BOOLEAN default false

updated_at                           TIMESTAMPTZ
updated_by                           UUID FK → clinic_staff.id  NULLABLE
```

#### New columns on `campaign_contact`
```
release_date     DATE      Nullable — hospital_flu only — from CSV
priority_order   INTEGER   hospital_flu = 0; all others = CSV row order
```

---

### 6. New Contact Statuses

| Status | Category | Meaning |
|---|---|---|
| `NOT_YET_ELIGIBLE` | Terminal | Preventive patient not eligible per insurance year rule — agent told patient earliest eligible date |
| `EXPIRED` | Terminal | Hospital flu 7-day deadline passed before call — worker never dials |
| `ORDER_AGREED` | Terminal | Order-based gap — patient verbally agreed — clinic admin sends order |
| `ORDER_DECLINED` | Terminal | Order-based gap — patient declined |

---

### 7. New API Endpoints

```
PUT /clinics/scheduling-rules
    Auth: Clinic Admin JWT (own clinic only)
    Body: 6 combination flags + telehealth window + 14 day booleans

PUT /clinics/insurance-rules
    Auth: Clinic Admin JWT (own clinic only)
    Body: array of { payer_name, preventive_rule, hospital_flu_rule, active }

PUT /admin/clinics/{id}/scheduling-rules
    Auth: X-Admin-Key
    Same body — Super Admin modifies any clinic

PUT /admin/clinics/{id}/insurance-rules
    Auth: X-Admin-Key
    Same body — Super Admin modifies any clinic
```

---

### 8. Dashboard Updates (extends Plan 009)

**New status colors:**
- Orange → `ORDER_AGREED` — "Send Order" indicator shown next to row
- Purple → `NOT_YET_ELIGIBLE`
- Red → also covers `EXPIRED` (added to existing red group)

**New urgent badge:** `🔴 URGENT` on `hospital_flu` contacts with ≤ 2 days before 7-day deadline. Shows days-remaining counter next to patient name.

**New column on patient table:**
- `Summary` — one-sentence Claude-generated description of what patient said

**New Settings screen (sidebar):**
- Section 1: Double Booking Rules — 6 toggles, Clinic Admin editable / Clinic Staff read-only
- Section 2: Hospital Follow-Up Telehealth — 7 day checkboxes + start/end time pickers (clinic timezone)
- Section 3: Hospital Follow-Up In-Person — 7 day checkboxes
- [Save Changes] → `PUT /clinics/scheduling-rules`
- Shows: "Last updated [date] by [staff name]" or "by System" if Super Admin changed it

---

### 9. Super Admin Onboarding Screen (Post-Pilot)

**When:** Build after first clinic onboarded manually during pilot.
**Why deferred:** Learn what the screen needs from doing it manually first.
**Tool:** Plain HTML form served from FastAPI — no separate frontend build.
**Auth:** Protected by `X-Admin-Key` — never linked from clinic dashboard.
**URL:** `/admin/onboard`

**Steps (in order, one transaction on submit):**
1. Clinic creation — name, location, timezone, phone
2. Staff entry — email + role (clinic_admin / clinic_staff / provider), multiple rows
3. EHR config — NextGen URL, credentials, Retell agent ID, from number, concurrency limit, calling hours, timezone, retry hours
4. Test Connection button — hits `POST /admin/clinics/{id}/ehr-test` inline; shows green/red without leaving page; must pass
5. Appointment type codes — one row per appointment-based gap type (`preventive_visit`, `hospital_flu` only); NextGen code per gap
6. Scheduling rules — 6 combination toggles + telehealth window + 14 day checkboxes
7. Insurance rules — one row per payer; dropdowns for `preventive_rule` and `hospital_flu_rule`
8. Submit all — single transaction
9. Success screen — shows `clinic_id` + staff login instructions to send to clinic

**Deferred:** Self-service signup, billing UI, offboarding flow.

**Payment model (decided):** Invoice only — no Stripe. QuickBooks / Wave / PDF invoices. ACH, check, or payment link. Only automate billing when clinic count > ~20.

---

### 10. Open Question — `updated_by` When Super Admin Acts

When Super Admin modifies scheduling rules via `X-Admin-Key` (no Google OAuth / no `clinic_staff.id`):

- **Option A:** Store `null` → dashboard shows "Last updated [date] by System"
- **Option B:** Create a Super Admin record in `clinic_staff` table → link to it

**NOT DECIDED YET** — must resolve before writing the Alembic migration for `clinic_scheduling_rules`.

---

### 11. Integration & enforcement model (decided 2026-03-27)

This section records **how** insurance and scheduling rules (§2–§5, tables in §5) connect to the **running app** — in plain terms, for implementers. It does not replace §5 schema; it describes **where** logic runs and **how** it interacts with the **Redis slot cache** used on the Retell hot path.

#### 11.1 The “three boxes” model (explain-like-I’m-five)

- **Box A — Rule sheet (per clinic, in the database)**  
  Think of a **printed list** taped to the wall for **that clinic only**: “We don’t book closer than 24 hours,” “this payer uses the one-year-and-one-day rule,” “these two visit types can’t share an hour,” etc.  
  In software this is **`clinic_insurance_rules`** + **`clinic_scheduling_rules`** (§5), or — for an early pilot — a **minimal** JSON/config row **scoped by `clinic_id`** until full migrations land.  
  **Customization:** change the sheet (admin API, Super Admin API, or DB row) — **no code deploy** for each tweak.

- **Box B — EHR robot (NextGen today)**  
  This is **Browser-Use / Playwright**: log in, open the schedule, **read what times look open** in the EHR, or **book** a time.  
  It should **not** encode every insurance law inside NextGen clicks. It **returns facts** (“here are slots the EHR shows”) or **executes** (“book this slot”).

- **Box C — Referee (your FastAPI code)**  
  The referee **reads Box A** and **checks Box B’s answers** before the patient hears anything or before a booking commits.  
  If the rule sheet says “no,” the referee **throws away** that option or **stops** the book — even if the EHR page looked fine.

#### 11.2 How this works with the **Redis slot cache** (simple)

- **What Redis holds today:** A **short-lived copy** of “next available slots” **per clinic + provider** (see `playbook_cache.py`, `SlotPrefetchWorker`). Think of it as a **sticky note**: “Last time we looked, these times were open.”  
- **Redis is not the rule book.** It’s a **speed shortcut** so `get_available_slots` can answer Retell in **under ~3 seconds** without launching a full browser on every tool call.

**Order of operations (conceptual):**

1. **Background job** (or first fetch) fills Redis with slots **from NextGen** — “raw” availability the EHR exposed.  
2. When the **voice tool** runs, the API **reads** that cache (fast).  
3. **Then the referee (Box C)** loads **this clinic’s rules** from the DB and **filters** the list: drop slots that violate lead-time, insurance year, hospital-flu mode, double-book risk, etc.  
4. **Only the filtered list** is spoken to the patient / returned to the agent.

So: **Redis = remember what the schedule looked like; rules = decide what we’re allowed to offer from that list.**  
If the cache is empty or stale, behavior is defined elsewhere (miss → empty or trigger refresh); rules still apply **whenever** a list is returned.

#### 11.3 Where enforcement hooks go (must implement with §5)

| Step | What happens |
|------|----------------|
| **After** reading slots (from Redis or live fetch), **before** returning to Retell | Apply **scheduling + insurance + gap-type** rules → **filter** or annotate slots. |
| **Immediately before** `book_appointment` calls the EHR | Run **double-booking** and any **last-moment** checks using **DB bookings/holds** + **`clinic_scheduling_rules`**. If fail → do not book; return a safe message. |

Rules are **not** implemented only inside Browser-Use prompt text; they belong in **shared Python** keyed by **`clinic_id`**, so Epic/other EHRs can reuse the same referee with a different Box B later.

#### 11.4 How the system “chooses” slots for the patient

1. Start from **candidate slots** (from Redis cache or live).  
2. Load **clinic rules** + **this contact’s `gap_type`** + **metadata** (provider, payer if known).  
3. **Remove** candidates that break rules (eligibility, forbidden combinations, wrong mode for hospital_flu, etc.).  
4. **Sort** if needed (e.g. earliest first).  
5. Expose **top N** to the voice agent (see `MAX_SLOTS_RETURNED` patterns in code).  
The “choice” is **rule-driven filtering**, not the LLM guessing policy.

#### 11.5 MVP vs full Plan 013

- **Full Plan 013** implements §5 tables, PUT endpoints (§7), and EHR/worker updates in the implementation checklist below.  
- **Plan 014** deferred full rules to ship the test call faster.  
- **Exception (first production clinic):** If a pilot clinic **cannot** go live without specific rules, implement the **same three-box model** with a **minimal** rule payload (e.g. JSONB on `clinic` or a slim migration) **before** the full §5 surface area — still **`clinic_id`-scoped**, still referee at **read slots** + **pre-book** — then **expand** to full tables and dashboard toggles without redesigning the flow.

---

### Implementation Steps (Plan 013)

- [ ] Resolve open question: `updated_by = null vs. Super Admin staff record`
- [ ] Add `GapType` enum values to `data/enums.py` (8 values; no `generic` fallback; remove any `a1c` reference)
- [ ] Update CSV parser alias normalization map in `services/csv_parser.py` (or equivalent)
- [ ] Alembic: create `clinic_insurance_rules` table
- [ ] Alembic: create `clinic_scheduling_rules` table
- [ ] Alembic: add `release_date` + `priority_order` columns to `campaign_contact`
- [ ] Add `NOT_YET_ELIGIBLE`, `EXPIRED`, `ORDER_AGREED`, `ORDER_DECLINED` to `ContactStatus` enum + migration
- [ ] Add SQLAlchemy models for new tables
- [ ] Implement `PUT /clinics/scheduling-rules` and `PUT /clinics/insurance-rules`
- [ ] Implement `PUT /admin/clinics/{id}/scheduling-rules` and `PUT /admin/clinics/{id}/insurance-rules`
- [ ] Update campaign worker: `hospital_flu` priority sort + `EXPIRED` check before dialing
- [ ] Implement **referee layer** per **§11**: after reading slots (cache or live), filter by `clinic_insurance_rules` + `clinic_scheduling_rules` + `gap_type` before Retell response; before `book_appointment`, enforce double-booking + eligibility (see §11.3)
- [ ] Update EHR/Playwright layer: double booking check against `clinic_scheduling_rules`
- [ ] Update EHR/Playwright layer: preventive visit eligibility check + Redis cache for last visit date
- [ ] Update EHR/Playwright layer: hospital flu mode dispatch (`telehealth_4_5pm` vs `next_to_followup`)
- [ ] Tests: new enums, CSV alias normalization, scheduling rule endpoints, eligibility logic, expiry check

### Deferred
- Super Admin onboarding screen (`/admin/onboard`) — after pilot
- Stripe / billing automation — when clinic count > ~20
- Full transcript retention policy decision

---

## Plan 014 — MVP Sprint: Test Call by March 27
**Date:** 2026-03-23
**Status:** 🔴 ACTIVE — top priority
**Goal:** Edgar uploads a fake HEDIS CSV → system dials the contact via Retell → agent delivers correct gap-type script → for appointment-based gaps, agent checks slots + books in NextGen → post-call summary stored in DB. No dashboard required — Swagger UI is sufficient.

### What "done" looks like

- [ ] Fake CSV with at least one order-based contact (e.g. `colorectal`) and one appointment-based contact (e.g. `preventive_visit`) uploaded via `POST /campaigns/upload`
- [ ] Campaign started → worker dials → Retell call connects
- [ ] Agent says the right script for the gap type (driven by `gap_type` metadata)
- [ ] `get_available_slots` tool returns real slots from NextGen (or mocked sandbox)
- [ ] `book_appointment` tool creates the appointment (or mocked)
- [ ] `call_analyzed` webhook fires → summary stored encrypted in `campaign_audit`
- [ ] Contact status updated correctly in DB (BOOKED or ORDER_AGREED)

---

### Sprint A — Day 1 (March 23): Enum alignment + schema additions
**Blocking:** GapType enum has old values; ContactStatus missing statuses; campaign_contact missing columns.

- [x] **A1:** Replace GapType enum in `data/enums.py` with Plan 013 finalized values:
  `preventive_visit`, `hospital_flu`, `colorectal`, `eye_exam`, `breast_cancer`,
  `kidney`, `afr_cmp`, `medication_review` (excluded)
- [x] **A2:** Add missing ContactStatus values: `NOT_YET_ELIGIBLE`, `EXPIRED`, `ORDER_AGREED`, `ORDER_DECLINED`
- [x] **A3:** Update CSV alias normalization in `services/csv_parser.py` — alias table from Plan 013 §1 (Claude prompt must map all variants to new enum values; filter out `medication_review`)
- [x] **A4:** Alembic migration: rename PG enum values for GapType + add 4 new ContactStatus values
- [x] **A5:** Alembic migration: add `release_date DATE nullable` + `priority_order INT default 1` to `campaign_contact` (hospital_flu uses priority_order=0; checked before dialing)
- [x] **A6:** Update campaign worker: sort contacts by `priority_order ASC` (hospital_flu first); add `EXPIRED` check — if `gap_type == hospital_flu` and `release_date + 7 days < today` → set status=EXPIRED, skip
- [x] **A7:** Write/update tests for new enum values, alias normalization, EXPIRED check

**Hardcoded defaults for MVP (no new DB tables):**
- Preventive visit eligibility → always use `different_year` rule (appointment just needs to be in a different calendar year)
- Hospital flu scheduling mode → always use `next_to_followup` (in-person, same hour as existing follow-up)
- Double-booking enforcement → skipped for MVP (Playwright books whatever slot is available)

---

### Sprint B — Day 2 (March 24): Retell agent playbook + metadata audit
**Blocking:** Edgar cannot configure the Retell agent without knowing exact URLs, metadata keys, and prompt structure.

- [x] **B1:** Create `docs/retell_agent_playbook.md` with:
  - Env vars checklist: `RETELL_API_KEY`, `RETELL_FROM_NUMBER`, `RETELL_WEBHOOK_SECRET`, `APP_BASE_URL`
  - Retell dashboard webhook URLs (copy-paste): `/retell/webhook/call_started`, `/retell/webhook/call_ended`, `/retell/webhook/call_analyzed`
  - Custom tool URLs: `POST /retell/tools/get_available_slots`, `POST /retell/tools/book_appointment`
  - Exact metadata keys the worker sends with each outbound call: `clinic_id`, `campaign_contact_id`, `gap_type`, `patient_name` (for agent greeting), `provider_name` (for context)
  - Gap-type to script section mapping — which gap types use appointment path vs order path
  - Agent LLM prompt template: when to call `get_available_slots`, when to call `book_appointment`, when to summarize and end (order-based), timeout note (3 seconds max for slot lookup)
  - Allowed `gap_type` values (mirror `data/enums.py`) — list all 8
- [x] **B2:** Audit `services/retell_client.py` create_outbound_call — confirm all metadata keys in B1 are actually sent; fix any gaps
- [x] **B3:** Audit `Routes/retell.py` webhook handlers — confirm `call_started`, `call_ended`, `call_analyzed` extract metadata keys correctly; fix any gaps
- [x] **B4:** Confirm `call_analyzed` triggers `call_summarizer.py` correctly; confirm encrypted result persisted to `campaign_audit`

**Sprint B engineering note (2026-03-23) — order-based `call_ended` outcomes**

Order-based care gaps have no `ehr_appointment_id`, so a normal call hangup was previously mapped to **DECLINED** (terminal). **`_apply_hedis_call_ended`** now sets **`ORDER_AGREED`** optimistically when the mapped outcome would be **DECLINED** and `gap_type` is in **`ORDER_BASED_GAP_TYPES`**. This avoids false “declined” terminal states before transcript analysis exists. **Sprint C** must add structured extraction on **`call_analyzed`** (or equivalent) to set **`ORDER_DECLINED`** when the patient actually declined. Until then, staff rely on the encrypted one-sentence Claude summary in **`campaign_audit`**. Documented in **`docs/retell_agent_playbook.md`** §9.2.

---

### Sprint C — Day 3–4 (March 25–26): Simplified staff notes + E2E gate

- [x] **C1:** Extend `call_summarizer.py` (or add `call_staff_notes_extractor.py`) — Claude extracts structured output for order-based gaps:
  ```json
  {
    "patient_agreed": true/false,
    "action_for_staff": "Send colorectal stool kit order",
    "note": "Patient confirmed mailing address and agreed to receive kit"
  }
  ```
  Encrypt with AES-256-GCM; store in `campaign_audit`. Discard transcript. One-sentence summary still stored for appointment-based gaps. **Implemented:** `extract_order_based_notes_sync` + `webhook_call_analyzed` branch; note stored in `call_summary_encrypted`.

- [x] **C2:** E2E gate — **curl/Swagger steps** documented in `docs/retell_agent_playbook.md` §13. Execute the gate locally or on staging, then record in `PROGRESS.txt`:
  - Stand up API: `docker compose -f docker-compose.dev.yaml up -d` (see §13)
  - Run DB migrations: `docker compose ... --profile migrate run --rm migrate` or `alembic upgrade head`
  - Configure Retell agent (§10) with tunnel `APP_BASE_URL` if needed
  - Create clinic + EHR config via admin API (§13.2–13.3) or Swagger
  - Upload CSV + start campaign via Swagger or scripted client (§13.4)
  - Confirm logs + DB as in §13.5

---

### Deferred — post-MVP (do not build this week)

| Item | Deferred to |
|---|---|
| `clinic_insurance_rules` table | Plan 013 (post-MVP) |
| `clinic_scheduling_rules` table | Plan 013 (post-MVP) |
| Double-booking enforcement in Playwright EHR | Plan 013 (post-MVP) |
| Insurance year eligibility (one_year_one_day rule) | Plan 013 (post-MVP) |
| Hospital flu telehealth mode (`telehealth_4_5pm`) | Plan 013 (post-MVP) |
| PUT /clinics/scheduling-rules + PUT /clinics/insurance-rules | Plan 013 (post-MVP) |
| React dashboard (Feature 7) | Plan 009 (after MVP + Plan 012) |
| API security hardening + rate limits | Plan 012 (after MVP test call) |
| PHI audit, load test, production deploy | Plan 010 (after dashboard); **Plan 015** (`HIPAA_COMPLIANCE_AUDIT.md`) |
| Super Admin onboarding screen | Plan 013 §9 (after pilot) |

---

## Plan 015 — HIPAA Security Rule Compliance Audit
**Date:** 2026-03-23
**Status:** Active reference (not a build sprint — tracks findings and maps them to other plans)
**Source:** `HIPAA_COMPLIANCE_AUDIT.md` (45 CFR Part 164 — HIPAA Security Rule; static analysis of `Clinic_app/`, tests, Docker, migrations)

### What This Plan Is

A **documented compliance audit** of the codebase with severity-tagged findings (Critical / High / Warning / Compliant). It does not replace legal HIPAA sign-off; it is the engineering backlog for Security Rule gaps discovered in review.

### Why It Matters

- **Critical (C-01):** Google service account JSON stored as plaintext despite encryption intent — must align with `encrypt_phi()` / BYTEA patterns like other secrets.
- **High:** Includes Retell webhook signature bypass for test/playground call IDs, missing token revocation, rate limiting gaps, OpenAPI exposure — these align with **Plan 012** (API security hardening).
- **Warnings / operational:** Feed **Plan 010** (Feature 8) for production readiness and ongoing PHI-safe operations.

### How We Use It

1. Keep `HIPAA_COMPLIANCE_AUDIT.md` updated when major security-relevant code paths change (auth, webhooks, encryption, admin routes).
2. **Before production pilot:** Close or explicitly accept all Critical and High items (or document compensating controls).
3. **Cross-walk:** When implementing Plan 012 or Plan 010, grep the audit for matching finding IDs (e.g. H-01) and mark them resolved in the audit or in `PROGRESS.txt`.

### Deferred

- Full BAAs, penetration test, and organizational HIPAA policies remain out of scope for this engineering-only audit document.

---

## Plan 016 — Basic Application Logging
**Date:** 2026-03-23
**Status:** ✅ Complete (2026-03-25)
**Goal:** Add diagnostic logging so Edgar can trace the full E2E flow during the March 27 test call.

### What Was Built

- [x] **L1:** Created `Clinic_app/common/logging_utils.py` — shared PHI masking: `mask_phone_e164()` + `mask_phone_in_string()`
- [x] **L2:** `campaign_worker.py` — removed private `_mask_phone_e164`, imported shared utility; added 4 diagnostic `logger.info()` calls at silent decision branches (outside calling hours, at concurrency capacity, no eligible contact, pre-dial with contact_id + gap_type + masked phone)
- [x] **L3:** `call_summarizer.py` — added 6 `logger.info()` calls: empty transcript, pre-Claude-call, and success for both `summarize_transcript_sync` and `extract_order_based_notes_sync`
- [x] **L4:** Created `tests/test_logging_utils.py` — 11 unit tests for masking utility (all pass)
- [x] **L5:** `test_campaign_worker.py` — updated `test_mask_phone_e164` to import from shared utility

### Deferred to Plan 010 (Hardening)

| Item | Reason |
|------|--------|
| JSON structured logging | Production concern, not needed for E2E test |
| Request correlation IDs / trace IDs | Non-trivial to add mid-request; Plan 010 |
| Reformatting f-string logs to %-style | Opportunistic — not blocking |
| Azure Monitor / Log Analytics integration | Plan 010 |
| Log-level config via `LOG_LEVEL` env var | Plan 010 |
| `mask_phone_in_string` wired into existing code | Utility available; apply opportunistically |
| `logging.dictConfig` replacing `basicConfig` | Plan 010 |

---

---

## Plan 017 — No-Claude Local Test Mode
**Date:** 2026-03-25
**Status:** Pending
**Goal:** Allow the full E2E flow to run without `ANTHROPIC_API_KEY` so Edgar can test locally before obtaining an Anthropic key or BAA.

### Context

Two places in the codebase require Claude:
1. **`csv_parser.py`** — calls Claude once per upload to normalize column headers (e.g. "Pt Name" → `patient_name`)
2. **`call_summarizer.py`** — calls Claude after `call_analyzed` webhook to extract `patient_agreed` and store encrypted summary

For local testing with a well-formatted Google Sheet and non-critical outcome tracking, both can be bypassed safely.

### What to Build

#### Step 1 — Direct header mapping fallback in `csv_parser.py`

Add `_try_direct_header_mapping(header_row, sample_rows) -> Optional[dict]` that:
- Normalizes each header to lowercase + strips spaces/underscores
- Matches against a hard-coded alias table covering all common column names:
  - phone: `phone`, `phone number`, `member phone`, `patient phone`, `cell`, `mobile`, `telephone`
  - gap_type: `gap type`, `gap_type`, `gap`, `measure`, `hedis measure`, `care gap`
  - patient_name: `member name`, `patient name`, `patient_name`, `name`, `full name`
  - language: `language`, `lang`, `preferred language`
  - provider_name: `provider`, `provider name`, `provider_name`, `pcp`, `physician`, `doctor`
  - payer: `payer`, `insurance`, `plan`, `health plan`, `insurer`
  - release_date: `release date`, `discharge date`, `release_date`
- For gap_type values: if the cell value already matches a `GapType` enum value exactly (case-insensitive), use it directly — no mapping needed
- Returns a `dict` in the same shape as Claude's response if `phone` and `gap_type` columns are found; returns `None` if required columns can't be identified
- In `parse_file()`: call `_try_direct_header_mapping()` first; only call Claude if it returns `None`

Log line when direct mapping succeeds: `"Direct header mapping succeeded — skipping Claude column normalization"`
Log line when falling back to Claude: `"Direct header mapping failed — calling Claude for column normalization"`

#### Step 2 — Retell summary fallback in `retell.py` `webhook_call_analyzed`

If `ANTHROPIC_API_KEY` is not set:
- Use `_extract_transcript_for_summary(call_obj)` result directly as the summary string (this already reads `call_analysis.call_summary` from Retell's payload)
- For order-based gaps (colorectal, mammography, etc.): store the raw summary, log a warning that `patient_agreed` could not be extracted, leave contact status as set by `_apply_hedis_call_ended` (which already handles the ANSWERED/BOOKED/DECLINED logic from the call_ended webhook)
- For appointment-based gaps: store the raw summary — no change in behavior
- Log line: `"ANTHROPIC_API_KEY not set — using Retell call_summary directly (no structured extraction)"`

**What this means for testing:**
- Test A (colorectal): call summary will be Retell's generic text instead of Claude's structured JSON. Contact status will still be set by `_apply_hedis_call_ended` based on call outcome.
- Test B (preventive_visit): no behavior change — summary is one sentence anyway.

### Files to Change

| File | Change |
|------|--------|
| `Clinic_app/services/csv_parser.py` | Add `_try_direct_header_mapping()`, update `parse_file()` to call it first |
| `Clinic_app/Routes/retell.py` | In `webhook_call_analyzed`: check for `ANTHROPIC_API_KEY` before calling summarizer |
| `tests/test_csv_parser.py` | Add tests for direct mapping with standard headers |

### Explicitly Deferred

- Removing `anthropic` package from requirements (still needed for full prod path — just optional at runtime)
- Structured `patient_agreed` extraction from Retell summary text (post-MVP if needed)
- Making `ANTHROPIC_API_KEY` optional in `call_summarizer.py` itself (currently raises — keep raising, just bypass the import in the webhook handler)

---

## Plan 018 — AgentQL → Browser-Use + Azure OpenAI (HIPAA-Safe EHR Automation)
**Date:** 2026-03-26
**Status:** Pending — implement before pilot with real patients
**Trigger:** HIPAA audit finding T-01 (AgentQL has no BAA) + multi-EHR scalability requirement

### Context

AgentQL sends full page DOM (including PHI on NextGen scheduling pages) to their cloud API on every `query_elements()` call. No published BAA → violates 45 CFR §164.308(b)(1). Finding T-01 in `HIPAA_COMPLIANCE_AUDIT.md`. Hardcoded Playwright selectors don't scale to multi-EHR.

### What We Are Building

**Two-layer architecture** replacing AgentQL:

**Layer 1 — Playbook Recorder** (Browser-Use Agent, runs in background):
Browser-Use Agent navigates EHR using natural language + Azure OpenAI LLM. Every Playwright action is recorded as a **Playbook** (JSON action sequence) cached in Redis (7-day TTL). Runs once per clinic session setup or on playbook invalidation.

**Layer 2 — Playbook Executor** (raw Playwright, runs during live calls):
Replays cached playbook using `page.locator()` calls. No LLM involved. Sub-second execution. If a step fails (EHR UI changed), queues background re-discovery.

**Slot Pre-fetch Loop**: Background task refreshes slots every 90s for active campaigns, caching in Redis (120s TTL). Retell `get_available_slots` gets instant cache hit.

### Key Architecture Decisions

| Decision | Reasoning |
|---|---|
| Two-layer Playbook Recorder + Executor | Solves 3-second Retell webhook deadline. Browser-Use takes 5-15s; raw Playwright playback takes <1s. |
| Browser-Use open-source, NOT Cloud | Cloud version has same PHI exposure as AgentQL. Open-source keeps data local. |
| Azure OpenAI as LLM backend | HIPAA BAA covers text inputs. Data stays in Azure tenant. |
| `use_vision=False` (no screenshots) | Image BAA coverage unconfirmed. Text-only DOM stays in covered territory. |
| `sensitive_data` for EHR credentials | Credentials isolated from LLM context via placeholder tokens. |
| `allowed_domains` | Locks browser navigation to authorized EHR domain only. |
| ZDR + private endpoints required in production | 30-day abuse monitoring stores prompts by default. ZDR eliminates this. Private endpoints prevent public internet exposure. |

### Playbook vs Application Logic Boundary

The playbook is a **low-level EHR remote control**. It does NOT encode business rules.

| Responsibility | Where it lives |
|---|---|
| Navigate EHR pages, read slots, fill/submit forms | **Playbook** |
| Filter slots (no 2 preventatives same hour) | **App logic** (webhook handler / campaign worker) |
| Insurance eligibility rules | **App logic** (future plan) |
| Offer best slot to patient | **Retell agent prompt** |
| Decide which slot to book | **App logic** (retell.py) |

### Redis Key Schema

| Key | TTL | Purpose |
|-----|-----|---------|
| `ehr:playbook:{clinic_id}:{workflow}` | 7 days | Cached action sequence |
| `ehr:slots:{clinic_id}:{provider}:{date}` | 120s | Pre-fetched slots |
| `ehr:playbook:version:{clinic_id}` | No expiry | Version counter |

Replaces old `agentql:selector:{clinic_id}:{element_name}` keys.

### Implementation Steps

- [ ] Step 1: `requirements.txt` — remove `agentql==1.18.1`, add `browser-use>=0.12.0`, `langchain-openai>=0.3.0`
- [ ] Step 2: Rename `selector_cache.py` → `playbook_cache.py` — new key schema, playbook + slot cache functions
- [ ] Step 3: `playwright_ehr.py` — add PlaybookStep/Playbook/SlotData/ConfirmationData data structures, `_get_llm()` singleton, playbook management methods
- [ ] Step 4: `playwright_ehr.py` — replace 8 AgentQL calls with playbook recorder/executor pattern:
  - MFA detection → pure CSS heuristic (no LLM)
  - Login → playbook with `sensitive_data` credential placeholders
  - Navigation → playbook with cached nav selector
  - Provider dropdown → playbook with `{provider_name}` placeholder
  - Slot reading → playbook + `SlotData` output model + pre-fetch loop
  - Booking form → playbook with `{patient_name}`, `{appt_type_code}` placeholders
  - Submit + confirmation → playbook + `ConfirmationData` output model
- [ ] Step 5: Add slot pre-fetch loop (90s interval, 120s TTL), wire into `initialize_session()`/`shutdown_session()`
- [ ] Step 6: Update `admin.py` import (`invalidate_clinic_selectors` → `invalidate_clinic_playbooks`)
- [ ] Step 7: Update `env.example` — uncomment Azure OpenAI vars `[REQUIRED for EHR]`, deprecate AGENTQL_API_KEY
- [ ] Step 8: Update `CLAUDE.md` tech stack table
- [ ] Step 9: Update tests — replace AgentQL import tests, update cache key assertions, add playbook execution tests
- [ ] Step 10: Update `docs/local_test_guide.md` — add Azure OpenAI resource creation guide, update EHR section
- [ ] Step 11: Mark T-01 as REMEDIATED in `HIPAA_COMPLIANCE_AUDIT.md`

### Files to Change

| File | Change |
|---|---|
| `requirements.txt` | Remove agentql, add browser-use + langchain-openai |
| `Clinic_app/services/playwright_ehr.py` | Major rewrite: playbook infrastructure, Browser-Use integration, slot pre-fetch |
| `Clinic_app/services/selector_cache.py` → `playbook_cache.py` | Rename + repurpose for playbooks + slot cache |
| `Clinic_app/Routes/admin.py` | Update import |
| `env.example` | Uncomment Azure OpenAI vars, deprecate AGENTQL_API_KEY |
| `CLAUDE.md` | Update tech stack |
| `HIPAA_COMPLIANCE_AUDIT.md` | Mark T-01 remediated |
| `docs/local_test_guide.md` | Add Azure OpenAI setup guide |
| `tests/test_playwright_docker.py` | Replace AgentQL import tests |
| `tests/test_playwright_validation.py` | Update cache key assertions |
| `tests/test_selector_cache.py` → `test_playbook_cache.py` | Rename + update |
| `tests/test_playwright_ehr_service.py` | Add playbook mock tests |

### Local Dev: Azure OpenAI Setup

1. Azure Portal → Create resource → "Azure OpenAI" → East US region → Standard S0
2. Model deployments → Create → `gpt-4o` → deployment name `gpt-4o` → Standard type
3. Keys and Endpoint → copy Endpoint + Key 1
4. `.env`: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION=2025-03-01-preview`, `AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o`
5. Apply for access if needed: https://aka.ms/oai/access

### Production Prerequisites (Plan 010)

1. Apply for Modified Abuse Monitoring (ZDR) — eliminates 30-day prompt storage
2. Private endpoint + VNet — no public internet to LLM
3. Managed Identity instead of API key
4. Verify `ContentLogging: false` in Azure resource
5. US region Standard deployment

### Explicitly Deferred

- Production Azure OpenAI hardening (Plan 010)
- Epic / Athena task descriptions (post-MVP)
- Image/screenshot-based resolution (unconfirmed BAA coverage)
- Clinic-specific scheduling business rules (separate plan)

---

## Plan 019 — EHR automation architecture: MVP path vs post-MVP
**Date:** 2026-03-27  
**Status:** Active (reference — constrains scope for pilot/MVP vs later scale)  
**Source:** Architecture discussion (selector cache, Playwright scripts, slot cache, multi-tenant EHR)

### Plain-language model (three pieces)

1. **Playwright script** — A fixed checklist in code (click here, type there). Fast and cheap; breaks when the EHR UI changes.
2. **Selector cache** — Saved “where to click” (CSS/AgentQL/playbook text) per clinic or EHR template, reused instead of rediscovering the DOM every run.
3. **Slot cache** — Redis copy of “next available slots” so Retell’s `get_available_slots` stays under ~3s; populated by a background job, short TTL.

**Ideal long-term:** deterministic Playwright + selector playbooks for stable flows; LLM/Browser-Use mainly for discovery, breakage, or ambiguous UIs. **Multi-EHR:** one “adapter” interface per product (NextGen, Epic, …), tenant-scoped config and caches (never global selectors for all clinics).

### What we have today (post–Plan 018)

- **NextGen-first:** `ClinicEHRConfig` (URL, encrypted creds, `appt_type_mapping` JSONB) — not a generic multi-EHR abstraction yet.
- **Slot cache:** `playbook_cache.py` + `SlotPrefetchWorker` — matches the “slot cache” pattern; keys include `clinic_id`.
- **Hot path:** `get_available_slots` reads Redis only (fast); prefetch uses **Browser-Use + LLM** (`fetch_slots_live`) to refresh slots.
- **No full selector-playbook layer** driving every click without LLM; Browser-Use task strings do the navigation. Redis docstring still references historical AgentQL selector-cache intent; implementation center of gravity is **LLM-driven Browser-Use** + **slot result cache**.

### MVP recommendation — keep it simple

**Goal:** Ship a **pilot-ready** path with **minimum moving parts**: one EHR (NextGen), one clinic’s reality, HIPAA-safe LLM (Azure OpenAI in prod per Plan 018), Retell deadlines met.

**Include for MVP (must ship or already in place):**

| Item | Rationale |
|------|-----------|
| **NextGen-only automation** | Matches PRD pilot; avoid abstract “EHR adapter” interfaces until a second EHR is contracted. |
| **Slot cache + prefetch** | Already the design; required for sub–3s tool responses. Keep worker healthy and TTL sensible. |
| **Per-clinic `ClinicEHRConfig`** | URL, creds, `appt_type_mapping` — customization without code changes for appointment-type codes. |
| **Browser-Use + Azure OpenAI for EHR tasks in prod** | Resolves T-01 (no AgentQL in prod); acceptable MVP cost/latency for **pilot volume**. |
| **Manual gate: `browser-use-test/test_nextgen_browseruse.py`** | Validates login/MFA/slots path against real NextGen before real patients. |
| **Tenant isolation** | All DB queries `clinic_id`-scoped; Redis keys include `clinic_id` (already required by PHI rules). |
| **`EHR_LLM_PROVIDER` env** | Ollama local dev, `azure_openai` production — single deployment config is OK for MVP. |

**Explicitly defer post-MVP (do not block pilot on these):**

| Deferred item | Why defer |
|---------------|-----------|
| **Generic EHR adapter layer** (Epic, athena, …) | No second EHR in MVP; adds interfaces and tests without pilot value. |
| **Redis-backed selector/playbook cache** replacing most LLM navigation | Major engineering; optimize after pilot proves volume and pain (cost/latency). |
| **Per-clinic LLM routing** (different model per tenant) | Operational complexity; revisit when multi-tenant LLM cost tuning is required. |
| **Full scheduling rules engine** | Plan 013 complex rules (`clinic_scheduling_rules`, etc.) — post-MVP unless a hard blocker appears. |
| **Vision/screenshot-based EHR steps** | BAA/PHI and cost; stay `use_vision=False` unless headless text-only fails. |

### Evolution path (after MVP test call / pilot)

1. Measure **real** prefetch duration, token use, and failure modes on Azure OpenAI.
2. If **cost or latency** is the bottleneck, add **playbook or selector reuse** for the **stable** parts of NextGen (login → scheduler) first — **one pilot clinic**, then generalize keys by `clinic_id`.
3. When a **second EHR** is real, introduce an **adapter boundary** (interface + NextGen implementation) rather than scattering `if epic` in routes.

### Deferred (unchanged from other plans)

- Plan 013 advanced scheduling/insurance rules until core path is stable.
- Plan 010 production LLM hardening (private endpoint, ZDR) for non-pilot scale.

---

## Plan 020 — Unified Retell webhook (single URL + `event` dispatch)
**Date:** 2026-03-30  
**Status:** Complete (2026-03-30)  
**Source:** Retell product behavior ([Webhook Overview](https://docs.retellai.com/features/webhook), [Create Phone Call](https://docs.retellai.com/api-references/create-phone-call)) + codebase review (`Clinic_app/Routes/retell.py`)

### Problem

- Retell supports **one** webhook URL at account level (or per-agent `webhook_url`). Every subscribed lifecycle event (`call_started`, `call_ended`, `call_analyzed`, …) is **POSTed to that same URL**; the JSON body includes `"event": "<type>"`.
- The app currently exposes **three separate routes**: `POST /retell/webhook/call_started`, `/call_ended`, `/call_analyzed`. If the dashboard URL is set to only one of those paths, **all** events hit that path — wrong handler and broken validation.
- Outbound dialing is unchanged: `POST https://api.retellai.com/v2/create-phone-call` (see `services/retell_client.py`). Webhooks are **Retell → app**, not how calls start.

### What We Are Building

1. **`POST /retell/webhook`** — Read raw body → `verify_retell_signature` → parse JSON → `match` / `if` on `event` → invoke the same business logic as today’s three handlers (refactor into shared async functions if needed to avoid duplication).
2. **Unknown `event`** — Return 2xx (acknowledge) and log at warning; do not 500 (Retell retries on non-2xx).
3. **Tests** — Extend `tests/test_retell.py` / `tests/test_hedis_webhooks.py` to hit the unified route with each `event` and assert behavior matches existing expectations.
4. **Docs** — Update `docs/retell_agent_playbook.md` §5.3 (and `docs/local_test_guide.md` if it lists three webhook URLs) so the **single** URL is the documented contract; optional note that path-specific routes may remain for manual testing or be thin wrappers calling shared code.

### Key Decisions & Reasoning

- **One public URL** aligns with Retell’s model; dispatch on `event` is the standard pattern in Retell’s own SDK examples.
- **Keep HMAC verification** identical (raw body, same secret); no change to PHI handling in handlers.
- **Optional:** Deprecate or keep the three path-specific routes as aliases that forward to the same logic — if kept, document that Retell must not be pointed at them unless using a reverse-proxy fan-out (not recommended).

### Deferred

- Retell **transfer** / `transcript_updated` events — only add branches when product requires them.
- Rate limiting for `/retell/webhook` remains **Plan 012** scope unless merged earlier for ops reasons.

### Implementation Steps

- [x] Extract or delegate `webhook_call_*` body into shared handlers callable from one route (`_handle_call_started`, `_handle_call_ended`, `_handle_call_analyzed` in `retell.py`).
- [x] Add `POST /retell/webhook` with `event` dispatch + safe default for unknown events.
- [x] Tests for unified route (`tests/test_retell.py::TestUnifiedWebhook`); existing HEDIS webhook tests unchanged (aliases).
- [x] Playbook + local test guide: one webhook URL `…/retell/webhook`.

---

*Last updated: 2026-03-30 (Plan 020 implemented — unified Retell webhook)*
*Maintained by: Edgar J. Suárez Colón*
*Next action: **Plan 014 Sprint B/C** Retell dashboard setup (use `/retell/webhook`); then **Plan 014 Sprint C E2E gate** per `docs/local_test_guide.md`. Manual Browser-Use validation: `cd browser-use-test && python test_nextgen_browseruse.py` against real NextGen + Ollama before pilot with real patients.*
