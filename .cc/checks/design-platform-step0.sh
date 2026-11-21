#!/usr/bin/env bash
# Step-0 report: ./convo.sh checks writes .run/checks.json and .run/llm_mode
fail() { echo "FAIL: $1"; exit 1; }
cd convo-agent 2>/dev/null || fail "convo-agent/ directory missing"
[ -f convo.sh ] || fail "convo-agent/convo.sh missing"
export CONDUCTOR_SERVER_URL="${CONDUCTOR_SERVER_URL:-http://localhost:8080/api}"
curl -s -m 5 -o /dev/null "$CONDUCTOR_SERVER_URL/health" || curl -s -m 5 -o /dev/null "$CONDUCTOR_SERVER_URL/metadata/workflow" || fail "Conductor not reachable at $CONDUCTOR_SERVER_URL"
rm -f .run/checks.json .run/llm_mode
out=$(bash ./convo.sh checks 2>&1 </dev/null & pid=$!; i=0; while kill -0 $pid 2>/dev/null; do i=$((i+1)); [ $i -gt 600 ] && { kill $pid; echo TIMEOUT; break; }; sleep 0.2; done; wait $pid 2>/dev/null)
[ "$out" = "TIMEOUT" ] && fail "./convo.sh checks exceeded 120s"
[ -f .run/checks.json ] || fail ".run/checks.json not written"
[ -f .run/llm_mode ] || fail ".run/llm_mode not written"
/Users/mrai/.uv/venvs/conductor/bin/python -I - <<'PY' || exit 1
import json,sys
try: d=json.load(open('.run/checks.json'))
except Exception as e: print("FAIL: checks.json invalid: %s"%e); sys.exit(1)
miss=[k for k in ("llm_native","get_workflow","get_workflow_missing","switch_not_taken") if k not in d]
if miss: print("FAIL: checks.json missing keys %s"%miss); sys.exit(1)
m=open('.run/llm_mode').read().strip()
if m not in ("native","worker"): print("FAIL: llm_mode is %r"%m); sys.exit(1)
PY
echo PASS
