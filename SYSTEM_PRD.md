# CallCenterAI – System Product Requirements Document (PRD v5)

## 1. Overview

CallCenterAI is a HIPAA-compliant, AI-powered voice system that manages inbound and outbound calls for medical clinics.
It uses Azure Communication Services (ACS) for telephony, Azure Speech for STT/TTS, Azure OpenAI for dialog understanding and response, and Azure PostgreSQL for persistence.
Each clinic runs in its own containerized instance, ensuring data isolation and individualized configuration, while sharing a central metrics and licensing infrastructure.

## 2. Core System Goals

| Goal | Description |
|------|-------------|
| Fully automated call handling | Book, cancel, reschedule, answer FAQs, or forward to staff. |
| Bilingual natural conversation | Detect and respond in English or Spanish. |
| Double-booking prevention | Strong transactional controls using DB locks + partial unique indexes. |
| PHI security | Tokenization, encryption, audit trails, and per-clinic encryption keys. |
| Modular features | Reminders and HEDIS outbound campaigns toggle per license tier. |
| Real-time streaming | Low-latency bidirectional audio via WebSocket between ACS and the AI orchestrator. |
| Scalable multi-tenant design | Global gateway + per-clinic containers with feature gating. |
| Operational observability | Centralized metrics: tokens, minutes, latency, conversions. |
| HIPAA BAA compliance | Azure BAA coverage, encrypted PHI, and limited data exposure. |

## 3. System Architecture

### High-Level Components

**Global Gateway**

- Single ACS event ingress (`/webhook/acs`)
- Routes events to correct clinic container via `clinic_id` (from DID or header)
- Optionally proxies WS audio between ACS and the target container.

**Clinic Container**

- Self-contained FastAPI app handling all inbound/outbound logic.
- Reads configuration (keys, limits, feature flags) from env vars at startup.
- Runs async workers for reminders, HEDIS, and cleanup tasks.

**Async Workers**

- `holds_reaper`: expires tentative holds.
- `reminders_worker`: T-24 h appointment reminders (if licensed).
- `hedis_dialer`: insurance outreach campaigns (if licensed).

**Database (Azure PostgreSQL)**

- Shared DB with tenant isolation via `clinic_id`.
- SQLAlchemy models with Alembic migrations.
- Partial unique index on `(provider_id, slot_start, slot_end)` for bookings.

**PHI Tokenization Layer**

- Reversible AES-GCM encryption; per-clinic keys from Key Vault (or env for MVP).
- Audit logs record every decrypt event.

**Speech & AI Orchestration**

- Azure Speech WS for STT/TTS.
- Azure OpenAI GPT model for dialog generation (short, deterministic mode).
- Dialog state tracked per call via `CallFlowState`.

**Google Calendar Integration**

- Tentative event on hold.
- Confirm → update to confirmed.
- Cancel → delete event.
- Sync cancellations from GCal → DB (bidirectional merge).

**Central Metrics Aggregator**

- Collects and aggregates metrics across all clinics.
- Computes token usage, call minutes, booking conversions, latency.

## 4. Functional Requirements

| Category | Description |
|----------|-------------|
| Inbound Calls | ACS webhook triggers new `call_session`. AI greets caller, detects intent, executes booking/cancel/reschedule/FAQ. Transfers to clinic PSTN if necessary. |
| Outbound Calls | Used for reminders and HEDIS outreach. Calls follow same dialog loop but initiated by async worker. |
| Real-Time Audio Streaming | WS endpoint streams audio frames between ACS and Speech; supports barge-in and partial transcripts. |
| Dialog Flow | Defined by `CallFlowState`: greeting → intent detection → booking info → confirm → wrap-up. |
| Booking Lifecycle | Hold slot → create tentative GCal → confirm → mark slot/booked → update metrics. |
| Double-Booking Protection | Achieved via advisory locks and partial unique constraint `(provider_id, slot_start, slot_end)` on slots with `status IN ('tentative','confirmed')`. |
| Reminders (Modular) | Periodic worker checks upcoming confirmed bookings and triggers ACS outbound reminder calls. |
| HEDIS (Modular) | CSV upload → enqueue outreach targets → call patients → mark completion or retry. |
| License Control | `license.features` JSONB toggles (`{"reminders":true,"hedis":false}`). When suspended, container halts inbound/outbound operations. |
| Metrics & Logging | Token counts, latency, minutes, and conversions stored in `metrics_event`; decrypts recorded in `audit_log`. |
| PHI Tokenization | All PHI fields replaced by opaque tokens; decrypted only by authorized admin actions. |
| Language Detection | Auto-detects English/Spanish; selects matching ASR/TTS model. |
| Graceful Suspension | If payment lapses, `license.status` → suspended; all active calls terminate, workers pause. |
| Manual Reactivation | Admin restarts container and renews license token manually. |

## 5. Non-Functional Requirements

