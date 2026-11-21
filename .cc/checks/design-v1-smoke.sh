#!/usr/bin/env bash
# v1: ./convo.sh start v1, then python -m v1.smoke exits 0 and prints execution links; manifest processes empty.
ROOT="$(pwd)"
PY=/Users/mrai/.uv/venvs/conductor/bin/python
fail() { echo "FAIL: $1"; exit 1; }
[ -d "$ROOT/convo-agent" ] || fail "convo-agent/ directory does not exist"
cd "$ROOT/convo-agent" || fail "cannot enter convo-agent"
[ -x ./convo.sh ] || fail "convo-agent/convo.sh missing or not executable"
OUT="${TMPDIR:-/tmp}/v1smoke.$$"
mkdir -p "$OUT"
cleanup() { ./convo.sh stop v1 >/dev/null 2>&1; rm -rf "$OUT"; }
trap cleanup EXIT

[ -f v1/manifest.json ] || fail "v1/manifest.json missing"
"$PY" - <<'PY' || fail "v1/manifest.json processes list is not empty"
import json,sys
m=json.load(open("v1/manifest.json"))
sys.exit(0 if m.get("processes")==[] else 1)
PY

# bounded background runner
run_bounded() { # secs outfile cmd...
  local secs=$1 of=$2; shift 2
  "$@" >"$of" 2>&1 &
  local pid=$! n=0
  while kill -0 $pid 2>/dev/null; do
    n=$((n+1)); [ $n -gt $((secs*2)) ] && { kill $pid 2>/dev/null; sleep 1; kill -9 $pid 2>/dev/null; return 124; }
    sleep 0.5
  done
  wait $pid
}
run_bounded 240 "$OUT/start.log" ./convo.sh start v1 || { tail -5 "$OUT/start.log"; fail "./convo.sh start v1 failed or timed out"; }
run_bounded 300 "$OUT/smoke.log" "$PY" -m v1.smoke
rc=$?
[ $rc -eq 0 ] || { tail -5 "$OUT/smoke.log"; fail "python -m v1.smoke exit code $rc"; }
grep -Eq 'https?://[^ ]+' "$OUT/smoke.log" || fail "smoke printed no execution links"
grep -Eiq 'execution' "$OUT/smoke.log" || fail "smoke output does not mention executions"
echo "PASS"
