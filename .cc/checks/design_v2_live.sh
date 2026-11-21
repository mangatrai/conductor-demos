#!/bin/bash
# v2 live: smoke passes against running stack; foreign session cannot resume.
PY=/Users/mrai/.uv/venvs/conductor/bin/python
fail(){ echo "FAIL: $1"; exit 1; }
[ -d convo-agent ] || fail "convo-agent/ directory missing"
cd convo-agent || fail "cd"
[ -x ./convo.sh ] || fail "convo-agent/convo.sh missing or not executable"
command -v curl >/dev/null || fail "curl missing"
cleanup(){ ./convo.sh stop v2 >/dev/null 2>&1; }
trap cleanup EXIT
curl -s -m 5 -o /dev/null http://localhost:8080/api/health || fail "Conductor OSS not reachable on localhost:8080"
curl -s -m 5 -o /dev/null http://localhost:11434/api/tags || fail "Ollama not reachable on localhost:11434"
./convo.sh start v2 >"${TMPDIR:-/tmp}/v2_start.log" 2>&1 || fail "./convo.sh start v2 exited non-zero"
ok=0
for i in $(seq 1 30); do
  curl -s -m 3 -f http://localhost:8720/healthz >/dev/null && { ok=1; break; }; sleep 1
done
[ $ok = 1 ] || fail "v2 /healthz not answering on 8720"
"$PY" -m v2.smoke --base http://localhost:8720 >"${TMPDIR:-/tmp}/v2_smoke.log" 2>&1 &
sp=$!
d=$((SECONDS+240))
while kill -0 $sp 2>/dev/null; do
  [ $SECONDS -gt $d ] && { kill $sp 2>/dev/null; fail "v2.smoke exceeded 240s"; }
  sleep 2
done
wait $sp || fail "python -m v2.smoke exited non-zero: $(tail -n 1 "${TMPDIR:-/tmp}/v2_smoke.log")"
resp=$(curl -s -m 150 -X POST http://localhost:8720/api/chat -H 'Content-Type: application/json' \
  -d '{"sessionId":"live-owner","message":"Say hello in one short sentence."}') || fail "POST /api/chat failed"
eid=$(printf '%s' "$resp" | "$PY" -c 'import sys,json;print(json.load(sys.stdin).get("executionId",""))') || fail "chat response not JSON"
[ -n "$eid" ] || fail "chat response has no executionId"
own=$(curl -s -m 30 "http://localhost:8720/api/session?executionId=$eid&sessionId=live-owner")
printf '%s' "$own" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d.get("found") is True and len(d.get("history",[]))>0 else 1)' || fail "owner session not found"
other=$(curl -s -m 30 "http://localhost:8720/api/session?executionId=$eid&sessionId=live-intruder")
printf '%s' "$other" | "$PY" -c 'import sys,json;d=json.load(sys.stdin);sys.exit(0 if d.get("found") is False and d.get("history")==[] else 1)' || fail "foreign session not rejected: $other"
echo "PASS"
