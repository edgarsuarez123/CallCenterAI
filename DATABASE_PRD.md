# CallCenterAI – Database PRD

## 1. Scope & Design Principles

### Multi-tenant, per-clinic isolation

Single Postgres server (or cluster).

All tenant-scoped tables include `clinic_id` and are logically isolated by that field.

Each clinic runs in its own container but shares the same DB instance/schema.

### PHI tokenization

No raw PHI in core business tables.

Sensitive strings (name, phone, DOB, address, etc.) are stored as `*_token` fields that reference the Mapping table, which holds encrypted values.

Decrypt operations are logged in AuditLog.

### Per-clinic licensing and feature flags

Clinic describes the clinic itself and high-level settings.

ClinicLicense enforces operational status and usage caps.

Feature flags (reminders, HEDIS campaigns) are controlled via license/clinic fields.

### Scheduling correctness

AvailabilitySlot + DB constraints enforce no double booking per provider/time.

Booking is the canonical appointment record, mirrored to Google Calendar.

### Call/session-centric design

CallSession tracks the lifecycle/state of each call (inbound & outbound).

Metrics and usage are tracked via MetricsEvent.

### Optional modules

Reminders and HEDIS campaigns are modular and gated by license/feature flags:

- Reminders: Reminder, ReminderLog
- HEDIS/outreach: Campaign, CampaignTarget

## 2. Entity Overview

### Core entities:

- Clinic
- ClinicLicense
- Mapping
- Patient
- Provider
- ProviderCalendarCredentials
- AvailabilitySlot
- Booking
- CallSession
- MetricsEvent
- AuditLog

### Reminder

- Reminder
- ReminderLog

### HEDIS/outreach

- Campaign
- CampaignTarget

## 3. Entity Definitions

### 3.1 Clinic

**Purpose**: Represents one clinic (one tenant / one container).

**Key fields:**

- `clinic_id` (PK)
- `network_id` - Groups multiple clinics under the same owner/network.
- `clinic_name`
- `timezone`
- `default_language` (en, es, …)
- `supported_languages` (e.g. en,es)
- `subscription_tier` (basic, professional, enterprise)

**Feature flags:**

- `reminders_enabled` (bool)
- `hedis_enabled` (bool)

**Capacity / routing:**

- `max_concurrent_calls`
- `overload_action` (queue, forward, busy)
- `staff_forward_number` (PSTN for live transfer / overload)

**Timestamps:**

- `created_at`, `updated_at`, `last_call_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`

**Important indexes:**

- `idx_clinic_network` on `(network_id)`
- `idx_clinic_phone` if you store clinic phone here.

### 3.2 ClinicLicense

**Purpose**: Enforces whether a clinic is allowed to operate and what limits apply.

**Key fields:**

- `license_id` (PK)
- `clinic_id` (unique FK → Clinic)
- `license_status` (active, grace_period, suspended, cancelled)
- `tier` (basic, professional, enterprise)

**Limits:**

- `max_concurrent_calls`
- `max_calls_per_month` (nullable for "unlimited")

**Feature JSON:**

- `features` (JSONB: `{ "reminders": true, "hedis": false, ... }`)

**Billing cycle:**

- `billing_cycle_start`, `billing_cycle_end`, `next_billing_date`

**Usage counters (for fast checks):**

- `current_month_calls`, `current_month_minutes`, `current_concurrent_calls`

**Grace period:**

- `grace_period_days`, `grace_period_start`, `grace_period_end`

**Suspension:**

- `suspended_at`, `suspension_reason`

**Timestamps:**

- `created_at`, `updated_at`

**Important indexes:**

- `idx_clinic_license_status` on `(license_status, tier)`
- `idx_clinic_license_billing` on `(clinic_id, billing_cycle_start)`

### 3.3 Mapping (Token Vault)

**Purpose**: Stores encrypted PHI for any token referenced in other tables.

**Key fields:**

- `token` (PK) - e.g. NAME_xxx, PHONE_xxx, DOB_xxx
- `clinic_id`
- `value_nonce`, `value_ciphertext` (encrypted PHI)
- `value_type` (name, phone, dob, address, email, insurance, etc.)
- `call_id` (optional FK to CallSession.call_id where it was created)

**Timestamps:**

- `created_at`, `last_used_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`, `deletion_reason`

**Important indexes:**

- `idx_mapping_clinic` on `(clinic_id)`
- `idx_mapping_type` on `(value_type)`

