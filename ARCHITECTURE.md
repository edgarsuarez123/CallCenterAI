# System Architecture & Requirements Checklist (CallCenterAI)

## 1) Objectives

- Automate inbound and outbound clinic calls (EN/ES): book, reschedule, cancel, FAQs, transfer to staff.
- Enforce HIPAA (BAA), PHI tokenization, audit/access logging.
- Prevent double-booking under concurrency.
- Modular licensing: Reminders and HEDIS can be toggled per clinic.
- One container per clinic; shared Azure tenant/Postgres; centralized metrics.

## 2) High-Level Architecture

### Global Gateway (shared)

- Public ACS webhook endpoint and optional WS proxy.
- DID → clinic routing; license checks; basic auth/rate-limits.

### Clinic Container (per clinic)

- FastAPI app + workers (reminders, HEDIS, ingest, holds reaper, metrics flush).
- Realtime audio over ACS Media WebSocket to Azure Speech; LLM via Azure OpenAI.
- Scheduler merging DB availability with GCal busy; anti-double-booking.

### Central Metrics Aggregator (shared)

- Consumes metrics_event from all clinics; writes 1-minute metrics_aggregate and network roll-ups.

### Azure Postgres (shared)

- Multi-tenant schema keyed by clinic_id.

### Azure Key Vault

- Per-clinic PHI encryption keys; (optional) service secrets.

### Azure Blob

- Templates/FAQs (master + per-clinic overrides) and CSV uploads (availability, HEDIS).

## 3) Tech Stack

- **Runtime**: Python 3.11+, FastAPI, Uvicorn (ASGI), asyncio.
- **Telephony**: Azure Communication Services (Call Automation, Media WS).
- **Speech**: Azure Speech (STT/TTS).
- **LLM**: Azure OpenAI (chat-completions, temp=0).
- **Calendar**: Google Calendar API (per-provider calendars).
- **DB/ORM**: Azure PostgreSQL, SQLAlchemy 2.x (async), Alembic.
- **Auth/Secrets**: Env vars; Azure Key Vault for PHI keys.
- **Messaging/Cache**: (Optional) Redis for per-clinic rate limits; DB locks are primary.
- **Deploy**: Azure Container Apps; ACR; GitHub Actions CI/CD.
- **Observability**: Structured logs to stdout + DB metrics; (Optional) Azure Monitor later.
- **Testing**: Pytest (unit/e2e), Locust/k6 (load), Schemathesis (API).

## 4) Core Functional Requirements (FR)

### Inbound Calling

- Detect language (EN/ES) automatically; short per-call memory only.
- Verify patient by name + DOB (spoken); compare against tokenized PHI.
- **Intents**:
  - **Book**: propose slots per provider; place hold; confirm; create GCal event; write booking.
  - **Reschedule**: cancel prior booking; rebook new slot.
  - **Cancel**: update DB and delete GCal event; sync back.
  - **FAQ**: exact-match templates; LLM fallback if no template.
  - **Transfer**: to clinic PSTN; mark session transferred.
- End call with summary; write call session, turns, event logs, metrics.

### Outbound: Reminders (modular)

- T−24h of appointment; up to 3 retries with backoff.
- If answered: remind date/time/provider; no DTMF flows.
- Record outcomes; feature flag gating.

### Outbound: HEDIS (modular)

- CSV ingest → campaign + targets; de-dup targets.
- Windowed dialing (08:00–19:00 local); 3 attempts; 24h cool-off.
- If patient agrees: normal booking path; mark target scheduled.
- Record outcomes; feature flag gating.

### Availability & Scheduling

- Availability CSV ingest per provider; normalize to slots.
- Offer = availability_slot.free minus GCal busy.
- **Anti-double-booking**: partial unique index on (provider_id, slot_start, slot_end) where status ∈ {tentative, confirmed}; row locks + advisory locks; tentative GCal event on hold; reaper expires holds.

### Licensing / Suspension

- Gateway blocks new calls if license != active.
- On suspend/expire: terminate active sessions; pause workers.
- Manual resume/reactivation; no automatic billing integration (MVP).

### Templates/FAQs

- Master + per-clinic override files in Blob.
- Manual reload endpoint to hot-swap templates.
- Exact-match first; LLM fallback (temp=0, short outputs).

## 5) Non-Functional Requirements (NFR)

### Performance/Scale

- First-token latency targets: template replies ≤400 ms; LLM ≤1.2 s.
- Concurrency caps per clinic enforced by license.
- Gateway route time ≤30 ms p50.
- Aggregation interval 60 s; DB write burst protection via buffering.

### Reliability

- Uptime ≥99.9% per clinic.
- Idempotent webhooks; replay-safe.
- Graceful termination on suspend; no orphan holds (reaper covers).

### Security/Compliance

- HIPAA BAA with Azure services.
- PHI tokenization: AES per clinic; zero plaintext PHI at rest; strictly minimal PHI in prompts/logs.
- AccessLog on every decrypt; AuditLog on sensitive ops.
- TLS everywhere; signed service-to-service auth (gateway → clinic).
- No call recordings (MVP).

### Data Retention

- metrics_event: 90 days; metrics_aggregate: ≥6 years.
- audit_log, access_log: 6 years.
- call_turn, call_event_log: 180 days.
- campaign_call_attempt: 2 years.

## 6) Data Model (summary)

