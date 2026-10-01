#!/usr/bin/env bash
# =============================================================================
# CallCenterAI — Demo Walkthrough Script
# =============================================================================
# Runs the full happy-path demo using curl + the API.
# Requires: curl, jq
#
# BEFORE RUNNING:
#   1. docker compose -f docker-compose.dev.yaml up
#   2. python scripts/seed_demo.py  (copy the clinic_id printed at the end)
#   3. Set CLINIC_ID below
#   4. bash scripts/demo_walkthrough.sh
# =============================================================================

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${ADMIN_API_KEY:-demo-api-key}"
CLINIC_ID="${CLINIC_ID:-}"   # paste clinic_id from seed_demo.py output

if [ -z "$CLINIC_ID" ]; then
  echo "ERROR: Set CLINIC_ID to the value printed by seed_demo.py"
  echo "  export CLINIC_ID=<uuid>"
  exit 1
fi

CAMPAIGNS_BASE="$BASE_URL/admin/clinics/$CLINIC_ID/campaigns"

# Helper: print a step header
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "STEP $1: $2"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()   { echo "[OK] $*"; }

# ─── Step 1: Health Check ────────────────────────────────────────────────────
step 1 "Health Check"
curl -s "$BASE_URL/health" | jq .
ok "DB connection confirmed"

# ─── Step 2: List Campaigns (see seeded data) ────────────────────────────────
step 2 "List Campaigns for Clinic"
curl -s -H "X-API-Key: $API_KEY" "$CAMPAIGNS_BASE" | jq .
ok "Two campaigns: Q3 COMPLETED + Q4 DRAFT"

# ─── Step 3: View Completed Campaign Report ───────────────────────────────────
step 3 "View Completed Campaign Report (Q3 Wellness)"
CAMPAIGN1_ID=$(curl -s -H "X-API-Key: $API_KEY" "$CAMPAIGNS_BASE" | \
  jq -r '.data[] | select(.name | test("Q3")) | .id')
echo "Campaign 1 ID: $CAMPAIGN1_ID"
curl -s -H "X-API-Key: $API_KEY" "$CAMPAIGNS_BASE/$CAMPAIGN1_ID/report" | jq .
ok "Shows decrypted patient names + outcomes"

# ─── Step 4: Create a New Campaign ───────────────────────────────────────────
step 4 "Create a New Campaign (live demo)"
NEW_CAMPAIGN=$(curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Demo Live Campaign","reason":"Annual mammogram is overdue per HEDIS measure criteria."}' \
  "$CAMPAIGNS_BASE")
echo "$NEW_CAMPAIGN" | jq .
NEW_CAMPAIGN_ID=$(echo "$NEW_CAMPAIGN" | jq -r '.data.id')
echo "New Campaign ID: $NEW_CAMPAIGN_ID"
ok "Campaign created in DRAFT status"

# ─── Step 5: Upload Patient CSV ──────────────────────────────────────────────
step 5 "Upload Patient CSV"
# Create a temp CSV
CSV_FILE=$(mktemp /tmp/patients_XXXXXX.csv)
cat > "$CSV_FILE" <<'CSVEOF'
patient_name,phone,reason
Rosa Delgado,+17875550301,Mammogram screening overdue
Kevin Park,+17875550302,Mammogram screening overdue
Diane Foster,+17875550303,Mammogram referral pending
CSVEOF

curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -F "file=@$CSV_FILE" \
  "$CAMPAIGNS_BASE/$NEW_CAMPAIGN_ID/upload" | jq .
rm -f "$CSV_FILE"
ok "3 contacts imported, PHI encrypted at rest"

# ─── Step 6: Start Campaign ───────────────────────────────────────────────────
step 6 "Start Campaign (DRAFT → QUEUED)"
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  "$CAMPAIGNS_BASE/$NEW_CAMPAIGN_ID/start" | jq .
ok "Campaign queued for background worker"

# ─── Step 7: Manually Process Contacts (Demo Mode) ───────────────────────────
step 7 "Process Contacts One by One (Demo Mode)"
for i in 1 2 3; do
  echo "  → Processing contact $i..."
  curl -s -X POST \
    -H "X-API-Key: $API_KEY" \
    "$CAMPAIGNS_BASE/$NEW_CAMPAIGN_ID/process-next" | jq '.data | {patient_name,outcome,duration_seconds,notes}'
  sleep 0.5
done
ok "All 3 contacts processed with simulated outcomes"

# ─── Step 8: View Final Report ────────────────────────────────────────────────
step 8 "View Final Campaign Report"
curl -s -H "X-API-Key: $API_KEY" \
  "$CAMPAIGNS_BASE/$NEW_CAMPAIGN_ID/report" | jq '.data | {summary, contacts: [.contacts[] | {patient_name, outcome, call_date}]}'
ok "Report shows decrypted names + outcomes"

# ─── Step 9: Get Clinic Details ───────────────────────────────────────────────
step 9 "Clinic Details (Admin CRUD)"
curl -s -H "X-API-Key: $API_KEY" \
  "$BASE_URL/admin/clinics/$CLINIC_ID" | jq .
ok "Multi-tenant clinic data with license info"

echo
echo "═══════════════════════════════════════════════════"
echo "DEMO COMPLETE"
echo "  Swagger UI:  $BASE_URL/docs"
echo "  Dashboard:   http://localhost:5173"
echo "═══════════════════════════════════════════════════"
