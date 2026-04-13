---
name: hipaa-auditor
description: Audits code for HIPAA Security Rule violations and PHI handling errors in the CallCenterAI SaaS platform. Activates automatically before and after planning or writing any code — verifies PHI encryption, tenant isolation, logging safety, authentication guards, and secure data handling. Use when reviewing code changes, planning new features, writing routes/services/models/workers, or when the user asks for a security or HIPAA audit.
---

# HIPAA Auditor — CallCenterAI

Security and HIPAA compliance are non-negotiable. Every line of code must be evaluated against these rules before being written and after being written. If a violation is found, stop and fix it before proceeding.

## Audit Trigger Points

Run a HIPAA audit check at each of these moments:
1. **Before planning** — flag any proposed design that would create a violation
2. **Before writing code** — verify the implementation approach is compliant
3. **After writing code** — scan the output for violations before presenting it
4. **When explicitly invoked** — full codebase audit (see Full Audit Workflow below)

---

## Core PHI Rules (Project-Specific)

These are non-negotiable rules from this project's CLAUDE.md:

| Rule | Detail |
|------|--------|
| **No plaintext patient name in DB** | Name goes to Retell as call metadata only; if stored, use `campaign_audit.patient_name_encrypted` with AES-256-GCM |
| **No patient DOB in DB** | Passed as Retell metadata only — never persisted |
| **No raw call transcripts** | Generate a one-sentence Claude summary on `call_analyzed` webhook, store that encrypted, discard transcript |
| **Encryption module only** | All PHI at rest uses `common/encryption.py` (AES-256-GCM) — never roll custom encryption |
| **No plaintext phone numbers in logs** | Mask as `***-***-XXXX` in all log output |
| **No plaintext NextGen credentials** | Must be AES-256-GCM encrypted in `ClinicIntegration` |
| **Tenant isolation on all queries** | Every DB query must include a `clinic_id` filter — no exceptions |
| **Phone number storage** | AES-256-GCM encrypted column + SHA-256 hash column for dedup — both required |

---

## Audit Checklist

### 1. PHI Encryption
- [ ] All PHI fields use `common/encryption.py` — no `hashlib`, `base64`, or custom AES
- [ ] No patient name, DOB, phone, or transcript stored in plaintext DB columns
- [ ] `encrypt()` called before DB insert, `decrypt()` called after DB read
- [ ] Phone number stored as both encrypted blob and SHA-256 hash

### 2. Logging Safety
- [ ] No PHI appears in any `logging.*` call
- [ ] Phone numbers masked as `***-***-XXXX` before logging
- [ ] No patient name or DOB in log messages, error messages, or exception strings
- [ ] No API keys, secrets, or credentials in logs

### 3. Multi-Tenant Isolation
- [ ] Every SQLAlchemy query filters by `clinic_id`
- [ ] No cross-tenant data leakage possible in any query path
- [ ] `clinic_id` validated against the authenticated session — not taken from request body blindly

### 4. Authentication & Authorization
- [ ] All `/admin/*` routes have `Depends(verify_admin_api_key)`
- [ ] All clinic-scoped routes validate the authenticated clinic's identity
- [ ] No unauthenticated endpoints that touch PHI
- [ ] Retell webhooks verified with HMAC signature before processing

### 5. Data Minimization
- [ ] No PHI collected or stored beyond what is needed for the outreach workflow
- [ ] Call transcripts discarded after Claude summary is generated
- [ ] Patient DOB never written to any DB table or Redis key
- [ ] Redis cache keys never contain PHI (use hashed identifiers only)

### 6. Secrets & Credentials
- [ ] No secrets hardcoded in source code
- [ ] All credentials come from environment variables
- [ ] No secrets in comments or docstrings
- [ ] NextGen credentials encrypted at rest using `common/encryption.py`

### 7. Input Validation & Injection Prevention
- [ ] All DB queries use SQLAlchemy ORM or parameterized statements — no raw SQL string interpolation
- [ ] CSV uploads validated for structure and field types before processing
- [ ] Phone numbers validated before encryption and storage
- [ ] No user-controlled input used in shell commands or file paths

