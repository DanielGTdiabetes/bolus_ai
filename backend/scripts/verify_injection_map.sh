#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
TOKEN="${BOLUS_AI_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "Please set BOLUS_AI_TOKEN with a valid Bearer token."
  exit 1
fi

BASAL_POINT="${BASAL_POINT:-glute_left:1}"
RAPID_POINT="${RAPID_POINT:-abd_r_top:1}"

echo "🔄 Setting manual basal point to ${BASAL_POINT}"
curl -s -X POST "${API_URL}/api/injection/manual" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"insulin_type\":\"basal\",\"point_id\":\"${BASAL_POINT}\"}" \
  | tee /tmp/injection_manual_basal.json

STATE1=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${API_URL}/api/injection/state")
STATE1="$STATE1" EXPECTED="$BASAL_POINT" python - <<'PY'
import json, os, sys
state = json.loads(os.environ["STATE1"])
expected = os.environ["EXPECTED"]
actual = state["states"]["basal"]["last_point_id"]
if actual != expected:
    sys.exit(f"[FAIL] Basal last point mismatch: got {actual}, expected {expected}")
print(f"[OK] Basal manual persisted: {actual}")
PY

echo "↪️ Rotating basal (auto)"
curl -s -X POST "${API_URL}/api/injection/rotate" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"type":"basal"}' \
  >/tmp/injection_rotate_basal.json

STATE2=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${API_URL}/api/injection/state")
STATE2="$STATE2" PREV="$BASAL_POINT" python - <<'PY'
import json, os, sys
state = json.loads(os.environ["STATE2"])
prev = os.environ["PREV"]
actual = state["states"]["basal"]["last_point_id"]
if actual == prev:
    sys.exit(f"[FAIL] Basal rotation did not advance (still {actual})")
print(f"[OK] Basal rotated to {actual}")
PY

echo "📍 Setting manual rapid point to ${RAPID_POINT}"
curl -s -X POST "${API_URL}/api/injection/manual" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"insulin_type\":\"rapid\",\"point_id\":\"${RAPID_POINT}\"}" \
  | tee /tmp/injection_manual_rapid.json

STATE3=$(curl -s -H "Authorization: Bearer ${TOKEN}" "${API_URL}/api/injection/state")
STATE3="$STATE3" EXPECTED="$RAPID_POINT" python - <<'PY'
import json, os, sys
state = json.loads(os.environ["STATE3"])
expected = os.environ["EXPECTED"]
actual = state["states"]["bolus"]["last_point_id"]
if actual != expected:
    sys.exit(f"[FAIL] Rapid last point mismatch: got {actual}, expected {expected}")
print(f"[OK] Rapid manual persisted: {actual}")
PY

echo "✅ Verification completed."