| Area | Requirement |
|------|-------------|
| Performance | Handle 50+ concurrent calls per clinic container (tunable via license). |
| Scalability | Horizontal scaling via Azure Container Apps or AKS. |
| Reliability | All calls recoverable; holds released automatically on crash via `holds_reaper`. |
| Security | PHI encrypted, per-clinic keys, strict tenant separation. |
| Compliance | Fully HIPAA-aligned: encryption in transit (TLS 1.2+), at rest (Postgres TDE), audit logs. |
| Observability | Structured JSON logs; per-call correlation IDs; metrics rollups every N minutes. |
| Cost Control | Token budgets per clinic configurable; cached template answers reduce LLM usage. |
| Localization | Multi-language voice configuration (voice ID, rate, style). |
| Maintainability | Async I/O, modular workers, single source for DB models and config. |

## 6. Data Model Summary

Core tables (see database PRD v1.2 for full schema):

| Table | Purpose |
|-------|---------|
| `clinic` | Tenant identity, timezone, network_id, default language, feature flags. |
| `clinic_license` | Status, tier, concurrency caps, feature flags. |
| `mapping` | PHI token ↔ ciphertext map. |
| `patient` | Tokenized patient record. |
| `provider` | Provider details, calendar id. |
| `availability_slot` | Provider slots; holds and confirmations. |
| `booking` | Appointments; linked to patient + GCal event. |
| `call_session` | Live call lifecycle + current_flow_state. |
| `metrics_event` | Tokens, latency, minutes per turn/call. |
| `audit_log` | All decrypt and PHI access events. |

## 7. Licensing & Feature Gating

Each clinic has one active license row:

```json
{
  "tier": "pro",
  "max_concurrent_calls": 50,
  "features": {
    "reminders": true,
    "hedis": false
  }
}
```

Feature checks occur before job scheduling or call handling.

Suspension immediately disables:

- Inbound call handling (`/webhook/acs`)
- Outbound job workers (`reminders_worker`, `hedis_dialer`)

Reactivation requires manual license token renewal and container restart.

## 8. Deployment & Operations

| Component | Platform | Notes |
|-----------|----------|-------|
| Containers | Azure Container Apps | One per clinic; deployed via CI/CD. |
| Database | Azure Database for PostgreSQL | Shared; encrypted at rest. |
| Secrets | Env vars per container (Key Vault later) | Simpler for MVP; move to Key Vault for production. |
| Monitoring | Central metrics schema; optional Azure Monitor later. | |
| Backups | Daily Postgres snapshot; 7–30 days retention. | |
| Disaster Recovery | Restore from snapshot; redeploy container manually. | |
| Licensing Ops | Manual suspension/reactivation for now; Stripe webhooks planned later. | |

## 9. Technical Stack

| Layer | Technology |
|-------|------------|
| Language/Framework | Python 3.11 +, FastAPI (Async) |
| Telephony | Azure Communication Services (Call Automation + Media Streaming WS) |
| Speech | Azure Speech Service (STT/TTS Real-Time WS) |
| LLM Integration | Azure OpenAI (GPT-4o Mini for low latency responses) |
| Database | Azure PostgreSQL (Async SQLAlchemy + Alembic) |
| Caching | Optional Redis for FAQ + session state (later) |
| Scheduling | Google Calendar API (Service Account OAuth) |
| Deployment | Azure Container Apps / Docker Compose (local dev) |
| Monitoring | Structured logs → Central Metrics Aggregator |

## 10. Call Lifecycle Summary

1. **Inbound call received**
   - ACS webhook → Gateway → Clinic Container.
   - Creates `call_session` (row).

2. **WebSocket negotiation**
   - ACS event → generate WS URL → start bi-directional audio.

3. **Speech & Intent**
   - STT stream → LLM intent → state machine advances via `CallFlowState`.

4. **Booking flow**
   - `place_hold()` → tentative GCal event → confirm → commit booking.

5. **Metrics**
   - Log tokens + latency per turn and per call.

6. **Termination**
   - End call → close WS → persist metrics → update license usage.

## 11. Security & Compliance

| Control | Description |
|---------|-------------|
| PHI tokenization | Reversible AES-GCM per clinic key. |
| Audit logging | Every decrypt or admin action logged with timestamp + user. |
| TLS | All traffic ACS↔App↔Speech encrypted. |
| Data Retention | Audit logs ≥ 6 yrs (default HIPAA guidance). |
| Access control | Only admin account (me) can decrypt PHI for now. |
| Suspension mechanism | License off → container halts telephony. |

## 12. Future Enhancements

- Admin Dashboard (UI) for metrics, licenses, logs.
- Stripe webhook automation for payment suspension/reactivation.
- Redis session cache for real-time state sharing.
- Full Key Vault integration for per-clinic keys.
- Automated clinic provisioning via Terraform/Bicep.
- Cross-clinic analytics dashboards.
- Multi-voice and emotion style support via Speech SDK.
- Staff portal for manual overrides and call review.

## 13. Acceptance Criteria for MVP

- ✅ Real-time WS audio stream ACS ↔ AI works (bilingual STT/TTS).
- ✅ Intent routing to booking/cancel/reschedule verified.
- ✅ Booking engine prevents double booking.
- ✅ Tentative → Confirmed Google Calendar sync works.
- ✅ License toggle stops and resumes calls.
- ✅ Tokenization and audit logging fully functional.
- ✅ Metrics table captures tokens and latency per call.
- ✅ HEDIS + Reminders flagged off by default until licensed.

