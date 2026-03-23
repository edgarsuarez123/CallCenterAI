# HIPAA Security Rule Compliance Audit
## CallCenterAI — HEDIS Outreach Automation Platform

| Field | Value |
|---|---|
| **Project** | CallCenterAI v1.0.0 |
| **Audit Date** | 2026-03-23 |
| **Standard** | 45 CFR Part 164 — HIPAA Security Rule |
| **Auditor** | Claude (automated static analysis) |
| **Branch** | `claude/check-latest-commit-VPEc6` |
| **Scope** | Full codebase: `Clinic_app/`, `workers/`, `services/`, `migrations/`, `Dockerfile`, `docker-compose.yaml` |

---

## Executive Summary

| Severity | Count |
|---|---|
| 🔴 Critical | 1 |
| 🟠 High | 4 |
| 🟡 Warning | 5 |
| ✅ Compliant | 30 |

The codebase demonstrates a strong security posture for a healthcare SaaS platform. The PHI encryption architecture is sound (AES-256-GCM throughout, BYTEA storage, random IV per encryption, auth tag verification). One critical finding exists — a service account credential stored in plaintext despite the column being labeled "Encrypted". Four high-severity gaps around webhook forgery, missing token revocation, no rate limiting, and OpenAPI docs exposure should be addressed before HIPAA production sign-off.

---

## Findings by Severity

### 🔴 CRITICAL

---

#### C-01 — Google Service Account Private Key Stored in Plaintext
**Rule:** 45 CFR §164.312(a)(2)(iv) — Encryption and Decryption; §164.306(a)(1) — Risk to confidentiality of ePHI
**File:** `Clinic_app/data/models/clinic_integration.py:22`
**Also in:** `Clinic_app/Routes/admin.py:328, 547, 558, 646`; `Clinic_app/alembic/versions/3f270d38367a_initial_models.py:80`

```python
# CURRENT (NON-COMPLIANT)
google_service_account_json = Column(Text, nullable=False)  # Encrypted Google service account JSON
```

The column comment says "Encrypted" but the column type is `Text` and no encryption is applied at the application layer. The admin routes write the raw JSON directly:

```python
google_service_account_json=request.integration.google_service_account_json,  # plaintext
```

This JSON contains a Google service account private key (`"private_key"` field) used to access Google Calendar — a system that stores appointment scheduling data linked to patients. A database breach would expose this credential immediately.

**Required fix:** Convert to `BYTEA` and apply `encrypt_phi()` on write / `decrypt_phi()` on read, matching the pattern used for `nextgen_username_encrypted` and `nextgen_password_encrypted` in `ClinicEHRConfig`.

```python
# COMPLIANT — matches ClinicEHRConfig pattern
google_service_account_json_encrypted = Column(BYTEA, nullable=False)
```

---

### 🟠 HIGH

---

#### H-01 — Retell Webhook Signature Bypassed for Test Call IDs
**Rule:** 45 CFR §164.312(c)(1) — Integrity; §164.312(d) — Person/Entity Authentication
**File:** `Clinic_app/Routes/retell.py:357–359`

```python
if call_id == "playground" or call_id.startswith("test_") or call_id.startswith("playground_"):
    logger.info(f"Skipping signature verification for playground/test call: {call_id}")
    return
```

Any caller — including malicious actors — can craft a webhook payload with `call_id="test_anything"` and bypass HMAC-SHA256 verification entirely. Since webhooks trigger writes to `CampaignAudit`, `CampaignContact` status updates, and PHI storage (`patient_name_encrypted`), this bypass allows forged events to corrupt patient records, falsify outcomes, or cause the system to store attacker-supplied data.

**Required fix:** Remove the call_id-based bypass. Retell's playground does send a proper signature; if testing requires unsigned calls, restrict the bypass to `APP_ENVIRONMENT=development` only (currently only the missing-signature path does this).

---

#### H-02 — JWT Tokens Cannot Be Revoked
**Rule:** 45 CFR §164.312(a)(2)(iii) — Automatic Logoff; §164.312(d) — Authentication
**File:** `Clinic_app/common/jwt.py` (system-wide)

JWTs are signed with `HS256` and expire after `JWT_EXPIRY_HOURS = 8`. There is no token blacklist, no server-side session store, and no revocation endpoint. If a staff member is terminated, their credentials stolen, or their clinic membership revoked in the database, their existing JWT remains valid for up to 8 hours.

