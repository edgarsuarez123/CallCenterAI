# Database Entity Relationship Diagram

All 12 models. Phase 2 models (booking engine) are marked as such.

```mermaid
erDiagram
    Clinic {
        UUID id PK
        UUID network_id
        string name
        string tier
        string status
        string license_token
        string business_hours_start
        string business_hours_end
        datetime created_at
    }

    License {
        UUID clinic_id PK_FK
        string token
        string tier
        string status
        int max_concurrency
        json features
    }

    ClinicIntegration {
        UUID id PK
        UUID clinic_id FK
        string retell_agent_id
        string retell_did
        text google_service_account_json
    }

    Campaign {
        UUID id PK
        UUID clinic_id FK
        string name
        text reason
        string status
        int total_contacts
        int completed_contacts
        datetime created_at
        datetime updated_at
    }

    CampaignContact {
        UUID id PK
        UUID campaign_id FK
        UUID clinic_id
        bytes patient_name_encrypted
        bytes phone_encrypted
        string phone_hash
        text reason
        string outcome
        string retell_call_id
        int call_duration_seconds
        datetime call_date
        int attempt_count
        text notes
        datetime created_at
    }

    CallLog {
        UUID id PK
        UUID clinic_id
        string call_type
        string retell_call_id
        string outcome
        int duration_seconds
        datetime created_at
    }

    %% Phase 2 — Booking Engine (implemented, not activated)
    Provider {
        UUID id PK
        UUID clinic_id FK
        string display_name
        string google_calendar_id
        string timezone
        int booking_duration_mins
        int capacity
        bool active
    }

    Patient {
        UUID id PK
        UUID clinic_id FK
        bytes name_token
        bytes dob_token
        bytes phone_token
        bytes email_token
        string name_dob_hash
        string language
    }

    Booking {
        UUID id PK
        UUID clinic_id FK
        UUID provider_id FK
        UUID patient_id FK
        datetime slot_start
        datetime slot_end
        string status
        UUID hold_token
        datetime hold_expires_at
        string google_event_id
    }

    BookingAudit {
        UUID id PK
        UUID clinic_id FK
        UUID booking_id FK
        string action
        string actor
        datetime timestamp
    }

    Clinic ||--o{ Campaign : "has"
    Clinic ||--o| License : "has"
    Clinic ||--o| ClinicIntegration : "has"
    Campaign ||--o{ CampaignContact : "contains"

    Clinic ||--o{ Provider : "Phase 2"
    Clinic ||--o{ Patient : "Phase 2"
    Provider ||--o{ Booking : "Phase 2"
    Patient ||--o{ Booking : "Phase 2"
    Booking ||--o{ BookingAudit : "Phase 2"
```