- **Tenancy**: clinic_id on all tables.
- **Key tables**: clinic, license (features JSONB), did_route, provider, availability_slot, patient (tokenized PHI), booking (+ audit), campaign (+ target + attempt), call_session (+ turn + event_log), metrics_event, metrics_aggregate, audit_log, access_log.
- **Indexes/constraints**: partial unique on booking; GIN on event JSON; time-based indexes for queries.
- **Network grouping**: clinic.network_id for roll-ups.

## 7) API Surface (MVP)

### Global Gateway

- `POST /acs/webhook` → route by DID; block if suspended.
- `GET /ws/{callId}` → optional WS proxy to clinic container.
- **Admin (internal)**: `POST /admin/did/register|disable`.

### Clinic Container

- `GET /health`
- `POST /webhooks/acs` — inbound telephony events.
- `POST /outbound/reminders` — gated by feature.
- `POST /admin/upload/availability_csv` — Blob + enqueue ingest.
- `POST /admin/upload/hedis_csv` — gated; Blob + enqueue ingest.
- `POST /admin/reload-templates`
- `POST /admin/license/suspend|resume`
- `GET /version`

## 8) Workers

- **reminder_worker** — T−24h reminders; retries; outcomes.
- **availability_ingest** — CSV → availability_slot.
- **hedis_ingest** — HEDIS CSV → campaign + targets (tokenize PHI).
- **hedis_dialer** — dialing loop with windows/caps; outcomes.
- **holds_reaper** — expire tentatives; delete tentative GCal; free slots.
- **metrics_flusher** — buffer → metrics_event writes.
- **Central metrics_aggregator (shared)** — 1-min roll-ups and network aggregates.

## 9) Concurrency & Booking Safety

- **Application**: `SELECT … FOR UPDATE` on availability_slot.
- **Advisory lock** around (provider_id, slot_start, slot_end).
- **DB constraint**: partial unique on booking across provider_id + slot.
- **Tentative GCal events**; confirm_hold finalizes; release_hold or reaper cleans.

## 10) Configuration & Secrets

### Env (clinic)

- CLINIC_ID, DATABASE_URL, ACS_CONN, SPEECH_KEY/REGION, AOAI_ENDPOINT/DEPLOYMENT, GCAL_SA_JSON (or secret ref), PHI_KEY_ID, FAQ_BLOB_URI, voice/style/speed, calling windows, concurrency caps, token budgets.

### Env (gateway)

- DATABASE_URL, HMAC secret for webhook, routing cache TTL.

### Env (aggregator)

- DATABASE_URL, interval config.

### Secrets

- Prefer Key Vault for PHI keys; other secrets may be env (MVP).

## 11) Observability

- Structured JSON logs with clinic_id, session_id, provider_id tags.
- Per-turn token counters; per-call STT/TTS/LLM latency metrics.
- Metrics written as events; aggregator produces minute buckets.
- (Optional) Worker-heartbeat metric; backlog depth alerting later.

## 12) Failure Modes & Handling

- **License suspended**: gateway blocks new; clinic sends terminate to active; workers sleep.
- **GCal API errors**: degrade by not offering uncertain slots; retry with backoff.
- **DB contention**: advisory lock + unique constraint surface clear errors; flow retries/backs off.
- **Speech/LLM timeouts**: template fallback; short apology; offer transfer.
- **CSV ingest errors**: reject with row-level error report; do not partially corrupt state.

## 13) Security Controls Checklist

- TLS for all ingress; signed HMAC on webhooks; CSRF not applicable (API).
- Principle of least privilege for service accounts (GCal SA restricted per clinic).
- Encrypt PHI fields; never log decrypted values.
- AccessLog on decrypt; AuditLog on license, campaign, booking changes.
- No public admin endpoints; protect with bearer tokens/IP allowlist (MVP).

## 14) Test Plan (high level)

- **Unit**: scheduler locks/holds; booking uniqueness; PHI tokenization; intent routing; workers gating by license.
- **Integration**: inbound call end-to-end EN/ES; reschedule; cancel; transfer.
- **Calendar sync**: tentative→confirm flows; staff-made bookings sync as booked.
- **Outbound**: reminders and HEDIS loops respect windows/caps/features; retry policy.
- **Gateway**: DID routing, license block, WS proxy.
- **Load**: concurrent holds across same slot; p95 latency under N calls.
- **Security**: PHI decrypt logs present; no PHI in logs; suspension behavior.

## 15) Acceptance Criteria (MVP)

- End-to-end inbound booking with concurrency safety and GCal sync.
- Reminders and HEDIS configurable via license.features; disabled features do not execute.
- Suspension terminates active sessions and blocks new traffic system-wide.
- Metrics aggregator produces per-minute aggregates; network roll-ups available.
- PHI is encrypted at rest; AccessLog/AuditLog populated correctly.
- One-container-per-clinic deployment reproducible via CI/CD.

## 16) Delivery Phases (checkpointed)

1. DB + ORM + Alembic (models, constraints, indices).
2. Gateway (routing, license gate, optional WS proxy).
3. Clinic API (ACS webhook, media WS, templates, intent, call flow).
4. Scheduler (GCal, holds, reaper, anti-double-booking).
5. Outbound (reminders, HEDIS ingest/dialer, feature gating).
6. Metrics (events, aggregator, core KPIs).
7. Hardening (suspension/termination behavior, retries, error budgets).

---

This is the complete architecture and behavior checklist you can implement against and QA.