### 3.4 Patient

**Purpose**: Logical patient entity, with all PHI fields tokenized.

**Key fields:**

- `patient_id` (PK)
- `clinic_id`

**Tokenized PHI:**

- `name_token`
- `phone_token`
- `dob_token`
- `email_token`
- `address_token`

**Optional insurance tokens:**

- `insurance_provider_token`
- `insurance_member_id_token`

**Timestamps:**

- `created_at`, `updated_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`, `deletion_reason`

**Important indexes:**

- `idx_patient_clinic` on `(clinic_id)`
- `idx_patient_phone_token` on `(phone_token)`

### 3.5 Provider

**Purpose**: Providers (doctors, NPs, etc.) that can be scheduled.

**Key fields:**

- `provider_id` (PK)
- `clinic_id`
- `name_token` (or plain name if you decide PHI doesn't apply)
- `title` (e.g. Dr., PA)
- `specialty`
- `calendar_identity` - Email/resource ID used to map to Google Calendar.
- `is_active`

**Timestamps:**

- `created_at`, `updated_at`

**Important indexes:**

- `idx_provider_clinic` on `(clinic_id)`
- `idx_provider_calendar_identity` on `(calendar_identity)`

### 3.6 ProviderCalendarCredentials

**Purpose**: Encrypted Google OAuth credentials for provider calendars.

**Key fields:**

- `credential_id` (PK)
- `provider_id` (unique FK → Provider)
- `access_token_nonce`, `access_token_ciphertext`
- `refresh_token_nonce`, `refresh_token_ciphertext` (nullable)
- `token_expires_at`
- `scope` (OAuth scopes)
- `is_active`
- `last_used_at`
- `created_at`, `updated_at`

**Important indexes:**

- `idx_provider_credentials` on `(provider_id)`
- `idx_credentials_active` on `(is_active, last_used_at)`

### 3.7 AvailabilitySlot

**Purpose**: Atomic time slots per provider; enforces no double booking.

**Key fields:**

- `slot_id` (PK)
- `clinic_id`
- `provider_id`
- `slot_start` (tz-aware timestamptz)
- `slot_end` or `duration_minutes`
- `status`: available | held | confirmed
- `held_until` (for temporary holds)
- `held_by_call_id` (FK to CallSession.call_id, optional)
- `booking_id` (nullable FK to Booking.booking_id when confirmed)
- `created_at`, `updated_at`

**Constraints:**

- `UNIQUE (provider_id, slot_start)` → prevents two confirmed bookings at the same moment.

**Important indexes:**

- `idx_slots_provider_time` on `(provider_id, slot_start)`
- `idx_slots_clinic_time` on `(clinic_id, slot_start, status)`

### 3.8 Booking

**Purpose**: Canonical appointment record (mirrored to Google Calendar).

**Key fields:**

- `booking_id` (PK)
- `clinic_id`
- `patient_id` (FK → Patient)
- `provider_id` (FK → Provider)
- `slot_start`, `slot_end`
- `status`: tentative | confirmed | cancelled
- `hold_token` (used to safely tie confirm step to earlier hold)
- `google_event_id`
- `needs_calendar_sync` (bool)

**Tokenized content:**

- `reason_token`
- `notes_token`

- `call_id` (FK → CallSession.call_id, the call that created it, nullable)
- `created_at`, `updated_at`

**Important indexes:**

- `idx_booking_clinic_time` on `(clinic_id, slot_start)`
- `idx_booking_patient` on `(patient_id, status)`

### 3.9 CallSession

**Purpose**: Tracks each phone call's lifecycle and state.

**Key fields:**

- `call_id` (PK – internal ID)
- `clinic_id`

**ACS identifiers:**

- `acs_server_call_id`
- `acs_connection_id`

**WebSocket:**

- `ws_session_id`

**Status:**

- `status`: initiated | active | completed | failed | abandoned
- `current_flow_state`: enum (greeting, intent_detection, booking_collect_info, booking_confirm, faq, handoff_to_staff, etc.)
- `language` (en, es, unknown)
- `started_at`, `ended_at`

**Important indexes:**

- `idx_call_clinic_started` on `(clinic_id, started_at)`
- `idx_call_acs_id` on `(acs_server_call_id)`

### 3.10 MetricsEvent

**Purpose**: Tracks per-call (and optionally per-turn) usage metrics for cost and performance.

**Key fields:**

- `metrics_id` (PK)
- `clinic_id`
- `call_id` (FK → CallSession)
- `turn_index` (nullable; 0 for aggregate, 1..N for per-turn)

**Tokens:**

- `prompt_tokens`
- `completion_tokens`

**Latency:**

- `stt_ms` (speech-to-text)
- `tts_ms` (text-to-speech)
- `llm_ms`
- `total_ms`

**Telephony/sample usage:**

- `call_minutes_increment` (for this event or final total)
- `created_at`

**Important indexes:**

- `idx_metrics_call` on `(call_id, turn_index)`
- `idx_metrics_clinic_time` on `(clinic_id, created_at)`

### 3.11 AuditLog

**Purpose**: Global audit trail for PHI and sensitive actions (HIPAA).

**Key fields:**

- `log_id` (PK)
- `clinic_id`
- `user_id` (system, admin id, etc.)
- `action_type` (tokenize, decrypt, read, update, access_phi, etc.)
- `table_name`
- `record_id`

**Request context:**

- `ip_address`
- `user_agent`
- `request_id`
- `details` (short description, no PHI)
- `success` (bool or small enum)
- `created_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`, `deletion_reason`

**Important indexes:**

- `idx_audit_table_date` on `(table_name, created_at)`
- `idx_audit_user_date` on `(user_id, created_at)`

### 3.12 Reminder

**Purpose**: Tracks scheduled reminder calls for bookings.

**Key fields:**

- `reminder_id` (PK)
- `clinic_id`
- `booking_id` (FK → Booking)
- `scheduled_time`
- `reminder_type` (appointment_reminder, follow_up, etc.)
- `status`: scheduled | calling | completed | failed | cancelled | no_answer

**Retry logic:**

- `retry_count`
- `max_retries`
- `next_retry_time`

**Call linkage:**

- `reminder_call_id` (FK → CallSession.call_id, nullable)
- `call_duration_seconds`
- `call_outcome` (answered, no_answer, busy, voicemail, failed, etc.)
- `created_at`, `updated_at`, `completed_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`, `deletion_reason`

**Important indexes:**

- `idx_reminder_schedule` on `(status, scheduled_time)`
- `idx_reminder_booking` on `(booking_id)`

### 3.13 ReminderLog

**Purpose**: Per-attempt log of reminder calls, for debugging and traceability.

**Key fields:**

- `log_id` (PK)
- `reminder_id` (FK → Reminder)
- `attempt_number`
- `call_started_at`, `call_ended_at`
- `call_status` (initiated, ringing, answered, no_answer, busy, failed, completed)
- `call_duration_seconds`
- `call_outcome`

**Error fields:**

- `error_code`
- `error_message`
- `caller_id` (clinic PSTN used)
- `created_at`

**Soft delete:**

- `is_deleted`, `deleted_at`, `deleted_by`, `deletion_reason`

**Important indexes:**

- `idx_reminder_logs_reminder` on `(reminder_id, attempt_number)`
- `idx_reminder_logs_status` on `(call_status, call_started_at)`

### 3.14 Campaign

**Purpose**: Groups outreach/HEDIS batches logically.

**Key fields:**

- `campaign_id` (PK)
- `clinic_id`
- `name` (e.g. "HEDIS Q4 2025 – Diabetes A1c")
- `type` (hedis, recall, etc.)
- `status`: draft | running | paused | completed

**Counts:**

- `total_targets`
- `completed_calls`
- `appointments_made`
- `created_at`, `started_at`, `ended_at`

**Important indexes:**

- `idx_campaign_clinic_status` on `(clinic_id, status)`

### 3.15 CampaignTarget

**Purpose**: Individual patients to be called in a campaign (HEDIS/outreach).

**Key fields:**

- `target_id` (PK)
- `campaign_id` (FK → Campaign)
- `clinic_id`

**Link to known patient:**

- `patient_id` (nullable; can be set on first successful call)

**Tokenized data from CSV (for cases where patient isn't yet in Patient):**

- `name_token`
- `phone_token`
- `dob_token`

**Outreach specifics:**

- `required_service` (e.g. "A1c", "colonoscopy")

**Status:**

- `status`: pending | calling | completed | failed | max_retries_reached
- `attempt_count`
- `last_attempt_at`

**Result:**

- `booking_id` (FK → Booking, if appointment created)
- `created_at`, `updated_at`

**Important indexes:**

- `idx_campaign_target_campaign` on `(campaign_id, status)`
- `idx_campaign_target_patient` on `(patient_id)`
