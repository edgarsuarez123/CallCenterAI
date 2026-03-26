# Local Test Guide — First Test Call End-to-End

This guide walks you through every step to run a real Retell outbound call from your local machine.

---

## What you need before starting

- [ ] Docker Desktop installed and running
- [ ] ngrok installed (`winget install ngrok` or download from ngrok.com)
- [ ] Your Retell account credentials:
  - `RETELL_API_KEY` (from Retell dashboard → API Keys)
  - `RETELL_WEBHOOK_SECRET` (from Retell dashboard → your agent settings)
  - `RETELL_FROM_NUMBER` — the outbound phone number Retell assigned you (E.164 format, e.g. `+15551234567`)
  - Your **Retell Agent ID** (from the agent page URL or settings)
- [ ] `ANTHROPIC_API_KEY`
- [ ] A real phone number to receive the test call

---

## Step 1 — Create your .env file

Copy the example file and fill it in:

```
copy env.example .env
```

Open `.env` and set these values (the rest can stay as defaults):

```
APP_ENVIRONMENT=development

DB_HOST=postgres
DB_PORT=5432
DB_NAME=callcenterai
DB_USER=postgres
DB_PASSWORD=postgres

PHI_ENCRYPTION_KEY=        ← generate: python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
PHI_HASH_KEY=              ← generate same way (must be different from PHI_ENCRYPTION_KEY)

RETELL_API_KEY=            ← from Retell dashboard
RETELL_WEBHOOK_SECRET=     ← from Retell dashboard
RETELL_FROM_NUMBER=        ← your Retell outbound number e.g. +15551234567

ANTHROPIC_API_KEY=         ← from Anthropic console

ADMIN_API_KEY=test-admin-key-123
JWT_SECRET_KEY=test-jwt-secret-123

REDIS_URL=redis://redis:6379
```

---

## Step 2 — Start the local server

In your terminal from the project root:

```bash
docker compose -f docker-compose.dev.yaml up -d
```

Wait about 15 seconds for everything to start. Then check it's running:

```bash
docker compose -f docker-compose.dev.yaml logs app --tail=20
```

You should see: `Uvicorn running on http://0.0.0.0:8000`

---

## Step 3 — Run database migrations

```bash
docker compose -f docker-compose.dev.yaml --profile migrate run --rm migrate
```

Wait for it to finish. You should see `Running upgrade ... -> head` with no errors.

---

## Step 4 — Open Swagger (your local API)

Open your browser and go to:

```
http://localhost:8000/docs
```

You should see the full API documentation. Keep this tab open — you'll use it for the next steps.

**Authorize Swagger with your admin key:**
1. Click the green **Authorize** button (top right)
2. In the `X-Admin-Key` field type: `test-admin-key-123`
3. Click **Authorize** then **Close**

---

## Step 5 — Start your ngrok tunnel

Open a **new terminal window** and run:

```bash
ngrok http 8000
```

ngrok will show something like:

```
Forwarding   https://abc123.ngrok-free.app -> http://localhost:8000
```

**Copy that `https://` URL.** This is your `APP_BASE_URL`. You'll use it in Retell and in Swagger.

> Keep this terminal open. If you close it the tunnel dies and Retell can't reach your server.

---

## Step 6 — Configure Retell dashboard

Go to your Retell agent. You need to do 3 things:

### 6a — Add the system prompt

Paste the full prompt from `docs/retell_agent_playbook.md` section 11.1 into your agent's system prompt field.

### 6b — Register LLM dynamic variables

In the agent settings, add each of these as a variable:

```
gap_type
patient_name
provider_name
clinic_name
clinic_phone
payer
call_type
campaign_contact_id
```

### 6c — Add the 2 custom functions

In the **Functions** section, add these two (replace `https://abc123.ngrok-free.app` with your actual ngrok URL):

**Function 1:**
- Name: `get_available_slots`
- URL: `https://abc123.ngrok-free.app/retell/tools/get_available_slots`
- Method: POST
- Signing secret: your `RETELL_WEBHOOK_SECRET`
- Parameters:
  - `provider_name` — string — not required
  - `date` — string — not required

