# HIPAA Security Rule Reference — CallCenterAI

Quick reference for the HIPAA Security Rule safeguards relevant to this SaaS platform.

---

## Administrative Safeguards (§164.308)

| Requirement | Implementation |
|-------------|---------------|
| Access controls | Google OAuth for staff, API key for admin, JWT for sessions |
| Workforce training | Document in clinic onboarding — not a code concern |
| Incident response | Log all auth failures, PHI access errors to Azure Monitor |
| Business Associate Agreements | Azure (BAA in effect), Retell AI (confirm BAA before PHI handoff) |

---

## Physical Safeguards (§164.310)

All physical safeguards are delegated to Azure (covered under BAA). No on-prem infrastructure.

---

## Technical Safeguards (§164.312)

### Access Control (§164.312(a))
- Unique user IDs via Google OAuth — no shared accounts
- Automatic logoff — JWT expiry enforced
- Encryption of PHI in transit and at rest

### Audit Controls (§164.312(b))
- All PHI access must be logged with: `clinic_id`, action type, timestamp
- Logs must NOT contain the PHI itself — log identifiers only
- Azure Monitor + application-level logs

### Integrity (§164.312(c))
- AES-256-GCM provides authentication tag — detects tampering at rest
- HTTPS (TLS 1.2+) for all data in transit
- Webhook HMAC verification for Retell callbacks

### Transmission Security (§164.312(e))
- All external API calls over HTTPS — enforce `verify=True` in httpx/requests
- Retell AI receives PHI (name, DOB) as call metadata — confirm Retell BAA covers this
- No PHI transmitted over unencrypted channels

---

## PHI Definition (What Counts as PHI)

The following are PHI when linked to a patient:

| Identifier | PHI? | How Handled in This Project |
|------------|------|-----------------------------|
| Patient name | Yes | Retell metadata only; encrypted if stored |
| Date of birth | Yes | Retell metadata only; never stored |
| Phone number | Yes | AES-256-GCM + SHA-256 hash |
| Address | Yes | Not collected — out of scope |
| MRN / Account number | Yes | Not stored — passed to NextGen session only |
| Appointment details | Potentially | Care gap type stored (not PHI alone); linked records encrypted |
| Call outcome | Potentially | Encrypted summary only; no transcript |
| IP address | No | Standard logging acceptable |

---

## Minimum Necessary Standard

Only access, use, or disclose the minimum PHI necessary:
- Campaign workers access phone numbers (encrypted) and gap type only
- Retell receives name + DOB as metadata — no other PHI
- Claude API receives call transcript for summarization — transcript discarded immediately after
- Dashboard shows encrypted summaries — decrypt only for display, never cache decrypted PHI

---

## Breach Notification (§164.400)

If a potential PHI breach is detected in code (e.g., PHI logged in plaintext, unencrypted column):
1. Treat it as a 🔴 Critical violation
2. Stop the session and alert Edgar immediately
3. Do not attempt to auto-fix without explicit direction — the fix strategy may have legal implications
4. Document the finding precisely: file, line, what PHI, how long it may have been exposed

---

## SaaS-Specific Considerations

### Multi-Tenancy Isolation
Failure to filter by `clinic_id` is a HIPAA violation — it allows one clinic to access another's patient data. Every query must be scoped.

### Redis Cache
- Never cache decrypted PHI
- Cache keys must not contain PHI (use hashed contact IDs or gap type strings only)
- AgentQL selector cache contains no PHI — safe to cache by selector string

### Background Workers
Workers process PHI asynchronously — same rules apply:
- Mask phone numbers in worker logs
- Encrypt before writing to DB
- Filter by `clinic_id` on all queries within worker tasks

### Retell AI Integration
- Retell receives `patient_name` and `patient_dob` as call metadata — this is intentional
- Confirm Retell BAA is signed and covers this data handoff
- Retell webhook payloads must be HMAC-verified before processing any data from them
- Never log the full Retell webhook payload — it may contain PHI in transcript fields
