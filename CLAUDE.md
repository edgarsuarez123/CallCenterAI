# CLAUDE.md — CallCenterAI / HEDIS Outreach Automation

> This file is read by Claude Code at the start of every session.
> It defines project context, rules, workflow, and session behavior.
> Do not delete or modify without explicit instruction from Edgar.

---

## Project Identity

**Project:** CallCenterAI — HEDIS Outreach Automation Platform
**Author:** Edgar J. Suárez Colón
**Codebase root:** `C:\Users\Edgar\Projects\CallCenterAI`
**PRD:** See `HEDIS_PRD_v2.0.md` (source of truth for all requirements)
**Status:** Active development — MVP phase

---

## What This Project Does

A multi-tenant SaaS platform that automates HEDIS care-gap outreach for primary care clinics on NextGen EHR. Clinics upload a CSV of patients with care gaps. The system calls each patient via Retell AI voice agents, checks NextGen availability mid-call via server-side Playwright + AgentQL, books appointments, and logs outcomes to a clinic dashboard. Built on FastAPI + Azure PostgreSQL + Azure hosting.

---

## Tech Stack (Do Not Change Without Explicit Approval)

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.104.1 (async) |
| ORM | SQLAlchemy 2.0.23 (async) |
| Migrations | Alembic 1.12.1 |
| Database | Azure PostgreSQL Flexible Server |
| Cache | Redis (Azure Cache) — selector cache + distributed lock |
| Encryption | AES-256-GCM via `common/encryption.py` |
| Voice | Retell AI — outbound calling + webhooks |
| LLM | Anthropic Claude API (`claude-sonnet-4-20250514`) |
| EHR Automation | Playwright (server-side headless Chromium) + AgentQL |
| Auth | Google OAuth 2.0 (staff) + API Key (admin routes) |
| Hosting | Microsoft Azure (HIPAA BAA in effect) |
| Container | Docker / docker-compose |

**Do NOT use:**
- OpenAI API for new features (Azure OpenAI config is left in place but inactive — do not activate)
- Supabase (no BAA — cannot handle PHI)
- Any new database vendor without Edgar's approval
- Chrome Extension architecture unless Playwright headless is confirmed blocked by NextGen

---

## Repository Layout

```
CallCenterAI/
├── Clinic_app/
│   ├── main.py                  # App factory — router registration here
│   ├── common/
│   │   ├── database.py          # Async SQLAlchemy engine + session factory
│   │   └── encryption.py        # AES-256-GCM — use this for ALL PHI at rest
│   ├── data/
│   │   ├── enums.py             # All domain enumerations
│   │   └── models/              # SQLAlchemy ORM models
│   ├── Routes/                  # FastAPI routers
│   ├── services/                # Business logic
│   ├── workers/                 # Background tasks (campaign worker goes here)
│   └── alembic/                 # DB migrations
├── agentql-test/
│   └── click-test.js            # Playwright + AgentQL proof-of-concept — RUN THIS FIRST
├── tests/                       # pytest async test suite
├── CLAUDE.md                    # This file
├── PLAN.md                      # Implementation plans with reasoning (auto-created if missing)
├── PROGRESS.txt                 # Session-by-session progress log (auto-updated)
├── PRD.md                       # Original PRD
├── HEDIS_PRD_v2.0.md            # Current source-of-truth PRD
├── HEDIS_CAMPAIGN_IMPLEMENTATION.md  # Detailed campaign implementation checklist
├── INFRASTRUCTURE.md            # Architecture reference
├── Dockerfile
├── docker-compose.yaml
├── docker-compose.dev.yaml
├── requirements.txt
└── env.example
```

---

## Session Startup Behavior

**At the start of every session, Claude MUST:**