**Function 2:**
- Name: `book_appointment`
- URL: `https://abc123.ngrok-free.app/retell/tools/book_appointment`
- Method: POST
- Signing secret: your `RETELL_WEBHOOK_SECRET`
- Parameters:
  - `provider_name` — string — required
  - `chosen_slot` — string — required
  - `patient_name` — string — required
  - `gap_type` — string — not required

### 6d — Register webhooks

Find the webhook settings for your agent (usually in the agent's General or Settings tab). Add:

```
call_started  →  https://abc123.ngrok-free.app/retell/webhook/call_started
call_ended    →  https://abc123.ngrok-free.app/retell/webhook/call_ended
call_analyzed →  https://abc123.ngrok-free.app/retell/webhook/call_analyzed
```

---

## Step 7 — Create the clinic in Swagger

In Swagger (`http://localhost:8000/docs`):

1. Find **POST /admin/clinics** → click **Try it out**
2. Paste this body:

```json
{
  "name": "Test Clinic",
  "tier": "basic",
  "status": "active",
  "license_token": "test-license-001"
}
```

3. Click **Execute**
4. Copy the `id` from the response — this is your **CLINIC_ID**. Save it.

---

## Step 8 — Create the clinic integration

1. Find **POST /admin/clinics/{clinic_id}/integration** → click **Try it out**
2. Enter your `CLINIC_ID` in the `clinic_id` field
3. Paste this body (replace values with your actual Retell info):

```json
{
  "retell_agent_id": "your-retell-agent-id",
  "retell_did": "+15551234567",
  "google_service_account_json": "{\"type\":\"service_account\",\"project_id\":\"test\",\"private_key_id\":\"test\",\"private_key\":\"test\",\"client_email\":\"test@test.iam.gserviceaccount.com\",\"client_id\":\"test\",\"auth_uri\":\"https://accounts.google.com/o/oauth2/auth\",\"token_uri\":\"https://oauth2.googleapis.com/token\"}"
}
```

> `retell_did` = the same as `RETELL_FROM_NUMBER`. `google_service_account_json` is required by the model but not used for HEDIS calls — the dummy value above is fine for testing.

4. Click **Execute** — expect a 200 or 201.

---

## Step 8b — Configure EHR (required for Test B only)

Skip this step if you only want to run Test A (colorectal). Come back here when you're ready for Test B.

**8b-1 — Add NextGen credentials**

1. Find **POST /admin/clinics/{clinic_id}/ehr-config** → click **Try it out**
2. Enter your `CLINIC_ID`
3. Paste this body with your real NextGen credentials:

```json
{
  "nextgen_url": "https://your-nextgen-instance.com",
  "nextgen_username": "your-username",
  "nextgen_password": "your-password"
}
```

4. Click **Execute**

**8b-2 — Set appointment type mapping**

This tells the system what to select in the NextGen appointment type dropdown for a `preventive_visit`.

1. Find **PUT /admin/clinics/{clinic_id}/appt-types** → click **Try it out**
2. Enter your `CLINIC_ID`
3. Paste this body (replace `"Annual Wellness Visit"` with the exact label NextGen uses):

```json
{
  "mapping": {
    "preventive_visit": "Annual Wellness Visit"
  }
}
```

4. Click **Execute**

**8b-3 — Test EHR connectivity (optional but recommended)**

1. Find **POST /admin/clinics/{clinic_id}/ehr-test** → click **Try it out**
2. Enter your `CLINIC_ID`
3. Click **Execute**

A success response means Playwright can log into NextGen. If this fails, fix it before running Test B.

---

## Step 9 — Create the test patient file

The admin uploads a Google Sheet exported as Excel (.xlsx). You will run **two tests** — one without EHR, one with EHR. Put both rows in the same sheet so they upload together.

1. Open **Google Sheets** and create a new spreadsheet
2. Add this data (row 1 = headers, rows 2–3 = patients):

| Member Name | Phone | Gap Type | Language | Payer | Provider |
|-------------|-------|----------|----------|-------|----------|
| Jane Test | +1YOUR_REAL_NUMBER | colorectal | en | Medicare | Dr. Smith |
| John Test | +1YOUR_REAL_NUMBER | preventive_visit | en | Medicare | Dr. Smith |

3. Replace `+1YOUR_REAL_NUMBER` (both rows) with your actual cell phone in E.164 format (e.g. `+17875551234`)
4. Go to **File → Download → Microsoft Excel (.xlsx)**
5. Save it somewhere easy to find (e.g. Desktop)

> The column names are flexible — Claude reads the headers and maps them to the right fields automatically.

### What each row tests

**Row 1 — `colorectal` (Test A — no EHR)**
- Agent delivers the colorectal screening script
- No tools are called — NextGen is never touched
- After hangup: Claude stores an encrypted one-sentence summary
- Expected final contact status: `ORDER_AGREED` (or `ORDER_DECLINED` if you say no)

**Row 2 — `preventive_visit` (Test B — full EHR booking)**
- Agent delivers the wellness visit script
- When you say yes to scheduling, agent calls `get_available_slots` → NextGen opens in headless browser
- You pick a slot → agent calls `book_appointment` → NextGen creates the appointment
- Expected final contact status: `BOOKED`
- **Requires:** NextGen EHR config (Step 8b below) and NextGen must be reachable

---

## Step 10 — Generate a staff JWT for local testing

Campaign routes require a JWT. Since Google OAuth requires a browser flow, generate one directly from the command line.

Open a terminal (outside Docker — on your Windows machine) and run:

```bash
python -c "
import jwt, datetime, uuid
SECRET = 'test-jwt-secret-123'
CLINIC_ID = 'PASTE_YOUR_CLINIC_ID_HERE'
payload = {
    'sub': 'test-user',
    'email': 'test@clinic.com',
    'clinic_id': CLINIC_ID,
    'role': 'admin',
    'type': 'scoped',
    'iat': datetime.datetime.now(datetime.timezone.utc),
    'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24),
}
print(jwt.encode(payload, SECRET, algorithm='HS256'))
"
```

Replace `PASTE_YOUR_CLINIC_ID_HERE` with the clinic `id` you got in Step 7.

Copy the printed token. It will look like `eyJhbGci...`

> If `jwt` is not installed: `pip install PyJWT`

---

## Step 11 — Upload the CSV

1. Click the **Authorize** button in Swagger (top right)
2. Find the `Authorization (http, Bearer)` field and paste your JWT token from Step 10 (just the token, Swagger adds "Bearer" automatically)
3. Click **Authorize** then **Close**
4. Find **POST /campaigns/upload** → click **Try it out**
5. Fill in:
   - `file`: select your `.xlsx` file downloaded from Google Sheets
   - `name`: `Test Campaign`
   - `measurement_year`: `2026`
4. Click **Execute**
5. Copy the `id` from the response — this is your **CAMPAIGN_ID**

---

## Step 12 — Start the campaign

1. Find **POST /campaigns/{campaign_id}/start** → click **Try it out**
2. Enter your `CAMPAIGN_ID`
3. Click **Execute**

---

## Step 13 — Watch it work

**Watch the logs in real time:**

```bash
docker compose -f docker-compose.dev.yaml logs app -f
```

---

### Test A — colorectal (no EHR)

The worker dials `colorectal` first (it comes first in the CSV).

**What you should see in logs:**
```
Campaign worker started clinic_id=...
Dialing contact_id=... campaign_id=... gap_type=colorectal attempt=1 to=***-***-XXXX
Outbound call placed retell_call_id=... to=***-***-XXXX
call_started webhook received ...
call_ended webhook received ...
call_analyzed webhook received ...
extract_order_based_notes_sync: calling Claude gap_type=colorectal transcript_len=...
extract_order_based_notes_sync: success gap_type=colorectal patient_agreed=True/False
```

**What you should hear on the phone:**
> "Hi, may I speak with Jane Test? ... I'm calling from Test Clinic. Your care team wanted to reach out about colon cancer screening..."

**Say yes** → agent says it will have someone follow up and ends the call.
**Say no** → agent acknowledges and ends politely.

**Verify the outcome:**
- In Swagger, call **GET /campaigns/{campaign_id}/contacts**
- The colorectal contact should show status `ORDER_AGREED` (if you said yes) or `ORDER_DECLINED` (if you said no)

---

### Test B — preventive_visit (full EHR booking)

After Test A completes the worker automatically moves to the `preventive_visit` contact.

**What you should see in logs:**
```
Dialing contact_id=... gap_type=preventive_visit attempt=1 to=***-***-XXXX
Outbound call placed retell_call_id=... to=***-***-XXXX
call_started webhook received ...
```

When you say yes to scheduling:
```
get_available_slots EHR tool called provider_name=Dr. Smith ...
```

When you confirm a slot:
```
book_appointment EHR tool called ...
book_appointment: success ehr_appointment_id=...
call_ended webhook received ...
call_analyzed webhook received ...
summarize_transcript_sync: calling Claude gap_type=preventive_visit ...
summarize_transcript_sync: success ...
```

**What you should hear on the phone:**
> "Hi, may I speak with John Test? ... I'm calling from Test Clinic. Our records show you're due for your annual wellness visit..."

**Say yes to scheduling** → agent reads 2–3 available time slots from NextGen.
**Pick one** → agent confirms the booking and thanks you.

**Verify the outcome:**
- In Swagger, call **GET /campaigns/{campaign_id}/contacts**
- The preventive_visit contact should show status `BOOKED` and have an `ehr_appointment_id`
- The appointment should also appear in NextGen

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Swagger won't open | Is Docker running? `docker compose -f docker-compose.dev.yaml ps` |
| Migrations failed | `docker compose -f docker-compose.dev.yaml logs migrate` |
| Worker not dialing | Logs say "outside calling hours"? Default window is 9am–6pm EST |
| Worker not dialing | Logs say "no eligible contact"? Campaign may not be ACTIVE — re-run start |
| Retell can't reach webhooks | Is ngrok still running? URL changes every restart — update Retell if you restarted ngrok |
| Call connects but wrong script | Dynamic variables not registered in Retell, or system prompt not saved |
| Agent doesn't call `get_available_slots` | Patient said yes but agent didn't call tool — check that functions are saved in Retell with the correct ngrok URL |
| `EHR not configured` on booking tool | Step 8b not done — add NextGen credentials first |
| `Booking form not found` in logs | NextGen URL or credentials wrong, or NextGen blocked headless browser |
| Contact stuck in `CALLING` status | `call_ended` webhook didn't fire — check ngrok is running and webhook URL is correct in Retell |
| 401 on campaign routes | JWT expired — re-run the Python one-liner from Step 10 |

---

## After the tests

Record the result in `PROGRESS.txt` per `PLAN.md §Plan 014 Sprint C`.

**Test A — colorectal checklist:**
- [ ] Phone rang and call connected
- [ ] Agent said the colorectal script (not a wellness visit or other gap)
- [ ] `call_analyzed` fired → logs show `extract_order_based_notes_sync: success`
- [ ] Contact status = `ORDER_AGREED` or `ORDER_DECLINED`

**Test B — preventive_visit checklist:**
- [ ] Phone rang and call connected
- [ ] Agent said the wellness visit script
- [ ] Agent read real available slots from NextGen
- [ ] After picking a slot, agent confirmed the booking
- [ ] `call_analyzed` fired → logs show `summarize_transcript_sync: success`
- [ ] Contact status = `BOOKED`
- [ ] `ehr_appointment_id` is set on the contact
- [ ] Appointment visible in NextGen

---

*Last updated: 2026-03-25*
