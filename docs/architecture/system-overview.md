# System Architecture Overview

CallCenterAI is a multi-tenant SaaS platform that automates HEDIS care-gap outreach.

```mermaid
graph TB
    subgraph Clinic["Clinic Staff"]
        Admin[Admin Dashboard\nReact SPA]
        CSV[Patient CSV\nUpload]
    end

    subgraph API["FastAPI Backend\n(Azure / Docker)"]
        GW[API Gateway\nCORS + Auth]
        CR[Campaign Routes\n/admin/campaigns]
        AR[Admin Routes\n/admin/clinics]
        RR[Retell Webhooks\n/retell/webhook]
        Worker[Campaign Worker\nBackgroundTask]
    end

    subgraph Data["Data Layer"]
        PG[(PostgreSQL\nAzure Flexible)]
        ENC[AES-256-GCM\nPHI Encryption]
    end

    subgraph Voice["Voice AI Layer"]
        Retell[Retell AI\nVoice Agent]
        Patient[Patient Phone]
    end

    Admin -->|X-API-Key| GW
    CSV -->|multipart/form-data| GW
    GW --> CR
    GW --> AR
    CR --> Worker
    Worker -->|trigger call| Retell
    Retell <-->|conversation| Patient
    Retell -->|HMAC-signed webhook| RR
    RR -->|record outcome| PG
    CR --> ENC
    ENC --> PG
    AR --> PG
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| One Retell agent per clinic | Avoids per-patient-per-gap-type agent sprawl; gap context passed as call metadata |
| AES-256-GCM for all PHI at rest | HIPAA §164.312(a)(2)(iv) — encryption of ePHI in storage |
| SHA-256 phone hash for dedup | Dedup check without decryption — O(1) lookup, no PHI exposure |
| `clinic_id` on every table | Row-level tenant isolation — no ORM-level multi-tenancy magic |
| Async FastAPI + asyncpg | Single-process handles 100+ concurrent webhook callbacks |
| Demo mode (no paid API) | Simulates call outcomes locally for dev/demo without Retell costs |