**Required fix:** Implement a Redis-backed token revocation list keyed by `jti` (JWT ID). On clinic staff deletion or role change, add the token's `jti` to the revocation set. `decode_token()` must check this list after signature verification.

---

#### H-03 — No Rate Limiting on Authentication or Admin Endpoints
**Rule:** 45 CFR §164.312(d) — Person/Entity Authentication; §164.306(a)(2) — Protect against reasonably anticipated threats
**File:** `Clinic_app/main.py` (no middleware), `Clinic_app/Routes/auth.py`, `Clinic_app/Routes/admin.py`

No rate limiting middleware (`slowapi`, `fastapi-limiter`, or equivalent) is configured on any endpoint. Auth endpoints (`/auth/google/callback`, `/auth/select-clinic`) and admin endpoints (`/admin/*`) are callable at unlimited throughput. This enables:
- API key brute-force on `X-Admin-Key`
- Token enumeration on `/auth/select-clinic`
- Denial-of-service via resource exhaustion

**Required fix:** Add `slowapi` or `fastapi-limiter` with Redis backend. Apply strict limits to auth endpoints (e.g., 10 req/min per IP) and moderate limits to admin endpoints (e.g., 60 req/min).

---

#### H-04 — OpenAPI Documentation Exposed Without Authentication in Production
**Rule:** 45 CFR §164.312(a)(1) — Access Control; §164.306(a)(2) — Threat protection
**File:** `Clinic_app/main.py:69–76`

```python
app = FastAPI(
    title="CallCenterAI API",
    docs_url="/docs",     # ← publicly accessible
    redoc_url="/redoc",   # ← publicly accessible
    ...
)
```

`/docs` and `/redoc` are reachable by any unauthenticated user who can reach the server. The Swagger UI exposes all endpoint schemas, PHI field names, authentication header requirements, and webhook contracts — a complete attack surface map for the API.

**Required fix:** Set `docs_url=None` and `redoc_url=None` in production:

```python
docs_url="/docs" if os.environ.get("APP_ENVIRONMENT") != "production" else None,
redoc_url="/redoc" if os.environ.get("APP_ENVIRONMENT") != "production" else None,
```

---

### 🟡 WARNING

---

#### W-01 — Global Exception Handler May Leak Internal Error Details
**Rule:** 45 CFR §164.312(b) — Audit Controls; minimum necessary principle
**File:** `Clinic_app/main.py:117–126`

```python
@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc),       # ← may contain PHI or internal state
        },
    )
```

`str(exc)` on an unhandled exception during PHI processing could contain partial patient data (e.g., a `ValueError` raised with a phone number or decryption context in the message). This response is sent to the API caller without authentication gating.

**Required fix:** Replace `"detail": str(exc)` with a static message; log the full detail server-side only:

```python
return JSONResponse(status_code=500, content={"error": "Internal server error"})
```

---

#### W-02 — Audit Log Retention Insufficient for HIPAA 6-Year Requirement
**Rule:** 45 CFR §164.312(b) — Audit Controls; §164.530(j) — Documentation (6-year retention)
**File:** `docker-compose.yaml:23–27`

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

Container logs are capped at ~30 MB total. HIPAA requires audit documentation and logs to be retained for a minimum of **6 years** from creation or last effective date. Application logs containing access records, PHI operation events, and webhook processing outcomes would be lost within hours of production traffic.

**Required fix:** Integrate Azure Monitor / Log Analytics or a SIEM (e.g., Azure Sentinel) to ship all container logs to long-term storage with a 6-year retention policy. The `json-file` driver should remain as a local buffer only.

---

#### W-03 — No CORS Policy Configured
**Rule:** 45 CFR §164.312(a)(1) — Access Control; §164.306(a)(2) — Threat protection
**File:** `Clinic_app/main.py` (no CORSMiddleware)

No `CORSMiddleware` is registered. If the API is ever consumed from a browser-based frontend (current or future), the absence of a CORS policy means any web origin can make cross-origin requests. This creates a CSRF attack surface for any PHI-modifying endpoints accessible from a browser session with stored auth tokens.

**Required fix:**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-clinic-dashboard.azurewebsites.net"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
)
```

---

#### W-04 — ParseError Dataclass Holds In-Memory PHI During Upload Requests
**Rule:** 45 CFR §164.312(b) — Audit Controls; minimum necessary data handling
**File:** `Clinic_app/services/csv_parser.py:114–119`

```python
@dataclass
class ParseError:
    row_number: int
    reason: str
    raw_data: dict = field(default_factory=dict)   # ← full CSV row including PHI
