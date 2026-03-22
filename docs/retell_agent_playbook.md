# Retell agent playbook — CallCenterAI (HEDIS campaigns)

Operational guide for wiring **one Retell agent per clinic** to this FastAPI app: outbound campaign calls, mid-call EHR tools, webhooks, and post-call analysis. Keep this document aligned with `Clinic_app/Routes/retell.py`, `Clinic_app/services/retell_client.py`, and `Clinic_app/workers/campaign_worker.py`.

---

## 1. Architecture rules (non-negotiable)

| Rule | Detail |
|------|--------|
| Agents | **One Retell agent per clinic.** `ClinicIntegration.retell_agent_id` must match the agent Retell runs for that clinic. |
| Gap type | Passed on every outbound call as **metadata** (`gap_type`). The agent prompt should branch behavior (script, which measures to mention) from this value. **Do not** create separate Retell agents per gap type. |
| HEDIS vs legacy | **HEDIS outbound campaigns** use **`/retell/tools/*`** and **`/retell/webhook/*`** as below. Older demo routes (`/retell/schedule`, `/retell/confirm_booking`, `/retell/availability`) target the **Google Calendar booking** flow, not NextGen Playwright booking. |

---

## 2. Environment variables

| Variable | Purpose |
|----------|---------|
| `RETELL_API_KEY` | Bearer token for `POST https://api.retellai.com/v2/create-phone-call` (campaign worker). |
| `RETELL_WEBHOOK_SECRET` | Shared secret for HMAC verification of incoming webhooks and tool requests (`x-retell-signature`). |
| `RETELL_FROM_NUMBER` | Default outbound caller ID (E.164). Overridden per clinic by `ClinicIntegration.retell_outbound_number` when set. |
| `APP_ENVIRONMENT` | `production` / `prod` → signature required for webhooks/tools; dev allows missing signature with warnings. |
| `ANTHROPIC_API_KEY` | Used on `call_analyzed` to produce the one-sentence summary (`call_summarizer`). |

Database (per clinic, `ClinicIntegration`):

| Field | Purpose |
|-------|---------|
| `retell_agent_id` | Retell agent ID (string). |
| `retell_did` | Clinic inbound DID (E.164); surfaced to the patient as `clinic_phone` in metadata when present. |
| `retell_outbound_number` | Optional outbound DID for campaigns; falls back to `RETELL_FROM_NUMBER`. |

---

## 3. Public base URL (`APP_BASE_URL`)

All Retell **custom tool URLs** and **webhook URLs** must be reachable from Retell’s servers over HTTPS.

```
APP_BASE_URL = https://your-deployment.example.com
```

**Replace** with any **public HTTPS** host Retell can reach. Paths below are **relative to the app root** (no global `/api` prefix in the current app). Until Azure (or similar) is live, use a **tunnel** (e.g. ngrok, Cloudflare Tunnel) — see **§12**.

---

## 4. HTTP routes (copy-paste checklist)

Prefix every URL with `APP_BASE_URL`.

### 4.1 Custom tools (HMAC-signed; Retell → your API)

| Purpose | Method | Path |
|---------|--------|------|
| Fetch NextGen slots for voice | `POST` | `/retell/tools/get_available_slots` |
| Book in NextGen mid-call | `POST` | `/retell/tools/book_appointment` |

**Latency:** Design agent dialogue and EHR automation so **slot lookup stays under ~3 seconds** (PRD / architecture target).

### 4.2 Webhooks (HMAC-signed; Retell → your API)

| Event | Method | Path |
|-------|--------|------|
| Call started | `POST` | `/retell/webhook/call_started` |
| Call ended | `POST` | `/retell/webhook/call_ended` |
| Post-call analysis | `POST` | `/retell/webhook/call_analyzed` |

### 4.3 Legacy / non-HEDIS (do not use for HEDIS NextGen flow)

| Path | Notes |
|------|--------|
| `POST /retell/schedule` | Calendar-based scheduling flow. |
| `POST /retell/confirm_booking` | Calendar confirmation. |
| `GET` / `POST /retell/availability` | Calendar availability. |

---

## 5. Outbound API (your backend → Retell)

The campaign worker calls Retell directly (not your own domain):