1. Check if `PLAN.md` exists in the project root
   - If it does NOT exist: create it using the template in the [PLAN.md Template](#planmd-template) section below
   - If it exists: read it to understand the current implementation plan and where work left off

2. Read `PROGRESS.txt` to understand what was completed in previous sessions

3. Read the relevant section of `HEDIS_PRD_v2.0.md` for whatever is being worked on that session

4. State clearly at the start of the session:
   - What was completed last session (from PROGRESS.txt)
   - What the current plan says to do next
   - What you are about to work on this session

**Do NOT start writing code until steps 1–4 are complete.**

---

## Session End Behavior

**At the end of every session, Claude MUST:**

1. Append a session entry to `PROGRESS.txt` (see format below)
2. Update `PLAN.md` if the implementation plan changed during the session
3. Summarize what was done, what was skipped, and what comes next

---

## PLAN.md Behavior

`PLAN.md` is the living implementation plan for this project. It is NOT a static document.

**Rules:**
- Every time a new implementation plan is created or refined in conversation with Edgar, it gets added to `PLAN.md` with a timestamp and the reasoning behind key decisions
- Plans are appended — never deleted. Old plans are marked `[SUPERSEDED]` and kept for reference
- Each plan entry must include: what we decided to build, why we made key architecture choices, and what was explicitly deferred
- When Edgar says "let's implement X" or "the plan is to do Y," Claude adds it to PLAN.md before writing code

---

## PROGRESS.txt Behavior

`PROGRESS.txt` is the session log. Every session gets one entry appended to the bottom.

**Format for each entry:**
```
================================================================================
SESSION: [Date] [approximate time]
================================================================================
COMPLETED:
- [Specific thing completed — file name, function name, migration name]
- [Another thing completed]

SKIPPED / DEFERRED:
- [Thing not done and why]

ERRORS / BLOCKERS:
- [Any error encountered and how it was resolved or left unresolved]

NEXT SESSION SHOULD START WITH:
- [Specific next action — be precise, not vague]

FILES MODIFIED:
- [list of files touched this session]
================================================================================
```

---

## PHI Rules — NEVER Violate These

These are non-negotiable. If a task would violate these rules, stop and ask Edgar.

1. **Never store patient name in plaintext in the database** — name goes to Retell as call metadata only, and is stored in `campaign_audit.patient_name_encrypted` using AES-256-GCM if needed for dashboard display
2. **Never store patient DOB in the database** — passed as Retell metadata only
3. **Never store raw call transcripts** — generate a one-sentence Claude summary on `call_analyzed` webhook, store that encrypted, discard the transcript
4. **Always use `common/encryption.py`** for any PHI stored at rest — never roll your own encryption
5. **Never log phone numbers in plaintext** — mask as `***-***-XXXX` in all log output
6. **Never store NextGen credentials in plaintext** — AES-256-GCM in `ClinicIntegration`
7. **All new DB queries must include `clinic_id` filter** — row-level tenant isolation is mandatory
8. **Phone numbers stored as AES-256-GCM encrypted + SHA-256 hash for dedup** — both required

---

## Architecture Rules — Follow These Every Time

- **One Retell agent per clinic** — gap_type passed as call metadata, not separate agents
- **Server-side Playwright only** — no Chrome extension unless NextGen blocks headless (test first)
- **AgentQL for dynamic EHR elements** — hardcoded Playwright selectors for stable navigation
- **Redis for AgentQL selector cache** — 24-hour TTL, reduces token cost ~60%
- **3 concurrent calls per clinic default** — configurable via `campaign_concurrency_limit`
- **Calling hours 9am–6pm clinic timezone** — enforced in campaign worker, configurable per clinic
- **FIFO across all campaigns** — contacts processed in CSV row order across active campaigns
- **Max 3 attempts per contact** — VOICEMAIL retries after `voicemail_retry_hours`, NO_ANSWER after `no_answer_retry_hours`, ERROR after `error_retry_hours` — all configurable per clinic
- **Retell webhook timing** — `get_available_slots` must respond in under 3 seconds

---

## Known Architectural Gaps (Fix Before HEDIS Work)

These must be resolved first — they are blocking:

| Gap | File | Fix |
|---|---|---|
| Routers not registered | `main.py` | Add `app.include_router()` for admin, retell, provider routers |
| Reaper worker not scheduled | `main.py` | Wire APScheduler to call reaper every 60 seconds on startup |
| No auth on admin routes | `Routes/admin.py` | Add `Depends(verify_admin_api_key)` to all /admin/* routes |
| Redis client not instantiated | `common/` or `main.py` | Instantiate Redis client for selector cache + distributed lock |

---

## Critical Validation Gate

**Before writing any backend HEDIS code:**
Run `agentql-test/click-test.js` against the pilot clinic's actual NextGen instance.
Confirm:
- Headless Chrome is NOT blocked
- Login works
- AgentQL can read available appointment slots
- Booking form can be filled and submitted

**If NextGen blocks headless Playwright → fall back to Chrome Extension architecture per `HEDIS_CAMPAIGN_IMPLEMENTATION.md`**

This test result must be logged in `PROGRESS.txt` before any other HEDIS work begins.

---

## PAQ Conflict of Interest — Do Not Violate

Edgar begins the U.S. Air Force Palace Acquire (PAQ) program in May 2026. The following are prohibited:

- No work on **GrantPilot** or any grant-writing automation targeting federal agencies
- No work that could constitute a conflict of interest with Air Force Weather Systems branch work
- All consulting and SaaS work must remain in the civilian healthcare / clinic space

---

## Environment Variables Reference

All secrets come from environment variables. Never hardcode any of these:

```bash
# Application
APP_ENVIRONMENT=development|production
APP_PORT=8000
APP_WORKERS=4

# Database
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=

# PHI Encryption (AES-256 key, base64-encoded 32 bytes)
PHI_ENCRYPTION_KEY=

# Retell AI
RETELL_WEBHOOK_SECRET=
RETELL_API_KEY=
RETELL_FROM_NUMBER=

# Admin Auth
ADMIN_API_KEY=

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=

# Anthropic Claude API
ANTHROPIC_API_KEY=

# Redis
REDIS_URL=redis://localhost:6379

# JWT
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256

# Azure OpenAI (inactive — do not use for new features)
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_API_VERSION=
AZURE_OPENAI_DEPLOYMENT_NAME=
```

---

## Testing Standards

- All new code gets async pytest tests following patterns in `tests/`
- Tests are tagged: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`
- PHI encryption must be tested — see `test_encryption.py` for patterns
- Webhook handlers must be tested with HMAC signature verification — see `test_retell.py`
- Never test against the real pilot clinic's NextGen — use sandbox or mock

---

## PLAN.md Template

Use this template when creating `PLAN.md` for the first time:

```markdown
# PLAN.md — CallCenterAI HEDIS Implementation Plans

> This file tracks all implementation plans in chronological order.
> Plans are never deleted — superseded plans are marked [SUPERSEDED].
> Each plan includes what was decided, why, and what was deferred.

---

## Plan Index

| # | Date | Title | Status |
|---|---|---|---|
| 1 | [date] | Pre-HEDIS Fixes + Playwright Validation | Active |

---

## Plan 001 — Pre-HEDIS Fixes + Playwright Validation
**Date:** [date]
**Status:** Active
**Source:** HEDIS_PRD_v2.0.md Section 15 + Section 10.6

### What We Are Building
[description]

### Key Architecture Decisions & Reasoning
[decisions]

### Deferred
[what is not in scope for this plan]

### Implementation Steps
- [ ] Step 1
- [ ] Step 2

---
```

---

## Coding Conventions

- **Python:** Black formatting, flake8 lint, type hints on all function signatures
- **Async:** All DB operations use `async with get_db() as db` — never sync in async context
- **Error handling:** Use `tenacity` retry decorator for all external API calls (Retell, Claude, AgentQL)
- **Logging:** Use Python `logging` module — never `print()` — mask PHI in all log messages
- **Migrations:** Every schema change gets an Alembic migration — never modify tables directly
- **Secrets:** Never in code, never in logs, always from environment variables

---

*Last updated: March 2026*
*Maintained by: Edgar J. Suárez Colón*
