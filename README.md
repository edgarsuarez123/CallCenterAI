# CallCenterAI

**HEDIS care-gap outreach automation** for primary care clinics on **NextGen EHR**. Clinics upload patient lists; the platform places **Retell AI** voice calls, can check **NextGen** availability during a call via **Playwright + AgentQL**, supports booking workflows, and exposes APIs for admin, providers, and voice tooling.

| | |
|---|---|
| **Author** | Edgar J. Suárez Colón |
| **Status** | Active development — MVP |
| **Stack** | FastAPI · PostgreSQL · Azure-oriented hosting |
| **Compliance note** | PHI must be handled per project rules — see [PHI & security](#phi--security) |

---

## Table of contents

- [What this project does](#what-this-project-does)
- [Architecture at a glance](#architecture-at-a-glance)
- [Repository layout](#repository-layout)
- [Tech stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Database migrations](#database-migrations)
- [Running tests](#running-tests)
- [EHR validation (NextGen / Playwright)](#ehr-validation-nextgen--playwright)
- [API documentation](#api-documentation)
- [PHI & security](#phi--security)
- [Documentation index](#documentation-index)
- [Contributing & operations notes](#contributing--operations-notes)

---

## What this project does

- **Multi-tenant SaaS shape**: clinic-scoped data; super-admin vs clinic roles (see PRD).
- **Outbound voice**: Retell AI agents and webhooks/tool endpoints for in-call logic.
- **Scheduling & bookings**: Services for availability, bookings, and audit trails; Google Calendar integration where configured.
- **EHR automation (NextGen)**: Server-side headless Chromium via Playwright, with AgentQL for resilient selectors (see `agentql-test/` and `INFRASTRUCTURE.md`).
- **PHI at rest**: AES-256-GCM via `Clinic_app/common/encryption.py` — do not roll your own crypto.

Detailed product scope, roles, and phased delivery are in **`HEDIS_PRD_v2.md`** (and related implementation docs below).

---

## Architecture at a glance

```text
Clinic staff / Admin
        │
        ▼
   FastAPI (Clinic_app)
        │
        ├── PostgreSQL (clinics, patients, bookings, integrations, …)
        ├── Redis (caching / locks — when enabled)
        ├── Retell AI (calls, webhooks)
        ├── Anthropic Claude (per PRD — parsing / summaries)
        └── Playwright + AgentQL → NextGen (availability / booking automation)
```

For tables, endpoints, and integration details, see **`INFRASTRUCTURE.md`**.

---

## Repository layout

```text
CallCenterAI/
├── Clinic_app/                 # FastAPI application
│   ├── main.py                 # App factory; add routers here
│   ├── common/                 # DB session, PHI encryption
│   ├── data/                   # Enums, SQLAlchemy models
│   ├── Routes/                 # health, retell, admin, provider, …
│   ├── services/               # Business logic
│   ├── workers/                # Background / campaign workers (evolving)
│   └── alembic/                # Migrations
├── agentql-test/               # NextGen / Playwright / AgentQL experiments
├── tests/                      # pytest (async) suite
├── Dockerfile
├── docker-compose.yaml         # App only; expects external PostgreSQL
├── docker-compose.dev.yaml     # App + PostgreSQL + Redis for local dev
├── start.sh                    # Prod-style entry: wait for PG → migrate → uvicorn
├── requirements.txt
├── env.example                 # Environment variable template
├── HEDIS_PRD_v2.md             # Current detailed MVP PRD
├── HEDIS_CAMPAIGN_IMPLEMENTATION.md
├── INFRASTRUCTURE.md           # Deep architecture reference
├── CLAUDE.md                   # Maintainer / agent session rules
├── PLAN.md                     # Living implementation plan
└── PROGRESS.txt                # Session log
```

---

## Tech stack

| Layer | Technology |
|-------|------------|
| API | FastAPI 0.104.x (async) |
| Server | Uvicorn |
| ORM | SQLAlchemy 2.0.x (async) |
| DB | PostgreSQL (Azure Flexible Server in production) |
| Migrations | Alembic |
| Cache | Redis (selector cache, locks — when wired) |
| Voice | Retell AI |
| LLM | Anthropic Claude (per PRD) |
| EHR UI automation | Playwright + AgentQL |
| Encryption | AES-256-GCM (`common/encryption.py`) |

Python version for containers: **3.11** (see `Dockerfile`).

---

## Prerequisites

- **Python 3.11+** (for local non-Docker dev)
- **PostgreSQL** (15+ recommended; matches dev compose)
- **Redis** (optional locally unless you enable features that require it)
- **Playwright Chromium** (for EHR automation): after `pip install -r requirements.txt`, run:
  ```bash
  python -m playwright install chromium
  ```

---

## Quick start

### 1. Clone and environment

```bash
git clone <your-repo-url> CallCenterAI
cd CallCenterAI
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Copy **`env.example`** to **`.env`** and set at least database and `PHI_ENCRYPTION_KEY` (see [Configuration](#configuration)).

### 2. Database and migrations

From the **repository root**:

```bash
cd Clinic_app
alembic upgrade head
cd ..
```

### 3. Run the API

From the **repository root** (module path `Clinic_app.main:app`):

```bash
uvicorn Clinic_app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000/docs** for Swagger UI.

### Docker (production-style)

Requires a reachable PostgreSQL matching `.env` (`DB_HOST`, etc.):

```bash
docker compose up --build
```

Uses **`start.sh`**: waits for PostgreSQL, runs **`alembic upgrade head`**, then starts Uvicorn with multiple workers.

### Docker (local full stack)

```bash
docker compose -f docker-compose.dev.yaml up --build
```

Adjust `.env` for `DB_HOST=postgres` when using the bundled Postgres service (see `docker-compose.dev.yaml`).

> **Note:** `docker-compose.dev.yaml` starts Uvicorn with `--reload` and does **not** run `start.sh`, so run **`alembic upgrade head`** from `Clinic_app` once after the DB is up, or use the production compose path if you want migrate-on-boot behavior.

---

## Configuration

Primary template: **`env.example`**. Common variables:

| Variable | Purpose |
|----------|---------|
| `APP_ENVIRONMENT` | `development` / `production` |
| `APP_PORT`, `APP_WORKERS` | Server binding and worker count |
| `DB_*` | PostgreSQL connection |
| `PHI_ENCRYPTION_KEY` | Base64-encoded 32-byte key for PHI at rest |
| `RETELL_WEBHOOK_SECRET` | Verify Retell webhook signatures |
| `REDIS_URL` | Redis connection (when used) |
| `ADMIN_API_KEY` | Protect `/admin/*` routes (per PRD) |

**Never commit real secrets.** The repo uses **`.cursorignore`** / ignore rules for `.env` — keep it that way.

For a fuller list aligned with deployment, see **`CLAUDE.md`** (environment reference) and **`DEPLOYMENT_GUIDE.md`** if present in your checkout.

---

## Database migrations

- Config lives under **`Clinic_app/alembic/`**.
- Run migrations from **`Clinic_app`** with Alembic (as in [Quick start](#quick-start)) or rely on **`start.sh`** in Docker.

Every schema change should ship as a **new Alembic revision**, not manual DDL in production.

---

## Running tests

```bash
pip install -r requirements.txt
pytest
```

With coverage:

```bash
pytest --cov=Clinic_app --cov-report=html
```

See **`tests/README.md`** for structure and examples. Prefer **async** tests for DB/API code (`pytest.ini` uses `asyncio_mode = auto`).

---

## EHR validation (NextGen / Playwright)

Before relying on headless automation against a real NextGen tenant, validate:

- Headless Chromium is not blocked
- Login (including MFA flows if applicable — see project tests under `agentql-test/`)
- Read availability and booking paths as designed

Proof-of-concept scripts live in **`agentql-test/`** (e.g. `click-test.js`, Python helpers such as `test_nextgen_headless.py` when present). Log pilot results in **`PROGRESS.txt`** per project process.

---

## API documentation

- **Swagger**: `/docs`
- **ReDoc**: `/redoc`
- **Health**: `/health` (and related routes in `Clinic_app/Routes/health.py`)

Routers under `Clinic_app/Routes/` include **retell**, **admin**, and **provider** surfaces; the exact registration list is defined in **`Clinic_app/main.py`** — verify there for your branch.

---

## PHI & security

Non-exhaustive rules enforced by architecture and code review:

1. **Do not store patient name or DOB in plaintext** in the DB beyond what the PRD explicitly allows; use encryption and minimal retention.
2. **Phone numbers**: encrypted + hash for lookup; **mask** in logs (e.g. `***-***-XXXX`).
3. **NextGen credentials**: encrypted at rest; never return in API responses or logs.
4. **Transcripts**: do not store raw call transcripts if the PRD specifies summaries only — follow **`HEDIS_PRD_v2.md`** and **`CLAUDE.md`**.
5. **Tenant isolation**: queries must scope by **`clinic_id`** unless super-admin tooling explicitly crosses tenants.

Implementers should read **`HEDIS_PRD_v2.md`** Section 11 and **`INFRASTRUCTURE.md`** Section 7.

---

## Documentation index

| Document | Description |
|----------|-------------|
| `HEDIS_PRD_v2.md` | Product requirements — MVP scope, roles, PHI, campaigns |
| `HEDIS_CAMPAIGN_IMPLEMENTATION.md` | Campaign implementation checklist |
| `INFRASTRUCTURE.md` | Architecture, schema, API surface, gaps |
| `PHASE_1_IMPLEMENTATION.md` / `PHASE_2_IMPLEMENTATION.md` | Phased technical notes (if present) |
| `DEPLOYMENT_GUIDE.md` | Deployment steps (if present) |
| `CLAUDE.md` | Maintainer workflow, env vars, strict PHI rules |
| `PLAN.md` | Current implementation plan |
| `PROGRESS.txt` | Session-to-session progress log |

---

## Contributing & operations notes

- **Code style**: Black, flake8, type hints on new Python code (see `CLAUDE.md`).
- **External calls**: use retries (e.g. `tenacity`) for Retell, Claude, and brittle EHR flows.
- **Logging**: use `logging`, not `print`; never log PHI or secrets.
- **Known gaps**: `INFRASTRUCTURE.md` §12 lists items that may still need wiring (routers, scheduler, Redis, admin auth hardening, etc.) — check your branch’s `main.py` and docs before assuming production readiness.

---

## License

Proprietary — **Edgar J. Suárez Colón**. All rights reserved unless otherwise stated in a separate license file.

If you add an explicit `LICENSE` file later, update this section to match.