- **Endpoint:** `POST https://api.retellai.com/v2/create-phone-call`
- **Auth:** `Authorization: Bearer <RETELL_API_KEY>`
- **Body (simplified):** `from_number`, `to_number`, `override_agent_id` (= clinic’s `retell_agent_id`), `metadata`, `retell_llm_dynamic_variables` (same key/value pairs as `metadata`, coerced to strings).

Reference: [Retell — Create phone call](https://docs.retellai.com/api-references/create-phone-call).

---

## 6. Metadata and dynamic variables (HEDIS campaigns)

The worker sends the following on **every** HEDIS outbound call. All values are **strings** in the JSON body. The same map is copied to **`retell_llm_dynamic_variables`** so prompts can reference them as dynamic variables (names depend on your Retell prompt template).

| Key | Source | Required | Notes |
|-----|--------|----------|--------|
| `call_type` | Worker | Yes | Must be exactly `hedis_campaign` for HEDIS webhook and booking side effects. |
| `campaign_contact_id` | Worker | Yes | UUID string; ties webhooks and `book_appointment` to `CampaignContact`. |
| `gap_type` | `CampaignContact.gap_type` | Yes | Must be one of the `GapType` enum values (snake_case), see §7. |
| `clinic_name` | `Clinic.name` | Yes | For prompts / patient context. |
| `clinic_phone` | `retell_did` or outbound `from_number` | Yes | Callback number for the patient. |
| `patient_name` | Decrypted from contact | Yes | Placeholder `"Patient"` if missing. |
| `provider_name` | CSV / contact | No | Empty string allowed; **tool** may still require `provider_name` in `args`. |
| `payer` | CSV / contact | No | Insurance/plan label for prompt context. |
| `patient_dob` | Decrypted | No | `YYYY-MM-DD` when present; omitted if not stored. |

**Important:** `clinic_id` is **not** in this map. The server resolves `clinic_id` from **`agent_id`** on every webhook/tool request via `ClinicIntegration.retell_agent_id`.

---

## 7. Gap types (`GapType` enum)

Use these **exact** string values in CSV, DB, metadata, and `book_appointment` `gap_type` when mapping appointment types:

| Value |
|-------|
| `colorectal_cancer_screening` |
| `breast_cancer_screening` |
| `cervical_cancer_screening` |
| `diabetes_hba1c` |
| `diabetes_eye_exam` |
| `diabetes_nephropathy` |
| `hypertension_control` |
| `depression_screening` |
| `well_child_visit` |
| `adolescent_well_care` |
| `adult_bmi_assessment` |
| `medication_adherence_diabetes` |
| `medication_adherence_hypertension` |
| `other` |

**Retell prompt:** Document each gap in plain language (what to say, compliance framing) and map utterances → the same canonical strings if the model fills tool arguments.

**NextGen appointment type:** Admin **gap_type → appointment type string** mapping lives in EHR config (`appt_type_mapping`). Values must match what Playwright selects in NextGen (often the **visible label** in the dropdown, not an opaque internal code). See `PLAN.md` Plan 011.

---

## 8. Custom tool request shape (implemented contract)

Handlers read the raw JSON body, verify signature, then parse:

- `body["call"]` — call object (includes `call_id`, `agent_id`, `metadata`, …).
- `body["args"]` — tool arguments from the agent.

### 8.1 `POST /retell/tools/get_available_slots`

| Input | Location | Required |
|-------|----------|----------|
| `agent_id` | `call.agent_id` | Yes — resolves clinic. |
| `provider_name` | `args.provider_name` or `call.metadata.provider_name` | Yes. |
| `date` | `args.date` | No — defaults to **today** (`YYYY-MM-DD`). |

**Response:** `success`, `message`, `slots` (human-readable strings for TTS), `slot_details` (structured; internal use).

### 8.2 `POST /retell/tools/book_appointment`

| Input | Location | Required |
|-------|----------|----------|
| `agent_id` | `call.agent_id` | Yes. |
| `provider_name` | `args.provider_name` | Yes. |
| `chosen_slot` | `args.chosen_slot` | Yes — must align with a slot the agent offered (same string format as returned in `slots`). |
| `patient_name` | `args.patient_name` | Yes. |
| `patient_dob` | `args.patient_dob` | Yes (`YYYY-MM-DD`). |
| `gap_type` | `args.gap_type` | No — if missing, server falls back to mapping default / generic appointment type. |

**HEDIS side effect:** If `call.metadata.call_type == "hedis_campaign"` and `campaign_contact_id` is valid, success updates `CampaignContact.ehr_appointment_id` and commits.

---

## 9. Webhook behavior (HEDIS)

All three webhooks:

1. Read raw body bytes.
2. Call `verify_retell_signature` (`x-retell-signature`, HMAC-SHA256 over compact JSON body with `RETELL_WEBHOOK_SECRET`).
3. Parse `call` object (fallback: top-level body).

**Playground / test:** Calls with `call_id` equal to `playground` or prefixed `test_` / `playground_` may skip verification (see code).

### 9.1 `call_started`

Creates `CallLog`, resolves clinic by `agent_id`. For HEDIS metadata, associates outbound campaign contacts when `call_type` and `campaign_contact_id` are present.

### 9.2 `call_ended`

Updates `CampaignContact` status (voicemail, no answer, booked, declined, exhausted, retries, etc.) from `disconnection_reason` and whether `ehr_appointment_id` is set.

### 9.3 `call_analyzed`

Only processes rows where merged metadata has `call_type == "hedis_campaign"` and a valid `campaign_contact_id`.

- Builds a short transcript string from `transcript`, `transcript_with_tool_calls`, or nested `call_analysis` fields (best effort).
- Runs **Claude** one-sentence summary; encrypts and stores `CampaignAudit` (`call_summary_encrypted`, optional encrypted name).
- **Does not** persist full transcript to the database (policy).

---

## 10. Retell dashboard configuration (checklist)

For **each** clinic agent:

1. **Agent ID** — copy into `ClinicIntegration.retell_agent_id` (admin API or DB).
2. **Webhooks** — register the three URLs in §4.2 using the clinic’s production `APP_BASE_URL`.
3. **Custom functions / tools** — point to §4.1 URLs; ensure HTTP method `POST` and signing secret matches `RETELL_WEBHOOK_SECRET`.
4. **Prompt** — inject dynamic variables matching §6 (`gap_type`, `patient_name`, `provider_name`, `clinic_name`, `clinic_phone`, `payer`, `patient_dob` when present). Instruct when to call **get_available_slots** (with `provider_name` and optional `date`) and **book_appointment** (all required args + `gap_type`).
5. **Outbound** — ensure Retell allows outbound from `retell_outbound_number` or platform number matching `RETELL_FROM_NUMBER`.

---

## 11. Verification flow (staging)

1. EHR: `ClinicEHRConfig` populated; `appt_type_mapping` covers all gap types you dial.
2. Admin: integration row has correct `retell_agent_id`, DIDs, outbound number.
3. Place a **test campaign** contact; start campaign; confirm `create-phone-call` succeeds.
4. During call, confirm tools hit your server (200, signed).
5. After hangup, confirm `call_ended` updated contact status and `call_analyzed` created `CampaignAudit`.

Log outcomes in `PROGRESS.txt` per `PLAN.md` Plan 011.

---

## 12. Decisions (Edgar)

Recorded product / deployment choices so the playbook stays grounded in how the pilot will actually run.

1. **`APP_BASE_URL` / domain / Azure** — No production site or Azure deploy yet. A **custom domain is optional** early on. For development and Retell integration tests, use a tunnel (**ngrok**, **Cloudflare Tunnel**, etc.) to get a temporary **`https://…`** URL. After Azure setup, use the **default app hostname** (e.g. `*.azurewebsites.net`) for webhooks/tools; add a branded domain later if desired.

2. **Agents and gap types** — **Each clinic gets one Retell agent.** That agent uses **one playbook / prompt** that branches by **`gap_type`** (metadata + dynamic variables) so the script matches the care gap — not a separate Retell agent per gap type.

3. **Inbound vs outbound** — **Outbound HEDIS only** for now. **Inbound** calling and legacy calendar routes are **not** in scope; ignore `/retell/schedule`, `/retell/confirm_booking`, and `/retell/availability` for this pilot unless that changes later.

4. **Post-call notes and cost (Plan 011)** — **Start with Retell’s post-call summary** (cheapest path). **If** it is not good enough for staff ops, **add Claude** that reads **that summary** and extracts **only the fields we need** (not necessarily the full transcript). Escalate input to transcript only if summaries remain insufficient and policy allows.

---

*Last updated: 2026-03-23 — maintained next to code changes in `Clinic_app/Routes/retell.py` and campaign worker.*