### 8. API & Transport Security
- [ ] All external calls use HTTPS — no HTTP endpoints for PHI
- [ ] Retell webhook payloads validated with `RETELL_WEBHOOK_SECRET` HMAC before trusting any data
- [ ] JWT tokens validated on all protected routes
- [ ] API keys never returned in response bodies

### 9. Error Handling
- [ ] Error responses never include PHI, stack traces with PHI, or internal DB structure
- [ ] Exception handlers sanitize messages before returning to client
- [ ] 500 errors log to server only — generic message to client

### 10. Audit Trail
- [ ] All PHI access logged with `clinic_id`, action, and timestamp (no PHI in the log itself)
- [ ] Campaign outcomes written to `campaign_audit` with encrypted fields
- [ ] Failed auth attempts logged for monitoring

---

## Violation Severity Levels

| Level | Label | Action |
|-------|-------|--------|
| 🔴 Critical | PHI exposed, no encryption, no auth | Stop. Fix before writing any more code. |
| 🟠 High | Missing tenant filter, secrets in code, plaintext in logs | Fix in same session before merging. |
| 🟡 Medium | Missing input validation, weak error messages | Flag and fix or create a task. |
| 🟢 Low | Code style deviates from secure patterns | Note it; fix opportunistically. |

---

## Inline Code Review Patterns

When reviewing or writing code, flag these patterns immediately:

```python
# 🔴 VIOLATION — plaintext PHI in log
logging.info(f"Calling patient {patient.name} at {patient.phone}")

# ✅ CORRECT
logging.info(f"Initiating call for contact_id={contact.id} clinic_id={contact.clinic_id}")
```

```python
# 🔴 VIOLATION — missing clinic_id filter
contacts = await db.execute(select(Contact))

# ✅ CORRECT
contacts = await db.execute(select(Contact).where(Contact.clinic_id == clinic_id))
```

```python
# 🔴 VIOLATION — raw transcript stored
audit.transcript = call_payload["transcript"]

# ✅ CORRECT — summarize via Claude, store encrypted summary, discard transcript
summary = await summarize_transcript(call_payload["transcript"])
audit.summary_encrypted = encrypt(summary)
```

```python
# 🔴 VIOLATION — plaintext phone in DB
contact.phone = "+15551234567"

# ✅ CORRECT
contact.phone_encrypted = encrypt("+15551234567")
contact.phone_hash = sha256_hash("+15551234567")
```

```python
# 🔴 VIOLATION — unauthenticated admin route
@router.get("/admin/clinics")
async def list_clinics(db: AsyncSession = Depends(get_db)):

# ✅ CORRECT
@router.get("/admin/clinics")
async def list_clinics(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_admin_api_key),
):
```

---

## Full Codebase Audit Workflow

When asked to audit the full codebase:

```
Audit Progress:
- [ ] Scan all files in Clinic_app/data/models/ — check every column for PHI stored plaintext
- [ ] Scan all files in Clinic_app/Routes/ — check auth guards on every endpoint
- [ ] Scan all files in Clinic_app/services/ — check encryption usage, logging, tenant filters
- [ ] Scan all files in Clinic_app/workers/ — check logging, PHI handling in background tasks
- [ ] Scan Clinic_app/common/ — verify encryption.py is the only crypto used
- [ ] Scan tests/ — verify PHI never hardcoded in test fixtures
- [ ] Scan all files for hardcoded secrets, API keys, or credentials
- [ ] Check all SQLAlchemy queries for missing clinic_id filters
- [ ] Check all logging calls for PHI leakage
- [ ] Report findings grouped by severity
```

Report format:

```
## HIPAA Audit Report — [date]

### 🔴 Critical Violations (X)
- File:Line — Description — Fix required

### 🟠 High Violations (X)
- File:Line — Description

### 🟡 Medium Violations (X)
- File:Line — Description

### Summary
X critical, X high, X medium, X low
Recommendation: [clear next step]
```

---

## Additional Resources

- For detailed HIPAA Security Rule requirements, see [hipaa-reference.md](hipaa-reference.md)
- Project PHI rules source of truth: `CLAUDE.md` — "PHI Rules" section
- Encryption implementation: `Clinic_app/common/encryption.py`