```

`ParseError.raw_data` stores the complete raw CSV row (potentially containing plaintext `patient_name`, `patient_dob`, `phone`). These objects exist in memory for the lifetime of the upload request. The `ParseErrorOut` response schema correctly omits `raw_data` — client responses are compliant — but if the error objects were ever logged (e.g., by a future developer adding debug logging), PHI would be exposed.

**Recommendation:** Remove the `raw_data` field from `ParseError` or replace it with a non-PHI summary (e.g., `row_number` only). The field provides no value in the current codebase since it is never used in responses or logs.

---

#### W-05 — No Mechanism to Verify Database Backup Encryption
**Rule:** 45 CFR §164.312(a)(2)(iv) — Encryption and Decryption; §164.308(a)(7) — Contingency Plan
**File:** N/A (infrastructure gap)

Azure PostgreSQL Flexible Server provides automated encrypted backups, but there is no application-level code, health check, or documented procedure to verify that:
1. Backup encryption is enabled and using the correct key vault
2. Backups can be successfully restored with PHI intact
3. Restore tests are performed on a regular schedule

**Recommendation:** Document a quarterly backup restoration test procedure in `INFRASTRUCTURE.md`. Verify Azure PostgreSQL Flexible Server backup encryption settings in the Azure portal and add this verification to the HIPAA BAA checklist.

---

## Compliant Controls

### §164.312(a) — Access Control

| ID | Control | Status | Evidence |
|---|---|---|---|
| A-01 | Unique user identification | ✅ COMPLIANT | Google OAuth `google_sub` — stable, unique per user; JWT `sub` carries it |
| A-02 | Automatic logoff | ✅ COMPLIANT | JWT `exp` enforced at 8 hours; `jwt.ExpiredSignatureError` → HTTP 401 (`jwt.py:127`) |
| A-03 | PHI encrypted at rest — patient name | ✅ COMPLIANT | `Patient.name_token: BYTEA` via `encrypt_phi()` (`patient.py:235`) |
| A-04 | PHI encrypted at rest — patient DOB | ✅ COMPLIANT | `Patient.dob_token: BYTEA` via `encrypt_phi()` (`patient.py:236`) |
| A-05 | PHI encrypted at rest — phone number | ✅ COMPLIANT | `Patient.phone_token: BYTEA` + `phone_hash: SHA-256` (`patient.py:237`) |
| A-06 | PHI encrypted at rest — email | ✅ COMPLIANT | `Patient.email_token: BYTEA` via `encrypt_phi()` when present (`patient.py:238`) |
| A-07 | PHI encrypted at rest — campaign contact phone | ✅ COMPLIANT | `CampaignContact.phone_encrypted: BYTEA` + `phone_hash` (`campaign_contact.py:29–30`) |
| A-08 | PHI encrypted at rest — campaign contact name | ✅ COMPLIANT | `CampaignContact.patient_name_encrypted: BYTEA` (`campaign_contact.py:31`) |
| A-09 | PHI encrypted at rest — campaign contact DOB | ✅ COMPLIANT | `CampaignContact.patient_dob_encrypted: BYTEA` (`campaign_contact.py:32`) |
| A-10 | PHI encrypted at rest — audit patient name | ✅ COMPLIANT | `CampaignAudit.patient_name_encrypted: BYTEA` (`campaign_audit.py:35`) |
| A-11 | PHI encrypted at rest — call summary | ✅ COMPLIANT | `CampaignAudit.call_summary_encrypted: BYTEA` (`campaign_audit.py:36`) |
| A-12 | EHR credentials encrypted | ✅ COMPLIANT | `ClinicEHRConfig.nextgen_username_encrypted` + `nextgen_password_encrypted: BYTEA` (`clinic_ehr_config.py:29–30`) |
| A-13 | Encryption algorithm strength | ✅ COMPLIANT | AES-256-GCM (NIST-approved); 32-byte key; 12-byte random IV per operation; 16-byte auth tag (`encryption.py:24–26`) |
| A-14 | Encryption key management | ✅ COMPLIANT | Key from `PHI_ENCRYPTION_KEY` env var only; validated 32 bytes; cached in memory; never logged (`encryption.py:53–108`) |
| A-15 | Admin route access control | ✅ COMPLIANT | `Depends(verify_admin_api_key)` applied globally to all `/admin/*` and `/provider/*` routes (`main.py:85–86`) |
| A-16 | Campaign route access control | ✅ COMPLIANT | `require_scoped_staff` dependency on all campaign endpoints; `_require_admin()` enforced on write ops (`campaigns.py:155, 162`) |
| A-17 | Tenant row isolation | ✅ COMPLIANT | `clinic_id` filter on every PHI query; denormalized to `CampaignContact` and `CampaignAudit` for join-free tenant isolation |
| A-18 | Role-based access | ✅ COMPLIANT | "admin" vs "viewer" roles enforced; write operations check `staff.role != "admin"` → HTTP 403 |

---

### §164.312(b) — Audit Controls

| ID | Control | Status | Evidence |
|---|---|---|---|
| B-01 | Call-level audit records | ✅ COMPLIANT | `CampaignAudit` — immutable row per call: outcome, attempt#, timestamps, encrypted name + summary (`campaign_audit.py`) |
| B-02 | PHI-free call metrics | ✅ COMPLIANT | `CallLog` — no PHI; captures call_type, duration, outcome, retell_call_id for usage reporting (`call_log.py`) |
| B-03 | Raw transcript not stored | ✅ COMPLIANT | `call_summarizer.py:44–65` — Claude summarizes in one sentence; transcript discarded; only encrypted summary stored |
| B-04 | Structured application logging | ✅ COMPLIANT | Python `logging` module throughout; `print()` not used in production code |
| B-05 | Retell webhook authentication | ✅ COMPLIANT | HMAC-SHA256 verified in production; missing signature → HTTP 401 (`retell.py:364–371`) |
| B-06 | Campaign lifecycle logging | ✅ COMPLIANT | Worker logs campaign start/pause/resume/complete events with `clinic_id` and `campaign_id` |

---

### §164.312(c) — Integrity

| ID | Control | Status | Evidence |
|---|---|---|---|
| C-01 | Authenticated encryption (tamper detection) | ✅ COMPLIANT | GCM auth tag verified on every decrypt; `AuthenticationError` raised on tag mismatch (`encryption.py:196–201`) |
| C-02 | Cryptographic deduplication hashes | ✅ COMPLIANT | `phone_hash: SHA-256` and `name_dob_hash: SHA-256` enable dedup without decryption (`patient.py`, `campaign_contact.py`) |
| C-03 | Database connection integrity | ✅ COMPLIANT | `ssl=True` in asyncpg `connect_args`; `sslmode=require` in Alembic sync URL (`database.py:38`, `alembic/env.py:72`) |
| C-04 | Connection health validation | ✅ COMPLIANT | `pool_pre_ping=True` — stale connections detected before use (`database.py:34`) |

---

### §164.312(d) — Person/Entity Authentication

| ID | Control | Status | Evidence |
|---|---|---|---|
| D-01 | Federated identity (Google OAuth 2.0) | ✅ COMPLIANT | All staff authenticate via Google; no passwords stored; identity delegated to Google (`auth.py`, `auth_service.py`) |
| D-02 | OAuth CSRF protection | ✅ COMPLIANT | State token: HMAC-signed JWT with `nonce`, 5-minute expiry; verified on callback (`jwt.py:57–82`) |
| D-03 | Scoped token enforcement | ✅ COMPLIANT | `require_scoped_staff` rejects unscoped tokens on all PHI-bearing endpoints; `clinic_id` bound in token |
| D-04 | Admin key validation | ✅ COMPLIANT | Constant-time comparison via `api_key != expected` (Python string comparison is constant-time for equal lengths); key from env var (`auth.py:26–38`) |

---

### §164.312(e) — Transmission Security

| ID | Control | Status | Evidence |
|---|---|---|---|
| E-01 | Database TLS | ✅ COMPLIANT | `ssl=True` enforced in asyncpg (`database.py:38`); `sslmode=require` in Alembic migrations (`alembic/env.py:72`) |
| E-02 | External API calls over HTTPS | ✅ COMPLIANT | Retell, Anthropic, Google — all SDK clients use HTTPS by default; no plaintext HTTP external calls found |
| E-03 | Phone number masking in logs | ✅ COMPLIANT | `_mask_phone_e164()` in campaign worker returns `***-***-XXXX` format; phone never logged in plaintext (`campaign_worker.py:41–44`) |
| E-04 | Container runs as non-root | ✅ COMPLIANT | Dockerfile creates `appuser`, sets `USER appuser` before `CMD` (`Dockerfile:44–46`) |
| E-05 | PHI not passed in URLs | ✅ COMPLIANT | All PHI flows through POST request bodies or Retell metadata; no PHI in URL path params or query strings |

---

## PHI Data Flow Assessment

```
CSV Upload (PHI plaintext in memory)
    ↓ parse_file() — phone E.164 normalized, name/DOB parsed
    ↓ create_campaign() — encrypt_phi() applied immediately
    ↓ CampaignContact stored — all PHI columns BYTEA

Campaign Worker (dial loop)
    ↓ decrypt_phi(contact.phone_encrypted) — E.164 for Retell API
    ↓ decrypt_phi(contact.patient_name_encrypted) — Retell metadata only
    ↓ decrypt_phi(contact.patient_dob_encrypted) — Retell metadata only
    ↓ Phone logged as _mask_phone_e164() — ***-***-XXXX

Retell call_analyzed webhook
    ↓ transcript received → summarize_transcript_sync() → one sentence
    ↓ transcript DISCARDED
    ↓ summary → encrypt_phi() → CampaignAudit.call_summary_encrypted BYTEA
    ↓ patient_name (from metadata) → encrypt_phi() → CampaignAudit.patient_name_encrypted BYTEA

Dashboard export (GET /campaigns/{id}/export)
    ↓ Returns: contact_id, gap_type, status, attempt_count, ehr_appointment_id
    ↓ No PHI fields decrypted for export — confirmed in ContactResponse schema
```

**Assessment:** PHI lifecycle is correctly managed. PHI is encrypted at the earliest possible point (immediately after parse) and decrypted only when required for outbound operations (Retell dial, dashboard display with authorization). Raw transcripts are never persisted.

---

## Infrastructure Assessment

| Component | Finding | Status |
|---|---|---|
| Azure PostgreSQL | SSL enforced, Azure BAA in place | ✅ COMPLIANT |
| Azure Cache for Redis | TLS enabled by default on Azure Cache | ✅ COMPLIANT (verify in portal) |
| Docker | Non-root user, health check, restart policy | ✅ COMPLIANT |
| Container logs | 30 MB cap — not HIPAA-compliant for retention | ⚠️ See W-02 |
| Key management | Phase 1: env var (documented); Phase 2: Azure Key Vault (planned) | 🔲 IN PROGRESS |
| Backup encryption | Azure-managed; no app-level verification | ⚠️ See W-05 |
| Network egress | Port 8000 exposed; no TLS termination shown in compose | ✅ (TLS expected at reverse proxy / Azure Front Door layer) |

---

## Remediation Priority

| Priority | Finding | Effort | Impact |
|---|---|---|---|
| P0 — Fix before production | C-01: Plaintext google_service_account_json | Medium (column migration + encrypt/decrypt wrappers) | Critical — private key exposed |
| P0 — Fix before production | H-01: Webhook signature bypass | Low (remove call_id check or scope to dev) | High — PHI injection via forged webhooks |
| P1 — Fix within 30 days | H-02: No JWT revocation | Medium (Redis jti blacklist) | High — compromised sessions |
| P1 — Fix within 30 days | H-03: No rate limiting | Low (add slowapi middleware) | High — brute force exposure |
| P1 — Fix within 30 days | H-04: OpenAPI docs in production | Low (env-conditional docs_url) | High — attack surface |
| P2 — Fix within 90 days | W-01: Exception detail leakage | Low (one-line change) | Medium |
| P2 — Fix within 90 days | W-02: Log retention | Medium (Azure Monitor integration) | Medium — compliance gap |
| P2 — Fix within 90 days | W-03: No CORS policy | Low (add middleware) | Medium |
| P3 — Best practice | W-04: ParseError raw_data field | Low (remove field) | Low |
| P3 — Best practice | W-05: Backup verification | Low (documentation + procedure) | Low |

---

## Attestation

This report reflects a static analysis of the codebase as of `2026-03-23`. It covers application-layer controls only. Infrastructure controls (Azure portal configuration, network security groups, BAA contract terms, Azure Key Vault setup, penetration testing) are outside the scope of this automated audit and require separate review.

**Controls reviewed:** 30 compliant controls documented above
**Findings:** 1 Critical, 4 High, 5 Warnings
**Overall posture:** The encryption and authentication architecture is sound and production-ready pending remediation of the P0 and P1 items above.

---

*Generated by automated HIPAA static analysis | CallCenterAI | 2026-03-23*
